using Avalonia.Media.Imaging;

namespace DordieWatch.App.Services;

public interface IImageCache
{
    Task<Bitmap?> LoadAsync(string? path, CancellationToken cancellationToken);
    void ClearMemoryCache();
}
