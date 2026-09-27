using System.Globalization;
using System.Text;

namespace DordieWatch.App.Services;

internal static class MatroskaFontAttachmentReader
{
    private const int SegmentId = 0x18538067;
    private const int SeekHeadId = 0x114D9B74;
    private const int SeekId = 0x4DBB;
    private const int SeekTargetId = 0x53AB;
    private const int SeekPositionId = 0x53AC;
    private const int AttachmentsId = 0x1941A469;
    private const int AttachedFileId = 0x61A7;
    private const int FileNameId = 0x466E;
    private const int FileMimeTypeId = 0x4660;
    private const int FileDataId = 0x465C;
    private const int ClusterId = 0x1F43B675;

    public static HashSet<string> ReadEmbeddedFontKeys(string? videoPath)
    {
        var result = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (string.IsNullOrWhiteSpace(videoPath)
            || !File.Exists(videoPath)
            || !string.Equals(Path.GetExtension(videoPath), ".mkv", StringComparison.OrdinalIgnoreCase))
        {
            return result;
        }

        using var stream = File.Open(videoPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using var reader = new BinaryReader(stream);
        var fileEnd = stream.Length;
        ElementHeader? segment = null;
        while (stream.Position < fileEnd)
        {
            var header = ReadHeader(reader, fileEnd);
            if (header is null)
            {
                break;
            }

            if (header.Id == SegmentId)
            {
                segment = header;
                break;
            }

            if (header.HasUnknownSize)
            {
                break;
            }

            stream.Position = header.DataEnd;
        }

        if (segment is null)
        {
            return result;
        }

        var segmentStart = segment.DataStart;
        var segmentEnd = segment.HasUnknownSize ? fileEnd : segment.DataEnd;
        var attachmentOffsets = new List<long>();
        var parsedOffsets = new HashSet<long>();
        stream.Position = segmentStart;

        while (stream.Position < segmentEnd)
        {
            var elementOffset = stream.Position;
            var header = ReadHeader(reader, segmentEnd);
            if (header is null)
            {
                break;
            }

            if (header.Id == AttachmentsId)
            {
                ParseAttachments(reader, header.DataEnd, result);
                parsedOffsets.Add(elementOffset);
            }
            else if (header.Id == SeekHeadId && !header.HasUnknownSize)
            {
                attachmentOffsets.AddRange(ParseSeekHead(reader, header.DataEnd, segmentStart));
            }

            if (header.HasUnknownSize)
            {
                break;
            }

            stream.Position = header.DataEnd;
            if (header.Id == ClusterId)
            {
                break;
            }
        }

        foreach (var offset in attachmentOffsets)
        {
            if (offset <= 0 || offset >= segmentEnd || parsedOffsets.Contains(offset))
            {
                continue;
            }

            stream.Position = offset;
            var header = ReadHeader(reader, segmentEnd);
            if (header is not null && header.Id == AttachmentsId)
            {
                ParseAttachments(reader, header.DataEnd, result);
            }
        }

        return result;
    }

    public static HashSet<string> ReadFontFileKeys(string fontPath)
    {
        var result = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        AddAlias(result, Path.GetFileName(fontPath));
        foreach (var name in ParseFontNames(File.ReadAllBytes(fontPath)))
        {
            AddAlias(result, name);
        }

        return result;
    }

    private static List<long> ParseSeekHead(BinaryReader reader, long end, long segmentStart)
    {
        var result = new List<long>();
        while (reader.BaseStream.Position < end)
        {
            var header = ReadHeader(reader, end);
            if (header is null)
            {
                break;
            }

            if (header.Id == SeekId && !header.HasUnknownSize)
            {
                var targetId = 0;
                ulong position = 0;
                while (reader.BaseStream.Position < header.DataEnd)
                {
                    var child = ReadHeader(reader, header.DataEnd);
                    if (child is null)
                    {
                        break;
                    }

                    if (child.Id == SeekTargetId && !child.HasUnknownSize)
                    {
                        foreach (var value in ReadBytes(reader, child.Size))
                        {
                            targetId = (targetId << 8) | value;
                        }
                    }
                    else if (child.Id == SeekPositionId && !child.HasUnknownSize)
                    {
                        position = ReadUnsignedBigEndian(ReadBytes(reader, child.Size));
                    }

                    reader.BaseStream.Position = child.DataEnd;
                }

                if (targetId == AttachmentsId && position <= long.MaxValue - (ulong)segmentStart)
                {
                    result.Add(segmentStart + (long)position);
                }
            }

            reader.BaseStream.Position = header.DataEnd;
        }

        return result;
    }

    private static void ParseAttachments(BinaryReader reader, long end, HashSet<string> result)
    {
        while (reader.BaseStream.Position < end)
        {
            var header = ReadHeader(reader, end);
            if (header is null)
            {
                break;
            }

            if (header.Id == AttachedFileId && !header.HasUnknownSize)
            {
                ParseAttachedFile(reader, header.DataEnd, result);
            }

            reader.BaseStream.Position = header.DataEnd;
        }
    }

    private static void ParseAttachedFile(BinaryReader reader, long end, HashSet<string> result)
    {
        var fileName = "";
        var mimeType = "";
        byte[]? data = null;
        while (reader.BaseStream.Position < end)
        {
            var header = ReadHeader(reader, end);
            if (header is null)
            {
                break;
            }

            if (header.Id == FileNameId && !header.HasUnknownSize)
            {
                fileName = DecodeString(ReadBytes(reader, header.Size));
            }
            else if (header.Id == FileMimeTypeId && !header.HasUnknownSize)
            {
                mimeType = DecodeString(ReadBytes(reader, header.Size));
            }
            else if (header.Id == FileDataId && !header.HasUnknownSize)
            {
                data = ReadBytes(reader, header.Size);
            }

            reader.BaseStream.Position = header.DataEnd;
        }

        if (!IsFont(fileName, mimeType))
        {
            return;
        }

        AddAlias(result, fileName);
        if (data is null)
        {
            return;
        }

        foreach (var name in ParseFontNames(data))
        {
            AddAlias(result, name);
        }
    }

    private static IEnumerable<string> ParseFontNames(byte[] data)
    {
        var names = new List<string>();
        if (data.Length < 12)
        {
            return names;
        }

        if (data[0] == 't' && data[1] == 't' && data[2] == 'c' && data[3] == 'f')
        {
            var count = ReadUInt32BigEndian(data, 8);
            for (uint index = 0; index < count && 12 + index * 4 + 4 <= data.Length; index++)
            {
                ParseSfntNames(data, (int)ReadUInt32BigEndian(data, 12 + (int)index * 4), names);
            }
        }
        else
        {
            ParseSfntNames(data, 0, names);
        }

        return names;
    }

    private static void ParseSfntNames(byte[] data, int fontOffset, List<string> names)
    {
        if (fontOffset < 0 || fontOffset + 12 > data.Length)
        {
            return;
        }

        var signature = ReadUInt32BigEndian(data, fontOffset);
        if (signature is not (0x00010000 or 0x4F54544F or 0x74727565 or 0x74797031))
        {
            return;
        }

        var tableCount = ReadUInt16BigEndian(data, fontOffset + 4);
        var tableDirectory = fontOffset + 12;
        var nameOffset = -1;
        for (var index = 0; index < tableCount; index++)
        {
            var record = tableDirectory + index * 16;
            if (record + 16 > data.Length)
            {
                return;
            }

            if (data[record] == 'n' && data[record + 1] == 'a'
                && data[record + 2] == 'm' && data[record + 3] == 'e')
            {
                nameOffset = (int)ReadUInt32BigEndian(data, record + 8);
                break;
            }
        }

        if (nameOffset < 0 || nameOffset + 6 > data.Length)
        {
            return;
        }

        var count = ReadUInt16BigEndian(data, nameOffset + 2);
        var stringStorage = nameOffset + ReadUInt16BigEndian(data, nameOffset + 4);
        var families = new Dictionary<string, string>();
        var subfamilies = new Dictionary<string, string>();
        for (var index = 0; index < count; index++)
        {
            var record = nameOffset + 6 + index * 12;
            if (record + 12 > data.Length)
            {
                break;
            }

            var platform = ReadUInt16BigEndian(data, record);
            var encoding = ReadUInt16BigEndian(data, record + 2);
            var language = ReadUInt16BigEndian(data, record + 4);
            var nameId = ReadUInt16BigEndian(data, record + 6);
            var length = ReadUInt16BigEndian(data, record + 8);
            var position = stringStorage + ReadUInt16BigEndian(data, record + 10);
            if (length <= 0 || position < 0 || position + length > data.Length)
            {
                continue;
            }

            var value = CleanName(DecodeFontName(data, position, length, platform));
            if (value.Length == 0)
            {
                continue;
            }

            if (nameId is 1 or 2 or 4 or 6 or 16 or 17)
            {
                names.Add(value);
            }

            var languageKey = $"{platform}:{encoding}:{language}";
            if (nameId is 1 or 16)
            {
                families[languageKey] = value;
            }
            else if (nameId is 2 or 17)
            {
                subfamilies[languageKey] = value;
            }
        }

        foreach (var (language, family) in families)
        {
            if (!subfamilies.TryGetValue(language, out var subfamily)
                || subfamily.Equals("Regular", StringComparison.OrdinalIgnoreCase)
                || subfamily.Equals("Normal", StringComparison.OrdinalIgnoreCase)
                || subfamily.Equals("Book", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            names.Add(family + " " + subfamily);
        }
    }

    private static ElementHeader? ReadHeader(BinaryReader reader, long limit)
    {
        if (reader.BaseStream.Position >= limit)
        {
            return null;
        }

        var id = ReadElementId(reader);
        if (id < 0)
        {
            return null;
        }

        var size = ReadElementSize(reader, out var unknownSize);
        var start = reader.BaseStream.Position;
        var end = unknownSize || size > limit - start ? limit : start + size;
        return new ElementHeader(id, size, unknownSize, start, end);
    }

    private static int ReadElementId(BinaryReader reader)
    {
        var first = reader.ReadByte();
        var length = (first & 0x80) != 0 ? 1
            : (first & 0x40) != 0 ? 2
            : (first & 0x20) != 0 ? 3
            : (first & 0x10) != 0 ? 4
            : 0;
        if (length == 0)
        {
            return -1;
        }

        var value = (int)first;
        for (var index = 1; index < length; index++)
        {
            value = (value << 8) | reader.ReadByte();
        }

        return value;
    }

    private static long ReadElementSize(BinaryReader reader, out bool unknown)
    {
        var first = reader.ReadByte();
        var length = 1;
        var mask = 0x80;
        while (length <= 8 && (first & mask) == 0)
        {
            mask >>= 1;
            length++;
        }

        if (length > 8)
        {
            throw new InvalidDataException("Invalid EBML element size.");
        }

        ulong value = (uint)(first & (mask - 1));
        for (var index = 1; index < length; index++)
        {
            value = (value << 8) | reader.ReadByte();
        }

        unknown = value == (1UL << (7 * length)) - 1;
        return unknown || value > long.MaxValue ? long.MaxValue : (long)value;
    }

    private static byte[] ReadBytes(BinaryReader reader, long size)
    {
        if (size < 0 || size > int.MaxValue)
        {
            throw new InvalidDataException("Font attachment is too large.");
        }

        return reader.ReadBytes((int)size);
    }

    private static string DecodeString(byte[] data)
    {
        return Encoding.UTF8.GetString(data).TrimEnd('\0');
    }

    private static string DecodeFontName(byte[] data, int offset, int length, int platform)
    {
        try
        {
            return platform is 0 or 3
                ? Encoding.BigEndianUnicode.GetString(data, offset, length)
                : Encoding.Latin1.GetString(data, offset, length);
        }
        catch
        {
            return "";
        }
    }

    private static bool IsFont(string fileName, string mimeType)
    {
        var extension = Path.GetExtension(fileName);
        return extension.Equals(".ttf", StringComparison.OrdinalIgnoreCase)
            || extension.Equals(".otf", StringComparison.OrdinalIgnoreCase)
            || extension.Equals(".ttc", StringComparison.OrdinalIgnoreCase)
            || extension.Equals(".otc", StringComparison.OrdinalIgnoreCase)
            || mimeType.Contains("font", StringComparison.OrdinalIgnoreCase)
            || mimeType.Contains("truetype", StringComparison.OrdinalIgnoreCase)
            || mimeType.Contains("opentype", StringComparison.OrdinalIgnoreCase);
    }

    private static void AddAlias(HashSet<string> keys, string value)
    {
        var clean = CleanName(value);
        if (clean.Length == 0)
        {
            return;
        }

        keys.Add(NormalizeFontKey(clean));
        keys.Add(NormalizeFontKey(Path.GetFileNameWithoutExtension(clean)));
        keys.Remove("");
    }

    private static string CleanName(string value)
    {
        var builder = new StringBuilder(value.Length);
        var previousWasSpace = false;
        foreach (var character in value)
        {
            if (char.IsControl(character))
            {
                continue;
            }

            if (char.IsWhiteSpace(character))
            {
                if (!previousWasSpace)
                {
                    builder.Append(' ');
                }

                previousWasSpace = true;
                continue;
            }

            builder.Append(character);
            previousWasSpace = false;
        }

        return builder.ToString().Trim();
    }

    private static string NormalizeFontKey(string value)
    {
        var normalized = CleanName(value).TrimStart('@').Normalize(NormalizationForm.FormKD);
        var builder = new StringBuilder(normalized.Length);
        foreach (var character in normalized)
        {
            var category = CharUnicodeInfo.GetUnicodeCategory(character);
            if (category is UnicodeCategory.NonSpacingMark
                or UnicodeCategory.SpacingCombiningMark
                or UnicodeCategory.EnclosingMark)
            {
                continue;
            }

            if (char.IsLetterOrDigit(character))
            {
                builder.Append(char.ToLowerInvariant(character));
            }
        }

        return builder.ToString();
    }

    private static int ReadUInt16BigEndian(byte[] data, int offset)
    {
        return offset + 2 <= data.Length ? (data[offset] << 8) | data[offset + 1] : 0;
    }

    private static uint ReadUInt32BigEndian(byte[] data, int offset)
    {
        return offset + 4 <= data.Length
            ? ((uint)data[offset] << 24) | ((uint)data[offset + 1] << 16)
                | ((uint)data[offset + 2] << 8) | data[offset + 3]
            : 0;
    }

    private static ulong ReadUnsignedBigEndian(byte[] data)
    {
        ulong value = 0;
        foreach (var item in data)
        {
            value = (value << 8) | item;
        }

        return value;
    }

    private sealed record ElementHeader(int Id, long Size, bool HasUnknownSize, long DataStart, long DataEnd);
}
