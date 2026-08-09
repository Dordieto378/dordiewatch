using Avalonia.Media.Imaging;
using System.Collections.Concurrent;

namespace DordieWatch.App.Services;

public sealed class ImageCache : IImageCache, IDisposable
{
    private readonly ConcurrentDictionary<string, Lazy<Task<Bitmap?>>> _memory = new(StringComparer.OrdinalIgnoreCase);

    public Task<Bitmap?> LoadAsync(string? path, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(path) || !File.Exists(path))
        {
            return Task.FromResult<Bitmap?>(null);
        }

        var lazy = _memory.GetOrAdd(
            path,
            key => new Lazy<Task<Bitmap?>>(() => LoadBitmapAsync(key, cancellationToken)));
        return lazy.Value;
    }

    public void ClearMemoryCache()
    {
        foreach (var item in _memory.Values)
        {
            if (item.IsValueCreated && item.Value.IsCompletedSuccessfully)
            {
                item.Value.Result?.Dispose();
            }
        }

        _memory.Clear();
    }

    public void Dispose() => ClearMemoryCache();

    private static Task<Bitmap?> LoadBitmapAsync(string path, CancellationToken cancellationToken)
    {
        return Task.Run(() =>
        {
            cancellationToken.ThrowIfCancellationRequested();
            try
            {
                using var stream = File.OpenRead(path);
                return (Bitmap?)new Bitmap(stream);
            }
            catch (IOException)
            {
                return null;
            }
            catch (UnauthorizedAccessException)
            {
                return null;
            }
        }, cancellationToken);
    }
}
