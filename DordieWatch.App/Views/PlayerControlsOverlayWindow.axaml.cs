using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Threading;
using DordieWatch.App.ViewModels;
using System.ComponentModel;

namespace DordieWatch.App.Views;

public partial class PlayerControlsOverlayWindow : Window
{
    private PlayerViewModel? _viewModel;
    private bool _isDraggingTimeline;
    private bool _isDraggingVolume;
    private bool _areControlsVisible = true;
    private bool _isFullscreen;
    private PixelPoint? _lastPointerScreenPosition;
    private readonly DispatcherTimer _controlsHideTimer;
    private readonly DispatcherTimer _loadingSpinnerTimer;
    private readonly Cursor _hiddenCursor;
    private static readonly TimeSpan ControlsIdleDelay = TimeSpan.FromSeconds(3);
    private TranslateTransform BackButtonTranslation => (TranslateTransform)BackButton.RenderTransform!;
    private TranslateTransform PlayerControlsTranslation => (TranslateTransform)PlayerControlsPanel.RenderTransform!;
    private RotateTransform LoadingSpinnerRotation => (RotateTransform)LoadingSpinner.RenderTransform!;
    private const double TimelineHitPadding = 7;
    private const double VolumeTrackTop = 22;
    private const double VolumeTrackHeight = 124;
    private const double EpisodeMenuReferenceWidth = 1920;
    private const double EpisodeMenuReferenceHeight = 1080;
    private const double EpisodeMenuDesignWidth = 940;
    private const double EpisodeMenuDesignHeight = 820;
    private const double EpisodeMenuDesignRightMargin = 0;
    private const double EpisodeMenuDesignBottomMargin = 68;
    private const int MinimumPointerMovementPixels = 2;

    public event EventHandler? FullscreenToggleRequested;

    public PlayerControlsOverlayWindow()
    {
        InitializeComponent();
        _hiddenCursor = new Cursor(StandardCursorType.None);
        _controlsHideTimer = new DispatcherTimer { Interval = ControlsIdleDelay };
        _controlsHideTimer.Tick += OnControlsHideTimerTick;
        _loadingSpinnerTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(16) };
        _loadingSpinnerTimer.Tick += (_, _) =>
        {
            LoadingSpinnerRotation.Angle = (LoadingSpinnerRotation.Angle + 7) % 360;
        };
        DataContextChanged += OnDataContextChanged;
        RootLayer.AddHandler(PointerPressedEvent, OnRootPointerPressed, RoutingStrategies.Tunnel | RoutingStrategies.Bubble, handledEventsToo: true);
        RootLayer.AddHandler(PointerMovedEvent, OnRootPointerMoved, RoutingStrategies.Tunnel, handledEventsToo: true);
        TimelineArea.AddHandler(PointerMovedEvent, OnTimelinePointerMoved, RoutingStrategies.Tunnel | RoutingStrategies.Bubble, handledEventsToo: true);
        TimelineArea.AddHandler(PointerExitedEvent, OnTimelinePointerExited, RoutingStrategies.Tunnel | RoutingStrategies.Bubble, handledEventsToo: true);
        TimelineArea.AddHandler(PointerPressedEvent, OnTimelinePointerPressed, RoutingStrategies.Tunnel | RoutingStrategies.Bubble, handledEventsToo: true);
        TimelineArea.AddHandler(PointerReleasedEvent, OnTimelinePointerReleased, RoutingStrategies.Tunnel | RoutingStrategies.Bubble, handledEventsToo: true);
        SizeChanged += OnOverlaySizeChanged;
        AddHandler(KeyDownEvent, OnOverlayKeyDown, RoutingStrategies.Tunnel, handledEventsToo: true);
        Opened += OnOpened;
        Deactivated += OnOverlayDeactivated;
        Closed += (_, _) =>
        {
            _controlsHideTimer.Stop();
            _loadingSpinnerTimer.Stop();
            _hiddenCursor.Dispose();
            if (_viewModel is not null)
            {
                _viewModel.PropertyChanged -= OnViewModelPropertyChanged;
                _viewModel.AutoPlayNextEpisodeRequested -= OnAutoPlayNextEpisodeRequested;
            }
        };
    }

    private void OnOpened(object? sender, EventArgs e)
    {
        Activate();
        RootLayer.Focus();
        UpdateVolumeVisual();
        UpdateMenuPanelsLayout();
        RegisterControlsActivity();
    }

    private void OnOverlaySizeChanged(object? sender, SizeChangedEventArgs e)
    {
        UpdateMenuPanelsLayout();
    }

    private void OnOverlayDeactivated(object? sender, EventArgs e)
    {
        _viewModel?.HideEpisodesMenu();
        _viewModel?.HideTrackMenu();
        _viewModel?.HideVolumePopup();
    }

    private void OnOverlayKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.KeyModifiers != KeyModifiers.None)
        {
            return;
        }

        if (_viewModel is not null)
        {
            if (e.Key == Key.Space)
            {
                e.Handled = true;
                _viewModel.TogglePausePlayback();
                RegisterControlsActivity();
                return;
            }

            if (e.Key == Key.Left)
            {
                e.Handled = true;
                _viewModel.SkipBackwardPlayback();
                RegisterControlsActivity();
                return;
            }

            if (e.Key == Key.Right)
            {
                e.Handled = true;
                _viewModel.SkipForwardPlayback();
                RegisterControlsActivity();
                return;
            }
        }

        if (e.Key == Key.F11 || (e.Key == Key.Escape && _isFullscreen))
        {
            e.Handled = true;
            FullscreenToggleRequested?.Invoke(this, EventArgs.Empty);
        }
    }

    private void OnRootPointerMoved(object? sender, PointerEventArgs e)
    {
        var screenPosition = this.PointToScreen(e.GetPosition(this));
        if (_lastPointerScreenPosition is { } previousPosition
            && Math.Abs(screenPosition.X - previousPosition.X) < MinimumPointerMovementPixels
            && Math.Abs(screenPosition.Y - previousPosition.Y) < MinimumPointerMovementPixels)
        {
            return;
        }

        _lastPointerScreenPosition = screenPosition;
        RegisterControlsActivity();
    }

    private void OnControlsHideTimerTick(object? sender, EventArgs e)
    {
        _controlsHideTimer.Stop();
        if (ShouldKeepControlsVisible())
        {
            _controlsHideTimer.Start();
            return;
        }

        SetControlsVisible(false);
    }

    private bool ShouldKeepControlsVisible()
    {
        return _isDraggingTimeline
            || _isDraggingVolume
            || _viewModel?.IsEpisodesMenuOpen == true
            || _viewModel?.IsTrackMenuOpen == true
            || _viewModel?.IsVolumePopupVisible == true;
    }

    private void RegisterControlsActivity()
    {
        if (PlaybackLoadingLayer.IsVisible)
        {
            return;
        }

        SetControlsVisible(true);
        _controlsHideTimer.Stop();
        _controlsHideTimer.Start();
    }

    private void SetControlsVisible(bool visible)
    {
        if (_areControlsVisible == visible)
        {
            return;
        }

        _areControlsVisible = visible;
        if (visible)
        {
            RootLayer.Cursor = null;
            BackButton.IsHitTestVisible = true;
            PlayerControlsPanel.IsHitTestVisible = true;
            BackButtonTranslation.Y = 0;
            PlayerControlsTranslation.Y = 0;
            return;
        }

        _viewModel?.HideTimelinePreview();
        RootLayer.Cursor = _hiddenCursor;
        BackButton.IsHitTestVisible = false;
        PlayerControlsPanel.IsHitTestVisible = false;
        BackButtonTranslation.Y = -90;
        PlayerControlsTranslation.Y = 260;
    }

    private void OnTimelinePointerMoved(object? sender, PointerEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }

        var position = e.GetPosition(TimelineArea);
        if (!_isDraggingTimeline && !IsOnTimelineRail(position.Y))
        {
            _viewModel.HideTimelinePreview();
            return;
        }

        _viewModel.UpdateTimelinePreview(position.X, TimelineArea.Bounds.Width);
        if (_isDraggingTimeline)
        {
            _viewModel.SeekFromTimelinePointer(position.X, TimelineArea.Bounds.Width);
            UpdateTimelineVisual();
            e.Handled = true;
        }
    }

    private void OnTimelinePointerExited(object? sender, PointerEventArgs e)
    {
        if (!_isDraggingTimeline)
        {
            _viewModel?.HideTimelinePreview();
        }
    }

    private void OnTimelinePointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }

        var position = e.GetPosition(TimelineArea);
        if (!IsOnTimelineRail(position.Y))
        {
            _viewModel.HideTimelinePreview();
            return;
        }

        _isDraggingTimeline = true;
        e.Pointer.Capture(TimelineArea);

        _viewModel.UpdateTimelinePreview(position.X, TimelineArea.Bounds.Width);
        _viewModel.SeekFromTimelinePointer(position.X, TimelineArea.Bounds.Width);
        UpdateTimelineVisual();
        e.Handled = true;
    }

    private void OnTimelinePointerReleased(object? sender, PointerReleasedEventArgs e)
    {
        if (_viewModel is not null && _isDraggingTimeline)
        {
            var position = e.GetPosition(TimelineArea);
            _viewModel.UpdateTimelinePreview(position.X, TimelineArea.Bounds.Width);
            _viewModel.SeekFromTimelinePointer(position.X, TimelineArea.Bounds.Width);
            UpdateTimelineVisual();
            e.Handled = true;
        }

        _isDraggingTimeline = false;
        e.Pointer.Capture(null);
        RegisterControlsActivity();
    }

    private void OnTimelineSizeChanged(object? sender, SizeChangedEventArgs e)
    {
        UpdateTimelineVisual();
    }

    private void OnDataContextChanged(object? sender, EventArgs e)
    {
        if (_viewModel is not null)
        {
            _viewModel.PropertyChanged -= OnViewModelPropertyChanged;
            _viewModel.AutoPlayNextEpisodeRequested -= OnAutoPlayNextEpisodeRequested;
        }

        _viewModel = DataContext as PlayerViewModel;

        if (_viewModel is not null)
        {
            _viewModel.PropertyChanged += OnViewModelPropertyChanged;
            _viewModel.AutoPlayNextEpisodeRequested += OnAutoPlayNextEpisodeRequested;
        }

        UpdateTimelineVisual();
        UpdateVolumeVisual();
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName is nameof(PlayerViewModel.Position)
            or nameof(PlayerViewModel.Duration)
            or nameof(PlayerViewModel.PositionSeconds)
            or nameof(PlayerViewModel.DurationSeconds))
        {
            Dispatcher.UIThread.Post(UpdateTimelineVisual);
        }

        if (e.PropertyName is nameof(PlayerViewModel.VolumePercent))
        {
            Dispatcher.UIThread.Post(UpdateVolumeVisual);
        }
    }

    private void UpdateTimelineVisual()
    {
        if (_viewModel is null)
        {
            return;
        }

        var width = Math.Max(0, TimelineArea.Bounds.Width);
        TimelineRail.Width = width;

        var ratio = _viewModel.DurationSeconds <= 1
            ? 0
            : Math.Clamp(_viewModel.PositionSeconds / _viewModel.DurationSeconds, 0, 1);

        var progressWidth = width * ratio;
        TimelineProgress.Width = progressWidth;
        Canvas.SetLeft(TimelineThumb, Math.Clamp(progressWidth - 6, 0, Math.Max(0, width - 12)));
    }

    private void UpdateMenuPanelsLayout()
    {
        var width = Math.Max(1, Bounds.Width);
        var height = Math.Max(1, Bounds.Height);
        var scale = Math.Min(width / EpisodeMenuReferenceWidth, height / EpisodeMenuReferenceHeight);
        if (!double.IsFinite(scale) || scale <= 0)
        {
            scale = 1;
        }

        EpisodesMenuPanel.Width = Math.Round(EpisodeMenuDesignWidth * scale);
        EpisodesMenuPanel.Height = Math.Round(EpisodeMenuDesignHeight * scale);
        EpisodesMenuPanel.Margin = new Thickness(
            0,
            0,
            Math.Round(EpisodeMenuDesignRightMargin * scale),
            EpisodeMenuDesignBottomMargin);

        TrackMenuPanel.Width = EpisodesMenuPanel.Width;
        TrackMenuPanel.Height = EpisodesMenuPanel.Height;
        TrackMenuPanel.Margin = EpisodesMenuPanel.Margin;
    }

    private void OnVolumeButtonClick(object? sender, RoutedEventArgs e)
    {
        _viewModel?.HandleVolumeButtonClick();
        UpdateVolumeVisual();
        e.Handled = true;
    }

    private void OnRootPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        _lastPointerScreenPosition = this.PointToScreen(e.GetPosition(this));
        RootLayer.Focus();
        RegisterControlsActivity();

        if (_viewModel?.IsEpisodesMenuOpen == true
            && !IsEventFrom(e.Source, EpisodesButton)
            && !IsEventFrom(e.Source, EpisodesMenuPanel))
        {
            _viewModel.HideEpisodesMenu();
        }

        if (_viewModel?.IsTrackMenuOpen == true
            && !IsEventFrom(e.Source, SubtitleButton)
            && !IsEventFrom(e.Source, TrackMenuPanel))
        {
            _viewModel.HideTrackMenu();
        }

        if (_viewModel?.IsVolumePopupVisible == true)
        {
            if (IsEventFrom(e.Source, VolumeButton) || IsEventFrom(e.Source, VolumePopupPanel))
            {
                return;
            }

            _viewModel.HideVolumePopup();
        }
    }

    private void OnEpisodesButtonClick(object? sender, RoutedEventArgs e)
    {
        _viewModel?.ToggleEpisodesMenu();
        e.Handled = true;
    }

    private async void OnNextEpisodeButtonClick(object? sender, RoutedEventArgs e)
    {
        e.Handled = true;
        await PlayNextEpisodeWithTransitionAsync();
    }

    private async void OnAutoPlayNextEpisodeRequested(object? sender, EventArgs e)
    {
        await PlayNextEpisodeWithTransitionAsync();
    }

    private async Task PlayNextEpisodeWithTransitionAsync()
    {
        if (_viewModel is null || !_viewModel.HasNextEpisode || PlaybackLoadingLayer.IsVisible)
        {
            return;
        }

        await ShowPlaybackLoadingAsync();
        try
        {
            await _viewModel.PlayNextEpisodeAsync();
            await Task.Delay(180);
        }
        finally
        {
            await HidePlaybackLoadingAsync();
        }
    }

    private async Task ShowPlaybackLoadingAsync()
    {
        _controlsHideTimer.Stop();
        SetControlsVisible(false);
        PlaybackLoadingLayer.Opacity = 0;
        PlaybackLoadingLayer.IsVisible = true;
        await Task.Delay(16);
        PlaybackLoadingLayer.Opacity = 1;
        await Task.Delay(240);
        LoadingSpinnerRotation.Angle = 0;
        LoadingSpinner.IsVisible = true;
        _loadingSpinnerTimer.Start();
    }

    private async Task HidePlaybackLoadingAsync()
    {
        _loadingSpinnerTimer.Stop();
        LoadingSpinner.IsVisible = false;
        PlaybackLoadingLayer.Opacity = 0;
        await Task.Delay(240);
        PlaybackLoadingLayer.IsVisible = false;
        RegisterControlsActivity();
    }

    private void OnSubtitleButtonClick(object? sender, RoutedEventArgs e)
    {
        _viewModel?.ToggleTrackMenu();
        e.Handled = true;
    }

    private void OnFullscreenButtonClick(object? sender, RoutedEventArgs e)
    {
        FullscreenToggleRequested?.Invoke(this, EventArgs.Empty);
        e.Handled = true;
    }

    public void SetFullscreenState(bool isFullscreen)
    {
        _isFullscreen = isFullscreen;
        EnterFullscreenIcon.IsVisible = !isFullscreen;
        ExitFullscreenIcon.IsVisible = isFullscreen;
        ToolTip.SetTip(FullscreenButton, isFullscreen ? "Exit full screen" : "Full screen");
    }

    private void OnAudioTrackOptionPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (sender is Control { Tag: PlayerTrackOptionViewModel option })
        {
            _viewModel?.SelectAudioTrack(option);
            e.Handled = true;
        }
    }

    private void OnSubtitleTrackOptionPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (sender is Control { Tag: PlayerTrackOptionViewModel option })
        {
            _viewModel?.SelectSubtitleOption(option);
            e.Handled = true;
        }
    }

    private void OnEpisodeMenuHeaderPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        _viewModel?.ShowEpisodeRangeSelector();
        e.Handled = true;
    }

    private void OnPlayerEpisodeRangeOptionPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (sender is not Control { Tag: PlayerEpisodeRangeViewModel range } || _viewModel is null)
        {
            return;
        }

        _viewModel.SelectPlayerEpisodeRange(range);
        e.Handled = true;
    }

    private async void OnPlayerEpisodeMenuItemPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (sender is not Control { Tag: PlayerEpisodeMenuItemViewModel item } || _viewModel is null)
        {
            return;
        }

        await _viewModel.PlayEpisodeFromMenuAsync(item);
        e.Handled = true;
    }

    private void OnVolumeSliderPointerPressed(object? sender, PointerPressedEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }

        _isDraggingVolume = true;
        e.Pointer.Capture(VolumeSliderArea);
        SetVolumeFromPointer(e);
        e.Handled = true;
    }

    private void OnVolumeSliderPointerMoved(object? sender, PointerEventArgs e)
    {
        if (_isDraggingVolume)
        {
            SetVolumeFromPointer(e);
            e.Handled = true;
        }
    }

    private void OnVolumeSliderPointerReleased(object? sender, PointerReleasedEventArgs e)
    {
        if (_isDraggingVolume)
        {
            SetVolumeFromPointer(e);
            e.Handled = true;
        }

        _isDraggingVolume = false;
        e.Pointer.Capture(null);
        RegisterControlsActivity();
    }

    private void SetVolumeFromPointer(PointerEventArgs e)
    {
        if (_viewModel is null)
        {
            return;
        }

        var pointer = e.GetPosition(VolumeSliderArea);
        var y = Math.Clamp(pointer.Y - VolumeTrackTop, 0, VolumeTrackHeight);
        _viewModel.SetVolumeFromSliderPointer(y, VolumeTrackHeight);
        UpdateVolumeVisual();
    }

    private void UpdateVolumeVisual()
    {
        if (_viewModel is null)
        {
            return;
        }

        var ratio = Math.Clamp(_viewModel.VolumePercent / 100.0, 0, 1);
        var fillHeight = Math.Round(VolumeTrackHeight * ratio);
        var fillTop = Math.Round(VolumeTrackTop + VolumeTrackHeight - fillHeight);
        var thumbTop = Math.Round(Math.Clamp(fillTop - 10, VolumeTrackTop - 10, VolumeTrackTop + VolumeTrackHeight - 10));

        Canvas.SetTop(VolumeFill, fillTop);
        VolumeFill.Height = fillHeight;
        Canvas.SetTop(VolumeThumb, thumbTop);
    }

    private bool IsOnTimelineRail(double y)
    {
        var railTop = Canvas.GetTop(TimelineRail);
        if (double.IsNaN(railTop))
        {
            railTop = 0;
        }

        var railBottom = railTop + TimelineRail.Bounds.Height;
        return y >= railTop - TimelineHitPadding && y <= railBottom + TimelineHitPadding;
    }

    private static bool IsEventFrom(object? source, Control target)
    {
        var current = source as Control;
        while (current is not null)
        {
            if (ReferenceEquals(current, target))
            {
                return true;
            }

            current = current.Parent as Control;
        }

        return false;
    }
}
