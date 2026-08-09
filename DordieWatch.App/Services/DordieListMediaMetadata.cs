namespace DordieWatch.App.Services;

public sealed record DordieListMediaMetadata(
    int Id,
    string Type,
    string DisplayTitle,
    string? CoverUrl,
    string? BannerUrl,
    string? LocalCoverPath,
    string? LocalBannerPath,
    string? WebsiteUrl);
