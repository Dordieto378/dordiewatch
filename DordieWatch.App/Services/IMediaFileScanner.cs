namespace DordieWatch.App.Services;

public interface IMediaFileScanner
{
    Task<IReadOnlyList<ScannedMediaItem>> ScanAsync(string rootDirectory, CancellationToken cancellationToken);
}
