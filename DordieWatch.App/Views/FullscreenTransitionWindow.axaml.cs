using Avalonia.Controls;

namespace DordieWatch.App.Views;

public partial class FullscreenTransitionWindow : Window
{
    private const int FadeDurationMilliseconds = 240;

    public FullscreenTransitionWindow()
    {
        InitializeComponent();
    }

    public async Task FadeToBlackAsync()
    {
        BlackoutLayer.Opacity = 1;
        await Task.Delay(FadeDurationMilliseconds);
    }

    public async Task FadeFromBlackAsync()
    {
        BlackoutLayer.Opacity = 0;
        await Task.Delay(FadeDurationMilliseconds);
    }
}
