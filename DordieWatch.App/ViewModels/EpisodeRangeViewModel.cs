namespace DordieWatch.App.ViewModels;

public sealed record EpisodeRangeViewModel(int StartIndex, int EndIndex)
{
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
}
