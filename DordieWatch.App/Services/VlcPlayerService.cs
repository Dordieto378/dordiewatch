using LibVLCSharp.Shared;

namespace DordieWatch.App.Services;

public sealed class VlcPlayerService : IPlayerService
{
    private readonly LibVLC _libVlc;
    private bool _disposed;

    public VlcPlayerService()
    {
        Core.Initialize();
        _libVlc = new LibVLC(
            "--avcodec-hw=any",
            "--no-video-title-show",
            "--no-osd");
        MediaPlayer = new MediaPlayer(_libVlc);
        MediaPlayer.TimeChanged += (_, _) => PositionChanged?.Invoke(this, EventArgs.Empty);
        MediaPlayer.LengthChanged += (_, _) => PositionChanged?.Invoke(this, EventArgs.Empty);
        MediaPlayer.EndReached += (_, _) => PlaybackEnded?.Invoke(this, EventArgs.Empty);
    }

    public MediaPlayer MediaPlayer { get; }
    public event EventHandler? PositionChanged;
    public event EventHandler? PlaybackEnded;

    public TimeSpan Position => TimeSpan.FromMilliseconds(Math.Max(0, MediaPlayer.Time));
    public TimeSpan Duration => TimeSpan.FromMilliseconds(Math.Max(0, MediaPlayer.Length));
    public bool IsPlaying => MediaPlayer.IsPlaying;

    public void Play(string videoPath, string? externalSubtitlePath, TimeSpan startPosition)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);

        using var media = new Media(_libVlc, new Uri(videoPath));
        if (!string.IsNullOrWhiteSpace(externalSubtitlePath) && File.Exists(externalSubtitlePath))
        {
            media.AddOption($":sub-file={externalSubtitlePath}");
        }

        MediaPlayer.Play(media);

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
        MediaPlayer.SetPause(MediaPlayer.IsPlaying);
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

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        MediaPlayer.Stop();
        MediaPlayer.Dispose();
        _libVlc.Dispose();
    }
}
