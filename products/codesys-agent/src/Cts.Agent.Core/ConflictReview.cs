// The conflict window's model.  Digits 1 and 2 of the quick window, without
// Shift, first ask `cts import --dry-run --json` which objects both sides
// changed in the same lines (an .xml: the same element), each with its disk
// and IDE text; when there are any, the window lists them, and a person picks
// for each the side that wins (its text goes to both) or, for a .st, the merge
// program, or makes one side win everywhere (the row's Shift run).  Apply runs the row's command with
// `--take KEY=disk|ide` for each choice and `--tool` when one is settled by
// hand.  The window (ConflictView) only draws it.
using System;
using System.Collections.Generic;
using System.Linq;
using static Cts.Agent.JsonMap;

namespace Cts.Agent
{
    public enum ConflictSide { Open, Disk, Ide, Hand }

    public sealed class ConflictItem
    {
        //: What --take names it by.
        public string Key { get; internal set; }
        public string Name { get; internal set; }
        public string Path { get; internal set; }
        //: Its text on disk and in the IDE: the declaration, then the body below the marker line.
        public string Disk { get; internal set; }
        public string Ide { get; internal set; }
        public ConflictSide Side { get; set; }
        //: Can the merge program settle it: a .st object's text, not a whole .xml or .csv file.
        public bool ByHand => (Path ?? "").EndsWith(".st", StringComparison.OrdinalIgnoreCase);
    }

    public static class ConflictReview
    {
        // The conflicts of a dry run's answer, in its order; none when it names none.
        public static List<ConflictItem> Parse(string json)
        {
            var data = Json.Parse(json) as Dictionary<string, object>;
            var conflicts = data != null && data.TryGetValue("conflicts", out var raw) ? raw as List<object> : null;
            return (conflicts ?? new List<object>()).OfType<Dictionary<string, object>>().Select(entry => new ConflictItem
            {
                Key = Convert.ToString(Value(entry, "key") ?? Value(entry, "path")),
                Name = Convert.ToString(Value(entry, "name")),
                Path = Convert.ToString(Value(entry, "path")),
                Disk = Text(entry, "disk"),
                Ide = Text(entry, "ide"),
            }).ToList();
        }

        static string Text(Dictionary<string, object> entry, string side) => (Convert.ToString(Value(entry, side)) ?? "").Replace("\r\n", "\n");

        // Does the run of *args*, chosen on *item*, ask the dry run first: the
        // row's own run of 1 or 2, not Shift's, while the header's compare did
        // not say that no object changed on both sides (*both*, -1 not known)?
        public static bool AsksFirst(WidgetItem item, string[] args, int both)
            => item.Forced != null && ReferenceEquals(args, item.Args) && both != 0;

        // The dry run that names the conflicts.
        public static readonly string[] DryRun = { "import", "--dry-run", "--json" };

        // The run that carries the choices: the row's command (import or
        // export) with each side chosen, and --tool when one goes to the merge
        // program.  Null while one is still open.
        public static string[] Args(string command, IList<ConflictItem> items)
        {
            if (items.Any(item => item.Side == ConflictSide.Open)) return null;
            var args = new List<string> { command };
            foreach (var item in items.Where(item => item.Side == ConflictSide.Disk || item.Side == ConflictSide.Ide))
            {
                args.Add("--take");
                args.Add(item.Key + "=" + (item.Side == ConflictSide.Disk ? "disk" : "ide"));
            }
            if (items.Any(item => item.Side == ConflictSide.Hand)) args.Add("--tool");
            return args.ToArray();
        }

        // The next one still open after *from*, from the top again; -1 when all are chosen.
        public static int NextOpen(IList<ConflictItem> items, int from)
        {
            for (var step = 1; step <= items.Count; step++)
            {
                var at = (Math.Max(-1, from) + step) % items.Count;
                if (items[at].Side == ConflictSide.Open) return at;
            }
            return -1;
        }

        // What a row's mark reads: the side chosen, or "?".
        public static string Mark(ConflictItem item)
            => item.Side == ConflictSide.Disk ? "disk" : item.Side == ConflictSide.Ide ? "IDE" : item.Side == ConflictSide.Hand ? "by hand" : "?";
    }
}
