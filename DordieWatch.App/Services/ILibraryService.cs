using DordieWatch.App.Models;

namespace DordieWatch.App.Services;

public interface ILibraryService
{
    Task<IReadOnlyList<MediaLibraryItem>> GetLibraryAsync(CancellationToken cancellationToken);
    Task<IReadOnlyList<MediaLibraryItem>> RefreshAsync(CancellationToken cancellationToken);
    Task<IReadOnlyList<EpisodeItem>> GetEpisodesAsync(long mediaItemId, CancellationToken cancellationToken);
    Task SaveProgressAsync(long episodeId, TimeSpan position, TimeSpan duration, CancellationToken cancellationToken);
}
