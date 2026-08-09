using DordieWatch.App.Models;

namespace DordieWatch.App.Services;

public interface INavigationService
{
    event EventHandler<object?>? CurrentViewModelChanged;
    object? CurrentViewModel { get; }
    void ShowLibrary();
    Task PlayMediaAsync(MediaLibraryItem mediaItem, CancellationToken cancellationToken);
    Task PlayEpisodeAsync(EpisodeItem episode, CancellationToken cancellationToken);
}
