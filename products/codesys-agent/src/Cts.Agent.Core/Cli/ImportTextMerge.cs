using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    // The text half of an import: merging the disk's, the base's and the IDE's text
    // of one object part by part, and writing the merged parts back into a .st.
    internal static partial class ImportCommand
    {
        static string StripPragma(string declaration)
        {
            var lines = StText.Lf(declaration).Split('\n').ToList();
            if (StPragma.Is(lines[0])) lines.RemoveAt(0);
            return string.Join("\n", lines).Trim('\n');
        }

        // The disk's, the base's and the IDE's text of one object merged part by
        // part; null when the two sides overlap.  The disk's cts pragma rides on
        // the merged declaration (the base and the IDE carry the export's).
        static StViewObject MergeObject(StViewObject disk, StViewObject baseline, StViewObject ide)
        {
            var declaration = MergePart(StripPragma(disk.Declaration), StripPragma(baseline.Declaration), StripPragma(ide.Declaration));
            var implementation = MergePart(disk.Implementation, baseline.Implementation, ide.Implementation);
            if (!declaration.Resolved || !implementation.Resolved) return null;
            var pragma = PragmaLine(disk.Declaration);
            return new StViewObject
            {
                File = disk.File, Path = disk.Path, Kind = disk.Kind,
                Declaration = pragma == null ? declaration.Text : pragma + "\n" + declaration.Text,
                Implementation = disk.Implementation == null && ide.Implementation == null ? null : implementation.Text,
                TypeGuid = disk.TypeGuid, Settings = disk.Settings,
            };
        }

        static string PragmaLine(string declaration)
        {
            var first = StText.Lf(declaration).Split('\n')[0];
            return StPragma.Is(first) ? first : null;
        }

        internal sealed class MergedPart
        {
            internal bool Resolved;
            internal string Text;
        }

        internal static MergedPart MergePart(string disk, string baseline, string ide)
        {
            disk = NormalizePart(disk);
            baseline = NormalizePart(baseline);
            ide = NormalizePart(ide);
            if (disk == baseline || disk == ide) return new MergedPart { Resolved = true, Text = ide };
            if (ide == baseline) return new MergedPart { Resolved = true, Text = disk };
            var directory = Path.Combine(Path.GetTempPath(), "cts-merge-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            try
            {
                var diskPath = Path.Combine(directory, "disk");
                var basePath = Path.Combine(directory, "base");
                var idePath = Path.Combine(directory, "ide");
                File.WriteAllText(diskPath, disk + "\n", new UTF8Encoding(false));
                File.WriteAllText(basePath, baseline + "\n", new UTF8Encoding(false));
                File.WriteAllText(idePath, ide + "\n", new UTF8Encoding(false));
                var run = GitRun.In(directory, "merge-file -p -q -L Disk -L Base -L IDE disk base ide");
                if (run.ExitCode < 0 || run.ExitCode > 127) throw new InvalidOperationException("git merge-file failed: " + run.Message);
                return new MergedPart { Resolved = run.ExitCode == 0, Text = run.Output.TrimEnd('\n', '\r') };
            }
            finally { if (Directory.Exists(directory)) Directory.Delete(directory, true); }
        }

        static string NormalizePart(string value) => StText.Lf(value).Trim('\n');

        static bool IsStMember(string kind) => new[] { "METHOD", "ACTION", "PROPERTY", "GET", "SET" }.Contains(kind, StringComparer.OrdinalIgnoreCase);

        static void AppendNewMember(ViewStamps stamps, string file, byte[] exported, StViewObject item)
        {
            var source = StText.Lf(new UTF8Encoding(false, true).GetString(exported).TrimStart('\uFEFF'));
            var lines = source.Split('\n');
            var pathName = item.Path.Last();
            var pattern = item.Kind == "GET" || item.Kind == "SET"
                ? @"^\s*" + item.Kind + @"\s*$"
                : @"^\s*" + item.Kind + @"\s+" + Regex.Escape(pathName) + @"\b";
            var start = Array.FindIndex(lines, line => Regex.IsMatch(line, pattern, RegexOptions.IgnoreCase));
            if (start < 0) throw new InvalidOperationException("cannot find exported " + item.Kind + " block for " + item.Key);
            var endKeyword = StPragma.EndForKind(item.Kind);
            var end = Array.FindIndex(lines, start, lines.Length - start, line => line.Trim().Equals(endKeyword, StringComparison.OrdinalIgnoreCase));
            if (end < 0) throw new InvalidOperationException("cannot find " + endKeyword + " for " + item.Key);
            var block = string.Join("\n", lines.Skip(start).Take(end - start + 1));
            var original = File.ReadAllBytes(file);
            var text = new UTF8Encoding(false, true).GetString(original).TrimStart('\uFEFF');
            var newline = text.Contains("\r\n") ? "\r\n" : text.Contains("\r") ? "\r" : "\n";
            // As the export joins a file's blocks: one blank line between them, a newline at the end.
            var separator = text.EndsWith("\n", StringComparison.Ordinal) || text.EndsWith("\r", StringComparison.Ordinal) ? newline : newline + newline;
            var suffix = separator + block.Replace("\n", newline) + newline;
            stamps.Write(file, original.Concat(new UTF8Encoding(false).GetBytes(suffix)).ToArray());
        }

        static void ReplaceObjectParts(string view, ViewStamps stamps, StViewObject oldItem, StViewObject newItem)
        {
            var full = Path.Combine(view, oldItem.File.Replace('/', Path.DirectorySeparatorChar));
            var bytes = File.ReadAllBytes(full);
            var text = new UTF8Encoding(false, true).GetString(bytes);
            var bom = text.StartsWith("\uFEFF", StringComparison.Ordinal);
            if (bom) text = text.Substring(1);
            var newline = text.Contains("\r\n") ? "\r\n" : text.Contains("\r") ? "\r" : "\n";
            // A file written while the body was empty has no implementation
            // part: the IDE's body goes in after the declaration, below the marker.
            var declaration = oldItem.Implementation == null && NormalizePart(newItem.Implementation ?? "").Length > 0
                ? NormalizePart(newItem.Declaration) + "\n" + StPragma.ImplementationMarker + "\n" + NormalizePart(newItem.Implementation)
                : newItem.Declaration;
            text = ReplacePart(text, oldItem.Declaration, declaration, oldItem.DeclarationLine, newline);
            text = ReplacePart(text, oldItem.Implementation, newItem.Implementation, oldItem.ImplementationLine, newline);
            stamps.Write(full, new UTF8Encoding(bom).GetBytes(text));
        }

        static string ReplacePart(string file, string oldPart, string newPart, int? firstLine, string newline)
        {
            if (string.IsNullOrEmpty(oldPart) || !firstLine.HasValue || string.Equals(oldPart, newPart, StringComparison.Ordinal)) return file;
            var normalized = StText.Lf(file);
            var lineStart = 0;
            for (var line = 1; line < firstLine.Value; line++)
            {
                lineStart = normalized.IndexOf('\n', lineStart);
                if (lineStart < 0) return file;
                lineStart++;
            }
            var oldText = NormalizePart(oldPart);
            var start = normalized.IndexOf(oldText, lineStart, StringComparison.Ordinal);
            if (start < 0) start = normalized.IndexOf(oldText, StringComparison.Ordinal);
            if (start < 0) return file;
            var replaced = normalized.Substring(0, start) + NormalizePart(newPart) + normalized.Substring(start + oldText.Length);
            return newline == "\n" ? replaced : replaced.Replace("\n", newline);
        }

        // How alike two objects' texts are, 0 to 1: 1 when they match but
        // for the names in *names*, else the share of their lines with
        // something besides keywords that both have, those names masked.
        static double RenameScore(StViewObject oldObject, StViewObject newObject, ISet<string> names)
        {
            List<string> Lines(StViewObject item) => StText.Lf(StripPragma(item.Declaration) + "\n" + (item.Implementation ?? "")).Split('\n')
                .Select(line => Regex.Replace(line.Trim(), @"[A-Za-z_]\w*", word => names.Contains(word.Value) ? "\u0001" : word.Value.ToUpperInvariant()))
                .Where(line => line.Length > 0).ToList();
            var oldLines = Lines(oldObject);
            var newLines = Lines(newObject);
            if (oldLines.SequenceEqual(newLines)) return 1;
            var oldContent = oldLines.Where(Content).ToList();
            var newContent = newLines.Where(Content).ToList();
            if (oldContent.Count == 0 || newContent.Count == 0) return 0;
            var left = oldContent.GroupBy(line => line).ToDictionary(group => group.Key, group => group.Count());
            var shared = newContent.Count(line => left.TryGetValue(line, out var count) && count > 0 && (left[line] = count - 1) >= 0);
            return 2.0 * shared / (oldContent.Count + newContent.Count);
        }

        // A line that holds more than keywords and masked names.
        static bool Content(string line) => Regex.IsMatch(line, @"[^A-Z0-9_\s;:()\u0001]")
            || Regex.Matches(line, @"[A-Z_][A-Z0-9_]*|[0-9]+").Cast<Match>().Any(word => !StHighlight.IsKeyword(word.Value));

        // How alike two names are: their shared letter pairs, 0 to 1.
        static double RenameScore(string oldName, string newName)
        {
            List<string> Pairs(string name) => Enumerable.Range(0, Math.Max(0, name.Length - 1)).Select(at => name.Substring(at, 2).ToUpperInvariant()).ToList();
            var oldPairs = Pairs(oldName);
            var newPairs = Pairs(newName);
            if (oldPairs.Count + newPairs.Count == 0) return 0;
            return 2.0 * oldPairs.Intersect(newPairs).Count() / (oldPairs.Count + newPairs.Count);
        }
    }
}
