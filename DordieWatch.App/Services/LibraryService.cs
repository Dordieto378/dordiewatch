using DordieWatch.App.Data;
using DordieWatch.App.Models;
using Microsoft.EntityFrameworkCore;
using System.Text.Json;

namespace DordieWatch.App.Services;

public sealed class LibraryService(
    IAppPaths paths,
    IMediaFileScanner scanner,
    IDordieListClient dordieListClient,
    IDbContextFactory<AppDbContext> dbFactory) : ILibraryService
{
    public async Task<IReadOnlyList<MediaLibraryItem>> GetLibraryAsync(CancellationToken cancellationToken)
    {
        await using var db = await dbFactory.CreateDbContextAsync(cancellationToken);
        var entities = await db.MediaItems
            .AsNoTracking()
            .Include(x => x.Episodes)
                .ThenInclude(x => x.Progress)
            .OrderBy(x => x.Title)
            .ToListAsync(cancellationToken);

        return entities.Select(ToLibraryItem).ToArray();
    }

    public async Task<IReadOnlyList<MediaLibraryItem>> RefreshAsync(CancellationToken cancellationToken)
    {
        var scan = await scanner.ScanAsync(paths.VideoLibraryDirectory, cancellationToken);
        var websiteMetadata = await dordieListClient.GetLibraryAsync(
            scan.SelectMany(x => x.WebsiteIds).Distinct().ToArray(),
            cancellationToken);

        await using var db = await dbFactory.CreateDbContextAsync(cancellationToken);

        foreach (var item in scan)
        {
            var matchedMetadata = item.WebsiteIds
                .Select(id => websiteMetadata.TryGetValue(id, out var metadata) ? metadata : null)
                .Where(metadata => metadata is not null)
                .Cast<DordieListMediaMetadata>()
                .ToArray();
            var primaryMetadata = matchedMetadata.FirstOrDefault();
            var category = matchedMetadata.Any(metadata => metadata.Type == "hentai")
                ? "hentai"
                : primaryMetadata?.Type ?? item.Category;

            var entity = await db.MediaItems
                .Include(x => x.Episodes)
                .FirstOrDefaultAsync(x => x.FolderPath == item.FolderPath, cancellationToken);

            if (entity is null)
            {
                entity = new MediaItemEntity { FolderPath = item.FolderPath };
                db.MediaItems.Add(entity);
            }

            entity.Title = string.IsNullOrWhiteSpace(primaryMetadata?.DisplayTitle)
                ? item.Title
                : primaryMetadata.DisplayTitle;
            entity.Kind = item.Kind;
            entity.Category = NormalizeCategory(category);
            entity.PosterPath = File.Exists(primaryMetadata?.LocalCoverPath)
                ? primaryMetadata.LocalCoverPath
                : item.PosterPath;
            entity.BackdropPath = File.Exists(primaryMetadata?.LocalBannerPath)
                ? primaryMetadata.LocalBannerPath
                : File.Exists(primaryMetadata?.LocalCoverPath)
                    ? primaryMetadata.LocalCoverPath
                    : item.BackdropPath;
            entity.WebsiteIdsJson = JsonSerializer.Serialize(item.WebsiteIds);
            entity.UpdatedAt = DateTimeOffset.UtcNow;

            var existingByPath = entity.Episodes.ToDictionary(x => x.VideoPath, StringComparer.OrdinalIgnoreCase);
            foreach (var episode in item.Episodes)
            {
                if (!existingByPath.TryGetValue(episode.VideoPath, out var episodeEntity))
                {
                    episodeEntity = new EpisodeEntity { VideoPath = episode.VideoPath };
                    entity.Episodes.Add(episodeEntity);
                }

                episodeEntity.EpisodeNumber = episode.EpisodeNumber;
                episodeEntity.Title = episode.Title;
                episodeEntity.ExternalSubtitlePath = episode.ExternalSubtitlePath;
                episodeEntity.UpdatedAt = DateTimeOffset.UtcNow;
            }
        }

        await db.SaveChangesAsync(cancellationToken);
        return await GetLibraryAsync(cancellationToken);
    }

    public async Task<MediaLibraryItem?> FindByWebsiteIdAsync(int websiteId, CancellationToken cancellationToken)
    {
        if (websiteId <= 0)
        {
            return null;
        }

        var items = await GetLibraryAsync(cancellationToken);
        return items.FirstOrDefault(item => item.WebsiteIds.Contains(websiteId));
    }

    public async Task<IReadOnlyList<EpisodeItem>> GetEpisodesAsync(long mediaItemId, CancellationToken cancellationToken)
    {
        await using var db = await dbFactory.CreateDbContextAsync(cancellationToken);
        var episodes = await db.Episodes
            .AsNoTracking()
            .Include(x => x.Progress)
            .Where(x => x.MediaItemId == mediaItemId)
            .OrderBy(x => x.EpisodeNumber)
            .ToListAsync(cancellationToken);

        return episodes.Select(ToEpisodeItem).ToArray();
    }

    public async Task SaveProgressAsync(long episodeId, TimeSpan position, TimeSpan duration, CancellationToken cancellationToken)
    {
        await using var db = await dbFactory.CreateDbContextAsync(cancellationToken);
        var progress = await db.WatchProgress.FirstOrDefaultAsync(x => x.EpisodeId == episodeId, cancellationToken);
        if (progress is null)
        {
            progress = new WatchProgressEntity { EpisodeId = episodeId };
            db.WatchProgress.Add(progress);
        }

        progress.Position = position;
        progress.Duration = duration;
        progress.Completed = duration > TimeSpan.Zero && position.TotalSeconds / duration.TotalSeconds > 0.92;
        progress.LastWatchedAt = DateTimeOffset.UtcNow;
        await db.SaveChangesAsync(cancellationToken);
    }

    private static MediaLibraryItem ToLibraryItem(MediaItemEntity entity)
    {
        var progress = entity.Episodes
            .Select(x => x.Progress)
            .Where(x => x is not null && x.Duration > TimeSpan.Zero)
            .Select(x => x!.Position.TotalSeconds / x.Duration.TotalSeconds)
            .DefaultIfEmpty(0)
            .Max();

        return new MediaLibraryItem(
            entity.Id,
            entity.Title,
            entity.Kind,
            NormalizeCategory(entity.Category),
            entity.FolderPath,
            entity.PosterPath,
            entity.BackdropPath,
            JsonSerializer.Deserialize<int[]>(entity.WebsiteIdsJson) ?? [],
            entity.Episodes.Count,
            progress);
    }

    private static string NormalizeCategory(string? category)
    {
        return string.Equals(category, "hentai", StringComparison.OrdinalIgnoreCase)
            ? "hentai"
            : "anime";
    }

    private static EpisodeItem ToEpisodeItem(EpisodeEntity entity)
    {
        return new EpisodeItem(
            entity.Id,
            entity.MediaItemId,
            entity.EpisodeNumber,
            entity.Title,
            entity.VideoPath,
            entity.ExternalSubtitlePath,
            entity.Progress?.Duration ?? entity.Duration,
            entity.Progress?.Position ?? TimeSpan.Zero,
            entity.Progress?.LastWatchedAt);
    }
}
