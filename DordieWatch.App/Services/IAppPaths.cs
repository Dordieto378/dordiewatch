namespace DordieWatch.App.Services;

public interface IAppPaths
{
    string AppDataDirectory { get; }
    string DatabasePath { get; }
    string VideoLibraryDirectory { get; }
    string ImageCacheDirectory { get; }
    string WebsiteCoverDirectory { get; }
    string PreviewCacheDirectory { get; }
    string DordieListLibraryUrl { get; }
}
