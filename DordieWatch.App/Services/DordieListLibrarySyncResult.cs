namespace DordieWatch.App.Services;

public sealed record DordieListLibrarySyncResult(
    IReadOnlyDictionary<int, DordieListMediaMetadata> Media,
    bool IsAvailable);
