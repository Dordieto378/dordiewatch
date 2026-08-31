using LibVLCSharp.Shared;
using DordieWatch.App.Models;

namespace DordieWatch.App.Services;

public sealed class VlcPlayerService : IPlayerService
{
    private readonly LibVLC _libVlc;
    private int _volume = 100;
    private bool _disposed;

    public VlcPlayerService(LibVLC libVlc)
    {
        _libVlc = libVlc;
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
    public int SelectedSubtitleTrackId => MediaPlayer.Spu;
    public int Volume
    {
        get => _volume;
        set
        {
            _volume = Math.Clamp(value, 0, 100);
            ApplyVolume();
        }
    }

    public void Play(string videoPath, string? externalSubtitlePath, TimeSpan startPosition)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        using var media = new Media(_libVlc, new Uri(videoPath));
        if (!string.IsNullOrWhiteSpace(externalSubtitlePath) && File.Exists(externalSubtitlePath))
        {
            media.AddOption($":sub-file={externalSubtitlePath}");
        }

        ApplyVolume();
        MediaPlayer.Play(media);
        ApplyVolume();
        _ = ReapplyVolumeAfterPlaybackStartsAsync();

        if (startPosition > TimeSpan.Zero)
        {
            _ = Task.Run(async () =>
            {
                await Task.Delay(350).ConfigureAwait(false);
                Seek(startPosition);
            });
        }
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

    public IReadOnlyList<PlaybackTrackInfo> GetSubtitleTracks()
    {
        return MediaPlayer.SpuDescription
            .Where(track => track.Id >= 0)
            .Select((track, index) => new PlaybackTrackInfo(
                track.Id,
                GetTrackName(track.Name, "Subtitle", index + 1)))
            .GroupBy(track => track.Id)
            .Select(group => group.First())
            .ToArray();
    }

    public bool SelectAudioTrack(int trackId)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        return MediaPlayer.SetAudioTrack(trackId);
    }

    public bool SelectSubtitleTrack(int trackId)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        return MediaPlayer.SetSpu(trackId);
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

    private async Task ReapplyVolumeAfterPlaybackStartsAsync()
    {
        try
        {
            await Task.Delay(250).ConfigureAwait(false);
            if (!_disposed)
            {
                ApplyVolume();
            }

            await Task.Delay(750).ConfigureAwait(false);
            if (!_disposed)
            {
                ApplyVolume();
            }
        }
        catch (ObjectDisposedException)
        {
            // Expected if the player is closed while startup audio state is being applied.
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
