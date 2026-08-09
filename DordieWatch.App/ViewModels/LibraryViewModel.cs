using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Avalonia.Media.Imaging;
using DordieWatch.App.Models;
using DordieWatch.App.Services;
using LibVLCSharp.Shared;
using System.Collections.ObjectModel;

namespace DordieWatch.App.ViewModels;

public sealed partial class LibraryViewModel(
    ILibraryService libraryService,
    IImageCache imageCache,
    IVideoPreviewService videoPreviewService,
    IPreviewPlayerService previewPlayer,
    INavigationService navigation,
    IAppPaths appPaths) : ViewModelBase
{
    private CancellationTokenSource? _loadCancellation;
    private CancellationTokenSource? _detailsCancellation;
    private MediaCardViewModel? _selectedCard;
    private IReadOnlyList<EpisodeItem> _selectedEpisodeItems = [];
    private List<MediaCardViewModel> _allItems = [];

    public ObservableCollection<MediaCardViewModel> Items { get; } = [];
    public ObservableCollection<EpisodeCardViewModel> SelectedEpisodes { get; } = [];
    public ObservableCollection<EpisodeRangeViewModel> EpisodeRanges { get; } = [];
    public MediaPlayer PreviewMediaPlayer => previewPlayer.MediaPlayer;

    [ObservableProperty]
    private bool _isBusy;

    [ObservableProperty]
    private string _statusText = "";

    [ObservableProperty]
    private string _activeCategory = "anime";

    public string AnimeNavForeground => ActiveCategory == "anime" ? "#FFFFFF" : "#A8A8A8";
    public string HentaiNavForeground => ActiveCategory == "hentai" ? "#FFFFFF" : "#A8A8A8";
    public bool IsAnimeActive => ActiveCategory == "anime";
    public bool IsHentaiActive => ActiveCategory == "hentai";

    partial void OnActiveCategoryChanged(string value)
    {
        OnPropertyChanged(nameof(AnimeNavForeground));
        OnPropertyChanged(nameof(HentaiNavForeground));
        OnPropertyChanged(nameof(IsAnimeActive));
        OnPropertyChanged(nameof(IsHentaiActive));
        ApplyCategoryFilter();
        _ = LoadVisiblePostersAsync(CancellationToken.None);
    }

    [ObservableProperty]
    private bool _isDetailsOpen;

    [ObservableProperty]
    private string _selectedTitle = "";

    [ObservableProperty]
    private string _selectedCountText = "";

    [ObservableProperty]
    private bool _isSelectedSeries;

    [ObservableProperty]
    private Bitmap? _selectedPoster;

    [ObservableProperty]
    private Bitmap? _selectedBackdrop;

    [ObservableProperty]
    private EpisodeRangeViewModel? _selectedEpisodeRange;

    [ObservableProperty]
    private bool _hasEpisodeRanges;

    partial void OnSelectedEpisodeRangeChanged(EpisodeRangeViewModel? value)
    {
        _ = RebuildSelectedEpisodePageAsync(value, CancellationToken.None);
    }

    [RelayCommand]
    public async Task LoadAsync(CancellationToken cancellationToken)
    {
        await LoadFromDatabaseAsync(cancellationToken);
        if (_allItems.Count == 0)
        {
            await RefreshAsync(cancellationToken);
        }
    }

    [RelayCommand]
    private async Task RefreshAsync(CancellationToken cancellationToken)
    {
        IsBusy = true;
        StatusText = $"Scanning: {appPaths.VideoLibraryDirectory}";
        try
        {
            var items = await libraryService.RefreshAsync(cancellationToken);
            await ReplaceItemsAsync(items, cancellationToken);
            StatusText = $"{Items.Count} titles - {appPaths.VideoLibraryDirectory}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task LoadFromDatabaseAsync(CancellationToken cancellationToken)
    {
        IsBusy = true;
        try
        {
            var items = await libraryService.GetLibraryAsync(cancellationToken);
            await ReplaceItemsAsync(items, cancellationToken);
            StatusText = Items.Count == 0 ? $"No titles found - {appPaths.VideoLibraryDirectory}" : $"{Items.Count} titles - {appPaths.VideoLibraryDirectory}";
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task ReplaceItemsAsync(
        IReadOnlyList<MediaLibraryItem> items,
        CancellationToken cancellationToken)
    {
        _loadCancellation?.Cancel();
        _loadCancellation?.Dispose();
        _loadCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);

        _allItems = items.Select(item => new MediaCardViewModel(item, imageCache, navigation)).ToList();
        ApplyCategoryFilter();

        await LoadVisiblePostersAsync(_loadCancellation.Token);
    }

    [RelayCommand]
    private void SetCategory(string? category)
    {
        ActiveCategory = string.Equals(category, "hentai", StringComparison.OrdinalIgnoreCase)
            ? "hentai"
            : "anime";
    }

    private void ApplyCategoryFilter()
    {
        Items.Clear();
        foreach (var item in _allItems.Where(item => item.Category == ActiveCategory))
        {
            Items.Add(item);
        }
    }

    private Task LoadVisiblePostersAsync(CancellationToken cancellationToken)
    {
        return Task.WhenAll(Items.Take(36).Select(x => x.LoadPosterAsync(cancellationToken)));
    }

    [RelayCommand]
    private async Task OpenDetailsAsync(MediaCardViewModel? card, CancellationToken cancellationToken)
    {
        if (card is null)
        {
            return;
        }

        _detailsCancellation?.Cancel();
        _detailsCancellation?.Dispose();
        _detailsCancellation = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        var token = _detailsCancellation.Token;

        _selectedCard = card;
        SelectedTitle = card.Title;
        SelectedCountText = card.CountText;
        IsSelectedSeries = card.Item.Kind == MediaKind.Series;
        IsDetailsOpen = true;
        SelectedEpisodes.Clear();
        EpisodeRanges.Clear();
        HasEpisodeRanges = false;

        var imagePath = card.Item.BackdropPath ?? card.Item.PosterPath;
        var posterTask = imageCache.LoadAsync(card.Item.PosterPath, token);
        var backdropTask = imageCache.LoadAsync(imagePath, token);
        var episodesTask = libraryService.GetEpisodesAsync(card.Id, token);

        await Task.WhenAll(posterTask, backdropTask, episodesTask);
        token.ThrowIfCancellationRequested();

        SelectedPoster = posterTask.Result;
        SelectedBackdrop = backdropTask.Result ?? posterTask.Result;
        _selectedEpisodeItems = episodesTask.Result;
        var previewEpisode = _selectedEpisodeItems.FirstOrDefault();
        if (previewEpisode is not null)
        {
            previewPlayer.PlayLoop(previewEpisode.VideoPath);
        }

        BuildEpisodeRanges();
        SelectedEpisodeRange = EpisodeRanges.FirstOrDefault();
        if (SelectedEpisodeRange is null)
        {
            await RebuildSelectedEpisodePageAsync(null, token);
        }
    }

    [RelayCommand]
    private void CloseDetails()
    {
        IsDetailsOpen = false;
        previewPlayer.Stop();
        _detailsCancellation?.Cancel();
    }

    [RelayCommand]
    private async Task PlaySelectedAsync(CancellationToken cancellationToken)
    {
        if (_selectedCard is null)
        {
            return;
        }

        await navigation.PlayMediaAsync(_selectedCard.Item, cancellationToken);
    }

    private void BuildEpisodeRanges()
    {
        EpisodeRanges.Clear();
        if (_selectedEpisodeItems.Count <= 12)
        {
            HasEpisodeRanges = false;
            return;
        }

        for (var start = 0; start < _selectedEpisodeItems.Count; start += 12)
        {
            EpisodeRanges.Add(new EpisodeRangeViewModel(start, Math.Min(start + 12, _selectedEpisodeItems.Count)));
        }

        HasEpisodeRanges = EpisodeRanges.Count > 0;
    }

    private async Task RebuildSelectedEpisodePageAsync(EpisodeRangeViewModel? range, CancellationToken cancellationToken)
    {
        SelectedEpisodes.Clear();
        if (!IsSelectedSeries || _selectedEpisodeItems.Count == 0)
        {
            return;
        }

        var start = range?.StartIndex ?? 0;
        var end = range?.EndIndex ?? Math.Min(12, _selectedEpisodeItems.Count);
        var imagePath = _selectedCard?.Item.BackdropPath ?? _selectedCard?.Item.PosterPath;
        var page = _selectedEpisodeItems.Skip(start).Take(end - start)
            .Select(episode => new EpisodeCardViewModel(episode, imagePath, imageCache, videoPreviewService, navigation))
            .ToArray();

        foreach (var episode in page)
        {
            SelectedEpisodes.Add(episode);
        }

        await Task.WhenAll(page.Select(x => x.LoadThumbnailAsync(cancellationToken)));
    }
}
