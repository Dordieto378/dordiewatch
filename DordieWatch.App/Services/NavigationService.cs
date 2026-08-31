using DordieWatch.App.Models;
using DordieWatch.App.ViewModels;
using Avalonia.Threading;
using Microsoft.Extensions.DependencyInjection;

namespace DordieWatch.App.Services;

public sealed class NavigationService(
    IServiceProvider serviceProvider,
    ILibraryService libraryService) : INavigationService
{
    public event EventHandler<object?>? CurrentViewModelChanged;
    public object? CurrentViewModel { get; private set; }

    public void ShowLibrary()
    {
        var viewModel = serviceProvider.GetRequiredService<LibraryViewModel>();
        SetCurrent(viewModel);
        _ = viewModel.LoadAsync(CancellationToken.None);
    }

    public async Task ShowMediaDetailsAsync(MediaLibraryItem mediaItem, CancellationToken cancellationToken)
    {
        var viewModel = serviceProvider.GetRequiredService<LibraryViewModel>();
        SetCurrent(viewModel);
        await Dispatcher.UIThread.InvokeAsync(
            () => { },
            DispatcherPriority.Render,
            cancellationToken);
        cancellationToken.ThrowIfCancellationRequested();
        await viewModel.OpenDetailsForMediaAsync(mediaItem, cancellationToken);
    }

    public async Task PlayMediaAsync(MediaLibraryItem mediaItem, CancellationToken cancellationToken)
    {
        var episodes = await libraryService.GetEpisodesAsync(mediaItem.Id, cancellationToken);
        var firstUnfinished = episodes.FirstOrDefault(x => x.Position > TimeSpan.Zero && x.Position < x.Duration - TimeSpan.FromSeconds(30));
        var episode = firstUnfinished ?? episodes.FirstOrDefault();
        if (episode is not null)
        {
            await PlayEpisodeAsync(episode, cancellationToken);
        }
    }

    public async Task PlayEpisodeAsync(EpisodeItem episode, CancellationToken cancellationToken)
    {
        var viewModel = serviceProvider.GetRequiredService<PlayerViewModel>();
        SetCurrent(viewModel);
        await Dispatcher.UIThread.InvokeAsync(
            () => { },
            DispatcherPriority.Render,
            cancellationToken);
        cancellationToken.ThrowIfCancellationRequested();
        viewModel.Open(episode);
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
}
