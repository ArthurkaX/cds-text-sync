using System;
using System.Collections.Generic;
using System.Linq;
using Cts.Agent;

namespace Cts.Cli
{
    // The lines cts compare answers, and the Next lines import shares.
    internal static partial class ComparePlanner
    {
        internal static string OwnerKeptNote(ICollection<string> paths) => string.Join(", ", paths) + (paths.Count == 1 ? " differs" : " differ")
            + " in this IDE; only the project's owner changes its libraries and settings, so cts leaves " + (paths.Count == 1 ? "it" : "them") + " out on this PC";

        // The folders of the view git tracks in two spellings that differ only in
        // case, the topmost of each: Windows holds them as one folder, and a copy
        // of the sync folder merges them.
        internal static IList<string> CaseTwins(string folder, string viewRelative)
        {
            var folders = GitRepository.Run(folder, "ls-files -z -- " + ProcessArgs.Quote(viewRelative)).Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries)
                .SelectMany(path => path.Split('/').Skip(1).Select((_, depth) => string.Join("/", path.Split('/').Take(depth + 1))))
                .Distinct(StringComparer.Ordinal);
            var twins = folders.GroupBy(path => path, StringComparer.OrdinalIgnoreCase).Where(group => group.Count() > 1)
                .ToDictionary(group => group.Key, group => group.OrderBy(path => path, StringComparer.Ordinal).ToList(), StringComparer.OrdinalIgnoreCase);
            return twins.Where(twin => !twins.ContainsKey(twin.Key.Contains('/') ? twin.Key.Substring(0, twin.Key.LastIndexOf('/')) : ""))
                .OrderBy(twin => twin.Key, StringComparer.OrdinalIgnoreCase).Select(twin => string.Join(" and ", twin.Value)).ToList();
        }

        internal static string CaseTwinsNote(IList<string> twins) => "git tracks folders whose names differ only in case, which Windows holds as one: "
            + string.Join("; ", twins) + ". Keep the spelling cts export writes: git rm -r --cached the other, then cts export";

        // What to do about objects the IDE changed: compare's and import's last line; a deleted one has no text to read.
        internal static string IdeChangedNext(ICollection<IDictionary<string, object>> items)
        {
            var deleted = items.Count(item => Convert.ToString(item.ContainsKey("reason") ? item["reason"] : "").StartsWith("deleted in the IDE", StringComparison.Ordinal));
            if (deleted == items.Count) return "Next: cts sync removes the files of the objects deleted in the IDE (git keeps them)";
            return "Next: cts read-object NAME --body shows the IDE's text of one; if the IDE's edits are right, cts sync writes them into their files (edit the files after that); if the files are right, cts import --force gives the IDE their text and the folder stays the source (the IDE's text is kept in refs/cts/overwritten)"
                + (deleted > 0 ? "; cts sync also removes the files of the ones deleted in the IDE" : "");
        }

        // An object only the IDE changed, as compare and import --dry-run list it; one the IDE deleted says so.
        internal static string IdeChangedLine(IDictionary<string, object> item) => "ide_changed " + item["name"] + " " + item["path"]
            + (Convert.ToString(item.ContainsKey("reason") ? item["reason"] : "").StartsWith("deleted in the IDE", StringComparison.Ordinal) ? ": deleted in the IDE" : "");

        internal static bool IdeDeleted(CompareRecord record) => record.Category == "ide_changed" && DeletedInIde(record);

        static bool DeletedInIde(CompareRecord item) => (item.Reason ?? "").StartsWith("deleted in the IDE", StringComparison.Ordinal);

        public static Answer Build(IDictionary<string, object> data)
        {
            if (data.ContainsKey("tool"))
            {
                var toolAnswer = new Answer().Add("tool", data["tool"]).Add("files", data["files"]).Add("ide", data["ide"]).Add("against", data["against"]);
                var paths = data["paths"] as IEnumerable<string>;
                if (paths != null) foreach (var path in paths.Take(20)) toolAnswer.Detail(path);
                if (JsonMap.Int(data, "files") == 0) toolAnswer.Detail("the IDE and " + (data["against"] ?? "the disk") + " agree on every view file: no tool opened");
                if (Equals(data["tool"], "github-desktop") && JsonMap.Int(data, "files") > 0)
                    toolAnswer.Detail("GitHub Desktop shows " + data["desktop_repository"] + ": Changes are " + (data["against"] ?? "the disk") + " against the IDE (branch ide); it is a copy, nothing done there reaches the sync folder");
                return toolAnswer;
            }
            var summary = data["summary"] as IDictionary<string, object>;
            var other = data.ContainsKey("base_project");
            var answer = new Answer().Add("base", Equals(data["base"], true) ? null : other ? "other" : "none");
            foreach (var key in new[] { "unchanged", "modified", "added", "deleted", "not_importable", "ide_changed", "both" }) if (summary != null && summary.ContainsKey(key) && (key != "ide_changed" && key != "both" || JsonMap.Int(summary, key) > 0)) answer.Add(key, summary[key]);
            var lastEdit = data.ContainsKey("last_edit") ? data["last_edit"] as IDictionary<string, object> : null;
            answer.Add("ide_edit", lastEdit != null && lastEdit.ContainsKey("ide") ? lastEdit["ide"] : null)
                .Add("disk_edit", lastEdit != null && lastEdit.ContainsKey("disk") ? lastEdit["disk"] : null);
            answer.Add("ide", data["ide"]);
            if (!Equals(data["base"], true) && !other) answer.Detail("no sync base yet: the counts say only whether the IDE and the files agree, not which side changed, and cts import refuses; cts export writes the project to disk and records the base");
            var objects = data["objects"] as IDictionary<string, object>;
            IList<IDictionary<string, object>> Rows(string category) => (objects != null && objects.ContainsKey(category) ? objects[category] as IEnumerable<IDictionary<string, object>> : null)?.ToList() ?? new List<IDictionary<string, object>>();
            foreach (var category in new[] { "modified", "added", "deleted", "not_importable", "ide_changed" }.Concat(objects != null && objects.ContainsKey("unchanged") ? new[] { "unchanged" } : new string[0]))
                foreach (var item in Rows(category))
                    answer.Detail(category == "ide_changed" ? IdeChangedLine(item) : category + " " + item["name"] + (item.ContainsKey("path") ? " " + item["path"] : "")
                        + (category == "modified" && Equals(item.TryGetValue("ide_changed", out var ide) ? ide : null, true) ? ": changed in the IDE too" : ""));
            // The rows name files by their path in the view; an agent opens them from the sync folder.
            var view = data.ContainsKey("view") ? Convert.ToString(data["view"]) : ".";
            if (view != "." && objects != null && objects.Values.OfType<IEnumerable<IDictionary<string, object>>>().Any(rows => rows.Any()))
                answer.Detail("the paths are of files under " + view + "/ in the sync folder");
            if (Rows("ide_changed").Count > 0) answer.Detail(IdeChangedNext(Rows("ide_changed")));
            if (Rows("modified").Any(item => Equals(item.TryGetValue("ide_changed", out var ide) ? ide : null, true)))
                answer.Detail("Next: cts import --dry-run says whether the IDE's and the files' edits of one changed on both sides overlap; cts sync merges them when they do not, an overlap needs cts sync --take disk|ide");
            return answer;
        }
    }
}
