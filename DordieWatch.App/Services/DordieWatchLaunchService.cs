using System.Text;

namespace DordieWatch.App.Services;

public sealed class DordieWatchLaunchService(
    IAppPaths paths,
    IDordieListClient dordieListClient,
    ILibraryService libraryService,
    INavigationService navigation) : IDordieWatchLaunchService
{
    public async Task HandleStartupArgsAsync(IReadOnlyList<string> args, CancellationToken cancellationToken)
    {
        var manifestUrl = args
            .Select(TryGetManifestUrl)
            .FirstOrDefault(url => !string.IsNullOrWhiteSpace(url));

        if (string.IsNullOrWhiteSpace(manifestUrl))
        {
            return;
        }

        if (!paths.IsAllowedDordieListMediaUrl(manifestUrl))
        {
            await LogAsync($"launch rejected manifest url={manifestUrl}", cancellationToken);
            return;
        }

        var manifest = await dordieListClient.GetMediaManifestAsync(manifestUrl, cancellationToken);
        if (manifest is null)
        {
            await LogAsync("launch manifest unavailable", cancellationToken);
            return;
        }

        await libraryService.RefreshAsync(cancellationToken);
        var media = await libraryService.FindByWebsiteIdAsync(manifest.Metadata.Id, cancellationToken);
        if (media is null)
        {
            await LogAsync($"launch local media missing id={manifest.Metadata.Id}", cancellationToken);
            return;
        }

        await navigation.ShowMediaDetailsAsync(media, cancellationToken, manifest.Metadata.Type);
    }

    private async Task LogAsync(string message, CancellationToken cancellationToken)
    {
        try
        {
            var path = Path.Combine(paths.AppDataDirectory, "dordiewatch-launch.log");
            await File.AppendAllTextAsync(path, $"{DateTimeOffset.Now:u} {message}{Environment.NewLine}", cancellationToken);
        }
        catch
        {
            // Launch logging must not interrupt app startup.
        }
    }

    private static string? TryGetManifestUrl(string arg)
    {
        if (!Uri.TryCreate(arg, UriKind.Absolute, out var uri)
            || !string.Equals(uri.Scheme, "dordiewatch", StringComparison.OrdinalIgnoreCase)
            || !string.Equals(uri.Host, "open", StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        var encodedManifest = GetQueryValue(uri.Query, "manifest");
        return string.IsNullOrWhiteSpace(encodedManifest)
            ? null
            : DecodeBase64Url(encodedManifest);
    }

    private static string? GetQueryValue(string query, string key)
    {
        foreach (var part in query.TrimStart('?').Split('&', StringSplitOptions.RemoveEmptyEntries))
        {
            var pieces = part.Split('=', 2);
            var name = Uri.UnescapeDataString(pieces[0]);
            if (!string.Equals(name, key, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            return pieces.Length == 2 ? Uri.UnescapeDataString(pieces[1]) : "";
        }

        return null;
    }

    private static string? DecodeBase64Url(string value)
    {
        try
        {
            var padded = value.Replace('-', '+').Replace('_', '/');
            padded = padded.PadRight(padded.Length + (4 - padded.Length % 4) % 4, '=');
            return Encoding.UTF8.GetString(Convert.FromBase64String(padded));
        }
        catch (FormatException)
        {
            return null;
        }
    }
}
