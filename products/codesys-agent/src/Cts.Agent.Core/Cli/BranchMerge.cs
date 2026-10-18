using System;
using System.Collections.Generic;
using System.Linq;
using Cts.Agent;

namespace Cts.Cli
{
    // One file of a merge of another branch into the one checked out: how
    // each side changed it since their common commit and what the merge
    // makes of it.
    internal sealed class MergeRow
    {
        internal string Path { get; set; }
        // added, modified, deleted or changed (its type); null: that side left it alone.
        internal string Ours { get; set; }
        internal string Theirs { get; set; }
        // theirs (the branch brings it), ours (only this branch changed it),
        // merged (git joined both sides' edits), same (both made the same
        // change), conflict (someone chooses).
        internal string Result { get; set; }
        // For a conflict: text (a person can join it, one both sides
        // added included) or side (one side is taken whole: a file git does
        // not merge, or one side deleted it).
        internal string Resolve { get; set; }
        // Which sides still hold the file in a conflict, so a choice of the
        // other one deletes it.
        internal bool OursHas { get; set; }
        internal bool TheirsHas { get; set; }
    }

    internal sealed class MergePlan
    {
        internal string Branch { get; set; }
        internal string Into { get; set; }
        internal string Commit { get; set; }
        // The branch is already part of the one checked out.
        internal bool UpToDate { get; set; }
        internal List<MergeRow> Rows { get; set; }
    }

    // A merge of another branch into the sync folder's branch: git merges,
    // cts shows the outcome per file first and takes a side per conflict.
    internal static class BranchMerge
    {
        // The merge as git would make it, in the object store only
        // (merge-tree): the work tree and the branch stay as they are.
        internal static MergePlan Plan(string folder, string branch)
        {
            var into = GitRepository.Position(folder)["branch"] as string;
            var theirs = Commit(folder, branch);
            var plan = new MergePlan { Branch = branch, Into = into ?? "HEAD", Commit = theirs, Rows = new List<MergeRow>() };
            var ancestor = GitRun.In(folder, "merge-base --is-ancestor " + theirs + " HEAD");
            if (ancestor.ExitCode == 0)
            {
                plan.UpToDate = true;
                return plan;
            }
            var common = GitRun.In(folder, "merge-base HEAD " + theirs);
            if (common.ExitCode != 0) throw new InvalidOperationException(branch + " shares no commit with " + plan.Into + ": git cannot tell what each side changed");
            var origin = common.Output.Trim();
            var ours = Changes(folder, origin, "HEAD");
            var theirChanges = Changes(folder, origin, theirs);
            var merged = GitRun.In(folder, "merge-tree --write-tree -z HEAD " + theirs);
            if (merged.ExitCode != 0 && merged.ExitCode != 1) throw new InvalidOperationException(merged.Message);
            var fields = merged.Output.Split('\0');
            var stages = new Dictionary<string, HashSet<char>>(StringComparer.Ordinal);
            var at = 1;
            for (; at < fields.Length && fields[at].Length > 0; at++)
            {
                var tab = fields[at].IndexOf('\t');
                var path = fields[at].Substring(tab + 1);
                if (!stages.TryGetValue(path, out var seen)) stages[path] = seen = new HashSet<char>();
                seen.Add(fields[at][tab - 1]);
            }
            var binary = Binary(fields, at + 1);
            var result = Changes(folder, "HEAD", fields[0]);
            foreach (var path in ours.Keys.Union(theirChanges.Keys).OrderBy(path => path, StringComparer.Ordinal))
            {
                var row = new MergeRow { Path = path };
                row.Ours = ours.TryGetValue(path, out var mine) ? mine : null;
                row.Theirs = theirChanges.TryGetValue(path, out var their) ? their : null;
                if (stages.TryGetValue(path, out var held))
                {
                    row.Result = "conflict";
                    row.OursHas = held.Contains('2');
                    row.TheirsHas = held.Contains('3');
                    // The XML merge driver leaves a conflict as this side's file, with no markers to join.
                    row.Resolve = row.OursHas && row.TheirsHas && !binary.Contains(path) && !path.EndsWith(".xml", StringComparison.OrdinalIgnoreCase) ? "text" : "side";
                }
                else if (row.Ours == null) row.Result = "theirs";
                else if (row.Theirs == null) row.Result = "ours";
                else row.Result = result.ContainsKey(path) ? "merged" : "same";
                plan.Rows.Add(row);
            }
            return plan;
        }

        // Merges *branch* into the branch checked out and commits it. Each
        // conflict takes the side *takes* names (PATH=ours|theirs, PATH a
        // file or a folder, or a bare side for every other conflict). Refused,
        // with nothing changed, while a conflict has no answer.
        internal static MergePlan Merge(string folder, string branch, IList<string> takes)
        {
            if (GitRepository.Position(folder)["branch"] == null) throw new InvalidOperationException("no branch is checked out: cts checkout BRANCH first");
            var dirty = GitRepository.Run(folder, "status --porcelain=v1 -z --untracked-files=no");
            if (dirty.Length > 0) throw new InvalidOperationException("the sync folder has uncommitted changes: commit them first (cts commit), then merge");
            var plan = Plan(folder, branch);
            if (plan.UpToDate) return plan;
            var conflicts = plan.Rows.Where(row => row.Result == "conflict").ToList();
            var chosen = Choices(conflicts, takes);
            var open = conflicts.Where(row => !chosen.ContainsKey(row.Path)).ToList();
            if (open.Count > 0)
                throw new InvalidOperationException(open.Count + " conflict(s) need a side, nothing was merged: --take PATH=ours|theirs, or merge in your git program (cts open): " + Names(open));
            var message = ProcessArgs.Quote("Merge " + plan.Branch + " into " + plan.Into);
            var started = GitRun.In(folder, "merge --no-ff --no-commit -q -m " + message + " " + plan.Commit);
            var merging = GitRun.In(folder, "rev-parse -q --verify MERGE_HEAD");
            if (merging.ExitCode != 0) throw new InvalidOperationException("git did not start the merge: " + started.Message);
            try
            {
                Take(folder, conflicts, chosen, "ours");
                Take(folder, conflicts, chosen, "theirs");
                GitRepository.Run(folder, "commit -q --no-edit");
            }
            catch (InvalidOperationException)
            {
                GitRun.In(folder, "merge --abort");
                throw;
            }
            plan.Commit = GitRepository.Run(folder, "rev-parse HEAD").Trim();
            return plan;
        }

        static string Commit(string folder, string branch)
        {
            if (string.IsNullOrWhiteSpace(branch) || branch.StartsWith("-", StringComparison.Ordinal)) throw new ArgumentException("name the branch to merge: cts merge BRANCH");
            var commit = GitRun.In(folder, "rev-parse -q --verify " + ProcessArgs.Quote(branch + "^{commit}"));
            if (commit.ExitCode != 0) throw new InvalidOperationException("no branch, tag or commit is named " + branch + ": cts branch lists them");
            return commit.Output.Trim();
        }

        // What changed from commit or tree *from* to *to*, per path.
        static Dictionary<string, string> Changes(string folder, string from, string to)
        {
            var fields = GitRepository.Run(folder, "diff --name-status -z --no-renames " + from + " " + to).Split('\0');
            var changes = new Dictionary<string, string>(StringComparer.Ordinal);
            for (var i = 0; i + 1 < fields.Length; i += 2)
            {
                var code = fields[i];
                if (code.Length == 0) break;
                changes[fields[i + 1]] = code[0] == 'A' ? "added" : code[0] == 'D' ? "deleted" : code[0] == 'M' ? "modified" : "changed";
            }
            return changes;
        }

        // The paths merge-tree's messages, from *at* on, call binary: git
        // does not merge them (the .gitattributes -merge of the XML objects).
        static HashSet<string> Binary(string[] fields, int at)
        {
            var paths = new HashSet<string>(StringComparer.Ordinal);
            while (at < fields.Length && int.TryParse(fields[at], out var count))
            {
                var named = fields.Skip(at + 1).Take(count).ToList();
                var kind = at + 1 + count < fields.Length ? fields[at + 1 + count] : "";
                if (kind == "CONFLICT (binary)") paths.UnionWith(named);
                at += count + 3;
            }
            return paths;
        }

        static Dictionary<string, string> Choices(IList<MergeRow> conflicts, IList<string> takes)
        {
            var chosen = new Dictionary<string, string>(StringComparer.Ordinal);
            string every = null;
            foreach (var take in takes)
            {
                var equals = take.LastIndexOf('=');
                var side = equals < 0 ? take : take.Substring(equals + 1);
                if (side != "ours" && side != "theirs") throw new ArgumentException("--take takes PATH=ours|theirs or ours|theirs, not " + take);
                if (equals < 0)
                {
                    every = side;
                    continue;
                }
                var path = take.Substring(0, equals).Replace('\\', '/').TrimEnd('/');
                var matched = conflicts.Where(row => row.Path == path || row.Path.StartsWith(path + "/", StringComparison.Ordinal)).ToList();
                if (matched.Count == 0) throw new ArgumentException("--take " + take + " names no conflicting file");
                foreach (var row in matched) chosen[row.Path] = side;
            }
            if (every == null) return chosen;
            foreach (var row in conflicts.Where(row => !chosen.ContainsKey(row.Path))) chosen[row.Path] = every;
            return chosen;
        }

        // Gives the conflicts that chose *side* that side's file, or deletes
        // the ones that side deleted.
        static void Take(string folder, IList<MergeRow> conflicts, IDictionary<string, string> chosen, string side)
        {
            var picked = conflicts.Where(row => chosen.TryGetValue(row.Path, out var choice) && choice == side).ToList();
            var kept = picked.Where(row => side == "ours" ? row.OursHas : row.TheirsHas).Select(row => row.Path).ToList();
            var gone = picked.Where(row => side == "ours" ? !row.OursHas : !row.TheirsHas).Select(row => row.Path).ToList();
            const string fromInput = " --pathspec-from-file=- --pathspec-file-nul";
            if (kept.Count > 0)
            {
                GitRepository.RunWithInput(folder, "checkout --" + side + fromInput, null, string.Join("\0", kept));
                GitRepository.RunWithInput(folder, "add" + fromInput, null, string.Join("\0", kept));
            }
            if (gone.Count > 0) GitRepository.RunWithInput(folder, "rm -q" + fromInput, null, string.Join("\0", gone));
        }

        static string Names(IList<MergeRow> rows)
        {
            var names = string.Join(", ", rows.Take(5).Select(row => row.Path));
            return rows.Count > 5 ? names + " and " + (rows.Count - 5) + " more" : names;
        }
    }
}
