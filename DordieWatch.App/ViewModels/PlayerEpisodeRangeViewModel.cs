using CommunityToolkit.Mvvm.ComponentModel;

namespace DordieWatch.App.ViewModels;

public sealed partial class PlayerEpisodeRangeViewModel(int startIndex, int endIndex) : ViewModelBase
{
    public int StartIndex { get; } = startIndex;
    public int EndIndex { get; } = endIndex;
    public string Label
    {
        get
        {
            var start = StartIndex + 1;
            var end = EndIndex;
            if (start == end)
            {
                return $"Episode {start}";
            }

            if (end == start + 1)
            {
                return $"Episode {start} and {end}";
            }

            return $"Episodes {start} - {end}";
        }
    }

    [ObservableProperty]
    private bool _isSelected;
}
