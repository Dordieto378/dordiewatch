using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Threading;
using DordieWatch.App.ViewModels;
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;

namespace DordieWatch.App.Views;

public partial class LibraryView : UserControl
{
    private LibraryViewModel? _viewModel;
    private CancellationTokenSource? _popupAnimationCancellation;
    private RenderTargetBitmap? _detailsTransitionBitmap;
    private bool _isPlaybackTransitionRunning;
    private bool _searchPressStartedOutside;
    private ScaleTransform DetailsScale => (ScaleTransform)DetailsTransitionVisual.RenderTransform!;
    private ScaleTransform LibraryScale => (ScaleTransform)LibrarySurface.RenderTransform!;

    public LibraryView()
    {
        InitializeComponent();
        AddHandler(PointerPressedEvent, OnLibraryPointerPressed, RoutingStrategies.Tunnel, handledEventsToo: true);
        AddHandler(PointerReleasedEvent, OnLibraryPointerReleased, RoutingStrategies.Bubble, handledEventsToo: true);
    }

    protected override void OnDataContextChanged(EventArgs e)
    {
        if (_viewModel is not null)
        {
            _viewModel.PropertyChanged -= OnViewModelPropertyChanged;
        }

        _viewModel = DataContext as LibraryViewModel;
        if (_viewModel is not null)
        {
            _viewModel.PropertyChanged += OnViewModelPropertyChanged;
            SetDetailsStateInstant(_viewModel.IsDetailsOpen);
            UpdateHomeGridSizing();
        }

        base.OnDataContextChanged(e);
    }

    private void OnLibraryScrollViewerSizeChanged(object? sender, SizeChangedEventArgs e)
    {
        UpdateHomeGridSizing();
    }

    private void UpdateHomeGridSizing()
    {
        if (_viewModel is null)
        {
            return;
        }

        var availableWidth = Math.Max(0, LibraryScrollViewer.Bounds.Width - 76);
        _viewModel.SetHomeGridWidth(availableWidth);

        var layout = LibraryItemsRepeater.Layout;
        if (layout is not null)
        {
            var layoutType = layout.GetType();
            layoutType.GetProperty("MinItemWidth")?.SetValue(layout, _viewModel.HomeGridItemWidth);
            layoutType.GetProperty("MinItemHeight")?.SetValue(layout, _viewModel.HomeGridItemHeight);
        }
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(LibraryViewModel.IsDetailsOpen) && _viewModel is not null)
        {
            _ = AnimateDetailsAsync(_viewModel.IsDetailsOpen);
        }

        if (e.PropertyName == nameof(LibraryViewModel.IsSearchOpen) && _viewModel?.IsSearchOpen == true)
        {
            Dispatcher.UIThread.Post(
                () =>
                {
                    if (_viewModel?.IsSearchOpen != true)
                    {
                        return;
                    }

                    SearchTextBox.Focus();
                    SearchTextBox.SelectAll();
                },
                DispatcherPriority.Input);
        }
    }

    private void OnSearchTextBoxKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key != Key.Escape || _viewModel is null)
        {
            return;
        }

        if (_viewModel.CloseSearchCommand.CanExecute(null))
        {
            _viewModel.CloseSearchCommand.Execute(null);
            e.Handled = true;
        }
    }

    private void OnSearchButtonClick(object? sender, RoutedEventArgs e)
    {
        if (_viewModel?.IsSearchOpen == true)
        {
            SearchTextBox.Focus();
        }
    }

    private void OnLibraryPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        _searchPressStartedOutside = _viewModel?.IsSearchOpen == true
            && !new Rect(SearchControl.Bounds.Size).Contains(e.GetPosition(SearchControl));
    }

    private void OnLibraryPointerReleased(object? sender, PointerReleasedEventArgs e)
    {
        var closeSearch = _searchPressStartedOutside;
        _searchPressStartedOutside = false;
        if (!closeSearch || _viewModel?.IsSearchOpen != true
            || new Rect(SearchControl.Bounds.Size).Contains(e.GetPosition(SearchControl)))
        {
            return;
        }

        // Let the clicked control act before clearing the search rebuilds the library.
        _viewModel.CloseSearchCommand.Execute(null);
    }

    private void OnDetailsLayerPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (_viewModel is null || !_viewModel.IsDetailsOpen)
        {
            return;
        }

        if (_viewModel.IsEpisodeRangeDropdownOpen)
        {
            _viewModel.IsEpisodeRangeDropdownOpen = false;
        }

        var point = e.GetPosition(DetailsPanel);
        var insidePanel = point.X >= 0
            && point.Y >= 0
            && point.X <= DetailsPanel.Bounds.Width
            && point.Y <= DetailsPanel.Bounds.Height;

        if (insidePanel)
        {
            return;
        }

        if (_viewModel.CloseDetailsCommand.CanExecute(null))
        {
            _viewModel.CloseDetailsCommand.Execute(null);
            e.Handled = true;
        }
    }

    private void OnEpisodeRangeButtonPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (_viewModel?.ToggleEpisodeRangeDropdownCommand.CanExecute(null) == true)
        {
            _viewModel.ToggleEpisodeRangeDropdownCommand.Execute(null);
            e.Handled = true;
        }
    }

    private void OnEpisodeRangeOptionPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (sender is not Control { Tag: EpisodeRangeViewModel range } || _viewModel is null)
        {
            return;
        }

        if (_viewModel.SelectEpisodeRangeCommand.CanExecute(range))
        {
            _viewModel.SelectEpisodeRangeCommand.Execute(range);
            e.Handled = true;
        }
    }

    private async void OnPlaySelectedClick(object? sender, RoutedEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }

        await RunPlaybackTransitionAsync(_viewModel.PlaySelectedAsync);
    }

    private async void OnEpisodePlayClick(object? sender, RoutedEventArgs e)
    {
        if (sender is not Control { Tag: EpisodeCardViewModel episode })
        {
            return;
        }

        await RunPlaybackTransitionAsync(episode.PlayAsync);
    }

    private async Task RunPlaybackTransitionAsync(Func<CancellationToken, Task> startPlaybackAsync)
    {
        if (_isPlaybackTransitionRunning)
        {
            return;
        }

        _isPlaybackTransitionRunning = true;
        _popupAnimationCancellation?.Cancel();
        if (_viewModel is not null)
        {
            _viewModel.IsEpisodeRangeDropdownOpen = false;
        }

        LibrarySurface.IsHitTestVisible = false;
        PlaybackTransitionLayer.IsHitTestVisible = true;
        PlaybackTransitionLayer.Opacity = 0;
        LibraryScale.ScaleX = 1;
        LibraryScale.ScaleY = 1;

        try
        {
            var duration = TimeSpan.FromMilliseconds(900);
            var stopwatch = Stopwatch.StartNew();
            while (stopwatch.Elapsed < duration)
            {
                var progress = Math.Clamp(
                    stopwatch.Elapsed.TotalMilliseconds / duration.TotalMilliseconds,
                    0,
                    1);
                var zoomProgress = EaseOutCubic(progress);
                var fadeProgress = SmoothStep(progress);
                var scale = Lerp(1, 1.06, zoomProgress);

                LibraryScale.ScaleX = scale;
                LibraryScale.ScaleY = scale;
                PlaybackTransitionLayer.Opacity = fadeProgress;
                await Task.Delay(16);
            }

            LibraryScale.ScaleX = 1.06;
            LibraryScale.ScaleY = 1.06;
            PlaybackTransitionLayer.Opacity = 1;
            await Task.Delay(70);
            await startPlaybackAsync(CancellationToken.None);
        }
        finally
        {
            LibraryScale.ScaleX = 1;
            LibraryScale.ScaleY = 1;
            PlaybackTransitionLayer.Opacity = 0;
            PlaybackTransitionLayer.IsHitTestVisible = false;
            LibrarySurface.IsHitTestVisible = true;
            _isPlaybackTransitionRunning = false;
        }
    }

    private void SetDetailsStateInstant(bool open)
    {
        DisposeDetailsTransitionSnapshot();
        DetailsLayer.IsVisible = open;
        DetailsLayer.IsHitTestVisible = open;
        DetailsLayer.Opacity = 1;
        DetailsBackdrop.Opacity = open ? 1 : 0;
        DetailsPanel.Opacity = 1;
        DetailsPanel.IsVisible = true;
        DetailsContent.Opacity = 1;
    }

    private async Task AnimateDetailsAsync(bool open)
    {
        _popupAnimationCancellation?.Cancel();
        _popupAnimationCancellation?.Dispose();
        _popupAnimationCancellation = new CancellationTokenSource();
        var token = _popupAnimationCancellation.Token;

        DetailsLayer.IsHitTestVisible = false;
        if (!await PrepareDetailsTransitionSnapshotAsync(open, token))
        {
            if (token.IsCancellationRequested)
            {
                return;
            }

            SetDetailsStateInstant(open);
            return;
        }

        var startOpacity = open ? 0d : 1d;
        var endOpacity = open ? 1d : 0d;
        var startScale = open ? 0.965d : 1d;
        var endScale = open ? 1d : 0.965d;
        DetailsTransitionSnapshot.Opacity = startOpacity;
        DetailsScale.ScaleX = startScale;
        DetailsScale.ScaleY = startScale;
        DetailsBackdrop.Opacity = startOpacity;
        DetailsLayer.Opacity = 1;
        var duration = TimeSpan.FromMilliseconds(open ? 260 : 230);
        var stopwatch = Stopwatch.StartNew();

        while (stopwatch.Elapsed < duration)
        {
            if (token.IsCancellationRequested)
            {
                return;
            }
            var progress = stopwatch.Elapsed.TotalMilliseconds / duration.TotalMilliseconds;
            var eased = open ? EaseOutCubic(progress) : EaseInCubic(progress);
            var opacity = Lerp(startOpacity, endOpacity, eased);
            var scale = Lerp(startScale, endScale, eased);
            DetailsBackdrop.Opacity = opacity;
            DetailsTransitionSnapshot.Opacity = opacity;
            DetailsScale.ScaleX = scale;
            DetailsScale.ScaleY = scale;
            try
            {
                await Task.Delay(16, token);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }

        DetailsBackdrop.Opacity = endOpacity;
        DetailsTransitionSnapshot.Opacity = endOpacity;
        DetailsScale.ScaleX = endScale;
        DetailsScale.ScaleY = endScale;

        if (open)
        {
            DetailsPanel.IsVisible = true;
            await Dispatcher.UIThread.InvokeAsync(() => { }, DispatcherPriority.Render);
            DisposeDetailsTransitionSnapshot();
            DetailsLayer.IsHitTestVisible = true;
        }
        else
        {
            DetailsLayer.IsVisible = false;
            DetailsPanel.IsVisible = true;
            DisposeDetailsTransitionSnapshot();
        }
    }

    private async Task<bool> PrepareDetailsTransitionSnapshotAsync(bool open, CancellationToken token)
    {
        try
        {
            DisposeDetailsTransitionSnapshot();
            DetailsLayer.IsVisible = true;
            DetailsLayer.Opacity = open ? 0 : 1;
            DetailsBackdrop.Opacity = open ? 0 : 1;
            DetailsPanel.IsVisible = true;
            DetailsPanel.Opacity = 1;
            DetailsContent.Opacity = 1;

            await Dispatcher.UIThread.InvokeAsync(
                () => { },
                DispatcherPriority.Render,
                token);
            token.ThrowIfCancellationRequested();

            var width = DetailsPanel.Bounds.Width;
            var height = DetailsPanel.Bounds.Height;
            if (width <= 0 || height <= 0)
            {
                return false;
            }

            var renderScaling = TopLevel.GetTopLevel(this)?.RenderScaling ?? 1d;
            var pixelSize = new PixelSize(
                Math.Max(1, (int)Math.Ceiling(width * renderScaling)),
                Math.Max(1, (int)Math.Ceiling(height * renderScaling)));
            var bitmap = new RenderTargetBitmap(
                pixelSize,
                new Vector(96 * renderScaling, 96 * renderScaling));
            bitmap.Render(DetailsPanel);
            _detailsTransitionBitmap = bitmap;

            DetailsTransitionSnapshot.Source = bitmap;
            DetailsTransitionVisual.Width = width;
            DetailsTransitionVisual.Height = height;
            DetailsTransitionSnapshot.Opacity = open ? 0 : 1;
            DetailsTransitionVisual.IsVisible = true;
            DetailsScale.ScaleX = open ? 0.965 : 1;
            DetailsScale.ScaleY = open ? 0.965 : 1;

            await Dispatcher.UIThread.InvokeAsync(
                () => { },
                DispatcherPriority.Render,
                token);
            token.ThrowIfCancellationRequested();
            DetailsPanel.IsVisible = false;
            return true;
        }
        catch (OperationCanceledException)
        {
            return false;
        }
        catch
        {
            DisposeDetailsTransitionSnapshot();
            return false;
        }
    }

    private void DisposeDetailsTransitionSnapshot()
    {
        DetailsTransitionVisual.IsVisible = false;
        DetailsTransitionSnapshot.Source = null;
        _detailsTransitionBitmap?.Dispose();
        _detailsTransitionBitmap = null;
    }

    private static double Lerp(double start, double end, double progress)
    {
        return start + ((end - start) * Math.Clamp(progress, 0, 1));
    }

    private static double EaseOutCubic(double progress)
    {
        var t = 1 - Math.Clamp(progress, 0, 1);
        return 1 - (t * t * t);
    }

    private static double EaseInCubic(double progress)
    {
        var t = Math.Clamp(progress, 0, 1);
        return t * t * t;
    }

    private static double SmoothStep(double progress)
    {
        var t = Math.Clamp(progress, 0, 1);
        return t * t * (3 - (2 * t));
    }
}
