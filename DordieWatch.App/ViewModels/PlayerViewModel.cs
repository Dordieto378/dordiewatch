using Avalonia.Media.Imaging;
using Avalonia.Threading;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using DordieWatch.App.Models;
using DordieWatch.App.Services;
using LibVLCSharp.Shared;
using System.Collections.ObjectModel;

namespace DordieWatch.App.ViewModels;

public sealed partial class PlayerViewModel(
    IPlayerService player,
    ILibraryService libraryService,
    IImageCache imageCache,
    IVideoPreviewService videoPreviewService,
    INavigationService navigation) : ViewModelBase, IDisposable
{
    private EpisodeItem? _episode;
    private bool _eventsSubscribed;
    private int _lastNonZeroVolume = 100;
    private readonly PeriodicTimer _saveTimer = new(TimeSpan.FromSeconds(5));
    private readonly CancellationTokenSource _disposeCancellation = new();
    private readonly List<Bitmap> _timelinePreviewFrames = [];
    private CancellationTokenSource? _episodeMenuCancellation;
    private CancellationTokenSource? _timelinePreviewCancellation;
    private IReadOnlyList<EpisodeItem> _episodeMenuEpisodes = [];
    private string? _episodeMenuFallbackImagePath;
    private bool _isChangingEpisode;
    private bool _saveLoopStarted;
    private int _disposeState;

    public ObservableCollection<PlayerEpisodeMenuItemViewModel> EpisodeMenuItems { get; } = [];
    public ObservableCollection<PlayerEpisodeRangeViewModel> PlayerEpisodeRanges { get; } = [];
    public ObservableCollection<PlayerTrackOptionViewModel> AudioTrackOptions { get; } = [];
    public ObservableCollection<PlayerTrackOptionViewModel> SubtitleTrackOptions { get; } = [];

    public event EventHandler? AutoPlayNextEpisodeRequested;

    public MediaPlayer MediaPlayer => player.MediaPlayer;

    [ObservableProperty]
    private string _title = "";

    [ObservableProperty]
    private string _seriesTitle = "";

    [ObservableProperty]
    private TimeSpan _position;

    [ObservableProperty]
    private TimeSpan _duration;

    [ObservableProperty]
    private bool _isTimelinePreviewVisible;

    [ObservableProperty]
    private double _timelinePreviewLeft;

    [ObservableProperty]
    private double _timelinePreviewBubbleLeft;

    [ObservableProperty]
    private string _timelinePreviewText = "00:00";

    [ObservableProperty]
    private Bitmap? _timelinePreviewImage;

    [ObservableProperty]
    private bool _isVolumePopupVisible;

    [ObservableProperty]
    private bool _isEpisodesMenuOpen;

    [ObservableProperty]
    private bool _isEpisodeRangeSelectorOpen;

    [ObservableProperty]
    private bool _isTrackMenuOpen;

    [ObservableProperty]
    private PlayerEpisodeRangeViewModel? _selectedPlayerEpisodeRange;

    [ObservableProperty]
    private double _volumePercent = 100;

    public bool HasTimelinePreviewImage => TimelinePreviewImage is not null;
    public bool IsVolumeMuted => VolumePercent <= 0.5;
    public bool HasVolume => VolumePercent > 0.5;
    public bool IsVolumeLoud => VolumePercent > 50;
    public bool IsEpisodeListMenuVisible => IsEpisodesMenuOpen && !IsEpisodeRangeSelectorOpen;
    public bool IsEpisodeRangeSelectorVisible => IsEpisodesMenuOpen && IsEpisodeRangeSelectorOpen;
    public bool HasNextEpisode
    {
        get
        {
            if (_episode is null)
            {
                return false;
            }

            var currentIndex = _episodeMenuEpisodes
                .Select((episode, index) => new { episode.Id, index })
                .FirstOrDefault(item => item.Id == _episode.Id)?.index ?? -1;

            return currentIndex >= 0
                ? currentIndex + 1 < _episodeMenuEpisodes.Count
                : _episodeMenuEpisodes.Any(episode => episode.EpisodeNumber > _episode.EpisodeNumber);
        }
    }
    public string SelectedPlayerEpisodeRangeLabel => SelectedPlayerEpisodeRange?.Label ?? "Class 1";

    partial void OnTimelinePreviewImageChanged(Bitmap? value)
    {
        OnPropertyChanged(nameof(HasTimelinePreviewImage));
    }

    partial void OnVolumePercentChanged(double value)
    {
        OnPropertyChanged(nameof(IsVolumeMuted));
        OnPropertyChanged(nameof(HasVolume));
        OnPropertyChanged(nameof(IsVolumeLoud));
    }

    partial void OnIsEpisodesMenuOpenChanged(bool value)
    {
        if (!value)
        {
            IsEpisodeRangeSelectorOpen = false;
        }
        else
        {
            IsTrackMenuOpen = false;
            HideVolumePopup();
        }

        OnPropertyChanged(nameof(IsEpisodeListMenuVisible));
        OnPropertyChanged(nameof(IsEpisodeRangeSelectorVisible));
    }

    partial void OnIsTrackMenuOpenChanged(bool value)
    {
        if (!value)
        {
            return;
        }

        HideEpisodesMenu();
        HideVolumePopup();
        RefreshPlaybackTracks();
    }

    partial void OnIsEpisodeRangeSelectorOpenChanged(bool value)
    {
        OnPropertyChanged(nameof(IsEpisodeListMenuVisible));
        OnPropertyChanged(nameof(IsEpisodeRangeSelectorVisible));
    }

    partial void OnSelectedPlayerEpisodeRangeChanged(PlayerEpisodeRangeViewModel? value)
    {
        foreach (var range in PlayerEpisodeRanges)
        {
            range.IsSelected = ReferenceEquals(range, value);
        }

        OnPropertyChanged(nameof(SelectedPlayerEpisodeRangeLabel));
        RebuildEpisodeMenuItems();
    }

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
    public string TimeText => FormatTime(Duration);
    public bool IsPlaying => player.IsPlaying;

    public void Open(EpisodeItem episode)
    {
        _episode = episode;
        Title = $"Episode {episode.EpisodeNumber}";
        ResetEpisodeMenu();
        VolumePercent = player.Volume;
        if (VolumePercent > 0.5)
        {
            _lastNonZeroVolume = Math.Clamp((int)Math.Round(VolumePercent), 1, 100);
        }
        if (!_eventsSubscribed)
        {
            player.PositionChanged += OnPositionChanged;
            player.PlaybackEnded += OnPlaybackEnded;
            player.TracksChanged += OnTracksChanged;
            _eventsSubscribed = true;
        }

        player.Play(episode.VideoPath, episode.ExternalSubtitlePath, episode.Position);
        if (!_saveLoopStarted)
        {
            _saveLoopStarted = true;
            _ = SaveProgressLoopAsync(_disposeCancellation.Token);
        }

        _timelinePreviewCancellation?.Cancel();
        _timelinePreviewCancellation?.Dispose();
        _timelinePreviewCancellation = CancellationTokenSource.CreateLinkedTokenSource(_disposeCancellation.Token);
        _ = LoadTimelinePreviewFramesAsync(episode.VideoPath, _timelinePreviewCancellation.Token);
        _ = LoadEpisodeMenuAsync(episode);
    }

    [RelayCommand]
    private void TogglePause()
    {
        player.TogglePause();
        OnPropertyChanged(nameof(IsPlaying));
        _ = RefreshIsPlayingAsync();
    }

    [RelayCommand]
    private void SkipBackward()
    {
        var target = player.Position - TimeSpan.FromSeconds(10);
        player.Seek(target < TimeSpan.Zero ? TimeSpan.Zero : target);
    }

    [RelayCommand]
    private void SkipForward()
    {
        var target = player.Position + TimeSpan.FromSeconds(10);
        var duration = player.Duration;
        if (duration > TimeSpan.Zero && target > duration)
        {
            target = duration;
        }

        player.Seek(target);
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

    public void UpdateTimelinePreview(double pointerX, double timelineWidth)
    {
        if (timelineWidth <= 0 || DurationSeconds <= 1)
        {
            IsTimelinePreviewVisible = false;
            return;
        }

        var clampedX = Math.Clamp(pointerX, 0, timelineWidth);
        var ratio = clampedX / timelineWidth;
        var seconds = DurationSeconds * ratio;

        TimelinePreviewText = FormatTime(TimeSpan.FromSeconds(seconds));
        TimelinePreviewLeft = Math.Clamp(clampedX - 75, 0, Math.Max(0, timelineWidth - 150));
        TimelinePreviewBubbleLeft = Math.Clamp(clampedX - 34, 0, Math.Max(0, timelineWidth - 68));
        if (_timelinePreviewFrames.Count > 0)
        {
            var frameIndex = Math.Clamp(
                (int)Math.Floor(ratio * _timelinePreviewFrames.Count),
                0,
                _timelinePreviewFrames.Count - 1);
            TimelinePreviewImage = _timelinePreviewFrames[frameIndex];
        }

        IsTimelinePreviewVisible = true;
    }

    public void SeekFromTimelinePointer(double pointerX, double timelineWidth)
    {
        if (timelineWidth <= 0 || DurationSeconds <= 1)
        {
            return;
        }

        var clampedX = Math.Clamp(pointerX, 0, timelineWidth);
        var ratio = clampedX / timelineWidth;
        player.Seek(TimeSpan.FromSeconds(DurationSeconds * ratio));
    }

    public void HideTimelinePreview()
    {
        IsTimelinePreviewVisible = false;
    }

    public void ShowVolumePopup()
    {
        HideEpisodesMenu();
        HideTrackMenu();
        VolumePercent = player.Volume;
        IsVolumePopupVisible = true;
    }

    public void HideVolumePopup()
    {
        IsVolumePopupVisible = false;
    }

    public void ToggleVolumePopup()
    {
        if (IsVolumePopupVisible)
        {
            HideVolumePopup();
        }
        else
        {
            ShowVolumePopup();
        }
    }

    public void HandleVolumeButtonClick()
    {
        if (!IsVolumePopupVisible)
        {
            ShowVolumePopup();
            return;
        }

        if (VolumePercent > 0.5)
        {
            _lastNonZeroVolume = Math.Clamp((int)Math.Round(VolumePercent), 1, 100);
            player.Volume = 0;
            VolumePercent = 0;
            return;
        }

        var restoredVolume = Math.Clamp(_lastNonZeroVolume, 1, 100);
        player.Volume = restoredVolume;
        VolumePercent = restoredVolume;
        IsVolumePopupVisible = true;
    }

    public void ToggleEpisodesMenu()
    {
        IsEpisodesMenuOpen = !IsEpisodesMenuOpen;
    }

    public void ToggleTrackMenu()
    {
        IsTrackMenuOpen = !IsTrackMenuOpen;
    }

    public void HideTrackMenu()
    {
        IsTrackMenuOpen = false;
    }

    public void SelectAudioTrack(PlayerTrackOptionViewModel option)
    {
        if (player.SelectAudioTrack(option.Id))
        {
            RefreshPlaybackTracks();
            HideTrackMenu();
        }
    }

    public void SelectSubtitleTrack(PlayerTrackOptionViewModel option)
    {
        if (player.SelectSubtitleTrack(option.Id))
        {
            RefreshPlaybackTracks();
            HideTrackMenu();
        }
    }

    public void HideEpisodesMenu()
    {
        IsEpisodesMenuOpen = false;
    }

    public void ShowEpisodeRangeSelector()
    {
        IsEpisodesMenuOpen = true;
        IsEpisodeRangeSelectorOpen = true;
    }

    public void SelectPlayerEpisodeRange(PlayerEpisodeRangeViewModel range)
    {
        SelectedPlayerEpisodeRange = range;
        IsEpisodesMenuOpen = true;
        IsEpisodeRangeSelectorOpen = false;
    }

    public async Task PlayEpisodeFromMenuAsync(PlayerEpisodeMenuItemViewModel item)
    {
        if (_episode is not null && item.Episode.Id == _episode.Id)
        {
            return;
        }

        await SaveProgressAsync(CancellationToken.None);
        HideEpisodesMenu();
        await navigation.PlayEpisodeAsync(item.Episode, CancellationToken.None);
    }

    public async Task PlayNextEpisodeAsync()
    {
        if (_episode is null || _isChangingEpisode)
        {
            return;
        }

        _isChangingEpisode = true;
        try
        {
            var episodes = _episodeMenuEpisodes.Count > 0
                ? _episodeMenuEpisodes
                : await libraryService.GetEpisodesAsync(_episode.MediaItemId, CancellationToken.None);
            var currentIndex = episodes
                .Select((episode, index) => new { episode.Id, index })
                .FirstOrDefault(item => item.Id == _episode.Id)?.index ?? -1;
            var nextEpisode = currentIndex >= 0 && currentIndex + 1 < episodes.Count
                ? episodes[currentIndex + 1]
                : episodes.FirstOrDefault(episode => episode.EpisodeNumber > _episode.EpisodeNumber);

            if (nextEpisode is null)
            {
                return;
            }

            await SaveProgressAsync(CancellationToken.None);
            HideEpisodesMenu();
            HideTrackMenu();

            var playbackStarted = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            void OnPlaybackStarted(object? sender, EventArgs e) => playbackStarted.TrySetResult(true);

            player.PlaybackStarted += OnPlaybackStarted;
            try
            {
                Open(nextEpisode);
                await playbackStarted.Task.WaitAsync(TimeSpan.FromSeconds(20));
            }
            catch (TimeoutException)
            {
                // Do not leave the loading screen stuck forever if a file cannot start.
            }
            finally
            {
                player.PlaybackStarted -= OnPlaybackStarted;
            }
        }
        finally
        {
            _isChangingEpisode = false;
        }
    }

    public void SetVolumeFromSliderPointer(double pointerY, double sliderHeight)
    {
        if (sliderHeight <= 0)
        {
            return;
        }

        var ratio = 1 - Math.Clamp(pointerY / sliderHeight, 0, 1);
        var volume = (int)Math.Round(ratio * 100);
        player.Volume = volume;
        VolumePercent = volume;
        if (volume > 0)
        {
            _lastNonZeroVolume = volume;
        }
        IsVolumePopupVisible = true;
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

    private void OnTracksChanged(object? sender, EventArgs e)
    {
        Dispatcher.UIThread.Post(RefreshPlaybackTracks);
    }

    private void RefreshPlaybackTracks()
    {
        try
        {
            ReplaceTrackOptions(AudioTrackOptions, player.GetAudioTracks(), player.SelectedAudioTrackId);

            var subtitleTracks = new[] { new PlaybackTrackInfo(-1, "Off") }
                .Concat(player.GetSubtitleTracks());
            ReplaceTrackOptions(SubtitleTrackOptions, subtitleTracks, player.SelectedSubtitleTrackId);
        }
        catch (ObjectDisposedException)
        {
            // Native track events can arrive while the player is closing.
        }
    }

    private static void ReplaceTrackOptions(
        ObservableCollection<PlayerTrackOptionViewModel> target,
        IEnumerable<PlaybackTrackInfo> tracks,
        int selectedTrackId)
    {
        var options = tracks
            .GroupBy(track => track.Id)
            .Select(group => group.First())
            .ToArray();

        target.Clear();
        foreach (var track in options)
        {
            target.Add(new PlayerTrackOptionViewModel(
                track.Id,
                track.Name,
                track.Id == selectedTrackId));
        }
    }

    private static string FormatTime(TimeSpan value)
    {
        return value.TotalHours >= 1
            ? $"{(int)value.TotalHours}:{value:mm\\:ss}"
            : $"{value:mm\\:ss}";
    }

    private async void OnPlaybackEnded(object? sender, EventArgs e)
    {
        if (HasNextEpisode)
        {
            Dispatcher.UIThread.Post(() => AutoPlayNextEpisodeRequested?.Invoke(this, EventArgs.Empty));
            return;
        }

        await SaveProgressAsync(CancellationToken.None);
    }

    private async Task RefreshIsPlayingAsync()
    {
        await Task.Delay(80);
        OnPropertyChanged(nameof(IsPlaying));
        await Task.Delay(160);
        OnPropertyChanged(nameof(IsPlaying));
    }

    private async Task LoadTimelinePreviewFramesAsync(string videoPath, CancellationToken cancellationToken)
    {
        try
        {
            await Dispatcher.UIThread.InvokeAsync(() =>
            {
                _timelinePreviewFrames.Clear();
                TimelinePreviewImage = null;
            });

            // Let VLC establish playback before FFmpeg starts decoding the same file.
            await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken);

            var preview = await videoPreviewService.EnsurePreviewAsync(videoPath, cancellationToken);
            var paths = preview.FramePaths.Count > 0
                ? preview.FramePaths
                : preview.ThumbnailPath is not null
                    ? [preview.ThumbnailPath]
                    : [];

            foreach (var path in paths)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var bitmap = await imageCache.LoadAsync(path, cancellationToken);
                if (bitmap is null)
                {
                    continue;
                }

                await Dispatcher.UIThread.InvokeAsync(() =>
                {
                    _timelinePreviewFrames.Add(bitmap);
                    TimelinePreviewImage ??= bitmap;
                });
            }
        }
        catch (OperationCanceledException)
        {
            // Expected when leaving the player.
        }
        catch
        {
            // Preview thumbnails are optional. The timeline still works without them.
        }
    }

    private void ResetEpisodeMenu()
    {
        _episodeMenuCancellation?.Cancel();
        _episodeMenuCancellation?.Dispose();
        _episodeMenuCancellation = CancellationTokenSource.CreateLinkedTokenSource(_disposeCancellation.Token);
        _episodeMenuEpisodes = [];
        _episodeMenuFallbackImagePath = null;
        OnPropertyChanged(nameof(HasNextEpisode));

        SeriesTitle = "";
        IsEpisodesMenuOpen = false;
        IsTrackMenuOpen = false;
        IsEpisodeRangeSelectorOpen = false;
        SelectedPlayerEpisodeRange = null;
        EpisodeMenuItems.Clear();
        PlayerEpisodeRanges.Clear();
        AudioTrackOptions.Clear();
        SubtitleTrackOptions.Clear();
    }

    private async Task LoadEpisodeMenuAsync(EpisodeItem currentEpisode)
    {
        var cancellationToken = _episodeMenuCancellation?.Token ?? _disposeCancellation.Token;

        try
        {
            var libraryTask = libraryService.GetLibraryAsync(cancellationToken);
            var episodesTask = libraryService.GetEpisodesAsync(currentEpisode.MediaItemId, cancellationToken);
            await Task.WhenAll(libraryTask, episodesTask);

            var mediaItem = libraryTask.Result.FirstOrDefault(item => item.Id == currentEpisode.MediaItemId);
            var episodes = episodesTask.Result.Count > 0
                ? episodesTask.Result
                : [currentEpisode];

            cancellationToken.ThrowIfCancellationRequested();
            await Dispatcher.UIThread.InvokeAsync(() =>
            {
                SeriesTitle = mediaItem?.Title ?? "Episodes";
                _episodeMenuEpisodes = episodes;
                _episodeMenuFallbackImagePath = mediaItem?.BackdropPath ?? mediaItem?.PosterPath;
                OnPropertyChanged(nameof(HasNextEpisode));
                BuildPlayerEpisodeRanges(currentEpisode.Id);
            }, DispatcherPriority.Render, cancellationToken);
        }
        catch (OperationCanceledException)
        {
            // Expected when changing player episodes or leaving the player.
        }
    }

    private void BuildPlayerEpisodeRanges(long currentEpisodeId)
    {
        PlayerEpisodeRanges.Clear();
        const int pageSize = 12;
        var count = Math.Max(1, _episodeMenuEpisodes.Count);

        for (var start = 0; start < count; start += pageSize)
        {
            PlayerEpisodeRanges.Add(new PlayerEpisodeRangeViewModel(
                start,
                Math.Min(start + pageSize, count)));
        }

        var currentIndex = Math.Max(0, _episodeMenuEpisodes
            .Select((episode, index) => new { episode.Id, index })
            .FirstOrDefault(x => x.Id == currentEpisodeId)?.index ?? 0);

        SelectedPlayerEpisodeRange = PlayerEpisodeRanges.FirstOrDefault(range =>
            currentIndex >= range.StartIndex && currentIndex < range.EndIndex)
            ?? PlayerEpisodeRanges.FirstOrDefault();
    }

    private void RebuildEpisodeMenuItems()
    {
        EpisodeMenuItems.Clear();
        if (_episode is null || _episodeMenuEpisodes.Count == 0)
        {
            return;
        }

        var range = SelectedPlayerEpisodeRange;
        var start = range?.StartIndex ?? 0;
        var end = range?.EndIndex ?? Math.Min(12, _episodeMenuEpisodes.Count);
        var page = _episodeMenuEpisodes
            .Skip(start)
            .Take(Math.Max(0, end - start))
            .Select(episode => new PlayerEpisodeMenuItemViewModel(
                episode,
                episode.Id == _episode.Id,
                _episodeMenuFallbackImagePath,
                imageCache,
                videoPreviewService))
            .ToArray();

        foreach (var item in page)
        {
            EpisodeMenuItems.Add(item);
        }

        var cancellationToken = _episodeMenuCancellation?.Token ?? _disposeCancellation.Token;
        _ = LoadEpisodeMenuThumbnailsSequentiallyAsync(page, cancellationToken);
    }

    private static async Task LoadEpisodeMenuThumbnailsSequentiallyAsync(
        IReadOnlyList<PlayerEpisodeMenuItemViewModel> page,
        CancellationToken cancellationToken)
    {
        foreach (var item in page)
        {
            cancellationToken.ThrowIfCancellationRequested();
            await item.LoadThumbnailAsync(cancellationToken);
        }
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
        if (Interlocked.Exchange(ref _disposeState, 1) != 0)
        {
            return;
        }

        _disposeCancellation.Cancel();
        _episodeMenuCancellation?.Cancel();
        _episodeMenuCancellation?.Dispose();
        _timelinePreviewCancellation?.Cancel();
        _timelinePreviewCancellation?.Dispose();
        _disposeCancellation.Dispose();
        _saveTimer.Dispose();
        if (_eventsSubscribed)
        {
            player.PositionChanged -= OnPositionChanged;
            player.PlaybackEnded -= OnPlaybackEnded;
            player.TracksChanged -= OnTracksChanged;
        }
    }
}
