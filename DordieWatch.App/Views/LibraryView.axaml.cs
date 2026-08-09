using Avalonia.Controls;
using Avalonia.Media;
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
    private ScaleTransform DetailsScale => (ScaleTransform)DetailsPanel.RenderTransform!;

    public LibraryView()
    {
        InitializeComponent();
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
        }

        base.OnDataContextChanged(e);
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(LibraryViewModel.IsDetailsOpen) && _viewModel is not null)
        {
            _ = AnimateDetailsAsync(_viewModel.IsDetailsOpen);
        }
    }

    private void SetDetailsStateInstant(bool open)
    {
        DetailsLayer.IsVisible = open;
        DetailsLayer.IsHitTestVisible = open;
        DetailsLayer.Opacity = open ? 1 : 0;
        DetailsScale.ScaleX = open ? 1 : 0.965;
        DetailsScale.ScaleY = open ? 1 : 0.965;
    }

    private async Task AnimateDetailsAsync(bool open)
    {
        _popupAnimationCancellation?.Cancel();
        _popupAnimationCancellation?.Dispose();
        _popupAnimationCancellation = new CancellationTokenSource();
        var token = _popupAnimationCancellation.Token;

        if (open)
        {
            DetailsLayer.IsVisible = true;
            DetailsLayer.IsHitTestVisible = true;
        }
        else
        {
            DetailsLayer.IsHitTestVisible = false;
        }

        var startOpacity = DetailsLayer.Opacity;
        var endOpacity = open ? 1d : 0d;
        var startScale = DetailsScale.ScaleX;
        var endScale = open ? 1d : 0.965d;
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
            DetailsLayer.Opacity = opacity;
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

        DetailsLayer.Opacity = endOpacity;
        DetailsScale.ScaleX = endScale;
        DetailsScale.ScaleY = endScale;
        if (!open)
        {
            DetailsLayer.IsVisible = false;
        }
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
}
