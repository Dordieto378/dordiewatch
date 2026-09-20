using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Avalonia.Media.Imaging;
using DordieWatch.App.Models;
using DordieWatch.App.Services;
using System.Collections.ObjectModel;

namespace DordieWatch.App.ViewModels;

public sealed partial class LibraryViewModel(
    ILibraryService libraryService,
    IImageCache imageCache,
    IVideoPreviewService videoPreviewService,
    INavigationService navigation,
    IAppPaths appPaths) : ViewModelBase
{
    private CancellationTokenSource? _loadCancellation;
    private CancellationTokenSource? _detailsCancellation;
    private MediaCardViewModel? _selectedCard;
    private IReadOnlyList<EpisodeItem> _selectedEpisodeItems = [];
    private List<MediaCardViewModel> _allItems = [];
    private readonly Dictionary<string, double> _homeScrollOffsets = new(StringComparer.OrdinalIgnoreCase);

    public ObservableCollection<MediaCardViewModel> Items { get; } = [];
    public ObservableCollection<EpisodeCardViewModel> SelectedEpisodes { get; } = [];
    public ObservableCollection<EpisodeRangeViewModel> EpisodeRanges { get; } = [];

    [ObservableProperty]
    private bool _isBusy;

    [ObservableProperty]
    private string _statusText = "";

    [ObservableProperty]
    private string _activeCategory = "anime";

    [ObservableProperty]
    private bool _isSearchOpen;

    [ObservableProperty]
    private string _searchText = "";

    [ObservableProperty]
    private double _homeScrollOffset;

    [ObservableProperty]
    private double _homeGridItemWidth = 204;

    [ObservableProperty]
    private double _homeGridItemHeight = 337;

    [ObservableProperty]
    private double _homePosterCardWidth = 190;

    [ObservableProperty]
    private double _homePosterCardHeight = 315;

    [ObservableProperty]
    private double _homePosterImageHeight = 285;

    public string AnimeNavForeground => ActiveCategory == "anime" ? "#FFFFFF" : "#A8A8A8";
    public string MovieNavForeground => ActiveCategory == "movie" ? "#FFFFFF" : "#A8A8A8";
    public string HentaiNavForeground => ActiveCategory == "hentai" ? "#FFFFFF" : "#A8A8A8";
    public bool IsAnimeActive => ActiveCategory == "anime";
    public bool IsMovieActive => ActiveCategory == "movie";
    public bool IsHentaiActive => ActiveCategory == "hentai";
    public double SearchControlWidth => IsSearchOpen ? 400 : 56;
    public double SearchPanelOpacity => IsSearchOpen ? 1 : 0;

    partial void OnActiveCategoryChanged(string value)
    {
        HomeScrollOffset = GetHomeScrollOffset();
        OnPropertyChanged(nameof(AnimeNavForeground));
        OnPropertyChanged(nameof(MovieNavForeground));
        OnPropertyChanged(nameof(HentaiNavForeground));
        OnPropertyChanged(nameof(IsAnimeActive));
        OnPropertyChanged(nameof(IsMovieActive));
        OnPropertyChanged(nameof(IsHentaiActive));
        ApplyCategoryFilter();
        _ = LoadPostersAsync(CancellationToken.None);
    }

    partial void OnIsSearchOpenChanged(bool value)
    {
        OnPropertyChanged(nameof(SearchControlWidth));
        OnPropertyChanged(nameof(SearchPanelOpacity));

        if (!value && SearchText.Length > 0)
        {
            SearchText = "";
        }
    }

    partial void OnSearchTextChanged(string value)
    {
        ApplyCategoryFilter();
    }

    public void SetHomeGridWidth(double availableWidth)
    {
        const int targetColumns = 6;
        const double minimumGridItemWidth = 130;
        const double minimumPosterWidth = 116;
        const double horizontalPaddingPerItem = 14;
        const double titleHeight = 30;
        const double posterAspectRatio = 1.5;
        const double verticalPaddingPerItem = 22;

        if (!double.IsFinite(availableWidth) || availableWidth <= 0)
        {
            return;
        }

        var gridItemWidth = Math.Max(
            minimumGridItemWidth,
            Math.Floor(availableWidth / targetColumns));
        var posterWidth = Math.Max(minimumPosterWidth, gridItemWidth - horizontalPaddingPerItem);
        var posterImageHeight = Math.Round(posterWidth * posterAspectRatio);
        var posterCardHeight = posterImageHeight + titleHeight;
        var gridItemHeight = posterCardHeight + verticalPaddingPerItem;

        HomeGridItemWidth = gridItemWidth;
        HomeGridItemHeight = gridItemHeight;
        HomePosterCardWidth = posterWidth;
        HomePosterCardHeight = posterCardHeight;
        HomePosterImageHeight = posterImageHeight;
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

    [ObservableProperty]
    private bool _isEpisodeRangeDropdownOpen;

    public bool IsEpisodeRangeDropdownClosed => !IsEpisodeRangeDropdownOpen;

    partial void OnIsEpisodeRangeDropdownOpenChanged(bool value)
    {
        OnPropertyChanged(nameof(IsEpisodeRangeDropdownClosed));
    }

    partial void OnSelectedEpisodeRangeChanged(EpisodeRangeViewModel? value)
    {
        _ = RebuildSelectedEpisodePageAsync(value, CancellationToken.None);
    }

    [RelayCommand]
    public async Task LoadAsync(CancellationToken cancellationToken)
    {
        if (HasLoaded)
        {
            return;
        }

        await LoadFromDatabaseAsync(cancellationToken);
        await RefreshAsync(cancellationToken);
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
            HasLoaded = true;
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
            HasLoaded = true;
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

        await LoadPostersAsync(_loadCancellation.Token);
    }

    [RelayCommand]
    private void SetCategory(string? category)
    {
        ActiveCategory = NormalizeCategory(category);
    }

    public bool HasLoaded { get; private set; }

    public void ShowHome(string? category = null)
    {
        if (!string.IsNullOrWhiteSpace(category))
        {
            ActiveCategory = NormalizeCategory(category);
        }
        else
        {
            HomeScrollOffset = GetHomeScrollOffset();
        }

        IsEpisodeRangeDropdownOpen = false;
        IsDetailsOpen = false;
        _detailsCancellation?.Cancel();
    }

    public void SaveHomeScrollOffset(double offset)
    {
        var normalizedCategory = NormalizeCategory(ActiveCategory);
        var normalizedOffset = double.IsFinite(offset) ? Math.Max(0, offset) : 0;
        _homeScrollOffsets[normalizedCategory] = normalizedOffset;
        HomeScrollOffset = normalizedOffset;
    }

    public double GetHomeScrollOffset()
    {
        return _homeScrollOffsets.TryGetValue(NormalizeCategory(ActiveCategory), out var offset)
            ? offset
            : 0;
    }

    private static string NormalizeCategory(string? category)
    {
        return category?.Trim().ToLowerInvariant() switch
        {
            "hentai" => "hentai",
            "movie" or "movies" => "movie",
            _ => "anime"
        };
    }

    [RelayCommand]
    private void OpenSearch()
    {
        IsSearchOpen = true;
    }

    [RelayCommand]
    private void CloseSearch()
    {
        IsSearchOpen = false;
    }

    private void ApplyCategoryFilter()
    {
        var query = SearchText.Trim();
        var categoryItems = _allItems.Where(item => item.Category == ActiveCategory);
        var filteredItems = string.IsNullOrEmpty(query)
            ? categoryItems
            : categoryItems.Where(item => item.Title.Contains(query, StringComparison.OrdinalIgnoreCase));

        Items.Clear();
        foreach (var item in filteredItems)
        {
            Items.Add(item);
        }
    }

    private async Task LoadPostersAsync(CancellationToken cancellationToken)
    {
        var items = Items.ToArray();
        using var gate = new SemaphoreSlim(8);
        var tasks = items.Select(async item =>
        {
            await gate.WaitAsync(cancellationToken);
            try
            {
                await item.LoadPosterAsync(cancellationToken);
            }
            finally
            {
                gate.Release();
            }
        });

        await Task.WhenAll(tasks);
    }

    public async Task OpenDetailsForMediaAsync(
        MediaLibraryItem mediaItem,
        CancellationToken cancellationToken,
        string? sourceCategory = null)
    {
        await LoadFromDatabaseAsync(cancellationToken);

        var card = _allItems.FirstOrDefault(item => item.Id == mediaItem.Id);
        if (card is null)
        {
            return;
        }

        ActiveCategory = NormalizeCategory(sourceCategory ?? card.Category);
        await OpenDetailsAsync(card, cancellationToken);
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
        IsEpisodeRangeDropdownOpen = false;
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

        BuildEpisodeRanges();
        var firstRange = EpisodeRanges.FirstOrDefault();
        SelectedEpisodeRange = firstRange;
        await RebuildSelectedEpisodePageAsync(firstRange, token);
        token.ThrowIfCancellationRequested();
        IsDetailsOpen = true;
    }

    [RelayCommand]
    private void CloseDetails()
    {
        IsEpisodeRangeDropdownOpen = false;
        IsDetailsOpen = false;
        _detailsCancellation?.Cancel();
    }

    [RelayCommand]
    private void ToggleEpisodeRangeDropdown()
    {
        IsEpisodeRangeDropdownOpen = !IsEpisodeRangeDropdownOpen;
    }

    [RelayCommand]
    private void SelectEpisodeRange(EpisodeRangeViewModel? range)
    {
        if (range is not null)
        {
            SelectedEpisodeRange = range;
        }

        IsEpisodeRangeDropdownOpen = false;
    }

    [RelayCommand]
    public async Task PlaySelectedAsync(CancellationToken cancellationToken)
    {
        if (_selectedCard is null)
        {
            return;
        }

        await navigation.PlayMediaAsync(_selectedCard.Item, cancellationToken, ActiveCategory);
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

    private Task RebuildSelectedEpisodePageAsync(EpisodeRangeViewModel? range, CancellationToken cancellationToken)
    {
        SelectedEpisodes.Clear();
        if (!IsSelectedSeries || _selectedEpisodeItems.Count == 0)
        {
            return Task.CompletedTask;
        }

        var start = range?.StartIndex ?? 0;
        var end = range?.EndIndex ?? Math.Min(12, _selectedEpisodeItems.Count);
        var imagePath = _selectedCard?.Item.BackdropPath ?? _selectedCard?.Item.PosterPath;
        var latestWatchedEpisodeId = _selectedEpisodeItems
            .Where(episode => episode.LastWatchedAt is not null)
            .OrderByDescending(episode => episode.LastWatchedAt)
            .Select(episode => episode.Id)
            .FirstOrDefault();
        var page = _selectedEpisodeItems.Skip(start).Take(end - start)
            .Select(episode => new EpisodeCardViewModel(
                episode,
                imagePath,
                latestWatchedEpisodeId != 0 && episode.Id == latestWatchedEpisodeId,
                ActiveCategory,
                imageCache,
                videoPreviewService,
                navigation))
            .ToArray();

        foreach (var episode in page)
        {
            SelectedEpisodes.Add(episode);
        }

        _ = LoadEpisodeThumbnailsSequentiallyAsync(page, cancellationToken);
        return Task.CompletedTask;
    }

    private static async Task LoadEpisodeThumbnailsSequentiallyAsync(
        IReadOnlyList<EpisodeCardViewModel> page,
        CancellationToken cancellationToken)
    {
        foreach (var episode in page)
        {
            try
            {
                await episode.LoadThumbnailAsync(cancellationToken);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

}
