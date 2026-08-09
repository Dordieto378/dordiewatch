using DordieWatch.App.Services;

namespace DordieWatch.App.ViewModels;

public sealed partial class MainWindowViewModel : ViewModelBase
{
    private readonly INavigationService _navigation;

    [CommunityToolkit.Mvvm.ComponentModel.ObservableProperty]
    private object? _currentViewModel;

    public MainWindowViewModel(INavigationService navigation)
    {
        _navigation = navigation;
        _navigation.CurrentViewModelChanged += (_, viewModel) => CurrentViewModel = viewModel;
        _navigation.ShowLibrary();
    }
}
