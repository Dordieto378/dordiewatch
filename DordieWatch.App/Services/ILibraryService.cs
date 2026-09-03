using DordieWatch.App.Models;

namespace DordieWatch.App.Services;

public interface ILibraryService
{
    Task<IReadOnlyList<MediaLibraryItem>> GetLibraryAsync(CancellationToken cancellationToken);
    Task<IReadOnlyList<MediaLibraryItem>> RefreshAsync(CancellationToken cancellationToken);
    Task<MediaLibraryItem?> FindByWebsiteIdAsync(int websiteId, CancellationToken cancellationToken);
    Task<IReadOnlyList<EpisodeItem>> GetEpisodesAsync(long mediaItemId, CancellationToken cancellationToken);
    Task SaveProgressAsync(long episodeId, TimeSpan position, TimeSpan duration, CancellationToken cancellationToken);
    Task<string?> GetPreferredSubtitleLanguageAsync(long mediaItemId, CancellationToken cancellationToken);
    Task SavePreferredSubtitleLanguageAsync(long mediaItemId, string? language, CancellationToken cancellationToken);
}
