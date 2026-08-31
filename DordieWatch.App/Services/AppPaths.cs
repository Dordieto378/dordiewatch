namespace DordieWatch.App.Services;

public sealed class AppPaths : IAppPaths
{
    public AppPaths()
    {
        var root = AppContext.BaseDirectory;

        AppDataDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "DordieWatchCSharp");
        ImageCacheDirectory = Path.Combine(AppDataDirectory, "image-cache");
        WebsiteCoverDirectory = Path.Combine(AppDataDirectory, "website-covers");
        PreviewCacheDirectory = Path.Combine(AppDataDirectory, "previews");
        DatabasePath = Path.Combine(AppDataDirectory, "dordiewatch.db");
        VideoLibraryDirectory = ResolveVideoLibraryDirectory(root);
        DordieListConfigUrl = "http://dordielist.test/api/dordiewatch/config";
        DordieListLibraryUrl = ResolveDordieListLibraryUrl();

        Directory.CreateDirectory(AppDataDirectory);
        Directory.CreateDirectory(ImageCacheDirectory);
        Directory.CreateDirectory(WebsiteCoverDirectory);
        Directory.CreateDirectory(PreviewCacheDirectory);
    }

    public string AppDataDirectory { get; }
    public string DatabasePath { get; }
    public string VideoLibraryDirectory { get; }
    public string ImageCacheDirectory { get; }
    public string WebsiteCoverDirectory { get; }
    public string PreviewCacheDirectory { get; }
    public string DordieListLibraryUrl { get; private set; }
    public string DordieListConfigUrl { get; }

    public bool TrySetDordieListLibraryUrl(string value)
    {
        if (!IsAllowedDordieListLibraryUrl(value))
        {
            return false;
        }

        Directory.CreateDirectory(AppDataDirectory);
        File.WriteAllText(DordieListLibraryUrlPath, value.Trim());
        DordieListLibraryUrl = value.Trim();
        return true;
    }

    public bool IsAllowedDordieListLibraryUrl(string value)
    {
        return IsAllowedDordieListUrl(value, "/api/dordiewatch/library", exactPath: true);
    }

    public bool IsAllowedDordieListMediaUrl(string value)
    {
        return IsAllowedDordieListUrl(value, "/api/dordiewatch/media/", exactPath: false);
    }

    private string ResolveDordieListLibraryUrl()
    {
        if (File.Exists(DordieListLibraryUrlPath))
        {
            var configured = File.ReadAllText(DordieListLibraryUrlPath).Trim();
            if (IsAllowedDordieListLibraryUrl(configured))
            {
                return configured;
            }
        }

        return "http://dordielist.test/api/dordiewatch/library";
    }

    private string DordieListLibraryUrlPath => Path.Combine(AppDataDirectory, "dordielist-library-url.txt");

    private static bool IsAllowedDordieListUrl(string value, string path, bool exactPath)
    {
        return Uri.TryCreate(value, UriKind.Absolute, out var uri)
            && uri.Scheme is "http" or "https"
            && string.Equals(uri.Host, "dordielist.test", StringComparison.OrdinalIgnoreCase)
            && (exactPath
                ? string.Equals(uri.AbsolutePath, path, StringComparison.OrdinalIgnoreCase)
                : uri.AbsolutePath.StartsWith(path, StringComparison.OrdinalIgnoreCase));
    }

    private static string ResolveVideoLibraryDirectory(string startDirectory)
    {
        var repoRoot = FindRepositoryRoot(startDirectory);
        if (repoRoot is not null)
        {
            var publishedVideos = Path.Combine(repoRoot.FullName, "publish", "DordieWatch", "videos");
            if (LooksLikeVideoLibrary(publishedVideos))
            {
                return publishedVideos;
            }

            var repoVideos = Path.Combine(repoRoot.FullName, "videos");
            if (LooksLikeVideoLibrary(repoVideos))
            {
                return repoVideos;
            }
        }

        var current = new DirectoryInfo(startDirectory);
        while (current is not null)
        {
            var candidate = Path.Combine(current.FullName, "videos");
            if (LooksLikeVideoLibrary(candidate))
            {
                return candidate;
            }

            current = current.Parent;
        }

        return Path.Combine(startDirectory, "videos");
    }

    private static DirectoryInfo? FindRepositoryRoot(string startDirectory)
    {
        var current = new DirectoryInfo(startDirectory);
        while (current is not null)
        {
            if (File.Exists(Path.Combine(current.FullName, "DordieWatch.slnx")))
            {
                return current;
            }

            current = current.Parent;
        }

        return null;
    }

    private static bool LooksLikeVideoLibrary(string path)
    {
        if (!Directory.Exists(path))
        {
            return false;
        }

        try
        {
            return Directory.EnumerateDirectories(path).Any()
                || Directory.EnumerateFiles(path).Any();
        }
        catch (IOException)
        {
            return false;
        }
        catch (UnauthorizedAccessException)
        {
            return false;
        }
    }
}
