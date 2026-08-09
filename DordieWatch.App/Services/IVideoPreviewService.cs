namespace DordieWatch.App.Services;

public interface IVideoPreviewService
{
    Task<EpisodePreview> EnsurePreviewAsync(string videoPath, CancellationToken cancellationToken);
}
