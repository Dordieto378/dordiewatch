using LibVLCSharp.Shared;

namespace DordieWatch.App.Services;

public interface IPlayerService : IDisposable
{
    MediaPlayer MediaPlayer { get; }
    event EventHandler? PositionChanged;
    event EventHandler? PlaybackEnded;
    void Play(string videoPath, string? externalSubtitlePath, TimeSpan startPosition);
    void TogglePause();
    void Seek(TimeSpan position);
    void Stop();
    TimeSpan Position { get; }
    TimeSpan Duration { get; }
    bool IsPlaying { get; }
}
