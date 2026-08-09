using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using DordieWatch.App.Models;
using DordieWatch.App.Services;

namespace DordieWatch.App.ViewModels;

public sealed partial class EpisodeCardViewModel(
    EpisodeItem episode,
    string? fallbackImagePath,
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

    [ObservableProperty]
    private Bitmap? _thumbnail;

    public async Task LoadThumbnailAsync(CancellationToken cancellationToken)
    {
        var preview = await videoPreviewService.EnsurePreviewAsync(episode.VideoPath, cancellationToken);
        Thumbnail = await imageCache.LoadAsync(preview.ThumbnailPath ?? fallbackImagePath, cancellationToken);
    }

    [RelayCommand]
    private Task PlayAsync(CancellationToken cancellationToken)
    {
        return navigation.PlayEpisodeAsync(episode, cancellationToken);
    }
}
