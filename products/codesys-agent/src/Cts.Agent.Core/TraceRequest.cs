using System.Linq;

namespace Cts.Agent
{
    // What `trace.set` changes in the trace (`cts trace set`); a setting left
    // null stays as the trace has it.
    public sealed class TraceRequest
    {
        //: The trace's name below the application, and on the PLC after it.
        public const string Name = "CtsTrace";
        //: A new trace's buffer, in samples per variable: 10 s of a 10 ms task.
        public const int DefaultSamples = 1000;
        //: The edge names a caller gives, and the IDE's TriggerEdge for each.
        static readonly string[][] Edges = { new[] { "rising", "Positive" }, new[] { "falling", "Negative" }, new[] { "both", "Both" } };

        public string[] Variables;
        public string Task, Trigger, Edge, Level, Condition;
        public int? Every, Samples, Post;
        public bool NoTrigger;

        public static TraceRequest Parse(Request request)
        {
            var parsed = new TraceRequest
            {
                Variables = request.Strings("variables"),
                Task = Text(request, "task"),
                Trigger = Text(request, "trigger"),
                Level = Text(request, "level"),
                Condition = request.String("condition", "\0"),
                Every = Count(request, "every", 1),
                Samples = Count(request, "samples", 1),
                Post = Count(request, "post", 0),
                NoTrigger = request.Bool("no_trigger", false),
            };
            if (parsed.Condition == "\0") parsed.Condition = null;
            if (parsed.Variables != null)
            {
                var bad = parsed.Variables.FirstOrDefault(name => !IsVariable(name));
                if (bad != null) throw new ProtocolException(ErrorCodes.BadParams, "'" + bad + "' is no variable: name it with its POU or GVL, e.g. GVL_IO.rLevel");
                if (parsed.Variables.Length == 0) throw new ProtocolException(ErrorCodes.BadParams, "the trace needs a variable to record");
            }
            if (parsed.Trigger != null && !IsVariable(parsed.Trigger))
                throw new ProtocolException(ErrorCodes.BadParams, "'" + parsed.Trigger + "' is no variable to trigger on: name it with its POU or GVL");
            if (parsed.Trigger != null && parsed.NoTrigger)
                throw new ProtocolException(ErrorCodes.BadParams, "a trigger and no trigger: give one of them");
            var edge = Text(request, "edge");
            if (edge != null)
                parsed.Edge = Edges.FirstOrDefault(pair => pair[0] == edge)?[1]
                    ?? throw new ProtocolException(ErrorCodes.BadParams, "edge takes " + string.Join(", ", Edges.Select(pair => pair[0])) + ", not '" + edge + "'");
            return parsed;
        }

        // The caller's name of the IDE's TriggerEdge *edge*; "none" for None.
        public static string EdgeName(string edge) => Edges.FirstOrDefault(pair => pair[1] == edge)?[0] ?? edge.ToLowerInvariant();

        static bool IsVariable(string name) => name.Length > 0 && !name.Any(char.IsWhiteSpace) && name.Contains(".");

        static string Text(Request request, string name)
        {
            var text = request.String(name, "\0");
            if (text == "\0") return null;
            if (text.Trim().Length == 0) throw new ProtocolException(ErrorCodes.BadParams, "parameter '" + name + "' is empty");
            return text.Trim();
        }

        static int? Count(Request request, string name, int least)
        {
            if (!request.Params.ContainsKey(name) || request.Params[name] == null) return null;
            var value = request.Int(name);
            if (value < least || value > int.MaxValue) throw new ProtocolException(ErrorCodes.BadParams, "parameter '" + name + "' takes " + least + " or more");
            return (int)value;
        }
    }
}
