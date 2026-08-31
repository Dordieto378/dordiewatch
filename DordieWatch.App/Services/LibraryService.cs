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
        var websiteSync = await dordieListClient.GetLibraryAsync(
            scan.SelectMany(x => x.WebsiteIds).Distinct().ToArray(),
            cancellationToken);
        var websiteMetadata = websiteSync.Media;

        await using var db = await dbFactory.CreateDbContextAsync(cancellationToken);
        await using var transaction = await db.Database.BeginTransactionAsync(cancellationToken);
        var existingItems = await db.MediaItems
            .Include(x => x.Episodes)
                .ThenInclude(x => x.Progress)
            .ToListAsync(cancellationToken);
        var unmatchedItems = new HashSet<MediaItemEntity>(
            existingItems,
            ReferenceEqualityComparer.Instance);

        foreach (var item in scan)
        {
            var entity = unmatchedItems.FirstOrDefault(existing =>
                string.Equals(existing.FolderPath, item.FolderPath, StringComparison.OrdinalIgnoreCase));

            if (entity is null && item.WebsiteIds.Count > 0)
            {
                var scannedIds = item.WebsiteIds.ToHashSet();
                entity = unmatchedItems.FirstOrDefault(existing =>
                    DeserializeWebsiteIds(existing.WebsiteIdsJson).Any(scannedIds.Contains));
            }

            var isNew = entity is null;
            if (isNew)
            {
                entity = new MediaItemEntity();
                db.MediaItems.Add(entity);
            }
            else
            {
                unmatchedItems.Remove(entity!);
            }

            var matchedMetadata = item.WebsiteIds
                .Select(id => websiteMetadata.TryGetValue(id, out var metadata) ? metadata : null)
                .Where(metadata => metadata is not null)
                .Cast<DordieListMediaMetadata>()
                .ToArray();
            var primaryMetadata = matchedMetadata.FirstOrDefault();
            var category = matchedMetadata.Any(metadata => metadata.Type == "hentai")
                ? "hentai"
                : primaryMetadata?.Type ?? item.Category;

            entity!.FolderPath = item.FolderPath;
            entity.Kind = item.Kind;
            entity.WebsiteIdsJson = JsonSerializer.Serialize(item.WebsiteIds);
            entity.UpdatedAt = DateTimeOffset.UtcNow;

            if (primaryMetadata is not null)
            {
                entity.Title = string.IsNullOrWhiteSpace(primaryMetadata.DisplayTitle)
                    ? item.Title
                    : primaryMetadata.DisplayTitle;
                entity.Category = NormalizeCategory(category);
                entity.PosterPath = FirstExistingPath(
                    primaryMetadata.LocalCoverPath,
                    entity.PosterPath,
                    item.PosterPath);
                entity.BackdropPath = FirstExistingPath(
                    primaryMetadata.LocalBannerPath,
                    primaryMetadata.LocalCoverPath,
                    entity.BackdropPath,
                    item.BackdropPath,
                    item.PosterPath);
            }
            else if (websiteSync.IsAvailable || isNew)
            {
                entity.Title = item.Title;
                entity.Category = NormalizeCategory(item.Category);
                entity.PosterPath = FirstExistingPath(item.PosterPath, entity.PosterPath);
                entity.BackdropPath = FirstExistingPath(
                    item.BackdropPath,
                    item.PosterPath,
                    entity.BackdropPath);
            }
            else
            {
                entity.PosterPath = FirstExistingPath(entity.PosterPath, item.PosterPath);
                entity.BackdropPath = FirstExistingPath(
                    entity.BackdropPath,
                    item.BackdropPath,
                    item.PosterPath);
            }

            var unmatchedEpisodes = new HashSet<EpisodeEntity>(
                entity.Episodes,
                ReferenceEqualityComparer.Instance);
            foreach (var episode in item.Episodes)
            {
                var episodeEntity = unmatchedEpisodes.FirstOrDefault(existing =>
                    string.Equals(existing.VideoPath, episode.VideoPath, StringComparison.OrdinalIgnoreCase))
                    ?? unmatchedEpisodes.FirstOrDefault(existing =>
                        existing.EpisodeNumber == episode.EpisodeNumber);

                if (episodeEntity is null)
                {
                    episodeEntity = new EpisodeEntity { VideoPath = episode.VideoPath };
                    entity.Episodes.Add(episodeEntity);
                }
                else
                {
                    unmatchedEpisodes.Remove(episodeEntity);
                }

                episodeEntity.EpisodeNumber = episode.EpisodeNumber;
                episodeEntity.Title = episode.Title;
                episodeEntity.VideoPath = episode.VideoPath;
                episodeEntity.ExternalSubtitlePath = episode.ExternalSubtitlePath;
                episodeEntity.UpdatedAt = DateTimeOffset.UtcNow;
            }

            db.Episodes.RemoveRange(unmatchedEpisodes);
        }

        db.MediaItems.RemoveRange(unmatchedItems);
        await db.SaveChangesAsync(cancellationToken);
        await transaction.CommitAsync(cancellationToken);
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

    private static IReadOnlyList<int> DeserializeWebsiteIds(string value)
    {
        try
        {
            return JsonSerializer.Deserialize<int[]>(value) ?? [];
        }
        catch (JsonException)
        {
            return [];
        }
    }

    private static string? FirstExistingPath(params string?[] candidates)
    {
        return candidates.FirstOrDefault(path =>
            !string.IsNullOrWhiteSpace(path) && File.Exists(path));
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
