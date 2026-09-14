using Avalonia.Media.Imaging;
using Avalonia.Media;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using DordieWatch.App.Models;
using DordieWatch.App.Services;

namespace DordieWatch.App.ViewModels;

public sealed partial class EpisodeCardViewModel(
    EpisodeItem episode,
    string? fallbackImagePath,
    bool isLatestWatched,
    string? returnCategory,
    IImageCache imageCache,
    IVideoPreviewService videoPreviewService,
    INavigationService navigation) : ViewModelBase
{
    public EpisodeItem Episode => episode;
    public int Number => episode.EpisodeNumber;
    public string Title => $"Episode {episode.EpisodeNumber}";
    public string RuntimeText => episode.Duration > TimeSpan.Zero
        ? $"{(int)episode.Duration.TotalMinutes}m"
        : "";
    public double Progress => episode.Duration > TimeSpan.Zero
        ? Math.Clamp(episode.Position.TotalSeconds / episode.Duration.TotalSeconds, 0, 1)
        : 0;
    public bool HasProgress => Progress > 0.001;
    public bool IsLatestWatched => isLatestWatched;
    public IBrush RowBackground { get; } = isLatestWatched
        ? new SolidColorBrush(Color.FromRgb(52, 52, 52))
        : Brushes.Transparent;

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

    [RelayCommand]
    public Task PlayAsync(CancellationToken cancellationToken)
    {
        return navigation.PlayEpisodeAsync(episode, cancellationToken, returnCategory);
    }
}
