using CommunityToolkit.Mvvm.ComponentModel;

namespace DordieWatch.App.ViewModels;

public sealed partial class PlayerTrackOptionViewModel(
    int id,
    string name,
    bool isSelected,
    string? subtitlePath = null,
    string? preferenceKey = null) : ObservableObject
{
    public int Id { get; } = id;
    public string Name { get; } = name;
    public string? SubtitlePath { get; } = subtitlePath;
    public string PreferenceKey { get; } = string.IsNullOrWhiteSpace(preferenceKey)
        ? name
        : preferenceKey;

    [ObservableProperty]
    [NotifyPropertyChangedFor(nameof(IsNotSelected))]
    private bool _isSelected = isSelected;

    public bool IsNotSelected => !IsSelected;
}
