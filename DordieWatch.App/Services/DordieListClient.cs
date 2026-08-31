using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Serialization;

namespace DordieWatch.App.Services;

public sealed class DordieListClient(IAppPaths paths) : IDordieListClient, IDisposable
{
    private readonly HttpClient _http = new()
    {
        Timeout = TimeSpan.FromSeconds(15)
    };

    public async Task<DordieListLibrarySyncResult> GetLibraryAsync(
        IReadOnlyCollection<int> mediaIds,
        CancellationToken cancellationToken)
    {
        var ids = mediaIds.Where(id => id > 0).Distinct().Order().ToArray();
        if (ids.Length == 0)
        {
            return new DordieListLibrarySyncResult(
                new Dictionary<int, DordieListMediaMetadata>(),
                true);
        }

        var result = await TryGetLibraryAsync(ids, paths.DordieListLibraryUrl, cancellationToken);
        if (result is not null)
        {
            await LogAsync($"sync complete requested={ids.Length} matched={result.Count}", cancellationToken);
            return new DordieListLibrarySyncResult(result, true);
        }

        if (await TryRefreshLibraryUrlAsync(cancellationToken))
        {
            result = await TryGetLibraryAsync(ids, paths.DordieListLibraryUrl, cancellationToken);
            if (result is not null)
            {
                await LogAsync($"sync complete requested={ids.Length} matched={result.Count}", cancellationToken);
                return new DordieListLibrarySyncResult(result, true);
            }
        }

        return new DordieListLibrarySyncResult(
            new Dictionary<int, DordieListMediaMetadata>(),
            false);
    }

    public async Task<DordieListMediaManifest?> GetMediaManifestAsync(
        string manifestUrl,
        CancellationToken cancellationToken)
    {
        if (!paths.IsAllowedDordieListMediaUrl(manifestUrl))
        {
            await LogAsync($"manifest rejected url={manifestUrl}", cancellationToken);
            return null;
        }

        try
        {
            using var response = await _http.GetAsync(manifestUrl, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                await LogAsync($"manifest failed status={(int)response.StatusCode} url={manifestUrl}", cancellationToken);
                return null;
            }

            var payload = await response.Content.ReadFromJsonAsync<DordieListMediaItem>(cancellationToken);
            if (payload is null || payload.Id <= 0 || !IsSupportedType(payload.Type))
            {
                return null;
            }

            if (!string.IsNullOrWhiteSpace(payload.LibraryUrl))
            {
                if (!paths.TrySetDordieListLibraryUrl(payload.LibraryUrl))
                {
                    await LogAsync($"manifest library url rejected url={payload.LibraryUrl}", cancellationToken);
                }
            }

            return new DordieListMediaManifest(
                await ToMetadataAsync(payload, cancellationToken),
                payload.LibraryUrl);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException or IOException)
        {
            await LogAsync($"manifest failed error={error.GetType().Name}: {error.Message}", cancellationToken);
            return null;
        }
    }

    public void Dispose()
    {
        _http.Dispose();
    }

    private async Task LogAsync(string message, CancellationToken cancellationToken)
    {
        try
        {
            var path = Path.Combine(paths.AppDataDirectory, "dordielist-sync.log");
            await File.AppendAllTextAsync(path, $"{DateTimeOffset.Now:u} {message}{Environment.NewLine}", cancellationToken);
        }
        catch
        {
            // Logging must never break library loading.
        }
    }

    private async Task<IReadOnlyDictionary<int, DordieListMediaMetadata>?> TryGetLibraryAsync(
        IReadOnlyList<int> ids,
        string libraryUrl,
        CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(
                libraryUrl,
                new DordieListLibraryRequest(ids),
                cancellationToken);

            if (!response.IsSuccessStatusCode)
            {
                await LogAsync($"sync failed status={(int)response.StatusCode} url={libraryUrl}", cancellationToken);
                return null;
            }

            var payload = await response.Content.ReadFromJsonAsync<DordieListLibraryResponse>(cancellationToken);
            if (payload?.Media is null)
            {
                await LogAsync($"sync failed invalid response url={libraryUrl}", cancellationToken);
                return null;
            }

            var result = new Dictionary<int, DordieListMediaMetadata>();
            foreach (var item in payload.Media.Where(x => x.Id > 0 && IsSupportedType(x.Type)).GroupBy(x => x.Id).Select(x => x.First()))
            {
                result[item.Id] = await ToMetadataAsync(item, cancellationToken);
            }

            return result;
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException or IOException)
        {
            await LogAsync($"sync failed error={error.GetType().Name}: {error.Message}", cancellationToken);
            return null;
        }
    }

    private async Task<bool> TryRefreshLibraryUrlAsync(CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.GetAsync(paths.DordieListConfigUrl, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                await LogAsync($"config failed status={(int)response.StatusCode} url={paths.DordieListConfigUrl}", cancellationToken);
                return false;
            }

            var payload = await response.Content.ReadFromJsonAsync<DordieListConfigResponse>(cancellationToken);
            if (string.IsNullOrWhiteSpace(payload?.LibraryUrl)
                || !paths.TrySetDordieListLibraryUrl(payload.LibraryUrl))
            {
                await LogAsync("config failed invalid library_url", cancellationToken);
                return false;
            }

            await LogAsync($"config updated library url={paths.DordieListLibraryUrl}", cancellationToken);
            return true;
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException or IOException or UnauthorizedAccessException)
        {
            await LogAsync($"config failed error={error.GetType().Name}: {error.Message}", cancellationToken);
            return false;
        }
    }

    private async Task<DordieListMediaMetadata> ToMetadataAsync(
        DordieListMediaItem item,
        CancellationToken cancellationToken)
    {
        var localCover = await DownloadImageAsync(item.Id, item.CoverUrl, "cover", cancellationToken);
        var localBanner = await DownloadImageAsync(item.Id, item.BannerUrl, "banner", cancellationToken);
        return new DordieListMediaMetadata(
            item.Id,
            NormalizeType(item.Type),
            item.DisplayTitle?.Trim() ?? "",
            item.CoverUrl,
            item.BannerUrl,
            localCover,
            localBanner,
            item.WebsiteUrl);
    }

    private async Task<string?> DownloadImageAsync(
        int mediaId,
        string? url,
        string role,
        CancellationToken cancellationToken)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri)
            || uri.Scheme is not ("http" or "https"))
        {
            return null;
        }

        var digest = Convert.ToHexString(SHA1.HashData(Encoding.UTF8.GetBytes(uri.ToString())))[..12].ToLowerInvariant();
        var extension = Path.GetExtension(uri.AbsolutePath);
        if (string.IsNullOrWhiteSpace(extension) || extension.Length > 8)
        {
            extension = ".img";
        }

        var target = Path.Combine(paths.WebsiteCoverDirectory, $"{mediaId}-{role}-{digest}{extension}");
        if (File.Exists(target))
        {
            return target;
        }

        var temporary = target + $".{Environment.ProcessId}.part";
        try
        {
            using var response = await _http.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }

            var contentType = response.Content.Headers.ContentType?.MediaType ?? "";
            if (!contentType.StartsWith("image/", StringComparison.OrdinalIgnoreCase))
            {
                return null;
            }

            var maxBytes = 30 * 1024 * 1024;
            await using var source = await response.Content.ReadAsStreamAsync(cancellationToken);
            await using var destination = File.Create(temporary);
            var buffer = new byte[81920];
            var total = 0;
            while (true)
            {
                var read = await source.ReadAsync(buffer, cancellationToken);
                if (read == 0)
                {
                    break;
                }

                total += read;
                if (total > maxBytes)
                {
                    return null;
                }

                await destination.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
            }

            destination.Close();
            File.Move(temporary, target, overwrite: true);
            return target;
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception error) when (error is HttpRequestException or IOException or UnauthorizedAccessException)
        {
            await LogAsync($"image download failed id={mediaId} role={role} url={uri} error={error.Message}", cancellationToken);
            return null;
        }
        finally
        {
            try
            {
                if (File.Exists(temporary))
                {
                    File.Delete(temporary);
                }
            }
            catch
            {
                // Ignore cleanup failure.
            }
        }
    }

    private static bool IsSupportedType(string? type)
    {
        var normalized = NormalizeType(type);
        return normalized is "anime" or "hentai";
    }

    private static string NormalizeType(string? type)
    {
        return string.Equals(type, "hentai", StringComparison.OrdinalIgnoreCase)
            ? "hentai"
            : "anime";
    }

    private sealed record DordieListLibraryRequest(
        [property: JsonPropertyName("ids")] IReadOnlyList<int> Ids);

    private sealed record DordieListLibraryResponse(
        [property: JsonPropertyName("media")] IReadOnlyList<DordieListMediaItem>? Media);

    private sealed record DordieListConfigResponse(
        [property: JsonPropertyName("library_url")] string? LibraryUrl);

    private sealed record DordieListMediaItem(
        [property: JsonPropertyName("id")] int Id,
        [property: JsonPropertyName("type")] string? Type,
        [property: JsonPropertyName("display_title")] string? DisplayTitle,
        [property: JsonPropertyName("cover_url")] string? CoverUrl,
        [property: JsonPropertyName("banner_url")] string? BannerUrl,
        [property: JsonPropertyName("website_url")] string? WebsiteUrl,
        [property: JsonPropertyName("library_url")] string? LibraryUrl);
}
