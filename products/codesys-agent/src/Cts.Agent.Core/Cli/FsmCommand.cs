using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Agent;
using Cts.Sync;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts fsm [NAME]`: the CASE state machines in the Structured Text, from
    // the IDE (what it holds now, saved or not) or with --disk from the sync
    // folder's files. The FSM window reads it with --layout.
    internal static class FsmCommand
    {
        internal static readonly CliCommand Command = new CliCommand
        {
            Name = "fsm",
            Arguments = "[NAME]",
            ArgumentLimit = 1,
            ArgumentHelp = "Only this object: Name or Parent.Name",
            Summary = "Find the state machines in the Structured Text",
            Description = "The CASE state machines in the IDE's Structured Text, saved or not: each state with its code, each transition with its condition and code, the state it starts in when the declaration says, and what looks wrong (a state never entered or without a way out, a value no branch handles). Transitions are listed in source order, the order IF/ELSIF branches are tested; a transition from (any) is code outside the CASE, so it leaves every state; one from (other value) is the CASE's ELSE. Lines count from the implementation's first line; --disk reads the sync folder's files instead, needs no IDE, and its lines are the file's. --svg FOLDER draws each machine as the FSM window does, on white, one SVG file per machine for a document or a review; hovering a step or a transition there shows its line. Text without a machine is not an error.",
            Seconds = 120,
            Options = new[]
            {
                CliOption.Switch("--disk", "disk", "Read the sync folder's files, not the IDE"),
                CliOption.Text("--sync-folder", "sync_folder", "PATH", "With --disk: the sync folder (default: the one around the current folder, else the open project's)"),
                CliOption.Switch("--mermaid", "mermaid", "Add each machine as a mermaid stateDiagram"),
                CliOption.Switch("--layout", "layout", "Add each machine's GRAFCET geometry, as the FSM window draws it"),
                CliOption.Text("--svg", "svg", "FOLDER", "Draw each machine as the FSM window does into FOLDER, one Object.selector.svg each"),
            },
            LocalExecute = Disk,
            LocalWhen = options => options.Params.ContainsKey("disk"),
            Execute = Ide,
            Build = Build,
        };

        sealed class Source { internal string Label, Name, Guid, File, Declaration, Text; internal int FirstLine = 1; }

        static IDictionary<string, object> Ide(CliCall call)
        {
            var records = Maps(call.Call("objects.texts", new Dictionary<string, object>()), "objects").ToList();
            var names = records.ToDictionary(r => Text(r, "guid"), r => Text(r, "name"), StringComparer.OrdinalIgnoreCase);
            var sources = records.Select(record => new Source
            {
                Guid = Text(record, "guid"), Name = Text(record, "name"),
                Label = names.TryGetValue(Text(record, "parent"), out var parent) && parent.Length > 0 ? parent + "." + Text(record, "name") : Text(record, "name"),
                Declaration = Text(record, "declaration"), Text = Text(record, "implementation"),
            });
            var watch = new FsmWatch(records.Select(r => new KeyValuePair<string, string>(Text(r, "name"), Text(r, "declaration"))));
            return Answer(call.Options, "ide", sources.ToList(), watch);
        }

        static IDictionary<string, object> Disk(CliOptions options, IAgentHost host, string work)
        {
            var folder = Folder(options, host, work);
            var view = ViewFolder.Of(folder);
            if (!Directory.Exists(view)) throw Failure("the sync folder has no " + view);
            var read = StViewReader.Read(view);
            var sources = read.Objects.Where(item => item.Implementation != null).Select(item =>
            {
                // The file's own names: the POU, then a member inside its file.
                var depth = (Path.GetDirectoryName(item.File) ?? "").Replace('\\', '/').Split('/').Count(part => part.Length > 0);
                return new Source { Label = string.Join(".", item.Path.Skip(depth)), Name = item.Path.Last(), File = item.File.Replace('\\', '/'), Declaration = item.Declaration, Text = item.Implementation, FirstLine = item.ImplementationLine ?? 1 };
            }).ToList();
            var watch = new FsmWatch(read.Objects.Select(item => new KeyValuePair<string, string>(item.Path.Last(), item.Declaration)));
            var data = Answer(options, "disk", sources, watch);
            data["sync_folder"] = folder;
            if (read.Errors.Count > 0)
                data["failed"] = (data.TryGetValue("failed", out var failed) ? (List<object>)failed : new List<object>())
                    .Concat(read.Errors.Select(error => (object)new Dictionary<string, object> { ["label"] = error.File, ["error"] = error.Reason })).ToList();
            return data;
        }

        // --sync-folder, else the sync folder around the current folder, else
        // the open project's.
        internal static string Folder(CliOptions options, IAgentHost host, string work)
        {
            if (options.Params.TryGetValue("sync_folder", out var named))
            {
                if (!Directory.Exists(Convert.ToString(named))) throw Failure("no such folder: " + Path.GetFullPath(Convert.ToString(named)));
                return ViewFolder.Named(Convert.ToString(named));
            }
            try { return ViewFolder.Around(work) ?? GitCommands.Folder(options, host, work); }
            catch (Exception error) when (error is InvalidOperationException || error is ArgumentException || error is AgentException) { throw Failure(error.Message); }
        }

        // The objects with a machine, by label; one that cannot be read is
        // named in failed and the rest still answer.  Each machine says what
        // to read online (watch) and what number a constant state stands for.
        static Dictionary<string, object> Answer(CliOptions options, string from, List<Source> sources, FsmWatch watch)
        {
            var name = options.Arguments.FirstOrDefault() ?? "";
            if (name.Length > 0)
            {
                sources = sources.Where(s => s.Label.Equals(name, StringComparison.OrdinalIgnoreCase) || s.Name.Equals(name, StringComparison.OrdinalIgnoreCase)).ToList();
                if (sources.Count == 0) throw Failure("no text object is named " + name);
            }
            var items = new List<object>();
            var failed = new List<object>();
            var drawings = options.Params.TryGetValue("svg", out var svg) ? Path.GetFullPath(Convert.ToString(svg)) : null;
            var drawn = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var source in sources.OrderBy(s => s.Label, StringComparer.OrdinalIgnoreCase))
            {
                var text = StText.Lf(source.Text);
                if (text.Trim().Length == 0) continue;
                List<Dictionary<string, object>> machines;
                try { machines = FsmDetector.Machines(text); }
                catch (Exception error) when (error is ArgumentException || error is InvalidOperationException || error is IndexOutOfRangeException)
                {
                    failed.Add(new Dictionary<string, object> { ["label"] = source.Label, ["error"] = error.Message });
                    continue;
                }
                if (machines.Count == 0) continue;
                foreach (var machine in machines)
                {
                    var initial = FsmDetector.Initial(source.Declaration, machine, out var basis);
                    if (initial != null) { machine["initial"] = initial; machine["initial_from"] = basis; }
                    var paths = watch.Paths(source.Label, source.Declaration, Convert.ToString(machine["selector"]));
                    if (paths.Count > 0) machine["watch"] = paths.Cast<object>().ToList();
                    foreach (var state in (List<Dictionary<string, object>>)machine["states"])
                    {
                        var values = watch.Values(Convert.ToString(state["label"]), source.Label.Split('.')[0], source.Declaration);
                        if (values.Count > 0) state["values"] = values.Cast<object>().ToList();
                    }
                    if (options.Params.ContainsKey("mermaid")) machine["mermaid"] = FsmMermaid.Render(machine);
                    if (options.Params.ContainsKey("layout")) machine["layout"] = FsmGrafcet.Layout(machine);
                    if (source.FirstLine != 1) Shift(machine, source.FirstLine - 1);
                    if (drawings == null) continue;
                    var drawing = new Dictionary<string, object>(machine) { ["layout"] = machine.TryGetValue("layout", out var layout) ? layout : FsmGrafcet.Layout(machine) };
                    machine["svg"] = FsmSvg.Write(drawings, source.Label, drawing, drawn);
                }
                var item = new Dictionary<string, object> { ["label"] = source.Label };
                if (source.Guid != null) item["guid"] = source.Guid;
                if (source.File != null) item["file"] = source.File;
                item["machines"] = machines.Cast<object>().ToList();
                items.Add(item);
            }
            var data = new Dictionary<string, object>
            {
                ["from"] = from,
                ["objects"] = sources.Count,
                ["with_fsm"] = items.Count,
                ["machines"] = items.Sum(item => ((List<object>)((Dictionary<string, object>)item)["machines"]).Count),
                ["items"] = items,
            };
            if (drawings != null) data["svg_folder"] = drawings;
            if (failed.Count > 0) data["failed"] = failed;
            return data;
        }

        // Lines of the implementation as lines of the file it starts in.
        static void Shift(Dictionary<string, object> machine, int by)
        {
            foreach (var key in new[] { "warnings", "states", "transitions" })
                foreach (var row in (System.Collections.IEnumerable)machine[key])
                {
                    var entry = (Dictionary<string, object>)row;
                    entry["line"] = Convert.ToInt32(entry["line"]) + by;
                }
        }

        internal static Answer Build(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("objects", data["objects"]).Add("with_fsm", data["with_fsm"]).Add("machines", data["machines"]);
            var items = Maps(data, "items").ToList();
            var failed = Maps(data, "failed").ToList();
            if (data.ContainsKey("svg_folder")) answer.Add("svg_folder", data["svg_folder"]);
            if (failed.Count > 0) answer.Add("failed", failed.Count).Partial();
            // One object asked for, or a diagram: every machine in full.
            var full = items.Count == 1 || items.Any(item => Maps(item, "machines").Any(machine => machine.ContainsKey("mermaid")));
            if (full) answer.Whole();
            foreach (var item in items)
                foreach (var machine in Maps(item, "machines"))
                {
                    var where = Text(item, "file").Length > 0 ? " in " + Text(item, "file") : "";
                    var states = Maps(machine, "states").ToList();
                    var transitions = Maps(machine, "transitions").ToList();
                    answer.Detail(Text(item, "label") + ": " + Text(machine, "selector") + " (" + states.Count + " states, " + transitions.Count + " transitions in source order" + (Text(machine, "initial").Length > 0 ? ", starts in " + Text(machine, "initial") + ", " + Text(machine, "initial_from") : "") + ")" + where
                        + (full && where.Length == 0 ? ", lines count from the implementation's first line" : "")
                        + (Text(machine, "svg").Length > 0 ? ", drawn in " + Text(machine, "svg") : ""));
                    if (!full) continue;
                    var watch = Items(machine, "watch").Select(Convert.ToString).ToList();
                    if (watch.Count > 0)
                        answer.Detail("  read it online: cts read " + watch[0] + (watch.Count > 1 ? "  (" + watch.Count + " instances, --json lists them)" : ""));
                    foreach (var transition in transitions)
                    {
                        var guard = Text(transition, "guard");
                        answer.Detail("  " + FsmMap.SourceLabel(transition) + " -> " + Text(transition, "target")
                            + (guard.Length > 0 ? " when " + string.Join(" ", guard.Split(new[] { ' ', '\t', '\n' }, StringSplitOptions.RemoveEmptyEntries)) : "") + "  line " + transition["line"]);
                    }
                    foreach (var warning in Maps(machine, "warnings")) answer.Detail("  [WARN] line " + warning["line"] + ": " + Text(warning, "text"));
                    if (machine.ContainsKey("mermaid")) answer.Detail(Text(machine, "mermaid"));
                }
            foreach (var item in failed) answer.Detail("[ERROR] " + Text(item, "label") + ": " + Text(item, "error"));
            return answer;
        }

        static CliFailure Failure(string message) => new CliFailure("fsm", "refused", message, "cts fsm --help", 1);
    }
}
