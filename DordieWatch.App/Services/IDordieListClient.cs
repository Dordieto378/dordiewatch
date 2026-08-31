namespace DordieWatch.App.Services;

public interface IDordieListClient
{
    Task<IReadOnlyDictionary<int, DordieListMediaMetadata>> GetLibraryAsync(
        IReadOnlyCollection<int> mediaIds,
        CancellationToken cancellationToken);

    Task<DordieListMediaManifest?> GetMediaManifestAsync(
        string manifestUrl,
        CancellationToken cancellationToken);
}
