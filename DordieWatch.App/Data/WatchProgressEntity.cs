namespace DordieWatch.App.Data;

public sealed class WatchProgressEntity
{
    public long Id { get; set; }
    public long EpisodeId { get; set; }
    public EpisodeEntity? Episode { get; set; }
    public TimeSpan Position { get; set; }
    public TimeSpan Duration { get; set; }
    public DateTimeOffset LastWatchedAt { get; set; }
    public bool Completed { get; set; }
}
