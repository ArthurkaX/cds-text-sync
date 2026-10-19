using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

// The quick widget's menu (Alt+Q in the IDE unless the user chose another): one fixed digit per action, so
// the hand learns it.  An action that cannot run now stays in its place,
// greyed, with the reason; nothing is ever renumbered.  Each action but the
// agent activity and the branch list is one cts command, run by the widget,
// whose verdict line it shows.  Settings is a third page: the sync folder,
// picked in a folder dialog (`cts set-sync-folder`), this window's own key
// (`cts config set quick_key`, the user's in every project), this PC's role
// and the permissions.  The branch list is a second page of the same
// kind: one row per local branch, each a `cts checkout --disk-only` -- the
// sync folder moves, the IDE keeps its work, so Compare shows what the branch
// changes and Disk → IDE carries it.  Its first row makes a new branch where
// the work is; Commit and that row ask for one line of text first, the
// message or the name, which becomes the command's last argument.  A commit
// that went through asks whether the branch goes to the team now (`cts
// push`) when the repository has a remote; Esc keeps it on this PC.
//
// Disk → IDE and IDE → Disk carry one side's edits to the other and merge
// an object both changed; one whose edits overlap opens side by side in the
// merge program (`--tool`), and what is saved there goes to both.  Shift
// with the digit (or the click) makes one side the other, no merge
// (`--force`, the overwritten text kept on refs/cts/overwritten).  Digit 7
// opens the sync folder in the person's git program (`cts open`) for what
// this window does not do, merging branches first; the row names the program
// once `cts tool` said which.
//
// The settings page names the program digit 7 opens (`cts tool open NAME`).  Its Permissions row opens
// the groups of the project's deny list (DenyRules.Catalog), each a
// page of check boxes, ticked for a key blocked; Space (or the digit, or
// Enter) switches one in the sync folder's cds-text-sync.json.  The agent
// writes that itself: no cts command changes the list, so an AI agent refused
// by it cannot lift it.
//
// The header names what changed on each side since the last sync, from a
// `cts compare` run when the window opens and after a command that moves it.
//
// Digit 0 opens the page of what is used now and then: the format window
// (`cts fmt`, the IDE's Structured Text laid out), the agent's activity, and
// the line that points an AI agent at this IDE and its project, put on the
// clipboard: `!cts --target ide-<pid> --expect-project <name> --help`,
// pasted into the agent's chat, so its every command lands here.
//
// Pure: the agent draws it (QuickWidget); the rules are unit tests.

namespace Cts.Agent
{
    public enum WidgetPage { None, Activity, Branches, Compare, Settings, Choices, Permissions, More, Format, Fsm, StaticAnalysis }

    //: How the header's state line reads: nothing to carry, changes, edits on both sides, not known.
    public enum WidgetTone { InSync, Changed, Both, Unknown }

    public sealed class WidgetItem
    {
        //: The digit; '\0' for a row reached with the arrows only.
        public char Key { get; internal set; }
        public string Label { get; internal set; }
        //: The cts arguments; null for a row that opens a page of the agent's own.
        public string[] Args { get; internal set; }
        //: The cts arguments Shift with the digit or the click runs, without a question; null for none.
        public string[] Forced { get; internal set; }
        public WidgetPage Opens { get; internal set; }
        //: Why it cannot run now; null when it can.
        public string Disabled { get; internal set; }
        //: What the row shows at the right.
        public string Hint { get; internal set; }
        //: The branch the work is on, in the branch list.
        public bool Current { get; internal set; }
        //: What the row asks for before it runs (the answer ends its Args); null when it runs at once.
        public string Asks { get; internal set; }
        //: The text the answer starts from: the value a setting has now.
        public string Initial { get; internal set; }
        //: What the folder dialog the row opens asks for (the folder chosen ends its Args); null for no dialog.
        //: A row that also asks opens the dialog from its line, and the folder chosen fills the line.
        public string Picks { get; internal set; }
        //: The rows of the list the row opens (WidgetPage.Choices).
        public List<WidgetItem> Choices { get; internal set; }
        //: The text the row puts on the clipboard; null for a row that does something else.
        public string Copies { get; internal set; }
        //: The deny-list key the row switches (the agent writes it, no cts command), a check box
        //: ticked while it is blocked (Current); null for another row.
        public string Toggles { get; internal set; }
        public string OpensProject { get; internal set; }
        public bool PicksProject { get; internal set; }
        public string WorkingFolder { get; internal set; }
    }

    public static partial class WidgetMenu
    {
        public const string NoSyncFolder = "the project has no sync folder: cts set-sync-folder";
        public const string Online = "online: cts disconnect first";
        public const string NoProjectReason = "open a project first";
        //: The known projects the no-project page lists, on 1 to 6.
        public const int KnownProjectRows = 6;

        public static List<WidgetItem> NoProject(IList<KnownProject> known, IDictionary<string, string> projectFiles, int pid)
        {
            var items = known.Take(KnownProjectRows).Select((project, index) =>
            {
                string file;
                var hasFile = projectFiles.TryGetValue(project.Id, out file) && file.Length > 0;
                return new WidgetItem
                {
                    Key = (char)('1' + index),
                    Label = project.Name,
                    Hint = project.Folder,
                    Args = project.Owner ? null : new[] { "project", "update" },
                    OpensProject = project.Owner && hasFile ? file : null,
                    WorkingFolder = project.Owner ? null : project.Folder,
                    Disabled = project.Owner && !hasFile ? "no project file in its repository" : null,
                };
            }).ToList();
            items.Add(new WidgetItem { Key = '7', Label = "Open project...", Hint = "any .project file", PicksProject = true });
            items.Add(new WidgetItem { Key = '8', Label = "Settings", Opens = WidgetPage.Settings, Hint = "sync folder, open program, quick key" });
            items.Add(More(pid, "", NoProjectReason, true));
            return items;
        }

        public static List<WidgetItem> NoProjectSettings(string tools, string config)
        {
            var items = Settings("", "", false, tools, config, null, false);
            items[0].Disabled = NoProjectReason;
            items[0].Hint = "unavailable";
            return items;
        }

        //: The branch list's rows beyond this many are left out.
        public const int MaxBranches = 12;

        // *syncFolder* is the project's sync folder, "" when it has none;
        // *pid* is this IDE's process and *project* the open project's name,
        // "" when none is open; *owner* says this machine publishes the
        // project file, which `6` does; on a colleague's `6` pulls the branch
        // and opens it on the published project (`cts project update`).
        public static List<WidgetItem> Items(bool online, string syncFolder, int pid, string project, bool owner)
        {
            var folder = syncFolder.Length > 0 ? null : NoSyncFolder;
            var items = new List<WidgetItem>
            {
                Forcing(Item('1', "Disk → IDE", folder ?? (online ? Online : null), "import", "--tool"), "the disk wins"),
                Forcing(Item('2', "IDE → Disk", folder, "export", "--tool"), "the IDE wins"),
                Page('3', "Compare", WidgetPage.Compare, folder, "IDE with the disk or a branch"),
                Page('4', "Switch branch", WidgetPage.Branches, folder, "on disk"),
                Asking(Item('5', "Commit the disk", folder, "commit", "-m"), "commit message", "the files on disk, not the IDE"),
                owner
                    ? Asking(Item('6', "Commit the disk, publish", folder, "commit", "--publish", "-m"),
                        "commit message", "+ the saved project file")
                    : Item('6', "Pull and update the project", folder ?? (online ? Online : null), "project", "update"),
                Hinted(Item('7', "Open the project folder", folder, "open"), "history, merging branches, undo"),
                Page('8', "Settings", WidgetPage.Settings, null, syncFolder.Length > 0 ? "sync folder, project" : "set the sync folder"),
                More(pid, project, folder),
            };
            return items;
        }

        // The open row of *items* named after the program `cts tool` (*tools*,
        // its JSON) says `cts open` starts: "Open in VS Code".  False when
        // there is no such row or the JSON does not name one.
        public static bool NameOpener(List<WidgetItem> items, string tools)
        {
            var row = items.FirstOrDefault(item => item.Args != null && item.Args.Length == 1 && item.Args[0] == "open");
            var open = Field(ParsedOrNull(tools), "open");
            var uses = open != null && open.ContainsKey("uses") ? open["uses"] as string : null;
            if (row == null || uses == null) return false;
            row.Label = "Open in " + Program(uses);
            return true;
        }

        // After a commit, or a pull that left the branch ahead of its upstream
        // (its verdict *line*): push the branch to the team's repository
        // (`cts push`), the one answer; Esc keeps it on this PC.
        public static List<WidgetItem> Pushing(string line, out string question)
        {
            question = line + "\nPush the branch to the team's repository?";
            return new List<WidgetItem> { Item('1', "Push the branch", null, "push") };
        }

        // After a push the team's repository refused for commits the branch
        // lacks (its line says to pull them first with `cts project update`),
        // whether to pull them into the project now; offline only, as the
        // pull row.  Null for any other line.
        public static List<WidgetItem> Pulling(string line, bool online, out string question)
        {
            question = null;
            if (line == null || line.IndexOf("pull them first (cts project update)", StringComparison.Ordinal) < 0) return null;
            question = line + "\nPull the team's commits into the project first?";
            return new List<WidgetItem> { Item('1', "Pull and update the project", online ? Online : null, "project", "update") };
        }

        // The header's state line from `cts compare`'s *verdict*: how many
        // objects changed on the disk, in the IDE and on both sides since the
        // last sync, or "in sync"; "not on disk yet" for a folder with no sync
        // base (`2` writes it), and which side to take when the folder was
        // last synced with another project file; "state unknown" for a line that is not a
        // compare's (it failed).
        public static string State(string verdict, out WidgetTone tone)
        {
            if (verdict == null || !verdict.StartsWith("ok compare", StringComparison.Ordinal))
            {
                tone = WidgetTone.Unknown;
                return "state unknown";
            }
            if (Value(verdict, "base") == "none")
            {
                tone = WidgetTone.Changed;
                return "not on disk yet — 2 writes it";
            }
            if (Value(verdict, "base") == "other")
            {
                tone = WidgetTone.Changed;
                return "the disk was synced with another project file — 2 writes this one, 1 takes the disk";
            }
            var counts = Counts(verdict);
            var both = counts("both");
            // A record changed on both sides is one of the disk's records too.
            var disk = counts("modified") + counts("added") + counts("deleted") + counts("not_importable") - both;
            var ide = counts("ide_changed");
            var parts = new[] { Tuple.Create("disk", disk), Tuple.Create("IDE", ide), Tuple.Create("both", both) }
                .Where(part => part.Item2 > 0).Select(part => part.Item1 + " " + part.Item2.ToString(CultureInfo.InvariantCulture)).ToList();
            tone = both > 0 ? WidgetTone.Both : parts.Count > 0 ? WidgetTone.Changed : WidgetTone.InSync;
            return parts.Count > 0 ? "changed: " + string.Join(" · ", parts) : "in sync";
        }

        // How many objects the IDE holds that the disk lacks, by a compare's
        // *verdict*: what only the IDE changed or both did; every difference
        // when the folder has no base of this project file; 0 for a line that
        // is not a compare's.  A commit takes the disk without them.
        public static int IdeEdits(string verdict)
        {
            if (verdict == null || !verdict.StartsWith("ok compare", StringComparison.Ordinal)) return 0;
            var counts = Counts(verdict);
            if (Value(verdict, "base") == "none" || Value(verdict, "base") == "other")
                return counts("modified") + counts("added") + counts("deleted") + counts("not_importable") + counts("ide_changed");
            return counts("ide_changed") + counts("both");
        }

        //: The commit message's prompt when the IDE holds *edits* the disk lacks; "" without any.
        public static string CommitNote(int edits)
            => edits > 0 ? "the IDE has " + edits.ToString(CultureInfo.InvariantCulture) + " edit(s) not on disk, 2 IDE → Disk takes them; " : "";

        //: Why the branch the work is on, with no upstream, does nothing.
        public const string Here = "the work is on this branch already; it has no team repository to pull from";

        //: Why a row that changes the disk or the IDE waits while a compare of the folder runs.
        public const string Busy = "wait: cts compare is running";

        // Does *item* wait while a compare of the folder runs: it changes the
        // disk, the IDE or the base, or compares itself?
        public static bool WaitsForCompare(WidgetItem item)
        {
            if (item.Opens == WidgetPage.Compare || item.Opens == WidgetPage.Branches) return true;
            return item.Args != null && (MovesState(item.Args) || item.Args.Length > 0 && new[] { "compare", "branch", "set-sync-folder" }.Contains(item.Args[0]));
        }

        // Does the run of *args* move what `cts compare` counts, so the header reads it again?
        public static bool MovesState(string[] args)
        {
            return args.Length > 0 && new[] { "import", "export", "sync", "checkout", "commit", "project" }.Contains(args[0]);
        }

        // The value of a verdict line's *key*, "" when it does not name it.
        static string Value(string verdict, string key)
        {
            var prefix = key + "=";
            var pair = (verdict ?? "").Split(' ').FirstOrDefault(part => part.StartsWith(prefix, StringComparison.Ordinal));
            return pair == null ? "" : pair.Substring(prefix.Length);
        }

        // The numbers of a verdict line's key=value pairs; 0 for one it does not name.
        static Func<string, int> Counts(string verdict)
        {
            var found = new Dictionary<string, int>();
            foreach (var pair in (verdict ?? "").Split(' '))
            {
                var at = pair.IndexOf('=');
                int value;
                if (at > 0 && int.TryParse(pair.Substring(at + 1), NumberStyles.None, CultureInfo.InvariantCulture, out value))
                    found[pair.Substring(0, at)] = value;
            }
            return key => found.TryGetValue(key, out var value) ? value : 0;
        }

        // The branch list: a new branch where the work is (key '+'), then the
        // local branches as git lists them (the most recent first), the first
        // nine with a digit, each switching the disk; the one the work is on
        // is marked and pulls the team's commits into the project instead
        // (`cts project update`), which waits while *online*; without an
        // *upstream* there is nothing to pull and the row only says so.
        public static List<WidgetItem> Branches(IEnumerable<string> names, string current, bool upstream, bool online)
        {
            var create = Asking(Item('+', current != null ? "New branch from " + current : "New branch here", null, "branch"),
                "new branch name", "cts branch");
            return new[] { create }.Concat(names.Where(name => name.Length > 0).Take(MaxBranches).Select((name, i) =>
            {
                var here = name == current;
                var pulls = here && upstream;
                return new WidgetItem
                {
                    Key = i < 9 ? (char)('1' + i) : '\0',
                    Label = name,
                    Args = pulls ? new[] { "project", "update" } : here ? null : new[] { "checkout", name, "--disk-only" },
                    Disabled = here && !upstream ? Here : pulls && online ? Online : null,
                    Hint = pulls ? "pull" : here ? "here" : "switch disk",
                    Current = here,
                };
            })).ToList();
        }

        // The compare page: the IDE against the disk's files (key '1'), then
        // against each local branch as git lists them (the most recent first,
        // the next eight with a digit), the one the work is on as last
        // committed; all in the compare program, nothing written.
        public static List<WidgetItem> Comparisons(IEnumerable<string> names, string current)
        {
            var disk = new WidgetItem { Key = '1', Label = "Disk", Args = new[] { "compare", "--tool" }, Hint = "the files" };
            return new[] { disk }.Concat(names.Where(name => name.Length > 0).Take(MaxBranches).Select((name, i) => new WidgetItem
            {
                Key = i < 8 ? (char)('2' + i) : '\0',
                Label = name,
                Args = new[] { "compare", "--tool", "--against", name },
                Hint = name == current ? "last commit" : "branch",
                Current = name == current,
            })).ToList();
        }

        static WidgetItem Item(char key, string label, string disabled, params string[] args)
        {
            return new WidgetItem
            {
                Key = key, Label = label, Args = args, Disabled = disabled,
                Hint = disabled == null ? "cts " + string.Join(" ", args) : "unavailable",
            };
        }

        // *item* with *hint* at its right in place of its command.
        static WidgetItem Hinted(WidgetItem item, string hint)
        {
            if (item.Disabled == null) item.Hint = hint;
            return item;
        }

        // *item* with its Shift run: the command with --force for --tool, *wins* named in its hint.
        static WidgetItem Forcing(WidgetItem item, string wins)
        {
            item.Forced = new[] { item.Args[0], "--force" };
            if (item.Disabled == null) item.Hint = "Shift: " + wins + ", no merge";
            return item;
        }

        static WidgetItem Asking(WidgetItem item, string asks, string hint)
        {
            item.Asks = asks;
            if (item.Disabled == null) item.Hint = hint;
            return item;
        }

        // The row of what is used now and then, a page of its own.
        static WidgetItem More(int pid, string project, string noFolder, bool noProject = false)
        {
            var item = Page('0', "More", WidgetPage.More, null, noProject ? "activity, AI line" : "format, activity, AI line, FSM, analysis");
            if (noProject)
            {
                item.Choices = new List<WidgetItem>
                {
                    Page('2', "Agent activity", WidgetPage.Activity, null, "live window"),
                    Target(pid, ""),
                };
                return item;
            }
            item.Choices = new List<WidgetItem>
            {
                Page('1', "Format ST", WidgetPage.Format, project.Length == 0 ? "no project is open" : null, "cts fmt, window"),
                Page('2', "Agent activity", WidgetPage.Activity, null, "live window"),
                Target(pid, project),
                Page('4', "FSM map", WidgetPage.Fsm, project.Length == 0 ? "no project is open" : null, "state machines in the ST, window"),
                Page('5', "Static analysis", WidgetPage.StaticAnalysis, noFolder, "cts analyze, window"),
            };
            return item;
        }

        // The row that copies the line for an AI agent: the project is named
        // when one is open, so the agent refuses to write into another.
        static WidgetItem Target(int pid, string project)
        {
            var target = "ide-" + pid.ToString(CultureInfo.InvariantCulture);
            var expect = project.Length == 0 ? "" : " --expect-project " + (project.Contains(" ") ? "\"" + project + "\"" : project);
            return new WidgetItem
            {
                Key = '3', Label = "Copy the line for an AI agent",
                Copies = "!cts --target " + target + expect + " --help",
                Hint = project.Length == 0 ? target : target + " · " + project,
            };
        }

        static WidgetItem Page(char key, string label, WidgetPage page, string disabled, string hint)
        {
            return new WidgetItem
            {
                Key = key, Label = label, Opens = page, Disabled = disabled,
                Hint = disabled == null ? hint : "unavailable",
            };
        }
    }
}
