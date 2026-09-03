using DordieWatch.App.Models;

namespace DordieWatch.App.Services;

public interface ISubtitleFileService
{
    IReadOnlyList<ExternalSubtitleInfo> FindForVideo(string videoPath);
    PreparedSubtitleInfo PrepareForPlayback(string subtitlePath);
}
