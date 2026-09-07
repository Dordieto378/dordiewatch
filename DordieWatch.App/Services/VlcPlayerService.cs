using LibVLCSharp.Shared;
using DordieWatch.App.Models;

namespace DordieWatch.App.Services;

public sealed class VlcPlayerService : IPlayerService
{
    private readonly LibVLC _libVlc;
    private readonly ISubtitleFileService _subtitleFileService;
    private int _volume = 100;
    private bool _disposed;
    private long _playbackGeneration;
    private string? _currentVideoPath;
    private string? _selectedExternalSubtitlePath;
    private string? _selectedPlaybackSubtitlePath;
    private string? _selectedSubtitleFontDirectory;

    public VlcPlayerService(LibVLC libVlc, ISubtitleFileService subtitleFileService)
    {
        _libVlc = libVlc;
        _subtitleFileService = subtitleFileService;
        MediaPlayer = new MediaPlayer(_libVlc);
        ApplyVolume();
        MediaPlayer.TimeChanged += (_, _) => PositionChanged?.Invoke(this, EventArgs.Empty);
        MediaPlayer.LengthChanged += (_, _) => PositionChanged?.Invoke(this, EventArgs.Empty);
        MediaPlayer.EndReached += (_, _) => PlaybackEnded?.Invoke(this, EventArgs.Empty);
        MediaPlayer.Playing += (_, _) =>
        {
            PlaybackStarted?.Invoke(this, EventArgs.Empty);
            TracksChanged?.Invoke(this, EventArgs.Empty);
        };
        MediaPlayer.ESAdded += (_, _) => TracksChanged?.Invoke(this, EventArgs.Empty);
        MediaPlayer.ESDeleted += (_, _) => TracksChanged?.Invoke(this, EventArgs.Empty);
        MediaPlayer.ESSelected += (_, _) => TracksChanged?.Invoke(this, EventArgs.Empty);
    }

    public MediaPlayer MediaPlayer { get; }
    public event EventHandler? PositionChanged;
    public event EventHandler? PlaybackEnded;
    public event EventHandler? PlaybackStarted;
    public event EventHandler? TracksChanged;

    public TimeSpan Position => TimeSpan.FromMilliseconds(Math.Max(0, MediaPlayer.Time));
    public TimeSpan Duration => TimeSpan.FromMilliseconds(Math.Max(0, MediaPlayer.Length));
    public bool IsPlaying => MediaPlayer.IsPlaying;
    public int SelectedAudioTrackId => MediaPlayer.AudioTrack;
    public int Volume
    {
        get => _volume;
        set
        {
            _volume = Math.Clamp(value, 0, 100);
            ApplyVolume();
        }
    }

    public void Play(string videoPath, TimeSpan startPosition, string? subtitlePath = null)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        _currentVideoPath = videoPath;
        if (!string.IsNullOrWhiteSpace(subtitlePath) && File.Exists(subtitlePath))
        {
            var playbackSubtitle = _subtitleFileService.PrepareForPlayback(subtitlePath);
            if (File.Exists(playbackSubtitle.Path))
            {
                _selectedExternalSubtitlePath = subtitlePath;
                _selectedPlaybackSubtitlePath = playbackSubtitle.Path;
                _selectedSubtitleFontDirectory = playbackSubtitle.FontDirectory;
                StartMedia(videoPath, playbackSubtitle.Path, playbackSubtitle.FontDirectory, startPosition);
                return;
            }
        }

        _selectedExternalSubtitlePath = null;
        _selectedPlaybackSubtitlePath = null;
        _selectedSubtitleFontDirectory = null;
        StartMedia(videoPath, null, null, startPosition);
    }

    public void TogglePause()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (MediaPlayer.IsPlaying)
        {
            MediaPlayer.Pause();
        }
        else
        {
            MediaPlayer.Play();
        }
    }

    public void Seek(TimeSpan position)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        MediaPlayer.Time = (long)Math.Max(0, position.TotalMilliseconds);
    }

    public void Stop()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        MediaPlayer.Stop();
    }

    public IReadOnlyList<PlaybackTrackInfo> GetAudioTracks()
    {
        return MediaPlayer.AudioTrackDescription
            .Where(track => track.Id >= 0)
            .Select((track, index) => new PlaybackTrackInfo(
                track.Id,
                GetTrackName(track.Name, "Audio", index + 1)))
            .GroupBy(track => track.Id)
            .Select(group => group.First())
            .ToArray();
    }

    public bool SelectAudioTrack(int trackId)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        return MediaPlayer.SetAudioTrack(trackId);
    }

    public bool SelectSubtitleFile(string? subtitlePath)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (string.IsNullOrWhiteSpace(subtitlePath))
        {
            _selectedExternalSubtitlePath = null;
            _selectedPlaybackSubtitlePath = null;
            _selectedSubtitleFontDirectory = null;
            if (_currentVideoPath is null)
            {
                MediaPlayer.SetSpu(-1);
                return true;
            }

            StartMedia(_currentVideoPath, null, null, Position);
            return true;
        }

        if (!File.Exists(subtitlePath) || _currentVideoPath is null)
        {
            return false;
        }

        var playbackSubtitle = _subtitleFileService.PrepareForPlayback(subtitlePath);
        if (!File.Exists(playbackSubtitle.Path))
        {
            return false;
        }

        _selectedExternalSubtitlePath = subtitlePath;
        _selectedPlaybackSubtitlePath = playbackSubtitle.Path;
        _selectedSubtitleFontDirectory = playbackSubtitle.FontDirectory;
        StartMedia(_currentVideoPath, playbackSubtitle.Path, playbackSubtitle.FontDirectory, Position);
        return true;
    }

    private static string GetTrackName(string? name, string fallbackPrefix, int number)
    {
        return string.IsNullOrWhiteSpace(name)
            ? $"{fallbackPrefix} {number}"
            : name.Trim();
    }

    private void ApplyVolume()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        MediaPlayer.Mute = _volume <= 0;
        MediaPlayer.Volume = _volume;
    }

    private void StartMedia(string videoPath, string? subtitlePath, string? subtitleFontDirectory, TimeSpan startPosition)
    {
        var generation = Interlocked.Increment(ref _playbackGeneration);
        using var media = new Media(_libVlc, new Uri(videoPath));
        media.AddOption(":no-sub-autodetect-file");
        media.AddOption(":sub-track=-1");
        media.AddOption(":sub-track-id=-1");
        media.AddOption(":sub-language=none");

        if (!string.IsNullOrWhiteSpace(subtitlePath) && File.Exists(subtitlePath))
        {
            media.AddOption($":sub-file={subtitlePath}");
            if (!string.IsNullOrWhiteSpace(subtitleFontDirectory) && Directory.Exists(subtitleFontDirectory))
            {
                media.AddOption($":ssa-fontsdir={subtitleFontDirectory}");
            }
        }
        ApplyVolume();
        MediaPlayer.Play(media);
        ApplyVolume();
        _ = ReapplyVolumeAfterPlaybackStartsAsync(generation);

        if (!string.IsNullOrWhiteSpace(subtitlePath))
        {
            _ = SelectExternalSubtitleAfterPlaybackStartsAsync(generation);
        }
        else
        {
            _ = DisableSubtitlesAfterPlaybackStartsAsync(generation);
        }

        if (startPosition > TimeSpan.Zero)
        {
            _ = SeekAfterPlaybackStartsAsync(startPosition, generation);
        }
    }

    private async Task SeekAfterPlaybackStartsAsync(TimeSpan startPosition, long generation)
    {
        try
        {
            await Task.Delay(350).ConfigureAwait(false);
            if (!_disposed && generation == Interlocked.Read(ref _playbackGeneration))
            {
                Seek(startPosition);
            }
        }
        catch (ObjectDisposedException)
        {
            // Expected if the player is closed while startup seek is being applied.
        }
    }

    private async Task ReapplyVolumeAfterPlaybackStartsAsync(long generation)
    {
        try
        {
            await Task.Delay(250).ConfigureAwait(false);
            if (!_disposed && generation == Interlocked.Read(ref _playbackGeneration))
            {
                ApplyVolume();
            }

            await Task.Delay(750).ConfigureAwait(false);
            if (!_disposed && generation == Interlocked.Read(ref _playbackGeneration))
            {
                ApplyVolume();
            }
        }
        catch (ObjectDisposedException)
        {
            // Expected if the player is closed while startup audio state is being applied.
        }
    }

    private async Task DisableSubtitlesAfterPlaybackStartsAsync(long generation)
    {
        try
        {
            await Task.Delay(300).ConfigureAwait(false);
            if (!_disposed
                && generation == Interlocked.Read(ref _playbackGeneration)
                && _selectedExternalSubtitlePath is null)
            {
                MediaPlayer.SetSpu(-1);
            }

            await Task.Delay(700).ConfigureAwait(false);
            if (!_disposed
                && generation == Interlocked.Read(ref _playbackGeneration)
                && _selectedExternalSubtitlePath is null)
            {
                MediaPlayer.SetSpu(-1);
            }
        }
        catch (ObjectDisposedException)
        {
            // Expected if the player is closed while startup subtitle state is being applied.
        }
    }

    private async Task SelectExternalSubtitleAfterPlaybackStartsAsync(long generation)
    {
        try
        {
            var slaveAdded = false;
            foreach (var delay in new[] { 350, 700, 1200 })
            {
                await Task.Delay(delay).ConfigureAwait(false);
                if (_disposed
                    || generation != Interlocked.Read(ref _playbackGeneration)
                    || _selectedPlaybackSubtitlePath is null)
                {
                    return;
                }

                if (!slaveAdded || MediaPlayer.Spu < 0)
                {
                    MediaPlayer.SetSpu(-1);
                    MediaPlayer.AddSlave(
                        MediaSlaveType.Subtitle,
                        new Uri(_selectedPlaybackSubtitlePath).AbsoluteUri,
                        select: true);
                    slaveAdded = true;
                    TracksChanged?.Invoke(this, EventArgs.Empty);
                }
            }
        }
        catch (ObjectDisposedException)
        {
            // Expected if the player is closed while subtitle selection is being applied.
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        MediaPlayer.Stop();
        MediaPlayer.Dispose();
    }
}
