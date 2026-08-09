using DordieWatch.App.Models;
using DordieWatch.App.ViewModels;
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

    public Task PlayEpisodeAsync(EpisodeItem episode, CancellationToken cancellationToken)
    {
        var viewModel = serviceProvider.GetRequiredService<PlayerViewModel>();
        viewModel.Open(episode);
        SetCurrent(viewModel);
        return Task.CompletedTask;
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
