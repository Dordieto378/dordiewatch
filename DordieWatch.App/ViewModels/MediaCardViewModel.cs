using Avalonia.Media.Imaging;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using DordieWatch.App.Models;
using DordieWatch.App.Services;

namespace DordieWatch.App.ViewModels;

public sealed partial class MediaCardViewModel(
    MediaLibraryItem item,
    IImageCache imageCache,
    INavigationService navigation) : ViewModelBase
{
    internal MediaLibraryItem Item => item;

    public long Id => item.Id;
    public string Title => item.Title;
    public string Category => item.Category;
    public string KindText => item.Kind == MediaKind.Series ? "Series" : "Movie";
    public int EpisodeCount => item.EpisodeCount;
    public double Progress => item.Progress;
    public string CountText => item.Kind == MediaKind.Series ? $"{item.EpisodeCount} Episodes" : "";

    [ObservableProperty]
    private Bitmap? _poster;

    public async Task LoadPosterAsync(CancellationToken cancellationToken)
    {
        Poster = await imageCache.LoadAsync(item.PosterPath, cancellationToken);
    }

    [RelayCommand]
    private Task PlayAsync(CancellationToken cancellationToken)
    {
        return navigation.PlayMediaAsync(item, cancellationToken);
    }
}
