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
    public string DordieListLibraryUrl { get; }

    private string ResolveDordieListLibraryUrl()
    {
        var configuredPath = Path.Combine(AppDataDirectory, "dordielist-library-url.txt");
        if (File.Exists(configuredPath))
        {
            var configured = File.ReadAllText(configuredPath).Trim();
            if (IsAllowedDordieListLibraryUrl(configured))
            {
                return configured;
            }
        }

        return "http://dordielist.test/api/dordiewatch/library";
    }

    private static bool IsAllowedDordieListLibraryUrl(string value)
    {
        return Uri.TryCreate(value, UriKind.Absolute, out var uri)
            && string.Equals(uri.Scheme, "http", StringComparison.OrdinalIgnoreCase)
            && string.Equals(uri.Host, "dordielist.test", StringComparison.OrdinalIgnoreCase)
            && string.Equals(uri.AbsolutePath, "/api/dordiewatch/library", StringComparison.OrdinalIgnoreCase);
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
