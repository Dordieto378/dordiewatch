using DordieWatch.App.Models;

namespace DordieWatch.App.Services;

public interface INavigationService
{
    event EventHandler<object?>? CurrentViewModelChanged;
    object? CurrentViewModel { get; }
    void ShowLibrary(string? category = null);
    Task ShowMediaDetailsAsync(MediaLibraryItem mediaItem, CancellationToken cancellationToken, string? sourceCategory = null);
    Task PlayMediaAsync(MediaLibraryItem mediaItem, CancellationToken cancellationToken, string? sourceCategory = null);
    Task PlayEpisodeAsync(EpisodeItem episode, CancellationToken cancellationToken, string? sourceCategory = null);
}
