namespace DordieWatch.App.Services;

public sealed record DordieListMediaManifest(
    DordieListMediaMetadata Metadata,
    string? LibraryUrl);
