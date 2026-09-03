using CommunityToolkit.Mvvm.ComponentModel;

namespace DordieWatch.App.ViewModels;

public sealed partial class PlayerTrackOptionViewModel(int id, string name, bool isSelected, string? subtitlePath = null) : ObservableObject
{
    public int Id { get; } = id;
    public string Name { get; } = name;
    public string? SubtitlePath { get; } = subtitlePath;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsNotSelected))]
    private bool _isSelected = isSelected;

    public bool IsNotSelected => !IsSelected;
}
