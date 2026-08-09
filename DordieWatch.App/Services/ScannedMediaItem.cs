using DordieWatch.App.Models;

namespace DordieWatch.App.Services;

public sealed record ScannedMediaItem(
    string Title,
    MediaKind Kind,
    string Category,
    string FolderPath,
    string? PosterPath,
    string? BackdropPath,
    IReadOnlyList<int> WebsiteIds,
    IReadOnlyList<ScannedEpisode> Episodes);

public sealed record ScannedEpisode(
    int EpisodeNumber,
    string Title,
    string VideoPath,
    string? ExternalSubtitlePath);
