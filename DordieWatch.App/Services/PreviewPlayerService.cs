using LibVLCSharp.Shared;

namespace DordieWatch.App.Services;

public sealed class PreviewPlayerService : IPreviewPlayerService
{
    private readonly LibVLC _libVlc;
    private string? _currentPath;
    private bool _disposed;

    public PreviewPlayerService(LibVLC libVlc)
    {
        _libVlc = libVlc;
        MediaPlayer = new MediaPlayer(_libVlc)
        {
            Mute = true,
            Volume = 0
        };
        MediaPlayer.EndReached += (_, _) =>
        {
            var path = _currentPath;
            if (!string.IsNullOrWhiteSpace(path) && File.Exists(path))
            {
                _ = Task.Run(async () =>
                {
                    await Task.Delay(80).ConfigureAwait(false);
                    PlayLoop(path);
                });
            }
        };
    }

    public MediaPlayer MediaPlayer { get; }

    public void PlayLoop(string videoPath)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (!File.Exists(videoPath))
        {
            Stop();
            return;
        }

        _currentPath = videoPath;
        using var media = new Media(_libVlc, new Uri(videoPath));
        media.AddOption(":no-audio");
        media.AddOption(":no-spu");
        media.AddOption(":start-time=8");
        media.AddOption(":input-repeat=65535");
        MediaPlayer.Mute = true;
        MediaPlayer.Volume = 0;
        MediaPlayer.Play(media);
    }

    public void Stop()
    {
        if (_disposed)
        {
            return;
        }

        _currentPath = null;
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
    }
}
