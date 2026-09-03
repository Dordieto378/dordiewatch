using DordieWatch.App.Models;
using System.Text.RegularExpressions;

namespace DordieWatch.App.Services;

public sealed partial class MediaFileScanner : IMediaFileScanner
{
    private static readonly HashSet<string> VideoExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".mkv", ".mp4", ".avi", ".mov", ".webm", ".m4v"
    };

    private static readonly HashSet<string> ImageExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".jpg", ".jpeg", ".png", ".webp"
    };

    private static readonly HashSet<string> SubtitleExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".ass", ".ssa", ".srt"
    };

    private static readonly HashSet<string> SubtitleFolderNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "subs", "sub", "subtitle", "subtitles"
    };

    public Task<IReadOnlyList<ScannedMediaItem>> ScanAsync(string rootDirectory, CancellationToken cancellationToken)
    {
        return Task.Run(() => Scan(rootDirectory, cancellationToken), cancellationToken);
    }

    private static IReadOnlyList<ScannedMediaItem> Scan(string rootDirectory, CancellationToken cancellationToken)
    {
        var logPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "DordieWatchCSharp",
            "scanner.log");
        Directory.CreateDirectory(Path.GetDirectoryName(logPath)!);
        File.AppendAllText(logPath, $"{DateTimeOffset.Now:u} scan root={rootDirectory}{Environment.NewLine}");

        if (!Directory.Exists(rootDirectory))
        {
            File.AppendAllText(logPath, $"{DateTimeOffset.Now:u} root missing{Environment.NewLine}");
            return [];
        }

        var folders = Directory.EnumerateDirectories(rootDirectory)
            .OrderBy(Path.GetFileName, StringComparer.CurrentCultureIgnoreCase);
        var items = new List<ScannedMediaItem>();

        foreach (var folder in folders)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var videos = Directory.EnumerateFiles(folder)
                .Where(path => VideoExtensions.Contains(Path.GetExtension(path)))
                .OrderBy(NaturalSortKey)
                .ToArray();
            File.AppendAllText(logPath, $"{DateTimeOffset.Now:u} folder={Path.GetFileName(folder)} videos={videos.Length}{Environment.NewLine}");

            if (videos.Length == 0)
            {
                continue;
            }

            var title = CleanTitle(Path.GetFileName(folder));
            var ids = IdRegex().Matches(Path.GetFileName(folder))
                .Select(match => int.TryParse(match.Groups[1].Value, out var id) ? id : 0)
                .Where(id => id > 0)
                .ToArray();
            var poster = FindImage(folder, ["poster", "cover", "folder"]) ?? FindFirstImage(folder);
            var backdrop = FindImage(folder, ["backdrop", "fanart", "banner"]) ?? poster;
            var subtitleFolders = Directory.EnumerateDirectories(folder)
                .Where(path => SubtitleFolderNames.Contains(Path.GetFileName(path)))
                .ToArray();

            var episodes = videos.Select((video, index) =>
            {
                var episodeNumber = ExtractEpisodeNumber(video) ?? index + 1;
                return new ScannedEpisode(
                    episodeNumber,
                    $"Episode {episodeNumber}",
                    video,
                    FindSubtitleForVideo(video, subtitleFolders));
            }).ToArray();

            items.Add(new ScannedMediaItem(
                title,
                episodes.Length == 1 ? MediaKind.Movie : MediaKind.Series,
                "anime",
                folder,
                poster,
                backdrop,
                ids,
                episodes));
        }

        File.AppendAllText(logPath, $"{DateTimeOffset.Now:u} result items={items.Count}{Environment.NewLine}");
        return items;
    }

    private static string? FindSubtitleForVideo(string videoPath, IReadOnlyList<string> subtitleFolders)
    {
        var stem = Path.GetFileNameWithoutExtension(videoPath);
        foreach (var folder in subtitleFolders)
        {
            var directSubtitle = FindSubtitleInFolder(folder, stem);
            if (directSubtitle is not null)
            {
                return directSubtitle;
            }

            foreach (var languageFolder in Directory.EnumerateDirectories(folder)
                .OrderBy(Path.GetFileName, StringComparer.CurrentCultureIgnoreCase))
            {
                var languageSubtitle = FindSubtitleInFolder(languageFolder, stem);
                if (languageSubtitle is not null)
                {
                    return languageSubtitle;
                }
            }
        }

        return null;
    }

    private static string? FindSubtitleInFolder(string folder, string stem)
    {
        foreach (var extension in SubtitleExtensions)
        {
            var exact = Path.Combine(folder, stem + extension);
            if (File.Exists(exact))
            {
                return exact;
            }
        }

        return null;
    }

    private static string? FindImage(string folder, IReadOnlyList<string> names)
    {
        foreach (var name in names)
        {
            foreach (var extension in ImageExtensions)
            {
                var path = Path.Combine(folder, name + extension);
                if (File.Exists(path))
                {
                    return path;
                }
            }
        }

        return null;
    }

    private static string? FindFirstImage(string folder)
    {
        return Directory.EnumerateFiles(folder)
            .FirstOrDefault(path => ImageExtensions.Contains(Path.GetExtension(path)));
    }

    private static int? ExtractEpisodeNumber(string path)
    {
        var stem = Path.GetFileNameWithoutExtension(path);
        var match = EpisodeNumberRegex().Match(stem);
        return match.Success && int.TryParse(match.Groups[1].Value, out var number) ? number : null;
    }

    private static string CleanTitle(string folderName)
    {
        return IdRegex().Replace(folderName, "").Trim();
    }

    private static string NaturalSortKey(string path)
    {
        return NumberRegex().Replace(Path.GetFileNameWithoutExtension(path), match => match.Value.PadLeft(12, '0'));
    }

    [GeneratedRegex(@"\[(\d+)\]")]
    private static partial Regex IdRegex();

    [GeneratedRegex(@"(?:^|[^\d])(\d{1,4})(?:[^\d]|$)")]
    private static partial Regex EpisodeNumberRegex();

    [GeneratedRegex(@"\d+")]
    private static partial Regex NumberRegex();
}
