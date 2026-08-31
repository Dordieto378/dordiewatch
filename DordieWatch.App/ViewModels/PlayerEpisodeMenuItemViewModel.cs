using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using DordieWatch.App.Models;
using DordieWatch.App.Services;

namespace DordieWatch.App.ViewModels;

public sealed partial class PlayerEpisodeMenuItemViewModel(
    EpisodeItem episode,
    bool isCurrent,
    string? fallbackImagePath,
    IImageCache imageCache,
    IVideoPreviewService videoPreviewService) : ViewModelBase
{
    public EpisodeItem Episode => episode;
    public int Number => episode.EpisodeNumber;
    public string Title => $"Episode {episode.EpisodeNumber}";
    public string Description => string.Equals(episode.Title, Title, StringComparison.OrdinalIgnoreCase)
        ? ""
        : episode.Title;
    public bool HasDescription => !string.IsNullOrWhiteSpace(Description);
    public bool IsCurrent => isCurrent;
    public bool IsNotCurrent => !isCurrent;
    public double RowHeight => isCurrent ? 252 : 106;
    public double Progress => episode.Duration > TimeSpan.Zero
        ? Math.Clamp(episode.Position.TotalSeconds / episode.Duration.TotalSeconds, 0, 1)
        : 0;
    public double ProgressPreviewWidth => 132 * Progress;
    public bool HasProgress => Progress > 0.001;

    [ObservableProperty]
    private Bitmap? _thumbnail;

    public async Task LoadThumbnailAsync(CancellationToken cancellationToken)
    {
        Thumbnail ??= await imageCache.LoadAsync(fallbackImagePath, cancellationToken);

        try
        {
            var preview = await videoPreviewService.EnsurePreviewAsync(episode.VideoPath, cancellationToken);
            var thumbnail = await imageCache.LoadAsync(preview.ThumbnailPath, cancellationToken);
            if (thumbnail is not null)
            {
                Thumbnail = thumbnail;
            }
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch
        {
            // Keep the fallback image if preview extraction fails.
        }
    }
}
