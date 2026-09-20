using LibVLCSharp.Shared;
using DordieWatch.App.Models;

namespace DordieWatch.App.Services;

public interface IPlayerService : IDisposable
{
    MediaPlayer MediaPlayer { get; }
    event EventHandler? PositionChanged;
    event EventHandler? PlaybackEnded;
    event EventHandler? PlaybackStarted;
    event EventHandler? PlaybackReady;
    event EventHandler? TracksChanged;
    void Play(string videoPath, TimeSpan startPosition, string? subtitlePath = null);
    void TogglePause();
    void Seek(TimeSpan position);
    void Stop();
    TimeSpan Position { get; }
    TimeSpan Duration { get; }
    bool IsPlaying { get; }
    int Volume { get; set; }
    int SelectedAudioTrackId { get; }
    IReadOnlyList<PlaybackTrackInfo> GetAudioTracks();
    bool SelectAudioTrack(int trackId);
    bool SelectSubtitleFile(string? subtitlePath);
}
