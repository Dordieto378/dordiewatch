using DordieWatch.App.Models;
using DordieWatch.App.ViewModels;
using Avalonia.Threading;
using Microsoft.Extensions.DependencyInjection;

namespace DordieWatch.App.Services;

public sealed class NavigationService(
    IServiceProvider serviceProvider,
    ILibraryService libraryService) : INavigationService
{
    private LibraryViewModel? _libraryViewModel;
    private long? _playerReturnMediaItemId;
    private string? _playerReturnCategory;

    public event EventHandler<object?>? CurrentViewModelChanged;
    public object? CurrentViewModel { get; private set; }

    public void ShowLibrary(string? category = null)
    {
        var viewModel = GetLibraryViewModel();
        viewModel.ShowHome(NormalizeCategoryOrNull(category) ?? _playerReturnCategory);
        SetCurrent(viewModel);
        if (!viewModel.HasLoaded)
        {
            _ = viewModel.LoadAsync(CancellationToken.None);
        }
    }

    public async Task ShowMediaDetailsAsync(
        MediaLibraryItem mediaItem,
        CancellationToken cancellationToken,
        string? sourceCategory = null)
    {
        var viewModel = GetLibraryViewModel();
        SetCurrent(viewModel);
        await Dispatcher.UIThread.InvokeAsync(
            () => { },
            DispatcherPriority.Render,
            cancellationToken);
        cancellationToken.ThrowIfCancellationRequested();
        await viewModel.OpenDetailsForMediaAsync(mediaItem, cancellationToken, sourceCategory);
    }

    public async Task PlayMediaAsync(
        MediaLibraryItem mediaItem,
        CancellationToken cancellationToken,
        string? sourceCategory = null)
    {
        RememberReturnCategory(mediaItem, sourceCategory);
        var episodes = await libraryService.GetEpisodesAsync(mediaItem.Id, cancellationToken);
        var firstUnfinished = episodes.FirstOrDefault(x => x.Position > TimeSpan.Zero && x.Position < x.Duration - TimeSpan.FromSeconds(30));
        var episode = firstUnfinished ?? episodes.FirstOrDefault();
        if (episode is not null)
        {
            await PlayEpisodeAsync(episode, cancellationToken);
        }
    }

    public async Task PlayEpisodeAsync(
        EpisodeItem episode,
        CancellationToken cancellationToken,
        string? sourceCategory = null)
    {
        if (!string.IsNullOrWhiteSpace(sourceCategory))
        {
            RememberReturnCategory(episode.MediaItemId, sourceCategory);
        }
        else
        {
            await RememberReturnCategoryAsync(episode.MediaItemId, cancellationToken);
        }

        var viewModel = serviceProvider.GetRequiredService<PlayerViewModel>();
        SetCurrent(viewModel);
        await Dispatcher.UIThread.InvokeAsync(
            () => { },
            DispatcherPriority.Render,
            cancellationToken);
        cancellationToken.ThrowIfCancellationRequested();
        await viewModel.OpenAsync(episode, cancellationToken);
    }

    private void SetCurrent(object? viewModel)
    {
        if (!ReferenceEquals(CurrentViewModel, viewModel) && CurrentViewModel is IDisposable disposable)
        {
            disposable.Dispose();
        }

        CurrentViewModel = viewModel;
        CurrentViewModelChanged?.Invoke(this, viewModel);
    }

    private LibraryViewModel GetLibraryViewModel()
    {
        return _libraryViewModel ??= serviceProvider.GetRequiredService<LibraryViewModel>();
    }

    private void RememberReturnCategory(MediaLibraryItem mediaItem, string? sourceCategory = null)
    {
        RememberReturnCategory(mediaItem.Id, sourceCategory ?? mediaItem.Category);
    }

    private void RememberReturnCategory(long mediaItemId, string? sourceCategory)
    {
        _playerReturnMediaItemId = mediaItemId;
        _playerReturnCategory = NormalizeCategoryOrNull(sourceCategory);
    }

    private async Task RememberReturnCategoryAsync(long mediaItemId, CancellationToken cancellationToken)
    {
        if (_playerReturnMediaItemId == mediaItemId && _playerReturnCategory is not null)
        {
            return;
        }

        var mediaItem = (await libraryService.GetLibraryAsync(cancellationToken))
            .FirstOrDefault(item => item.Id == mediaItemId);
        if (mediaItem is not null)
        {
            RememberReturnCategory(mediaItem);
        }
    }

    private static string? NormalizeCategoryOrNull(string? category)
    {
        if (string.IsNullOrWhiteSpace(category))
        {
            return null;
        }

        return string.Equals(category, "hentai", StringComparison.OrdinalIgnoreCase)
            ? "hentai"
            : "anime";
    }
}
