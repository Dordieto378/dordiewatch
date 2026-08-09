using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using DordieWatch.App.Models;
using DordieWatch.App.Services;
using LibVLCSharp.Shared;

namespace DordieWatch.App.ViewModels;

public sealed partial class PlayerViewModel(
    IPlayerService player,
    ILibraryService libraryService,
    INavigationService navigation) : ViewModelBase, IDisposable
{
    private EpisodeItem? _episode;
    private bool _eventsSubscribed;
    private readonly PeriodicTimer _saveTimer = new(TimeSpan.FromSeconds(5));
    private readonly CancellationTokenSource _disposeCancellation = new();

    public MediaPlayer MediaPlayer => player.MediaPlayer;

    [ObservableProperty]
    private string _title = "";

    [ObservableProperty]
    private TimeSpan _position;

    [ObservableProperty]
    private TimeSpan _duration;

    public double PositionSeconds
    {
        get => Position.TotalSeconds;
        set
        {
            if (Math.Abs(value - Position.TotalSeconds) > 1.0)
            {
                player.Seek(TimeSpan.FromSeconds(value));
            }
        }
    }

    public double DurationSeconds => Math.Max(1, Duration.TotalSeconds);
    public string TimeText => $"{Position:mm\\:ss} / {Duration:mm\\:ss}";
    public bool IsPlaying => player.IsPlaying;

    public void Open(EpisodeItem episode)
    {
        _episode = episode;
        Title = $"Episode {episode.EpisodeNumber}";
        if (!_eventsSubscribed)
        {
            player.PositionChanged += OnPositionChanged;
            player.PlaybackEnded += OnPlaybackEnded;
            _eventsSubscribed = true;
        }

        player.Play(episode.VideoPath, episode.ExternalSubtitlePath, episode.Position);
        _ = SaveProgressLoopAsync(_disposeCancellation.Token);
    }

    [RelayCommand]
    private void TogglePause()
    {
        player.TogglePause();
        OnPropertyChanged(nameof(IsPlaying));
    }

    [RelayCommand]
    private async Task BackAsync()
    {
        await SaveProgressAsync(CancellationToken.None);
        player.Stop();
        navigation.ShowLibrary();
    }

    [RelayCommand]
    private void Seek(double seconds)
    {
        player.Seek(TimeSpan.FromSeconds(seconds));
    }

    private void OnPositionChanged(object? sender, EventArgs e)
    {
        Position = player.Position;
        Duration = player.Duration;
        OnPropertyChanged(nameof(PositionSeconds));
        OnPropertyChanged(nameof(DurationSeconds));
        OnPropertyChanged(nameof(TimeText));
        OnPropertyChanged(nameof(IsPlaying));
    }

    private async void OnPlaybackEnded(object? sender, EventArgs e)
    {
        await SaveProgressAsync(CancellationToken.None);
    }

    private async Task SaveProgressLoopAsync(CancellationToken cancellationToken)
    {
        try
        {
            while (await _saveTimer.WaitForNextTickAsync(cancellationToken))
            {
                await SaveProgressAsync(cancellationToken);
            }
        }
        catch (OperationCanceledException)
        {
            // Expected on disposal/navigation.
        }
    }

    private Task SaveProgressAsync(CancellationToken cancellationToken)
    {
        if (_episode is null)
        {
            return Task.CompletedTask;
        }

        return libraryService.SaveProgressAsync(_episode.Id, player.Position, player.Duration, cancellationToken);
    }

    public void Dispose()
    {
        _disposeCancellation.Cancel();
        _disposeCancellation.Dispose();
        _saveTimer.Dispose();
        if (_eventsSubscribed)
        {
            player.PositionChanged -= OnPositionChanged;
            player.PlaybackEnded -= OnPlaybackEnded;
        }
    }
}
