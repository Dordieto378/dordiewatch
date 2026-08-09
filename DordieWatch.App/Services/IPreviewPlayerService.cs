using LibVLCSharp.Shared;

namespace DordieWatch.App.Services;

public interface IPreviewPlayerService : IDisposable
{
    MediaPlayer MediaPlayer { get; }
    void PlayLoop(string videoPath);
    void Stop();
}
