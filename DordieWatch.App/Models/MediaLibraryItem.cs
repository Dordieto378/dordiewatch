using System.Collections.Generic;

namespace DordieWatch.App.Models;

public sealed record MediaLibraryItem(
    long Id,
    string Title,
    MediaKind Kind,
    string Category,
    string FolderPath,
    string? PosterPath,
    string? BackdropPath,
    IReadOnlyList<int> WebsiteIds,
    int EpisodeCount,
    double Progress);
