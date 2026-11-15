using System;
using System.Collections.Generic;
using System.Linq;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    internal static partial class ImportCommand
    {
        // The records of *records* whose IDE text is one an earlier sync
        // recorded on refs/cts/base: the IDE went back to it, as a project file
        // saved before the last import does when opened again, rather than
        // edited it. A deleted object has no text to tell by.
        static List<CompareRecord> IdeOlder(ImportWork work, IEnumerable<CompareRecord> records)
        {
            var older = new List<CompareRecord>();
            var texts = records.Where(record => !record.IdeDeleted && (record.Path.EndsWith(".st", StringComparison.OrdinalIgnoreCase)
                ? At(work.IdeObjects, record.ObjectPath) != null : work.IdeFiles != null && work.IdeFiles.ContainsKey(record.Path))).ToList();
            if (texts.Count == 0) return older;
            var viewRelative = ExportCommand.Relative(work.Folder, work.View);
            var prefix = viewRelative == "." ? "" : viewRelative.TrimEnd('/') + "/";
            var log = GitRun.In(work.Folder, "log -z --root --raw --no-abbrev --no-renames --format= " + SyncBase.BaseRef + " -- "
                + string.Join(" ", texts.Select(record => ProcessArgs.Quote(prefix + record.Path)).Distinct()));
            if (log.ExitCode != 0) return older;
            // Each change is ":MODE MODE OLD NEW STATUS" and its path, both ended by a NUL.
            var versions = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
            var fields = log.Output.Split('\0');
            for (var at = 0; at + 1 < fields.Length; at++)
            {
                var change = fields[at].TrimStart('\n').Split(' ');
                if (change.Length < 4 || !change[0].StartsWith(":", StringComparison.Ordinal) || !fields[++at].StartsWith(prefix, StringComparison.Ordinal)) continue;
                var path = fields[at].Substring(prefix.Length);
                if (!versions.ContainsKey(path)) versions[path] = new HashSet<string>(StringComparer.Ordinal);
                foreach (var blob in new[] { change[2], change[3] }.Where(blob => blob.Trim('0').Length > 0)) versions[path].Add(blob);
            }
            if (versions.Count == 0) return older;
            using (var blobs = new GitTreeViewFiles(work.Folder, versions.Values.SelectMany(ids => ids).Distinct()))
            {
                var read = blobs.ReadMany(blobs.Paths);
                foreach (var record in texts)
                    if (versions.TryGetValue(record.Path, out var ids) && ids.Any(id => read[id] != null && IdeHad(work, record, read[id]))) older.Add(record);
            }
            return older;
        }

        // Does the IDE hold *record* as the file's *bytes* have it: a text object part for part, any other file by its content?
        static bool IdeHad(ImportWork work, CompareRecord record, byte[] bytes)
        {
            if (!record.Path.EndsWith(".st", StringComparison.OrdinalIgnoreCase))
                return ExportCommand.ContentKey(record.Path, bytes) == ExportCommand.ContentKey(record.Path, work.IdeFiles[record.Path]);
            var ide = At(work.IdeObjects, record.ObjectPath);
            var then = At(StViewReader.ReadFile(record.Path, bytes).Objects, record.ObjectPath);
            return then != null && string.Equals(then.Kind, ide.Kind, StringComparison.OrdinalIgnoreCase) && StViewObject.DifferentParts(then, ide).Count == 0;
        }
    }
}
