using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

public static class SubtitleFontAvailabilityScanner
{
    const int IdSegment = 0x18538067;
    const int IdSeekHead = 0x114D9B74;
    const int IdSeek = 0x4DBB;
    const int IdSeekID = 0x53AB;
    const int IdSeekPosition = 0x53AC;
    const int IdAttachments = 0x1941A469;
    const int IdAttachedFile = 0x61A7;
    const int IdFileName = 0x466E;
    const int IdFileMimeType = 0x4660;
    const int IdFileData = 0x465C;
    const int IdCluster = 0x1F43B675;

    class Header
    {
        public int Id;
        public long Size;
        public bool UnknownSize;
        public long DataStart;
        public long DataEnd;
    }

    class FontSet
    {
        readonly Dictionary<string, string> aliases = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        public void AddAlias(string value)
        {
            string clean = Clean(value);
            if (clean.Length == 0) return;
            AddKey(NormalizeFontKey(clean), clean);
            AddKey(NormalizeFontKey(NameWithoutExtension(clean)), clean);
        }

        public void AddAliases(IEnumerable<string> values)
        {
            foreach (string value in values) AddAlias(value);
        }

        void AddKey(string key, string value)
        {
            if (key.Length == 0) return;
            if (!aliases.ContainsKey(key)) aliases.Add(key, value);
        }

        public bool Has(string fontName)
        {
            string key = NormalizeFontKey(fontName);
            return key.Length > 0 && aliases.ContainsKey(key);
        }
    }

    class AssFile
    {
        public string Title;
        public string Path;
        public string FileName;
        public string BaseName;
        public HashSet<string> Fonts = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    }

    class TitleFontInfo
    {
        public string Font;
        public HashSet<string> RequiredMkvs = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        public int UnmatchedAssFiles;
    }

    class MkvFile
    {
        public string Title;
        public string Path;
        public string FileName;
        public string BaseName;
        public int NumericStem;
    }

    class TitleResult
    {
        public string Title;
        public int AssCount;
        public int MkvCount;
        public List<string> Embedded = new List<string>();
        public List<string> Installed = new List<string>();
        public List<string> NeedInstall = new List<string>();
        public List<string> CouldNotCheck = new List<string>();
    }

    static string root;
    static readonly FontSet InstalledFonts = new FontSet();
    static readonly Dictionary<string, FontSet> MkvFonts = new Dictionary<string, FontSet>(StringComparer.OrdinalIgnoreCase);

    static string Clean(string value)
    {
        if (value == null) return "";
        StringBuilder sb = new StringBuilder(value.Length);
        bool inSpace = false;
        for (int i = 0; i < value.Length; i++)
        {
            char ch = value[i];
            if (char.IsControl(ch)) continue;
            if (char.IsWhiteSpace(ch))
            {
                if (!inSpace) sb.Append(' ');
                inSpace = true;
            }
            else
            {
                sb.Append(ch);
                inSpace = false;
            }
        }
        return sb.ToString().Trim();
    }

    static string NameWithoutExtension(string value)
    {
        string clean = Clean(value);
        int slash = Math.Max(clean.LastIndexOf('/'), clean.LastIndexOf('\\'));
        if (slash >= 0) clean = clean.Substring(slash + 1);
        int dot = clean.LastIndexOf('.');
        if (dot > 0) clean = clean.Substring(0, dot);
        return clean;
    }

    static string NormalizeFontKey(string value)
    {
        string s = Clean(value).TrimStart('@');
        if (s.Length == 0) return "";
        s = s.Normalize(NormalizationForm.FormKD).ToLowerInvariant();
        StringBuilder sb = new StringBuilder(s.Length);
        for (int i = 0; i < s.Length; i++)
        {
            UnicodeCategory cat = CharUnicodeInfo.GetUnicodeCategory(s[i]);
            if (cat == UnicodeCategory.NonSpacingMark || cat == UnicodeCategory.SpacingCombiningMark || cat == UnicodeCategory.EnclosingMark) continue;
            if (char.IsLetterOrDigit(s[i])) sb.Append(s[i]);
        }
        return sb.ToString();
    }

    static int FontCompare(string a, string b)
    {
        int c = StringComparer.OrdinalIgnoreCase.Compare((a ?? "").TrimStart('@'), (b ?? "").TrimStart('@'));
        if (c != 0) return c;
        return StringComparer.OrdinalIgnoreCase.Compare(a, b);
    }

    static byte[] ReadBytes(BinaryReader br, long size)
    {
        if (size < 0 || size > int.MaxValue) throw new InvalidDataException("Element too large to read.");
        return br.ReadBytes((int)size);
    }

    static Header ReadHeader(BinaryReader br, long limit)
    {
        if (br.BaseStream.Position >= limit) return null;
        int id = ReadEbmlId(br);
        if (id < 0) return null;
        bool unknown;
        long size = ReadEbmlSize(br, out unknown);
        long start = br.BaseStream.Position;
        long end = unknown ? limit : start + size;
        if (end > limit) end = limit;
        return new Header { Id = id, Size = size, UnknownSize = unknown, DataStart = start, DataEnd = end };
    }

    static int ReadEbmlId(BinaryReader br)
    {
        int first = br.ReadByte();
        int len;
        if ((first & 0x80) != 0) len = 1;
        else if ((first & 0x40) != 0) len = 2;
        else if ((first & 0x20) != 0) len = 3;
        else if ((first & 0x10) != 0) len = 4;
        else return -1;
        int value = first;
        for (int i = 1; i < len; i++) value = (value << 8) | br.ReadByte();
        return value;
    }

    static long ReadEbmlSize(BinaryReader br, out bool unknown)
    {
        int first = br.ReadByte();
        int len = 1;
        int mask = 0x80;
        while (len <= 8 && (first & mask) == 0)
        {
            mask >>= 1;
            len++;
        }
        if (len > 8) throw new InvalidDataException("Invalid EBML size.");
        ulong value = (ulong)(first & (mask - 1));
        for (int i = 1; i < len; i++) value = (value << 8) | br.ReadByte();
        ulong max = (1UL << (7 * len)) - 1UL;
        unknown = value == max;
        if (unknown) return long.MaxValue;
        return value > long.MaxValue ? long.MaxValue : (long)value;
    }

    static int ReadUInt16BE(byte[] data, int offset)
    {
        if (offset + 2 > data.Length) return 0;
        return (data[offset] << 8) | data[offset + 1];
    }

    static uint ReadUInt32BE(byte[] data, int offset)
    {
        if (offset + 4 > data.Length) return 0;
        return ((uint)data[offset] << 24) | ((uint)data[offset + 1] << 16) | ((uint)data[offset + 2] << 8) | data[offset + 3];
    }

    static ulong ReadUnsignedBE(byte[] data)
    {
        ulong value = 0;
        for (int i = 0; i < data.Length; i++) value = (value << 8) | data[i];
        return value;
    }

    static string DecodeEbmlString(byte[] data)
    {
        if (data == null || data.Length == 0) return "";
        try { return Encoding.UTF8.GetString(data).TrimEnd('\0'); }
        catch { return Encoding.Default.GetString(data).TrimEnd('\0'); }
    }

    static bool IsFontFile(string filename, string mime)
    {
        string ext = Path.GetExtension(filename ?? "").ToLowerInvariant();
        string m = (mime ?? "").ToLowerInvariant();
        return ext == ".ttf" || ext == ".otf" || ext == ".ttc" || ext == ".otc" || m.Contains("font") || m.Contains("truetype") || m.Contains("opentype");
    }

    static FontSet ParseMkvAttachedFonts(string path)
    {
        FontSet result = new FontSet();
        using (FileStream fs = File.Open(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
        using (BinaryReader br = new BinaryReader(fs))
        {
            Header segment = null;
            long fileEnd = fs.Length;
            while (fs.Position < fileEnd)
            {
                Header h = ReadHeader(br, fileEnd);
                if (h == null) break;
                if (h.Id == IdSegment)
                {
                    segment = h;
                    break;
                }
                if (h.UnknownSize) break;
                fs.Position = h.DataEnd;
            }
            if (segment == null) return result;

            long segmentStart = segment.DataStart;
            long segmentEnd = segment.UnknownSize ? fileEnd : segment.DataEnd;
            List<long> attachmentOffsets = new List<long>();
            HashSet<long> parsedOffsets = new HashSet<long>();
            fs.Position = segmentStart;

            while (fs.Position < segmentEnd)
            {
                long elementOffset = fs.Position;
                Header h = ReadHeader(br, segmentEnd);
                if (h == null) break;

                if (h.Id == IdAttachments)
                {
                    ParseAttachments(br, h.DataEnd, result);
                    parsedOffsets.Add(elementOffset);
                }
                else if (h.Id == IdSeekHead && !h.UnknownSize)
                {
                    foreach (long offset in ParseSeekHead(br, h.DataEnd, segmentStart)) attachmentOffsets.Add(offset);
                }

                if (h.UnknownSize) break;
                fs.Position = h.DataEnd;
                if (h.Id == IdCluster) break;
            }

            foreach (long offset in attachmentOffsets)
            {
                if (offset <= 0 || offset >= segmentEnd || parsedOffsets.Contains(offset)) continue;
                fs.Position = offset;
                Header h = ReadHeader(br, segmentEnd);
                if (h != null && h.Id == IdAttachments)
                {
                    ParseAttachments(br, h.DataEnd, result);
                    parsedOffsets.Add(offset);
                }
            }
        }
        return result;
    }

    static List<long> ParseSeekHead(BinaryReader br, long end, long segmentStart)
    {
        List<long> result = new List<long>();
        while (br.BaseStream.Position < end)
        {
            Header h = ReadHeader(br, end);
            if (h == null) break;
            if (h.Id == IdSeek && !h.UnknownSize)
            {
                int seekId = 0;
                ulong seekPosition = 0;
                while (br.BaseStream.Position < h.DataEnd)
                {
                    Header sh = ReadHeader(br, h.DataEnd);
                    if (sh == null) break;
                    if (sh.Id == IdSeekID && !sh.UnknownSize)
                    {
                        byte[] data = ReadBytes(br, sh.Size);
                        seekId = 0;
                        for (int i = 0; i < data.Length; i++) seekId = (seekId << 8) | data[i];
                    }
                    else if (sh.Id == IdSeekPosition && !sh.UnknownSize)
                    {
                        seekPosition = ReadUnsignedBE(ReadBytes(br, sh.Size));
                    }
                    br.BaseStream.Position = sh.DataEnd;
                }
                if (seekId == IdAttachments) result.Add(segmentStart + (long)seekPosition);
            }
            br.BaseStream.Position = h.DataEnd;
        }
        return result;
    }

    static void ParseAttachments(BinaryReader br, long end, FontSet result)
    {
        while (br.BaseStream.Position < end)
        {
            Header h = ReadHeader(br, end);
            if (h == null) break;
            if (h.Id == IdAttachedFile && !h.UnknownSize) ParseAttachedFile(br, h.DataEnd, result);
            br.BaseStream.Position = h.DataEnd;
        }
    }

    static void ParseAttachedFile(BinaryReader br, long end, FontSet result)
    {
        string filename = "";
        string mime = "";
        byte[] fileData = null;
        while (br.BaseStream.Position < end)
        {
            Header h = ReadHeader(br, end);
            if (h == null) break;
            if (h.Id == IdFileName && !h.UnknownSize) filename = DecodeEbmlString(ReadBytes(br, h.Size));
            else if (h.Id == IdFileMimeType && !h.UnknownSize) mime = DecodeEbmlString(ReadBytes(br, h.Size));
            else if (h.Id == IdFileData && !h.UnknownSize) fileData = ReadBytes(br, h.Size);
            br.BaseStream.Position = h.DataEnd;
        }

        if (!IsFontFile(filename, mime)) return;
        result.AddAlias(filename);
        if (fileData != null) result.AddAliases(ParseFontNames(fileData));
    }

    static IEnumerable<string> ParseFontNames(byte[] data)
    {
        List<string> names = new List<string>();
        if (data == null || data.Length < 12) return names;
        if (data[0] == (byte)'t' && data[1] == (byte)'t' && data[2] == (byte)'c' && data[3] == (byte)'f')
        {
            uint count = ReadUInt32BE(data, 8);
            for (uint i = 0; i < count && 12 + i * 4 + 4 <= data.Length; i++)
            {
                uint offset = ReadUInt32BE(data, 12 + (int)i * 4);
                ParseSfntNames(data, (int)offset, names);
            }
        }
        else
        {
            ParseSfntNames(data, 0, names);
        }
        return names;
    }

    static void ParseSfntNames(byte[] data, int fontOffset, List<string> names)
    {
        if (fontOffset < 0 || fontOffset + 12 > data.Length) return;
        uint signature = ReadUInt32BE(data, fontOffset);
        if (signature != 0x00010000 && signature != 0x4F54544F && signature != 0x74727565 && signature != 0x74797031) return;

        int tableCount = ReadUInt16BE(data, fontOffset + 4);
        int tableDir = fontOffset + 12;
        int nameOffset = -1;
        for (int i = 0; i < tableCount; i++)
        {
            int rec = tableDir + i * 16;
            if (rec + 16 > data.Length) return;
            if (data[rec] == (byte)'n' && data[rec + 1] == (byte)'a' && data[rec + 2] == (byte)'m' && data[rec + 3] == (byte)'e')
            {
                nameOffset = (int)ReadUInt32BE(data, rec + 8);
                break;
            }
        }
        if (nameOffset < 0 || nameOffset + 6 > data.Length) return;

        int tableStart = nameOffset;
        int count = ReadUInt16BE(data, tableStart + 2);
        int stringOffset = ReadUInt16BE(data, tableStart + 4);
        int storage = tableStart + stringOffset;
        Dictionary<string, string> familyByLang = new Dictionary<string, string>();
        Dictionary<string, string> subfamilyByLang = new Dictionary<string, string>();

        for (int i = 0; i < count; i++)
        {
            int rec = tableStart + 6 + i * 12;
            if (rec + 12 > data.Length) break;
            int platform = ReadUInt16BE(data, rec);
            int encoding = ReadUInt16BE(data, rec + 2);
            int language = ReadUInt16BE(data, rec + 4);
            int nameId = ReadUInt16BE(data, rec + 6);
            int len = ReadUInt16BE(data, rec + 8);
            int off = ReadUInt16BE(data, rec + 10);
            int pos = storage + off;
            if (len <= 0 || pos < 0 || pos + len > data.Length) continue;

            string value = Clean(DecodeFontName(data, pos, len, platform));
            if (value.Length == 0) continue;
            if (nameId == 1 || nameId == 2 || nameId == 4 || nameId == 6 || nameId == 16 || nameId == 17) names.Add(value);

            string langKey = platform.ToString() + ":" + encoding.ToString() + ":" + language.ToString();
            if (nameId == 1 || nameId == 16) familyByLang[langKey] = value;
            if (nameId == 2 || nameId == 17) subfamilyByLang[langKey] = value;
        }

        foreach (KeyValuePair<string, string> pair in familyByLang)
        {
            string sub;
            if (!subfamilyByLang.TryGetValue(pair.Key, out sub)) continue;
            string lower = sub.ToLowerInvariant();
            if (lower != "regular" && lower != "normal" && lower != "book") names.Add(pair.Value + " " + sub);
        }
    }

    static string DecodeFontName(byte[] data, int offset, int length, int platform)
    {
        byte[] slice = new byte[length];
        Buffer.BlockCopy(data, offset, slice, 0, length);
        try
        {
            if (platform == 0 || platform == 3) return Encoding.BigEndianUnicode.GetString(slice);
            if (platform == 1)
            {
                try { return Encoding.GetEncoding(10000).GetString(slice); }
                catch { return Encoding.GetEncoding(1252).GetString(slice); }
            }
            return Encoding.UTF8.GetString(slice);
        }
        catch
        {
            return Encoding.Default.GetString(slice);
        }
    }

    static string DecodeTextFile(string path)
    {
        byte[] bytes = File.ReadAllBytes(path);
        if (bytes.Length >= 3 && bytes[0] == 0xEF && bytes[1] == 0xBB && bytes[2] == 0xBF) return Encoding.UTF8.GetString(bytes);
        if (bytes.Length >= 2 && bytes[0] == 0xFF && bytes[1] == 0xFE) return Encoding.Unicode.GetString(bytes);
        if (bytes.Length >= 2 && bytes[0] == 0xFE && bytes[1] == 0xFF) return Encoding.BigEndianUnicode.GetString(bytes);
        try { return new UTF8Encoding(false, true).GetString(bytes); }
        catch { }

        int[] cps = new int[] { 932, 1252, 1251, 949, 936, 950 };
        foreach (int cp in cps)
        {
            try { return Encoding.GetEncoding(cp).GetString(bytes); }
            catch { }
        }
        return Encoding.Default.GetString(bytes);
    }

    static List<string> SplitCsvLoose(string value)
    {
        List<string> parts = new List<string>();
        foreach (string p in value.Split(',')) parts.Add(p.Trim());
        return parts;
    }

    static List<string> SplitAssFields(string value, int count)
    {
        List<string> fields = new List<string>();
        if (count <= 1)
        {
            fields.Add(value);
            return fields;
        }
        int start = 0;
        int splits = 0;
        for (int i = 0; i < value.Length && splits < count - 1; i++)
        {
            if (value[i] == ',')
            {
                fields.Add(value.Substring(start, i - start));
                start = i + 1;
                splits++;
            }
        }
        fields.Add(value.Substring(start));
        while (fields.Count < count) fields.Add("");
        return fields;
    }

    static int IndexOfField(List<string> format, string field)
    {
        for (int i = 0; i < format.Count; i++)
            if (string.Equals(format[i], field, StringComparison.OrdinalIgnoreCase)) return i;
        return -1;
    }

    static string TrimTagArgument(string value)
    {
        string s = Clean(value);
        while (s.EndsWith(")", StringComparison.Ordinal))
        {
            int open = 0;
            int close = 0;
            for (int i = 0; i < s.Length; i++)
            {
                if (s[i] == '(') open++;
                else if (s[i] == ')') close++;
            }
            if (close <= open) break;
            s = s.Substring(0, s.Length - 1).TrimEnd();
        }
        return s;
    }

    static void AddTagArguments(string text, string tag, Action<string> add)
    {
        if (string.IsNullOrEmpty(text)) return;
        for (int i = 0; i < text.Length - tag.Length; i++)
        {
            if (text[i] != '\\') continue;
            bool match = true;
            for (int j = 0; j < tag.Length; j++)
            {
                if (char.ToLowerInvariant(text[i + 1 + j]) != char.ToLowerInvariant(tag[j]))
                {
                    match = false;
                    break;
                }
            }
            if (!match) continue;

            int start = i + 1 + tag.Length;
            int end = start;
            while (end < text.Length && text[end] != '\\' && text[end] != '}') end++;
            string arg = TrimTagArgument(text.Substring(start, end - start));
            if (arg.Length > 0) add(arg);
        }
    }

    static AssFile ParseAssFile(string path)
    {
        string text = DecodeTextFile(path);
        string[] lines = Regex.Split(text, "\\r\\n|\\n|\\r");
        Dictionary<string, string> styleFonts = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        string section = "";
        List<string> styleFormat = new List<string>();
        List<string> eventFormat = new List<string>();
        int styleNameIndex = -1;
        int styleFontIndex = -1;
        int eventStyleIndex = -1;
        int eventTextIndex = -1;

        AssFile report = new AssFile();
        report.Path = path;
        report.FileName = Path.GetFileName(path);
        report.BaseName = Path.GetFileNameWithoutExtension(path);
        report.Title = GetTitleFromPath(path);

        foreach (string rawLine in lines)
        {
            string line = rawLine.TrimStart();
            if (line.Length == 0) continue;
            if (line[0] == '[')
            {
                int close = line.IndexOf(']');
                if (close > 0) section = line.Substring(1, close - 1).Trim().ToLowerInvariant();
                continue;
            }

            if (section == "v4+ styles" || section == "v4 styles")
            {
                if (line.StartsWith("Format:", StringComparison.OrdinalIgnoreCase))
                {
                    styleFormat = SplitCsvLoose(line.Substring(7));
                    styleNameIndex = IndexOfField(styleFormat, "Name");
                    styleFontIndex = IndexOfField(styleFormat, "Fontname");
                    continue;
                }
                if (line.StartsWith("Style:", StringComparison.OrdinalIgnoreCase))
                {
                    if (styleFormat.Count == 0)
                    {
                        styleFormat = SplitCsvLoose("Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding");
                        styleNameIndex = 0;
                        styleFontIndex = 1;
                    }
                    List<string> fields = SplitAssFields(line.Substring(6), styleFormat.Count);
                    if (styleNameIndex >= 0 && styleFontIndex >= 0 && fields.Count > styleNameIndex && fields.Count > styleFontIndex)
                    {
                        string style = Clean(fields[styleNameIndex]);
                        string font = Clean(fields[styleFontIndex]);
                        if (style.Length > 0 && font.Length > 0) styleFonts[style] = font;
                    }
                    continue;
                }
            }

            if (section == "events")
            {
                if (line.StartsWith("Format:", StringComparison.OrdinalIgnoreCase))
                {
                    eventFormat = SplitCsvLoose(line.Substring(7));
                    eventStyleIndex = IndexOfField(eventFormat, "Style");
                    eventTextIndex = IndexOfField(eventFormat, "Text");
                    continue;
                }
                if (line.StartsWith("Dialogue:", StringComparison.OrdinalIgnoreCase))
                {
                    if (eventFormat.Count == 0)
                    {
                        eventFormat = SplitCsvLoose("Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text");
                        eventStyleIndex = 3;
                        eventTextIndex = 9;
                    }
                    List<string> fields = SplitAssFields(line.Substring(9), eventFormat.Count);
                    if (eventStyleIndex >= 0 && fields.Count > eventStyleIndex)
                    {
                        string style = Clean(fields[eventStyleIndex]);
                        string font;
                        if (styleFonts.TryGetValue(style, out font)) AddAssFont(report, font);
                    }
                    string eventText = eventTextIndex >= 0 && fields.Count > eventTextIndex ? fields[eventTextIndex] : "";
                    AddTagArguments(eventText, "fn", delegate(string font) { AddAssFont(report, font); });
                    AddTagArguments(eventText, "r", delegate(string style)
                    {
                        string font;
                        if (styleFonts.TryGetValue(style, out font)) AddAssFont(report, font);
                    });
                }
            }
        }
        return report;
    }

    static void AddAssFont(AssFile report, string font)
    {
        string clean = Clean(font);
        if (clean.Length == 0) return;
        if (string.Equals(clean, "NetflixSans-Bold", StringComparison.OrdinalIgnoreCase)) return;
        report.Fonts.Add(clean);
    }

    static string GetTitleFromPath(string path)
    {
        string rel = path.Substring(root.Length).TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        string[] parts = rel.Split(new char[] { Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar }, StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length >= 2 && string.Equals(parts[0], "videos", StringComparison.OrdinalIgnoreCase)) return parts[1];
        return Path.GetFileName(Path.GetDirectoryName(path));
    }

    static int NumericStem(string stem)
    {
        int value;
        return int.TryParse(stem, out value) ? value : int.MinValue;
    }

    static void LoadInstalledFonts()
    {
        List<string> dirs = new List<string>();
        dirs.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "Fonts"));
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (!string.IsNullOrEmpty(local)) dirs.Add(Path.Combine(local, "Microsoft", "Windows", "Fonts"));

        HashSet<string> seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (string dir in dirs)
        {
            if (!Directory.Exists(dir)) continue;
            foreach (string file in Directory.EnumerateFiles(dir))
            {
                string ext = Path.GetExtension(file).ToLowerInvariant();
                if (ext != ".ttf" && ext != ".otf" && ext != ".ttc" && ext != ".otc") continue;
                if (!seen.Add(file)) continue;
                try
                {
                    InstalledFonts.AddAlias(Path.GetFileName(file));
                    InstalledFonts.AddAliases(ParseFontNames(File.ReadAllBytes(file)));
                }
                catch { }
            }
        }
    }

    static MkvFile BuildMkvFile(string path)
    {
        MkvFile m = new MkvFile();
        m.Path = path;
        m.FileName = Path.GetFileName(path);
        m.BaseName = Path.GetFileNameWithoutExtension(path);
        m.Title = GetTitleFromPath(path);
        m.NumericStem = NumericStem(m.BaseName);
        return m;
    }

    static string MatchMkv(AssFile ass, List<MkvFile> mkvs)
    {
        if (mkvs == null || mkvs.Count == 0) return null;
        foreach (MkvFile mkv in mkvs)
            if (string.Equals(mkv.BaseName, ass.BaseName, StringComparison.OrdinalIgnoreCase)) return mkv.Path;

        int assNum = NumericStem(ass.BaseName);
        if (assNum != int.MinValue)
        {
            List<MkvFile> numeric = mkvs.FindAll(delegate(MkvFile m) { return m.NumericStem == assNum; });
            if (numeric.Count == 1) return numeric[0].Path;
        }
        if (mkvs.Count == 1) return mkvs[0].Path;
        return null;
    }

    static void AddSortedSection(StringBuilder sb, string label, List<string> values)
    {
        values.Sort(FontCompare);
        sb.AppendLine(label);
        if (values.Count == 0) sb.AppendLine("  - (none)");
        else foreach (string value in values) sb.AppendLine("  - " + value);
        sb.AppendLine();
    }

    public static string Run(string workspaceRoot)
    {
        root = workspaceRoot;
        string videos = Path.Combine(root, "videos");
        string outPath = Path.Combine(root, "subtitle-font-availability.txt");

        LoadInstalledFonts();

        List<AssFile> assFiles = new List<AssFile>();
        foreach (string path in Directory.EnumerateFiles(videos, "*.ass", SearchOption.AllDirectories))
        {
            try { assFiles.Add(ParseAssFile(path)); }
            catch { }
        }

        List<MkvFile> mkvFiles = new List<MkvFile>();
        foreach (string path in Directory.EnumerateFiles(videos, "*.mkv", SearchOption.AllDirectories)) mkvFiles.Add(BuildMkvFile(path));

        Dictionary<string, List<MkvFile>> mkvsByTitle = new Dictionary<string, List<MkvFile>>(StringComparer.OrdinalIgnoreCase);
        foreach (MkvFile mkv in mkvFiles)
        {
            List<MkvFile> list;
            if (!mkvsByTitle.TryGetValue(mkv.Title, out list))
            {
                list = new List<MkvFile>();
                mkvsByTitle[mkv.Title] = list;
            }
            list.Add(mkv);
        }

        int parsed = 0;
        foreach (MkvFile mkv in mkvFiles)
        {
            try { MkvFonts[mkv.Path] = ParseMkvAttachedFonts(mkv.Path); }
            catch { MkvFonts[mkv.Path] = new FontSet(); }
            parsed++;
            if (parsed % 50 == 0) Console.WriteLine("Parsed MKV attachments: " + parsed + " / " + mkvFiles.Count);
        }

        Dictionary<string, Dictionary<string, TitleFontInfo>> titleFonts = new Dictionary<string, Dictionary<string, TitleFontInfo>>(StringComparer.OrdinalIgnoreCase);
        Dictionary<string, int> assCountByTitle = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
        foreach (AssFile ass in assFiles)
        {
            if (!assCountByTitle.ContainsKey(ass.Title)) assCountByTitle[ass.Title] = 0;
            assCountByTitle[ass.Title]++;

            Dictionary<string, TitleFontInfo> fontMap;
            if (!titleFonts.TryGetValue(ass.Title, out fontMap))
            {
                fontMap = new Dictionary<string, TitleFontInfo>(StringComparer.OrdinalIgnoreCase);
                titleFonts[ass.Title] = fontMap;
            }

            List<MkvFile> titleMkvs;
            mkvsByTitle.TryGetValue(ass.Title, out titleMkvs);
            string matchedMkv = MatchMkv(ass, titleMkvs);

            foreach (string font in ass.Fonts)
            {
                TitleFontInfo info;
                if (!fontMap.TryGetValue(font, out info))
                {
                    info = new TitleFontInfo { Font = font };
                    fontMap[font] = info;
                }
                if (matchedMkv == null) info.UnmatchedAssFiles++;
                else info.RequiredMkvs.Add(matchedMkv);
            }
        }

        List<TitleResult> results = new List<TitleResult>();
        foreach (KeyValuePair<string, Dictionary<string, TitleFontInfo>> titlePair in titleFonts)
        {
            TitleResult tr = new TitleResult();
            tr.Title = titlePair.Key;
            tr.AssCount = assCountByTitle.ContainsKey(titlePair.Key) ? assCountByTitle[titlePair.Key] : 0;

            List<MkvFile> titleMkvs;
            tr.MkvCount = mkvsByTitle.TryGetValue(titlePair.Key, out titleMkvs) ? titleMkvs.Count : 0;

            foreach (TitleFontInfo info in titlePair.Value.Values)
            {
                bool hasUnmatched = info.UnmatchedAssFiles > 0;
                bool missingFromMkv = false;
                foreach (string mkvPath in info.RequiredMkvs)
                {
                    FontSet set;
                    if (!MkvFonts.TryGetValue(mkvPath, out set) || !set.Has(info.Font))
                    {
                        missingFromMkv = true;
                        break;
                    }
                }

                if (!hasUnmatched && !missingFromMkv && info.RequiredMkvs.Count > 0) tr.Embedded.Add(info.Font);
                else if (InstalledFonts.Has(info.Font)) tr.Installed.Add(info.Font);
                else if (hasUnmatched && info.RequiredMkvs.Count == 0) tr.CouldNotCheck.Add(info.Font);
                else tr.NeedInstall.Add(info.Font);
            }
            results.Add(tr);
        }

        results.Sort(delegate(TitleResult a, TitleResult b) { return StringComparer.OrdinalIgnoreCase.Compare(a.Title, b.Title); });

        int embeddedCount = 0;
        int installedCount = 0;
        int needCount = 0;
        int unknownCount = 0;
        HashSet<string> embeddedUnique = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        HashSet<string> installedUnique = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        HashSet<string> needUnique = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        HashSet<string> unknownUnique = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        StringBuilder sb = new StringBuilder();
        sb.AppendLine("Subtitle Font Availability by Title");
        sb.AppendLine("Generated: " + DateTimeOffset.Now.ToString("yyyy-MM-dd HH:mm:ss zzz"));
        sb.AppendLine("ASS files checked: " + assFiles.Count);
        sb.AppendLine("MKV files checked: " + mkvFiles.Count);
        sb.AppendLine("Default Netflix Sans Bold excluded: yes");
        sb.AppendLine();
        sb.AppendLine("How to use this:");
        sb.AppendLine("- Already inside the MKV = the matching video file has the font attached.");
        sb.AppendLine("- Already installed on this PC = not attached in the MKV, but Windows has it installed here.");
        sb.AppendLine("- Install these = not attached in the MKV and not found installed on this PC.");
        sb.AppendLine("- Could not check = no matching MKV file was found for that subtitle file.");
        sb.AppendLine();

        foreach (TitleResult tr in results)
        {
            foreach (string f in tr.Embedded) embeddedUnique.Add(f);
            foreach (string f in tr.Installed) installedUnique.Add(f);
            foreach (string f in tr.NeedInstall) needUnique.Add(f);
            foreach (string f in tr.CouldNotCheck) unknownUnique.Add(f);
            embeddedCount += tr.Embedded.Count;
            installedCount += tr.Installed.Count;
            needCount += tr.NeedInstall.Count;
            unknownCount += tr.CouldNotCheck.Count;

            sb.AppendLine(tr.Title);
            sb.AppendLine(new string('=', tr.Title.Length));
            sb.AppendLine("ASS files checked: " + tr.AssCount);
            sb.AppendLine("MKV files checked: " + tr.MkvCount);
            sb.AppendLine();
            AddSortedSection(sb, "Already inside the MKV:", tr.Embedded);
            AddSortedSection(sb, "Already installed on this PC:", tr.Installed);
            AddSortedSection(sb, "Install these:", tr.NeedInstall);
            AddSortedSection(sb, "Could not check:", tr.CouldNotCheck);
        }

        sb.AppendLine("Summary");
        sb.AppendLine("=======");
        sb.AppendLine("Title/font entries already inside MKV: " + embeddedCount);
        sb.AppendLine("Title/font entries already installed on this PC: " + installedCount);
        sb.AppendLine("Title/font entries needing install: " + needCount);
        sb.AppendLine("Title/font entries could not check: " + unknownCount);
        sb.AppendLine("Unique fonts already inside at least one MKV title: " + embeddedUnique.Count);
        sb.AppendLine("Unique fonts already installed on this PC but missing from at least one MKV title: " + installedUnique.Count);
        sb.AppendLine("Unique fonts needing install: " + needUnique.Count);
        sb.AppendLine("Unique fonts could not check: " + unknownUnique.Count);

        File.WriteAllText(outPath, sb.ToString(), new UTF8Encoding(true));
        return "Created: " + outPath + Environment.NewLine +
            "ASS files checked: " + assFiles.Count + Environment.NewLine +
            "MKV files checked: " + mkvFiles.Count + Environment.NewLine +
            "Titles: " + results.Count + Environment.NewLine +
            "Unique fonts needing install: " + needUnique.Count + Environment.NewLine +
            "Unique fonts already embedded somewhere: " + embeddedUnique.Count + Environment.NewLine +
            "Unique fonts already installed on this PC: " + installedUnique.Count + Environment.NewLine +
            "Unique fonts could not check: " + unknownUnique.Count;
    }
}
