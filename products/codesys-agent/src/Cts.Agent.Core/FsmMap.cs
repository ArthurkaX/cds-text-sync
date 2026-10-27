// The FSM window's model: the objects `cts fsm --layout --json` answers, each
// machine with its GRAFCET geometry (FsmGrafcet) and the code behind every
// step and transition;
// and which step or transition a point of the drawing falls on.  The window
// (FsmView) only draws it.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using static Cts.Agent.JsonMap;

namespace Cts.Agent
{
    public sealed class FsmObject
    {
        public string Guid { get; internal set; }
        public string Label { get; internal set; }
        public List<FsmMachine> Machines { get; } = new List<FsmMachine>();
    }

    public sealed class FsmMachine
    {
        //: The CASE selector: `state`, `stMachine.eStep`.
        public string Selector { get; internal set; }
        //: "line N: what is wrong", N a line of the implementation.
        public List<string> Warnings { get; } = new List<string>();
        public List<FsmCode> States { get; } = new List<FsmCode>();
        //: In the answer's order: an FsmLink's Transition indexes it.
        public List<FsmCode> Transitions { get; } = new List<FsmCode>();
        public FsmLayout Layout { get; internal set; }
        //: What reads the selector online, one path per instance.
        public List<string> Watch { get; } = new List<string>();
    }

    //: A state (Title its label, Values the numbers it stands for) or a
    //: transition (Title `A → B`, Guard its condition) with the code behind
    //: it and the line of the implementation it starts on.
    public sealed class FsmCode
    {
        public string Title { get; internal set; }
        public string Source { get; internal set; }
        public string Target { get; internal set; }
        public List<string> Values { get; } = new List<string>();
        public string Guard { get; internal set; }
        public string Code { get; internal set; }
        public int Line { get; internal set; }
    }

    public sealed class FsmLayout
    {
        public int Width { get; internal set; }
        public int Height { get; internal set; }
        //: The enum prefix every label shares, left out of the steps.
        public string Prefix { get; internal set; }
        //: x, y, w, h of the "any" box (transitions written outside the CASE); null without one.
        public int[] AnyBox { get; internal set; }
        public List<FsmStep> Steps { get; } = new List<FsmStep>();
        public List<FsmStep> Chips { get; } = new List<FsmStep>();
        public List<FsmLink> Links { get; } = new List<FsmLink>();
        //: The number cell's width, a text line's height, half a horizontal guard bar.
        public int NumW { get; internal set; }
        public int TextH { get; internal set; }
        public int BarHalf { get; internal set; }
    }

    //: A step box, or a chip (a priority transition's target: no FullLabel).
    public sealed class FsmStep
    {
        public int Number { get; internal set; }
        public string Label { get; internal set; }
        public string FullLabel { get; internal set; }
        public int X { get; internal set; }
        public int Y { get; internal set; }
        public int W { get; internal set; }
        public int H { get; internal set; }
        public bool Initial { get; internal set; }
        public bool Priority { get; internal set; }
        //: The steps that jump here from afar, written left of the box at InboundX.
        public List<int> Inbound { get; } = new List<int>();
        public int InboundX { get; internal set; }
    }

    public sealed class FsmLink
    {
        //: "global" (a priority transition), "jump" (a long hop) or another, plain.
        public string Kind { get; internal set; }
        //: Its index in FsmMachine.Transitions; -1 for none.
        public int Transition { get; internal set; }
        public List<int[]> Points { get; } = new List<int[]>();
        //: The guard bar, Way "h" or "v"; null without one.
        public FsmMark Bar { get; internal set; }
        public string GuardText { get; internal set; }
        public int[] GuardAt { get; internal set; }
        public int GuardW { get; internal set; }
        //: The arrow's tip, Way where it points: left, right, up, down; null without one.
        public FsmMark Arrow { get; internal set; }
        public string NoteText { get; internal set; }
        public int[] NoteAt { get; internal set; }
    }

    public sealed class FsmMark
    {
        public int X { get; internal set; }
        public int Y { get; internal set; }
        public string Way { get; internal set; }
    }

    public static class FsmMap
    {
        //: The arrowhead's length and half width.
        const int ArrowLen = 8;
        const int ArrowHalf = 5;

        // The objects of `cts fsm --layout --json`'s answer, in its order.
        public static List<FsmObject> Parse(string json)
        {
            var data = Json.Parse(json) as Dictionary<string, object>;
            var items = data != null && data.TryGetValue("items", out var raw) ? raw as List<object> : null;
            if (items == null) throw new JsonException("cts fsm --layout --json answered no items");
            var objects = new List<FsmObject>();
            foreach (var entry in items.OfType<Dictionary<string, object>>())
            {
                var item = new FsmObject { Guid = Text(entry, "guid"), Label = Text(entry, "label") };
                foreach (var machine in List(entry, "machines")) item.Machines.Add(Machine(machine));
                objects.Add(item);
            }
            return objects;
        }

        static FsmMachine Machine(Dictionary<string, object> entry)
        {
            var machine = new FsmMachine { Selector = Text(entry, "selector"), Layout = Layout(Dict(entry, "layout")) };
            machine.Watch.AddRange(Values(entry, "watch").Select(Convert.ToString));
            foreach (var warning in List(entry, "warnings"))
                machine.Warnings.Add("line " + Int(warning, "line") + ": " + Text(warning, "text"));
            foreach (var state in List(entry, "states"))
            {
                var code = new FsmCode { Title = Text(state, "label"), Code = Text(state, "code"), Line = Int(state, "line") };
                code.Values.AddRange(Values(state, "values").Select(Convert.ToString));
                machine.States.Add(code);
            }
            foreach (var transition in List(entry, "transitions"))
            {
                machine.Transitions.Add(new FsmCode
                {
                    Title = SourceLabel(transition) + " → " + Text(transition, "target"),
                    Source = Text(transition, "source"), Target = Text(transition, "target"),
                    Guard = Text(transition, "guard"),
                    Code = Text(transition, "code"),
                    Line = Int(transition, "line"),
                });
            }
            return machine;
        }

        static FsmLayout Layout(Dictionary<string, object> entry)
        {
            var metrics = Dict(entry, "metrics");
            var layout = new FsmLayout
            {
                Width = Int(entry, "width"), Height = Int(entry, "height"), Prefix = Text(entry, "prefix"),
                AnyBox = Ints(entry, "any_box"),
                NumW = Int(metrics, "num_w"), TextH = Int(metrics, "text_h"), BarHalf = Int(metrics, "bar_half"),
            };
            foreach (var step in List(entry, "steps"))
            {
                var box = Box(step);
                box.FullLabel = Text(step, "full_label");
                box.Initial = Equals(Value(step, "initial"), true);
                box.Priority = Equals(Value(step, "priority"), true);
                box.Inbound.AddRange(Values(step, "inbound").Select(Convert.ToInt32));
                box.InboundX = Int(step, "inbound_x");
                layout.Steps.Add(box);
            }
            foreach (var chip in List(entry, "chips")) layout.Chips.Add(Box(chip));
            foreach (var link in List(entry, "links"))
            {
                var line = new FsmLink
                {
                    Kind = Text(link, "kind"),
                    Transition = Value(link, "transition_index") == null ? -1 : Int(link, "transition_index"),
                    Bar = Mark(link, "bar"),
                    GuardText = Text(link, "guard_text"), GuardAt = Ints(link, "guard_at"), GuardW = Int(link, "guard_w"),
                    Arrow = Mark(link, "arrow"),
                    NoteText = Text(link, "note_text"), NoteAt = Ints(link, "note_at"),
                };
                foreach (var point in Values(link, "points").OfType<List<object>>())
                    line.Points.Add(point.Select(Convert.ToInt32).ToArray());
                layout.Links.Add(line);
            }
            return layout;
        }

        static FsmStep Box(Dictionary<string, object> entry)
        {
            return new FsmStep
            {
                Number = Int(entry, "number"), Label = Text(entry, "label"),
                X = Int(entry, "x"), Y = Int(entry, "y"), W = Int(entry, "w"), H = Int(entry, "h"),
            };
        }

        // ---- what a point of the drawing falls on

        // The step whose box holds (x, y); null for none.
        public static FsmStep StepAt(FsmLayout layout, int x, int y)
        {
            return layout.Steps.FirstOrDefault(step => x >= step.X && x <= step.X + step.W && y >= step.Y && y <= step.Y + step.H);
        }

        // The transition (its index) whose line, bar or guard text passes
        // within *slack* of (x, y), the nearest; -1 for none.
        public static int TransitionAt(FsmLayout layout, int x, int y, int slack)
        {
            var best = -1;
            var bestDistance = double.MaxValue;
            foreach (var link in layout.Links.Where(link => link.Transition >= 0))
            {
                var distance = double.MaxValue;
                for (var i = 1; i < link.Points.Count; i++)
                    distance = Math.Min(distance, Segment(x, y, link.Points[i - 1], link.Points[i]));
                if (link.GuardAt != null && Inside(x, y, link.GuardAt[0], link.GuardAt[1], link.GuardW, layout.TextH)) distance = 0;
                if (distance <= slack && distance < bestDistance)
                {
                    bestDistance = distance;
                    best = link.Transition;
                }
            }
            return best;
        }

        // The arrowhead's three corners, its tip at (x, y), pointing *direction*.
        public static int[][] Arrowhead(int x, int y, string direction)
        {
            switch (direction)
            {
                case "left": return new[] { new[] { x, y }, new[] { x + ArrowLen, y - ArrowHalf }, new[] { x + ArrowLen, y + ArrowHalf } };
                case "right": return new[] { new[] { x, y }, new[] { x - ArrowLen, y - ArrowHalf }, new[] { x - ArrowLen, y + ArrowHalf } };
                case "down": return new[] { new[] { x, y }, new[] { x - ArrowHalf, y - ArrowLen }, new[] { x + ArrowHalf, y - ArrowLen } };
                default: return new[] { new[] { x, y }, new[] { x - ArrowHalf, y + ArrowLen }, new[] { x + ArrowHalf, y + ArrowLen } };
            }
        }

        static bool Inside(int x, int y, int left, int top, int w, int h)
        {
            return x >= left && x <= left + w && y >= top && y <= top + h;
        }

        static double Segment(int x, int y, int[] a, int[] b)
        {
            double dx = b[0] - a[0], dy = b[1] - a[1];
            var length = dx * dx + dy * dy;
            var t = length == 0 ? 0 : Math.Max(0, Math.Min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / length));
            double px = a[0] + t * dx - x, py = a[1] + t * dy - y;
            return Math.Sqrt(px * px + py * py);
        }

        // ---- the state a value read online stands for

        static readonly Regex TypePrefix = new Regex(@"^[A-Za-z_]\w*#(?=[-+\d])");
        static readonly Regex Based = new Regex(@"^(2|8|16)#([0-9A-Fa-f_]+)$");

        // The state (its label) the selector's value *text* (as the IDE
        // spells it: `5`, `INT#5`, `E_Step.Run`) is in; null for none.
        public static string StateOf(FsmMachine machine, string text)
        {
            var value = (text ?? "").Trim();
            var number = Integer(TypePrefix.Replace(value, ""));
            foreach (var state in machine.States)
            {
                foreach (var alias in state.Title.Split(',').Select(alias => alias.Trim()))
                    if (alias.Equals(value, StringComparison.OrdinalIgnoreCase)
                        || alias.Contains('.') != value.Contains('.') && Last(alias).Equals(Last(value), StringComparison.OrdinalIgnoreCase) && !char.IsDigit(Last(value).FirstOrDefault())
                        || number != null && Integer(alias) == number)
                        return state.Title;
                if (number != null && state.Values.Any(entry => Holds(entry, number.Value))) return state.Title;
            }
            return null;
        }

        // The value one name of a `vars.read` answer has, as the IDE spells
        // it; null, and *failure* why, when there is none to show.
        public static string LiveValue(IDictionary<string, object> answer, out string failure)
        {
            failure = null;
            if (!Equals(Value(answer, "logged_in"), true))
            {
                failure = Equals(Value(answer, "online"), true) ? "not logged in" : "no application to read";
                return null;
            }
            var result = Maps(answer, "results").FirstOrDefault();
            if (result != null && Equals(Value(result, "ok"), true)) return Convert.ToString(Value(result, "text") ?? Value(result, "value"), System.Globalization.CultureInfo.InvariantCulture);
            var error = Value(result, "error") as IDictionary<string, object>;
            failure = Text(error, "code") == "not_exported" ? "not in the application on the PLC: misspelled, or never compiled in"
                : Text(error, "message", "the IDE answered no value");
            return null;
        }

        static string Last(string name) => name.Substring(name.LastIndexOf('.') + 1);

        // "5" or "3..7" holds *number*.
        static bool Holds(string entry, long number)
        {
            var parts = entry.Split(new[] { ".." }, StringSplitOptions.None);
            var low = Integer(parts[0]);
            var high = Integer(parts[parts.Length - 1]);
            return low != null && high != null && number >= low && number <= high;
        }

        static long? Integer(string text)
        {
            text = (text ?? "").Trim().Replace("_", "");
            var based = Based.Match(text);
            if (based.Success)
            {
                try { return Convert.ToInt64(based.Groups[2].Value, int.Parse(based.Groups[1].Value)); }
                catch (Exception error) when (error is FormatException || error is OverflowException || error is ArgumentException) { return null; }
            }
            return long.TryParse(text, System.Globalization.NumberStyles.AllowLeadingSign, System.Globalization.CultureInfo.InvariantCulture, out var value) ? value : (long?)null;
        }

        // The transitions (their indexes) that lead from state *from* to
        // state *to*: its own, else those written outside the CASE.
        public static List<int> Taken(FsmMachine machine, string from, string to)
        {
            var into = machine.Transitions.Select((transition, i) => new { transition, i }).Where(item => item.transition.Target == to).ToList();
            var own = into.Where(item => item.transition.Source == from).ToList();
            return (own.Count > 0 ? own : into.Where(item => item.transition.Source.Length == 0)).Select(item => item.i).ToList();
        }

        // ---- reading the answer

        // Where a transition leaves from: its state, (other value) for the
        // CASE's ELSE, (any) for code outside the CASE.
        internal static string SourceLabel(IDictionary<string, object> transition)
        {
            var source = transition.TryGetValue("source", out var value) ? Convert.ToString(value) ?? "" : "";
            return source.Length > 0 ? source : transition.ContainsKey("else") ? "(other value)" : "(any)";
        }

        static int[] Ints(Dictionary<string, object> entry, string key)
        {
            return (Value(entry, key) as List<object>)?.Select(Convert.ToInt32).ToArray();
        }

        // [x, y, way] as a mark; null when absent.
        static FsmMark Mark(Dictionary<string, object> entry, string key)
        {
            var value = Value(entry, key) as List<object>;
            if (value == null || value.Count < 3) return null;
            return new FsmMark { X = Convert.ToInt32(value[0]), Y = Convert.ToInt32(value[1]), Way = Convert.ToString(value[2]) };
        }

        static IEnumerable<object> Values(Dictionary<string, object> entry, string key)
        {
            return Value(entry, key) as List<object> ?? new List<object>();
        }

        static IEnumerable<Dictionary<string, object>> List(Dictionary<string, object> entry, string key)
        {
            return Values(entry, key).OfType<Dictionary<string, object>>();
        }

        static Dictionary<string, object> Dict(Dictionary<string, object> entry, string key)
        {
            return Value(entry, key) as Dictionary<string, object>;
        }
    }
}
