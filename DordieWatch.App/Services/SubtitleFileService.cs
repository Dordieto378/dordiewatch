using DordieWatch.App.Models;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

namespace DordieWatch.App.Services;

public sealed partial class SubtitleFileService(IAppPaths paths) : ISubtitleFileService
{
    private const string SubtitleRootFolderName = "subs";
    private const string AssExtension = ".ass";
    private const int DefaultPlayResX = 1920;
    private const int DefaultPlayResY = 1080;
    private const string NetflixSansBoldFontFamily = "Netflix Sans";
    private const string NetflixSansBoldFontFileName = "NetflixSans-Bold.otf";

    private static readonly HashSet<string> FontFileExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".otf", ".ttf", ".ttc", ".otc"
    };

    public IReadOnlyList<ExternalSubtitleInfo> FindForVideo(string videoPath)
    {
        try
        {
            var videoFolder = Path.GetDirectoryName(videoPath);
            if (string.IsNullOrWhiteSpace(videoFolder) || !Directory.Exists(videoFolder))
            {
                return [];
            }

            var subtitlesRoot = FindSubtitlesRoot(videoFolder);
            if (subtitlesRoot is null)
            {
                return [];
            }

            var videoStem = Path.GetFileNameWithoutExtension(videoPath);
            return Directory.EnumerateDirectories(subtitlesRoot)
                .Select(languageFolder => new ExternalSubtitleInfo(
                    Path.GetFileName(languageFolder),
                    FindSubtitleFile(languageFolder, videoStem) ?? ""))
                .Where(subtitle => !string.IsNullOrWhiteSpace(subtitle.Language)
                    && !string.IsNullOrWhiteSpace(subtitle.Path))
                .OrderBy(subtitle => subtitle.Language, StringComparer.CurrentCultureIgnoreCase)
                .ToArray();
        }
        catch (IOException)
        {
            return [];
        }
        catch (UnauthorizedAccessException)
        {
            return [];
        }
    }

    public PreparedSubtitleInfo PrepareForPlayback(string subtitlePath)
    {
        var originalPlaybackInfo = CreateOriginalPlaybackInfo(subtitlePath);
        if (!File.Exists(subtitlePath)
            || !string.Equals(Path.GetExtension(subtitlePath), AssExtension, StringComparison.OrdinalIgnoreCase))
        {
            return originalPlaybackInfo;
        }

        try
        {
            var sourceInfo = new FileInfo(subtitlePath);
            var hasFontFiles = HasSiblingFontFiles(sourceInfo.DirectoryName);
            var usesNetflixSansBold = UsesNetflixSansBold(subtitlePath);
            var normalizedText = NormalizeAss(subtitlePath, usesNetflixSansBold);
            if (normalizedText is null && !hasFontFiles && !usesNetflixSansBold)
            {
                return originalPlaybackInfo;
            }

            var cacheKey = $"prepare-ass-v11|{sourceInfo.FullName}|{sourceInfo.Length}|{sourceInfo.LastWriteTimeUtc.Ticks}|{normalizedText is not null}|{usesNetflixSansBold}";
            var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(cacheKey)))
                .ToLowerInvariant()[..16];
            var cacheDirectory = Path.Combine(paths.AppDataDirectory, "subtitle-cache", hash);
            Directory.CreateDirectory(cacheDirectory);
            if (hasFontFiles)
            {
                CopySiblingFontFiles(sourceInfo.DirectoryName, cacheDirectory);
            }

            if (usesNetflixSansBold)
            {
                CopyBundledNetflixSansBoldFont(cacheDirectory);
            }

            var cachePath = Path.Combine(cacheDirectory, sourceInfo.Name);
            if (normalizedText is null)
            {
                if (ShouldCopyFile(subtitlePath, cachePath))
                {
                    File.Copy(subtitlePath, cachePath, overwrite: true);
                }
            }
            else if (!File.Exists(cachePath)
                || !string.Equals(File.ReadAllText(cachePath), normalizedText, StringComparison.Ordinal))
            {
                File.WriteAllText(cachePath, normalizedText, Encoding.UTF8);
            }

            return new PreparedSubtitleInfo(cachePath, cacheDirectory);
        }
        catch (IOException)
        {
            return originalPlaybackInfo;
        }
        catch (UnauthorizedAccessException)
        {
            return originalPlaybackInfo;
        }
    }

    private string? FindSubtitlesRoot(string videoFolder)
    {
        var current = new DirectoryInfo(videoFolder);
        var libraryRoot = Directory.Exists(paths.VideoLibraryDirectory)
            ? new DirectoryInfo(paths.VideoLibraryDirectory).FullName
            : null;

        while (current is not null)
        {
            var subtitlesRoot = Directory.EnumerateDirectories(current.FullName)
                .FirstOrDefault(path => string.Equals(
                    Path.GetFileName(path),
                    SubtitleRootFolderName,
                    StringComparison.OrdinalIgnoreCase));
            if (subtitlesRoot is not null)
            {
                return subtitlesRoot;
            }

            if (libraryRoot is not null
                && string.Equals(current.FullName, libraryRoot, StringComparison.OrdinalIgnoreCase))
            {
                break;
            }

            current = current.Parent;
        }

        return null;
    }

    private static string? FindSubtitleFile(string languageFolder, string videoStem)
    {
        var exactPath = Path.Combine(languageFolder, videoStem + AssExtension);
        if (File.Exists(exactPath))
        {
            return exactPath;
        }

        var languageSubtitles = Directory.EnumerateFiles(languageFolder, "*" + AssExtension, SearchOption.AllDirectories)
            .OrderBy(path => path.Length)
            .ThenBy(path => path, StringComparer.CurrentCultureIgnoreCase)
            .ToArray();
        var caseInsensitiveMatch = languageSubtitles
            .FirstOrDefault(path => string.Equals(
                Path.GetFileNameWithoutExtension(path),
                videoStem,
                StringComparison.OrdinalIgnoreCase));
        if (caseInsensitiveMatch is not null)
        {
            return caseInsensitiveMatch;
        }

        if (!int.TryParse(videoStem, NumberStyles.Integer, CultureInfo.InvariantCulture, out var videoNumber))
        {
            return null;
        }

        return languageSubtitles.FirstOrDefault(path =>
            int.TryParse(Path.GetFileNameWithoutExtension(path), NumberStyles.Integer, CultureInfo.InvariantCulture, out var subtitleNumber)
            && subtitleNumber == videoNumber);
    }

    private static void CopySiblingFontFiles(string? sourceDirectory, string cacheDirectory)
    {
        if (string.IsNullOrWhiteSpace(sourceDirectory) || !Directory.Exists(sourceDirectory))
        {
            return;
        }

        foreach (var fontPath in Directory.EnumerateFiles(sourceDirectory, "*", SearchOption.AllDirectories)
            .Where(path => FontFileExtensions.Contains(Path.GetExtension(path))))
        {
            var targetPath = Path.Combine(cacheDirectory, Path.GetFileName(fontPath));
            if (ShouldCopyFile(fontPath, targetPath))
            {
                File.Copy(fontPath, targetPath, overwrite: true);
            }
        }
    }

    private static bool ShouldCopyFile(string sourcePath, string targetPath)
    {
        if (!File.Exists(targetPath))
        {
            return true;
        }

        var sourceInfo = new FileInfo(sourcePath);
        var targetInfo = new FileInfo(targetPath);
        return sourceInfo.Length != targetInfo.Length
            || sourceInfo.LastWriteTimeUtc != targetInfo.LastWriteTimeUtc;
    }

    private static bool HasSiblingFontFiles(string? sourceDirectory)
    {
        return !string.IsNullOrWhiteSpace(sourceDirectory)
            && Directory.Exists(sourceDirectory)
            && Directory.EnumerateFiles(sourceDirectory, "*", SearchOption.AllDirectories)
                .Any(path => FontFileExtensions.Contains(Path.GetExtension(path)));
    }

    private static void CopyBundledNetflixSansBoldFont(string cacheDirectory)
    {
        var sourcePath = Path.Combine(AppContext.BaseDirectory, "Assets", "Fonts", NetflixSansBoldFontFileName);
        if (!File.Exists(sourcePath))
        {
            return;
        }

        var targetPath = Path.Combine(cacheDirectory, NetflixSansBoldFontFileName);
        if (ShouldCopyFile(sourcePath, targetPath))
        {
            File.Copy(sourcePath, targetPath, overwrite: true);
        }
    }

    private static bool UsesNetflixSansBold(string subtitlePath)
    {
        var text = File.ReadAllText(subtitlePath);
        return text.Contains("NetflixSans", StringComparison.OrdinalIgnoreCase)
            || text.Contains("Netflix Sans", StringComparison.OrdinalIgnoreCase);
    }

    private static PreparedSubtitleInfo CreateOriginalPlaybackInfo(string subtitlePath)
    {
        return new PreparedSubtitleInfo(
            subtitlePath,
            Path.GetDirectoryName(subtitlePath) ?? "");
    }

    private static string? NormalizeAss(string subtitlePath, bool normalizeNetflixStyles)
    {
        var text = File.ReadAllText(subtitlePath);
        var newline = text.Contains("\r\n", StringComparison.Ordinal) ? "\r\n" : "\n";
        var lines = text.Replace("\r\n", "\n", StringComparison.Ordinal)
            .Replace('\r', '\n')
            .Split('\n')
            .ToList();
        var changed = normalizeNetflixStyles && EnsureScriptResolution(lines);
        var section = "";
        var playResY = DefaultPlayResY;
        var styleFormat = Array.Empty<string>();
        var eventFormat = Array.Empty<string>();
        var normalizedStyleNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        for (var index = 0; index < lines.Count; index++)
        {
            var line = lines[index];
            var trimmed = line.Trim();
            if (trimmed.StartsWith("[", StringComparison.Ordinal)
                && trimmed.EndsWith("]", StringComparison.Ordinal))
            {
                section = trimmed[1..^1];
                continue;
            }

            if (string.Equals(section, "Script Info", StringComparison.OrdinalIgnoreCase))
            {
                playResY = TryReadPlayResY(trimmed) ?? playResY;
                var normalizedLine = NormalizeScriptInfoLine(line);
                if (!string.Equals(line, normalizedLine, StringComparison.Ordinal))
                {
                    lines[index] = normalizedLine;
                    changed = true;
                }

                continue;
            }

            if (string.Equals(section, "V4+ Styles", StringComparison.OrdinalIgnoreCase)
                || string.Equals(section, "V4 Styles", StringComparison.OrdinalIgnoreCase))
            {
                if (trimmed.StartsWith("Format:", StringComparison.OrdinalIgnoreCase))
                {
                    styleFormat = ParseFormat(line, "Format:");
                    continue;
                }

                if (trimmed.StartsWith("Style:", StringComparison.OrdinalIgnoreCase))
                {
                    var normalizedLine = NormalizeStyleLine(
                        line,
                        styleFormat,
                        playResY,
                        normalizedStyleNames);
                    if (!string.Equals(line, normalizedLine, StringComparison.Ordinal))
                    {
                        lines[index] = normalizedLine;
                        changed = true;
                    }
                }

                continue;
            }

            if (string.Equals(section, "Events", StringComparison.OrdinalIgnoreCase))
            {
                if (trimmed.StartsWith("Format:", StringComparison.OrdinalIgnoreCase))
                {
                    eventFormat = ParseFormat(line, "Format:");
                    continue;
                }

                if (trimmed.StartsWith("Dialogue:", StringComparison.OrdinalIgnoreCase))
                {
                    var normalizedLine = NormalizeDialogueLine(line, eventFormat, normalizedStyleNames);
                    if (!string.Equals(line, normalizedLine, StringComparison.Ordinal))
                    {
                        lines[index] = normalizedLine;
                        changed = true;
                    }
                }
            }
        }

        return changed ? string.Join(newline, lines) : null;
    }

    private static int? TryReadPlayResY(string line)
    {
        const string prefix = "PlayResY:";
        return TryReadPositiveInt(line, prefix);
    }

    private static bool EnsureScriptResolution(List<string> lines)
    {
        var scriptInfoIndex = lines.FindIndex(line =>
            string.Equals(line.Trim(), "[Script Info]", StringComparison.OrdinalIgnoreCase));
        if (scriptInfoIndex < 0)
        {
            lines.InsertRange(0,
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                $"PlayResX: {DefaultPlayResX}",
                $"PlayResY: {DefaultPlayResY}",
                ""
            ]);
            return true;
        }

        var sectionEnd = lines.FindIndex(
            scriptInfoIndex + 1,
            line => line.TrimStart().StartsWith("[", StringComparison.Ordinal));
        if (sectionEnd < 0)
        {
            sectionEnd = lines.Count;
        }

        var hasPlayResX = false;
        var hasPlayResY = false;
        for (var index = scriptInfoIndex + 1; index < sectionEnd; index++)
        {
            var line = lines[index].Trim();
            hasPlayResX |= line.StartsWith("PlayResX:", StringComparison.OrdinalIgnoreCase);
            hasPlayResY |= line.StartsWith("PlayResY:", StringComparison.OrdinalIgnoreCase);
        }

        if (hasPlayResX && hasPlayResY)
        {
            return false;
        }

        var insertIndex = sectionEnd;
        while (insertIndex > scriptInfoIndex + 1 && string.IsNullOrWhiteSpace(lines[insertIndex - 1]))
        {
            insertIndex--;
        }

        if (!hasPlayResX)
        {
            lines.Insert(insertIndex++, $"PlayResX: {DefaultPlayResX}");
        }

        if (!hasPlayResY)
        {
            lines.Insert(insertIndex, $"PlayResY: {DefaultPlayResY}");
        }

        return true;
    }

    private static int? TryReadPositiveInt(string line, string prefix)
    {
        if (!line.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }

        return int.TryParse(line[prefix.Length..].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var value)
            && value > 0
            ? value
            : null;
    }

    private static string NormalizeScriptInfoLine(string line)
    {
        var separatorIndex = line.IndexOf(':');
        if (separatorIndex < 0)
        {
            return line;
        }

        var name = line[..separatorIndex].Trim();
        var prefix = line[..(separatorIndex + 1)];
        if (string.Equals(name, "WrapStyle", StringComparison.OrdinalIgnoreCase))
        {
            return prefix + " 0";
        }

        if (string.Equals(name, "ScaledBorderAndShadow", StringComparison.OrdinalIgnoreCase))
        {
            return prefix + " yes";
        }

        return line;
    }

    private static string NormalizeStyleLine(
        string line,
        IReadOnlyList<string> styleFormat,
        int playResY,
        HashSet<string> normalizedStyleNames)
    {
        var styleIndex = line.IndexOf("Style:", StringComparison.OrdinalIgnoreCase);
        if (styleIndex < 0 || styleFormat.Count == 0)
        {
            return line;
        }

        var payloadStart = styleIndex + "Style:".Length;
        var prefix = line[..payloadStart];
        var fields = SplitAssFields(line[payloadStart..], styleFormat.Count);
        var nameIndex = FindFormatIndex(styleFormat, "Name");
        var fontNameIndex = FindFormatIndex(styleFormat, "Fontname", "FontName");
        if (fields.Length != styleFormat.Count
            || nameIndex < 0
            || fontNameIndex < 0
            || !IsNetflixSansBold(fields[fontNameIndex]))
        {
            return line;
        }

        normalizedStyleNames.Add(fields[nameIndex].Trim());
        fields[fontNameIndex] = NetflixSansBoldFontFamily;
        SetField(styleFormat, fields, "Fontsize", GetDefaultFontSize(playResY));
        SetField(styleFormat, fields, "PrimaryColour", "&H00FFFFFF");
        SetField(styleFormat, fields, "SecondaryColour", "&H000000FF");
        SetField(styleFormat, fields, "OutlineColour", "&H00000000");
        SetField(styleFormat, fields, "TertiaryColour", "&H00000000");
        SetField(styleFormat, fields, "BackColour", "&H80000000");
        SetField(styleFormat, fields, "Bold", "-1");
        SetField(styleFormat, fields, "Italic", "0");
        SetField(styleFormat, fields, "Underline", "0");
        SetField(styleFormat, fields, "StrikeOut", "0");
        SetField(styleFormat, fields, "ScaleX", "100");
        SetField(styleFormat, fields, "ScaleY", "100");
        SetField(styleFormat, fields, "Spacing", "0");
        SetField(styleFormat, fields, "Angle", "0");
        SetField(styleFormat, fields, "BorderStyle", "1");
        SetField(styleFormat, fields, "Outline", GetDefaultOutline(playResY));
        SetField(styleFormat, fields, "Shadow", "0");
        SetField(styleFormat, fields, "Blur", "0");
        SetField(styleFormat, fields, "AlphaLevel", "0");
        SetField(styleFormat, fields, "Alignment", "2");
        SetField(styleFormat, fields, "MarginL", GetDefaultMargin(playResY));
        SetField(styleFormat, fields, "MarginR", GetDefaultMargin(playResY));
        SetField(styleFormat, fields, "MarginV", GetDefaultMargin(playResY));
        SetField(styleFormat, fields, "Encoding", "1");

        return prefix + string.Join(",", fields);
    }

    private static string NormalizeDialogueLine(
        string line,
        IReadOnlyList<string> eventFormat,
        HashSet<string> normalizedStyleNames)
    {
        var dialogueIndex = line.IndexOf("Dialogue:", StringComparison.OrdinalIgnoreCase);
        if (dialogueIndex < 0 || eventFormat.Count == 0)
        {
            return line;
        }

        var payloadStart = dialogueIndex + "Dialogue:".Length;
        var fields = SplitAssFields(line[payloadStart..], eventFormat.Count);
        var styleIndex = FindFormatIndex(eventFormat, "Style");
        var textIndex = FindFormatIndex(eventFormat, "Text");
        if (fields.Length != eventFormat.Count
            || styleIndex < 0
            || textIndex < 0
            || !normalizedStyleNames.Contains(fields[styleIndex].Trim()))
        {
            return line;
        }

        SetField(eventFormat, fields, "MarginL", "0000");
        SetField(eventFormat, fields, "MarginR", "0000");
        SetField(eventFormat, fields, "MarginV", "0000");
        SetField(eventFormat, fields, "Effect", "");

        fields[textIndex] = OverrideBlockRegex().Replace(fields[textIndex], match =>
        {
            var preservedTags = PreservePositionOverrideTags(match.Value[1..^1]);
            return preservedTags.Length == 0 ? "" : "{" + preservedTags + "}";
        });

        return line[..payloadStart] + string.Join(",", fields);
    }

    private static string PreservePositionOverrideTags(string value)
    {
        var builder = new StringBuilder();
        var index = 0;
        while (index < value.Length)
        {
            if (value[index] != '\\')
            {
                index++;
                continue;
            }

            var tagStart = index;
            index++;
            var nameStart = index;
            if (index < value.Length && char.IsDigit(value[index]))
            {
                while (index < value.Length && char.IsDigit(value[index]))
                {
                    index++;
                }

                while (index < value.Length && char.IsLetter(value[index]))
                {
                    index++;
                }
            }
            else
            {
                while (index < value.Length && char.IsLetter(value[index]))
                {
                    index++;
                }
            }

            if (index == nameStart)
            {
                continue;
            }

            var tagName = value[nameStart..index];
            if (index < value.Length && value[index] == '(')
            {
                index = ConsumeParenthesizedValue(value, index);
            }
            else
            {
                while (index < value.Length && value[index] != '\\')
                {
                    index++;
                }
            }

            if (IsPositionOverrideTag(tagName))
            {
                builder.Append(value, tagStart, index - tagStart);
            }
        }

        return builder.ToString();
    }

    private static int ConsumeParenthesizedValue(string value, int start)
    {
        var depth = 0;
        for (var index = start; index < value.Length; index++)
        {
            if (value[index] == '(')
            {
                depth++;
            }
            else if (value[index] == ')')
            {
                depth--;
                if (depth <= 0)
                {
                    return index + 1;
                }
            }
        }

        return value.Length;
    }

    private static bool IsPositionOverrideTag(string tagName)
    {
        return tagName.Equals("pos", StringComparison.OrdinalIgnoreCase)
            || tagName.Equals("move", StringComparison.OrdinalIgnoreCase)
            || tagName.Equals("org", StringComparison.OrdinalIgnoreCase)
            || tagName.Equals("an", StringComparison.OrdinalIgnoreCase)
            || tagName.Equals("a", StringComparison.OrdinalIgnoreCase);
    }

    private static string GetDefaultFontSize(int playResY)
    {
        var size = Math.Max(1, (int)Math.Round(playResY * 0.064));
        return size.ToString(CultureInfo.InvariantCulture);
    }

    private static string GetDefaultMargin(int playResY)
    {
        var margin = Math.Max(1, (int)Math.Round(playResY * 0.056));
        return margin.ToString("D4", CultureInfo.InvariantCulture);
    }

    private static string GetDefaultOutline(int playResY)
    {
        var outline = Math.Max(0.1, playResY * 0.00185);
        return outline.ToString("0.##", CultureInfo.InvariantCulture);
    }

    private static string[] ParseFormat(string line, string prefix)
    {
        var prefixIndex = line.IndexOf(prefix, StringComparison.OrdinalIgnoreCase);
        return prefixIndex < 0
            ? []
            : line[(prefixIndex + prefix.Length)..].Split(',', StringSplitOptions.TrimEntries);
    }

    private static string[] SplitAssFields(string value, int fieldCount)
    {
        var fields = new string[fieldCount];
        var start = 0;
        for (var index = 0; index < fieldCount - 1; index++)
        {
            var comma = value.IndexOf(',', start);
            if (comma < 0)
            {
                return [];
            }

            fields[index] = value[start..comma];
            start = comma + 1;
        }

        fields[^1] = value[start..];
        return fields;
    }

    private static int FindFormatIndex(IReadOnlyList<string> format, params string[] names)
    {
        for (var index = 0; index < format.Count; index++)
        {
            if (names.Any(name => string.Equals(format[index], name, StringComparison.OrdinalIgnoreCase)))
            {
                return index;
            }
        }

        return -1;
    }

    private static void SetField(
        IReadOnlyList<string> format,
        string[] fields,
        string name,
        string value)
    {
        var index = FindFormatIndex(format, name);
        if (index >= 0 && index < fields.Length)
        {
            fields[index] = value;
        }
    }

    private static bool IsNetflixSansBold(string fontName)
    {
        var normalized = NormalizeFontName(fontName);
        return normalized is "NETFLIXSANSBOLD" or "NETFLIXSANS";
    }

    private static string NormalizeFontName(string value)
    {
        var builder = new StringBuilder(value.Length);
        foreach (var character in value)
        {
            if (char.IsLetterOrDigit(character))
            {
                builder.Append(char.ToUpperInvariant(character));
            }
        }

        return builder.ToString();
    }

    [GeneratedRegex(@"\{[^{}]*\}")]
    private static partial Regex OverrideBlockRegex();
}
