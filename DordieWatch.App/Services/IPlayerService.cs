using LibVLCSharp.Shared;
using DordieWatch.App.Models;

namespace DordieWatch.App.Services;

public interface IPlayerService : IDisposable
{
    MediaPlayer MediaPlayer { get; }
    event EventHandler? PositionChanged;
    event EventHandler? PlaybackEnded;
    event EventHandler? PlaybackStarted;
    event EventHandler? TracksChanged;
    void Play(string videoPath, string? externalSubtitlePath, TimeSpan startPosition);
    void TogglePause();
    void Seek(TimeSpan position);
    void Stop();
    TimeSpan Position { get; }
    TimeSpan Duration { get; }
    bool IsPlaying { get; }
    int Volume { get; set; }
    int SelectedAudioTrackId { get; }
    int SelectedSubtitleTrackId { get; }
    IReadOnlyList<PlaybackTrackInfo> GetAudioTracks();
    IReadOnlyList<PlaybackTrackInfo> GetSubtitleTracks();
    bool SelectAudioTrack(int trackId);
    bool SelectSubtitleTrack(int trackId);
}
