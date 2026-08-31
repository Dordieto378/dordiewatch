namespace DordieWatch.App.Services;

public interface IDordieListClient
{
    Task<DordieListLibrarySyncResult> GetLibraryAsync(
        IReadOnlyCollection<int> mediaIds,
        CancellationToken cancellationToken);

    Task<DordieListMediaManifest?> GetMediaManifestAsync(
        string manifestUrl,
        CancellationToken cancellationToken);
}
