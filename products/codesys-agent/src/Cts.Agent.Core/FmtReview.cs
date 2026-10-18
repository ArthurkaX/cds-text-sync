// The format window's model: the objects `cts fmt --json` answers, each one's
// text before and after the formatter, which lines differ on each side, and
// where the next object or change to look at is.  The window (FmtView) only
// draws it; the formatting itself is the CLI's, the one the analyzer's rules use.
using System;
using System.Collections.Generic;
using System.Linq;
using static Cts.Agent.JsonMap;

namespace Cts.Agent
{
    public sealed class FmtItem
    {
        public string Guid { get; internal set; }
        public string Label { get; internal set; }
        //: The object's TimeStamp when `cts fmt` read it: a write asks for it unchanged.
        public long Timestamp { get; internal set; }
        //: The lines the formatter changes; 0 for an object it leaves as it is.
        public int Lines { get; internal set; }
        //: The declaration and the implementation, a blank line apart, as the IDE has them.
        public string Before { get; internal set; }
        public string After { get; internal set; }
    }

    public sealed class FmtDiff
    {
        //: The lines of the text before the formatter that it changes.
        public List<int> Left { get; } = new List<int>();
        //: The lines of the formatted text that differ from it.
        public List<int> Right { get; } = new List<int>();
        //: For each formatted line, the line before it is beside.
        public int[] LeftOf { get; internal set; }
    }

    public static class FmtReview
    {
        //: Between the declaration and the implementation in a pane.
        const string Gap = "\n\n";
        //: Beyond this many line pairs the diff compares line by line in place.
        const long MaxCells = 4000000;

        // The items of `cts fmt --json`'s answer, in its order.
        public static List<FmtItem> Parse(string json)
        {
            var data = Json.Parse(json) as Dictionary<string, object>;
            var items = data != null && data.TryGetValue("items", out var raw) ? raw as List<object> : null;
            if (items == null) throw new JsonException("cts fmt --json answered no items");
            return items.OfType<Dictionary<string, object>>().Select(entry => new FmtItem
            {
                Guid = Convert.ToString(Value(entry, "guid")),
                Label = Convert.ToString(Value(entry, "label")),
                Timestamp = Convert.ToInt64(Value(entry, "timestamp") ?? 0L),
                Lines = Int(entry, "lines"),
                Before = Joined(entry, "before"),
                After = Joined(entry, "after"),
            }).ToList();
        }

        static string Joined(Dictionary<string, object> entry, string side)
        {
            var parts = new[] { "declaration", "implementation" }
                .Select(part => Value(entry, part) as Dictionary<string, object>)
                .Where(part => part != null)
                .Select(part => Convert.ToString(Value(part, side)) ?? "");
            return string.Join(Gap, parts.Select(text => text.Replace("\r\n", "\n")));
        }

        // The next object after *from* that the formatter changes; -1 for none.
        public static int NextToFix(IList<FmtItem> items, int from)
        {
            for (var i = Math.Max(-1, from) + 1; i < items.Count; i++)
                if (items[i].Lines > 0) return i;
            return -1;
        }

        // The object written: it now reads as the formatter left it.
        public static void Written(FmtItem item)
        {
            item.Before = item.After;
            item.Lines = 0;
        }

        // The lines (0-based) that differ: those of *before* the formatter
        // replaces or drops, those of *after* it writes, by the longest run of
        // lines both keep; and for each line of *after* the line of *before*
        // beside it, so the panes scroll together.
        public static FmtDiff Changed(string before, string after)
        {
            var a = before.Split('\n');
            var b = after.Split('\n');
            var diff = new FmtDiff { LeftOf = new int[b.Length] };
            if ((long)a.Length * b.Length > MaxCells)
            {
                for (var i = 0; i < Math.Max(a.Length, b.Length); i++)
                {
                    if (i < b.Length) diff.LeftOf[i] = Math.Min(i, a.Length - 1);
                    if (i < a.Length && i < b.Length && a[i] == b[i]) continue;
                    if (i < a.Length) diff.Left.Add(i);
                    if (i < b.Length) diff.Right.Add(i);
                }
                return diff;
            }
            // kept[i, j]: the longest run both keep from a[i..] and b[j..].
            var kept = new int[a.Length + 1, b.Length + 1];
            for (var i = a.Length - 1; i >= 0; i--)
                for (var j = b.Length - 1; j >= 0; j--)
                    kept[i, j] = a[i] == b[j] ? kept[i + 1, j + 1] + 1 : Math.Max(kept[i + 1, j], kept[i, j + 1]);
            int x = 0, y = 0;
            while (x < a.Length || y < b.Length)
            {
                if (x < a.Length && y < b.Length && a[x] == b[y]) { diff.LeftOf[y++] = x++; }
                else if (y < b.Length && (x == a.Length || kept[x, y + 1] >= kept[x + 1, y]))
                {
                    diff.LeftOf[y] = Math.Min(x, a.Length - 1);
                    diff.Right.Add(y++);
                }
                else diff.Left.Add(x++);
            }
            return diff;
        }

        // The first line of each run of *changed* lines (ascending).
        public static List<int> Runs(IList<int> changed)
        {
            return changed.Where((value, i) => i == 0 || changed[i - 1] != value - 1).ToList();
        }

        // The first line of the next run of *changed* lines after *line*
        // (*forward*), or of the run before it; -1 when there is none.
        public static int NextChange(IList<int> changed, int line, bool forward)
        {
            var starts = Runs(changed);
            if (forward) return starts.Where(start => start > line).DefaultIfEmpty(-1).First();
            var before = starts.Where(start => start < line).ToList();
            return before.Count > 0 ? before[before.Count - 1] : -1;
        }
    }
}
