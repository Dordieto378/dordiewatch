namespace DordieWatch.App.Services;

public sealed record EpisodePreview(string? ThumbnailPath, IReadOnlyList<string> FramePaths);
