using System;

namespace DordieWatch.App.Models;

public sealed record EpisodeItem(
    long Id,
    long MediaItemId,
    int EpisodeNumber,
    string Title,
    string VideoPath,
    string? ExternalSubtitlePath,
    TimeSpan Duration,
    TimeSpan Position);
