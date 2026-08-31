using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Reactive;
using Avalonia.VisualTree;
using DordieWatch.App.ViewModels;

namespace DordieWatch.App.Views;

public partial class PlayerView : UserControl
{
    private PlayerControlsOverlayWindow? _overlay;
    private Window? _owner;
    private IDisposable? _ownerSizeSubscription;
    private IDisposable? _ownerWindowStateSubscription;
    private IDisposable? _boundsSubscription;
    private WindowState _windowStateBeforeFullscreen = WindowState.Normal;
    private bool _isFullscreenTransitioning;

    public PlayerView()
    {
        InitializeComponent();
        DataContextChanged += (_, _) =>
        {
            if (_overlay is not null)
            {
                _overlay.DataContext = DataContext;
            }
        };
    }

    protected override void OnAttachedToVisualTree(VisualTreeAttachmentEventArgs e)
    {
        base.OnAttachedToVisualTree(e);

        _owner = TopLevel.GetTopLevel(this) as Window;
        if (_owner is null)
        {
            return;
        }

        if (_overlay is not null)
        {
            _overlay.DataContext = DataContext;
            UpdateOverlayBounds();
            return;
        }

        _overlay = new PlayerControlsOverlayWindow
        {
            DataContext = DataContext,
            ShowActivated = false
        };
        _overlay.FullscreenToggleRequested += OnFullscreenToggleRequested;

        _owner.PositionChanged += OnOwnerPositionChanged;
        _owner.Deactivated += OnOwnerDeactivated;
        _owner.KeyDown += OnOwnerKeyDown;
        _ownerSizeSubscription = _owner.GetObservable(Window.ClientSizeProperty).Subscribe(new AnonymousObserver<Size>(_ =>
        {
            CloseOverlayMenus();
            UpdateOverlayBounds();
        }));
        _boundsSubscription = this.GetObservable(BoundsProperty).Subscribe(new AnonymousObserver<Rect>(_ => UpdateOverlayBounds()));
        _ownerWindowStateSubscription = _owner.GetObservable(Window.WindowStateProperty).Subscribe(
            new AnonymousObserver<WindowState>(OnOwnerWindowStateChanged));
        _overlay.Show(_owner);
        UpdateOverlayBounds();
    }

    protected override void OnDetachedFromVisualTree(VisualTreeAttachmentEventArgs e)
    {
        if (_owner?.WindowState == WindowState.FullScreen)
        {
            _owner.WindowState = _windowStateBeforeFullscreen == WindowState.FullScreen
                ? WindowState.Normal
                : _windowStateBeforeFullscreen;
        }

        if (_owner is not null)
        {
            _owner.PositionChanged -= OnOwnerPositionChanged;
            _owner.Deactivated -= OnOwnerDeactivated;
            _owner.KeyDown -= OnOwnerKeyDown;
        }

        if (_overlay is not null)
        {
            _overlay.FullscreenToggleRequested -= OnFullscreenToggleRequested;
            _overlay.Close();
            _overlay = null;
        }

        _ownerSizeSubscription?.Dispose();
        _ownerSizeSubscription = null;
        _ownerWindowStateSubscription?.Dispose();
        _ownerWindowStateSubscription = null;
        _boundsSubscription?.Dispose();
        _boundsSubscription = null;

        _owner = null;
        base.OnDetachedFromVisualTree(e);
    }

    private void OnOwnerPositionChanged(object? sender, PixelPointEventArgs e)
    {
        CloseOverlayMenus();
        UpdateOverlayBounds();
    }

    private void OnOwnerDeactivated(object? sender, EventArgs e)
    {
        CloseOverlayMenus();
    }

    private async void OnFullscreenToggleRequested(object? sender, EventArgs e)
    {
        await ToggleFullscreenAsync();
    }

    private async void OnOwnerKeyDown(object? sender, KeyEventArgs e)
    {
        if (e.Key == Key.F11 || (e.Key == Key.Escape && _owner?.WindowState == WindowState.FullScreen))
        {
            e.Handled = true;
            await ToggleFullscreenAsync();
        }
    }

    private async Task ToggleFullscreenAsync()
    {
        if (_owner is null || _overlay is null || _isFullscreenTransitioning)
        {
            return;
        }

        var owner = _owner;
        var screen = owner.Screens.ScreenFromWindow(owner) ?? owner.Screens.Primary;
        if (screen is null)
        {
            return;
        }

        _isFullscreenTransitioning = true;
        FullscreenTransitionWindow? transitionWindow = null;
        try
        {
            CloseOverlayMenus();
            var screenBounds = screen.Bounds;
            transitionWindow = new FullscreenTransitionWindow
            {
                Position = screenBounds.Position,
                Width = screenBounds.Width / screen.Scaling,
                Height = screenBounds.Height / screen.Scaling
            };
            transitionWindow.Show();
            await Task.Delay(40);
            await transitionWindow.FadeToBlackAsync();

            if (owner.WindowState == WindowState.FullScreen)
            {
                owner.WindowState = _windowStateBeforeFullscreen == WindowState.FullScreen
                    ? WindowState.Normal
                    : _windowStateBeforeFullscreen;
            }
            else
            {
                _windowStateBeforeFullscreen = owner.WindowState;
                owner.WindowState = WindowState.FullScreen;
            }

            await Task.Delay(120);
            UpdateOverlayBounds();
            _overlay.SetFullscreenState(owner.WindowState == WindowState.FullScreen);
            await transitionWindow.FadeFromBlackAsync();
        }
        finally
        {
            transitionWindow?.Close();
            _isFullscreenTransitioning = false;
        }
    }

    private void OnOwnerWindowStateChanged(WindowState state)
    {
        _overlay?.SetFullscreenState(state == WindowState.FullScreen);
        UpdateOverlayBounds();
    }

    private void CloseOverlayMenus()
    {
        if (_overlay?.DataContext is PlayerViewModel viewModel)
        {
            viewModel.HideEpisodesMenu();
            viewModel.HideTrackMenu();
            viewModel.HideVolumePopup();
        }
    }

    private void UpdateOverlayBounds()
    {
        if (_owner is null || _overlay is null)
        {
            return;
        }

        var topLeft = _owner.PointToScreen(new Point(0, 0));
        _overlay.Position = topLeft;
        _overlay.Width = Math.Max(1, _owner.ClientSize.Width);
        _overlay.Height = Math.Max(1, _owner.ClientSize.Height);
    }
}
