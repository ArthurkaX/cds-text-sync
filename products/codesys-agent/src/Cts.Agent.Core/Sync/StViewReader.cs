using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Sync
{
    public sealed class StViewObject
    {
        public string[] Path { get; internal set; }
        public string Kind { get; internal set; }
        public string Declaration { get; internal set; }
        public string Implementation { get; internal set; }
        public string File { get; internal set; }
        public int? DeclarationLine { get; internal set; }
        public int? ImplementationLine { get; internal set; }
        public string TypeGuid { get; internal set; }
        public IDictionary<string, string> Settings { get; internal set; }

        // The object's place in the tree, "Folder/POU/Method".
        internal string Key => string.Join("/", Path);

        // The parts two texts of one object differ in: blank lines and spaces at a part's
        // edges and a declaration's END line say nothing.
        internal static List<string> DifferentParts(StViewObject left, StViewObject right)
        {
            var result = new List<string>();
            if (!string.Equals(DeclarationText(left?.Declaration), DeclarationText(right?.Declaration), StringComparison.Ordinal)) result.Add("declaration");
            if (!string.Equals(PartText(left?.Implementation), PartText(right?.Implementation), StringComparison.Ordinal)) result.Add("implementation");
            if (StPragma.Settings.Any(setting => StPragma.Value(left?.Settings, setting) != StPragma.Value(right?.Settings, setting))) result.Add("settings");
            return result;
        }

        static string PartText(string value) => StText.Lf(value).Trim();
        static string DeclarationText(string value) => Regex.Replace(PartText(value), @"(?:^|\n)[ \t]*END_(?:PROGRAM|FUNCTION_BLOCK|FUNCTION|INTERFACE|METHOD|PROPERTY)[ \t]*$", "", RegexOptions.IgnoreCase).Trim();
    }

    public sealed class StViewError
    {
        public string File { get; internal set; }
        public string Reason { get; internal set; }
    }

    public sealed class StViewResult
    {
        public IList<StViewObject> Objects { get; } = new List<StViewObject>();
        public IList<StViewError> Errors { get; } = new List<StViewError>();
        internal IDictionary<string, string> BlobIds { get; } = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    }

    public static class StViewReader
    {
        public static StViewResult Read(string root)
        {
            return Read(new DirectoryViewFiles(root));
        }

        internal static StViewResult Read(IViewFiles files)
        {
            return Read(files, new Dictionary<string, StViewResult>(StringComparer.OrdinalIgnoreCase));
        }

        internal static StViewResult Read(IViewFiles files, IDictionary<string, StViewResult> parsedByBlob)
        {
            var result = new StViewResult();
            var paths = files.Paths.Where(path => path.EndsWith(".st", StringComparison.OrdinalIgnoreCase)).OrderBy(path => path, StringComparer.Ordinal).ToList();
            var needed = paths.Where(relative =>
            {
                var blobId = files.BlobId(relative);
                return blobId == null || !parsedByBlob.ContainsKey(relative + "\n" + blobId);
            }).ToList();
            var contents = files.ReadMany(needed);
            foreach (var relative in paths)
            {
                var blobId = files.BlobId(relative);
                contents.TryGetValue(relative, out var bytes);
                if (blobId == null && bytes != null)
                {
                    blobId = ViewExport.BlobId(bytes);
                }
                var cacheKey = blobId == null ? null : relative + "\n" + blobId;
                if (blobId != null)
                {
                    result.BlobIds[relative] = blobId;
                }
                StViewResult parsed;
                if (cacheKey != null && parsedByBlob.TryGetValue(cacheKey, out parsed))
                {
                    foreach (var item in parsed.Objects) result.Objects.Add(item);
                    foreach (var error in parsed.Errors) result.Errors.Add(error);
                    continue;
                }
                parsed = ReadFile(relative, bytes);
                if (cacheKey != null)
                {
                    parsedByBlob[cacheKey] = parsed;
                }
                foreach (var item in parsed.Objects) result.Objects.Add(item);
                foreach (var error in parsed.Errors) result.Errors.Add(error);
            }
            return result;
        }

        internal static StViewResult ReadFile(string relative, byte[] bytes)
        {
            var result = new StViewResult();
            if (bytes == null || relative.Split('/').Any(part => part.StartsWith(".")))
            {
                return result;
            }
            try
            {
                var text = StText.Lf(new UTF8Encoding(false, true).GetString(bytes).TrimStart('\uFEFF'));
                Parse(relative, text, result.Objects);
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException || error is DecoderFallbackException || error is FormatException || error is ArgumentException)
            {
                result.Errors.Add(new StViewError { File = relative, Reason = "cannot read or parse: " + error.Message });
            }
            return result;
        }

        // Two texts of one .st file hold the same objects, part for part, in whatever order.
        internal static bool SameObjects(string relative, byte[] left, byte[] right)
        {
            var a = ReadFile(relative, left); var b = ReadFile(relative, right);
            if (a.Errors.Count > 0 || b.Errors.Count > 0 || a.Objects.Count != b.Objects.Count) return false;
            var others = b.Objects.GroupBy(item => item.Key, StringComparer.OrdinalIgnoreCase).ToDictionary(group => group.Key, group => group.First(), StringComparer.OrdinalIgnoreCase);
            return others.Count == b.Objects.Count && a.Objects.All(item => others.TryGetValue(item.Key, out var other)
                && item.Kind == other.Kind && StViewObject.DifferentParts(item, other).Count == 0);
        }

        public static int FindLine(StViewObject item, string part, string text, int partLine)
        {
            if (item == null || text == null) return 0;
            var implementation = string.Equals(part, "implementation", StringComparison.OrdinalIgnoreCase);
            var body = implementation ? item.Implementation : item.Declaration;
            var start = implementation ? item.ImplementationLine : item.DeclarationLine;
            if (body == null || !start.HasValue) return 0;
            var lines = body.Split('\n');
            var wanted = text.TrimEnd();
            var found = Enumerable.Range(0, lines.Length).Where(i => lines[i].TrimEnd() == wanted).ToList();
            return found.Count == 0 ? 0 : start.Value + found.OrderBy(i => Math.Abs(i - Math.Max(0, partLine - 1))).First();
        }

        static void Parse(string file, string text, IList<StViewObject> output)
        {
            var lines = text.Split('\n');
            var names = Path.GetFileNameWithoutExtension(file).Split('.').ToArray();
            var folder = Path.GetDirectoryName(file)?.Replace('\\', '/').Split('/').Where(x => x.Length > 0).ToArray() ?? new string[0];
            var rootPath = folder.Concat(new[] { names[0] }).ToArray();
            if (names.Length > 1)
            {
                // The old layout, one member per file (Owner.Member.st, Owner.Property.Get.st), which an import still takes.
                var last = lines.Length - 1;
                var accessor = names.Length > 2 && (names[names.Length - 1].Equals("Get", StringComparison.OrdinalIgnoreCase) || names[names.Length - 1].Equals("Set", StringComparison.OrdinalIgnoreCase));
                var memberKind = Regex.IsMatch(FirstCodeLine(lines, 0, last), @"^ACTION\s+\w+", RegexOptions.IgnoreCase) ? "ACTION"
                    : accessor ? names[names.Length - 1].ToUpperInvariant() : Header(lines, 0, last);
                output.Add(Make(file, folder.Concat(names).ToArray(), memberKind, lines, 0, last));
                return;
            }
            var blocks = new List<Tuple<int, int, string>>();
            var start = 0;
            for (var i = 0; i < lines.Length; i++)
            {
                var end = Regex.Match(lines[i].Trim(), @"^END_(" + string.Join("|", StPragma.EndKeywords) + @")\b", RegexOptions.IgnoreCase);
                if (!end.Success || end.Groups[1].Value.Equals("GET", StringComparison.OrdinalIgnoreCase) || end.Groups[1].Value.Equals("SET", StringComparison.OrdinalIgnoreCase)) continue;
                blocks.Add(Tuple.Create(start, i, end.Groups[1].Value.ToUpperInvariant()));
                start = i + 1;
            }
            var ownerKind = Header(lines, 0, Math.Max(0, lines.Length - 1));
            if (blocks.Count == 0 && StPragma.EndForKind(ownerKind) != null) throw new FormatException("line 1: " + StPragma.EndForKind(ownerKind) + " is missing; see cts guide commands --section \"Files on disk\" for .st templates");
            if (blocks.Count > 0 && lines.Skip(start).Any(line => line.Trim().Length > 0)) throw new FormatException("line " + (start + 1) + ": expected a closed object block");
            if (blocks.Count == 0) blocks.Add(Tuple.Create(0, lines.Length - 1, ""));
            var firstBlock = blocks[0];
            var kind = Header(lines, firstBlock.Item1, firstBlock.Item2);
            if (kind.Length == 0) kind = Keyword(lines, firstBlock.Item1, firstBlock.Item2);
            output.Add(Make(file, rootPath, kind, lines, firstBlock.Item1, firstBlock.Item2 - (firstBlock.Item3.Length == 0 ? 0 : 1)));
            var memberBlocks = blocks.Skip(1).ToList();
            for (var b = 0; b < memberBlocks.Count; b++)
            {
                var block = memberBlocks[b];
                var memberKind = Header(lines, block.Item1, block.Item2);
                var memberName = HeaderName(lines, block.Item1, block.Item2);
                var actionHeader = Regex.Match(FirstCodeLine(lines, block.Item1, block.Item2), @"^ACTION\s+(\w+)", RegexOptions.IgnoreCase);
                if (memberKind.Length == 0 && actionHeader.Success) { memberKind = "ACTION"; memberName = actionHeader.Groups[1].Value; }
                if (memberKind.Length == 0) throw new FormatException("line " + (block.Item1 + 1) + ": expected a member header");
                if (memberKind == "PROPERTY")
                {
                    var accessorStart = Array.FindIndex(lines, block.Item1 + 1, Math.Max(0, block.Item2 - block.Item1 - 1), x => x.Trim() == "GET" || x.Trim() == "SET");
                    var prop = Make(file, rootPath.Concat(new[] { memberName }).ToArray(), memberKind, lines, block.Item1, accessorStart < 0 ? block.Item2 - 1 : accessorStart - 1);
                    output.Add(prop);
                    for (var i = block.Item1 + 1; i < block.Item2; i++)
                        if (lines[i].Trim() == "GET" || lines[i].Trim() == "SET")
                        {
                            var ak = lines[i].Trim(); var close = Array.FindIndex(lines, i + 1, block.Item2 - i - 1, x => x.Trim().Equals(StPragma.EndForKind(ak), StringComparison.OrdinalIgnoreCase));
                            if (close < 0) throw new FormatException("line " + (i + 1) + ": accessor is not closed");
                            output.Add(Make(file, rootPath.Concat(new[] { memberName, ak.Substring(0, 1) + ak.Substring(1).ToLowerInvariant() }).ToArray(), ak, lines, i + 1, close - 1)); i = close;
                        }
                }
                else output.Add(Make(file, rootPath.Concat(new[] { memberName }).ToArray(), memberKind, lines, block.Item1, block.Item2 - 1));
            }
        }

        static StViewObject Make(string file, string[] path, string kind, string[] lines, int first, int last)
        {
            var marker = Array.FindIndex(lines, first, Math.Max(0, last - first + 1), x => x.Trim() == StPragma.ImplementationMarker);
            int? il = null;
            string impl;
            string decl;
            int? dl;
            string typeGuid = null;
            IDictionary<string, string> settings = new Dictionary<string, string>();
            if (kind == "ACTION")
            {
                var header = Array.FindIndex(lines, first, Math.Max(0, last - first + 1), x => Regex.IsMatch(x.Trim(), @"^ACTION\s+", RegexOptions.IgnoreCase));
                decl = Text(lines, first, header - 1, out dl);
                impl = Text(lines, header + 1, last, out il);
            }
            else
            {
                var decEnd = marker >= 0 ? marker - 1 : last;
                decl = Text(lines, first, decEnd, out dl);
                settings = StPragma.Parse(decl.Split('\n').FirstOrDefault(), out typeGuid);
                if (decl.Length > 0)
                {
                    if (StPragma.Is(decl.Split('\n')[0]))
                    {
                        var cut = dl.GetValueOrDefault();
                        decl = Text(lines, cut, decEnd, out dl);
                    }
                }
                impl = marker >= 0 ? Text(lines, marker + 1, last, out il) : null;
            }
            if (kind == "ACTION") settings = StPragma.Parse(decl.Split('\n').FirstOrDefault(), out typeGuid);
            return new StViewObject { File = file, Path = path, Kind = kind, Declaration = decl, Implementation = impl, DeclarationLine = dl, ImplementationLine = il, TypeGuid = typeGuid, Settings = settings };
        }

        static string Text(string[] lines, int first, int last, out int? line)
        {
            while (first <= last && lines[first].Length == 0) first++;
            while (last >= first && lines[last].Length == 0) last--;
            if (last < first) { line = null; return ""; }
            line = first + 1; return string.Join("\n", lines.Skip(first).Take(last - first + 1));
        }
        static string Header(string[] lines, int first, int last) => Regex.Match(FirstCodeLine(lines, first, last), @"^\s*(PROGRAM|FUNCTION_BLOCK|FUNCTION|INTERFACE|METHOD|PROPERTY)\b", RegexOptions.IgnoreCase).Groups[1].Value.ToUpperInvariant();
        static string HeaderName(string[] lines, int first, int last) => Regex.Match(FirstCodeLine(lines, first, last), @"^\s*(?:PROGRAM|FUNCTION_BLOCK|FUNCTION|INTERFACE|METHOD|PROPERTY)(?:\s+(?:PUBLIC|PRIVATE|PROTECTED|INTERNAL|ABSTRACT|FINAL)\b)*\s+(\w+)", RegexOptions.IgnoreCase).Groups[1].Value;
        static string Keyword(string[] lines, int first, int last) => Regex.Match(FirstCodeLine(lines, first, last), @"^\s*(VAR_GLOBAL|TYPE)\b", RegexOptions.IgnoreCase).Groups[1].Value.ToUpperInvariant();
        static string FirstCodeLine(string[] lines, int first, int last)
        {
            var inComment = false;
            for (var i = first; i <= last && i < lines.Length; i++)
            {
                var line = lines[i].Trim();
                if (inComment) { if (line.Contains("*)")) inComment = false; continue; }
                if (line.Length == 0 || line.StartsWith("//") || line.StartsWith("(*") || line.StartsWith("{attribute", StringComparison.OrdinalIgnoreCase)) { if (line.StartsWith("(*") && !line.Contains("*)")) inComment = true; continue; }
                return line;
            }
            return "";
        }
    }
}
