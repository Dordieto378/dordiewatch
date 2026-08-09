namespace DordieWatch.App.Data;

public sealed class EpisodeEntity
{
    public long Id { get; set; }
    public long MediaItemId { get; set; }
    public MediaItemEntity? MediaItem { get; set; }
    public int EpisodeNumber { get; set; }
    public string Title { get; set; } = "";
    public string VideoPath { get; set; } = "";
    public string? ExternalSubtitlePath { get; set; }
    public TimeSpan Duration { get; set; }
    public DateTimeOffset UpdatedAt { get; set; }
    public WatchProgressEntity? Progress { get; set; }
}
