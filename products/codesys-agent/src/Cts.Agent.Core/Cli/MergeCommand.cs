using System;
using System.Collections.Generic;
using System.Linq;
using Cts.Sync;

namespace Cts.Cli
{
    // `cts merge BRANCH`: git merges another branch into the sync folder's
    // branch; --preview shows per file what it would do without touching
    // anything. The IDE gets the result with cts import afterwards.
    public static class MergeCommand
    {
        public static readonly CliCommand Command = new CliCommand
        {
            Name = "merge",
            Arguments = "BRANCH",
            ArgumentLimit = 1,
            ArgumentHelp = "The branch, tag or commit to merge into the branch checked out",
            Summary = "Merge another branch into the sync folder's branch, or preview the merge",
            Description = "git merges BRANCH into the branch checked out and commits the merge; the IDE does not change: cts import carries the result into the project. --preview runs the merge in git's object store only and lists each file both branches changed since their common commit: theirs (BRANCH brings it), merged (git joined both sides' edits), same, ours, or conflict. A conflict needs an answer before anything changes: --take PATH=ours|theirs (PATH a file or a folder of the view, or a bare ours|theirs for every other conflict); to join both sides' lines, merge in your git program instead (cts open). XML objects git does not merge line by line: they take a side. The work tree must be committed first.",
            Options = new[]
            {
                CliOption.Switch("--preview", "preview", "Show what the merge would do, change nothing"),
                CliOption.Many("--take", "take", "PATH=SIDE", "The side a conflict takes: ours or theirs, for PATH or for every other conflict"),
                GitCommands.SyncFolder,
            },
            LocalExecute = Execute,
            Build = Line,
        };

        static IDictionary<string, object> Execute(CliOptions options, IAgentHost host, string work)
        {
            try
            {
                var folder = GitCommands.Folder(options, host, work);
                var branch = options.Arguments.FirstOrDefault();
                var preview = options.Params.ContainsKey("preview");
                MergePlan plan;
                if (preview) plan = BranchMerge.Plan(folder, branch);
                else
                {
                    var takes = options.Params.TryGetValue("take", out var given) ? ((IEnumerable<object>)given).Select(Convert.ToString).ToList() : new List<string>();
                    using (FolderLock.Acquire(folder, Console.Error, TimeSpan.FromSeconds(120)))
                        plan = BranchMerge.Merge(folder, branch, takes);
                }
                return Data(plan, preview);
            }
            catch (Exception e) when (e is InvalidOperationException || e is ArgumentException || e is AgentException)
            {
                throw new CliFailure("merge", "refused", e.Message, "cts merge --help", 1);
            }
        }

        static IDictionary<string, object> Data(MergePlan plan, bool preview)
        {
            var rows = new List<object>();
            foreach (var row in plan.Rows)
            {
                var entry = new Dictionary<string, object> { { "path", row.Path }, { "ours", row.Ours }, { "theirs", row.Theirs }, { "result", row.Result } };
                if (row.Resolve != null) entry["resolve"] = row.Resolve;
                rows.Add(entry);
            }
            return new Dictionary<string, object>
            {
                { "branch", plan.Branch },
                { "into", plan.Into },
                { "preview", preview },
                { "up_to_date", plan.UpToDate },
                { "commit", plan.Commit },
                { "files", rows },
            };
        }

        static Answer Line(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("branch", data["branch"]).Add("into", data["into"]);
            if (Equals(data["up_to_date"], true)) return answer.Add("up_to_date", true);
            var rows = ((IEnumerable<object>)data["files"]).Cast<IDictionary<string, object>>().ToList();
            Func<string, int> count = result => rows.Count(row => Equals(row["result"], result));
            if (!Equals(data["preview"], true)) answer.Add("commit", Convert.ToString(data["commit"]).Substring(0, 8));
            answer.Add("theirs", count("theirs")).Add("merged", count("merged")).Add("same", count("same")).Add("ours", count("ours")).Add("conflicts", count("conflict"));
            if (!Equals(data["preview"], true)) return answer.Detail("the IDE does not have it yet: cts import carries it into the project");
            foreach (var row in rows.Where(row => Equals(row["result"], "conflict")))
                answer.Detail("conflict " + row["resolve"] + "  " + row["path"]);
            foreach (var row in rows.Where(row => Equals(row["result"], "theirs") || Equals(row["result"], "merged")))
                answer.Detail(row["result"] + " " + row["theirs"] + "  " + row["path"]);
            return answer;
        }
    }
}
