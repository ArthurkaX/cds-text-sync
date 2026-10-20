using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    public static partial class CliCommands
    {
        const string StillOpen = "the dialog did not close: it is still on screen. Nothing else will run until it is answered.";
        const string Covered = "the press opened another dialog on top of this one: answer that one first (the first id below), then this one if it stays.";

        public static readonly IList<CliCommand> All = BuildAll();

        static IList<CliCommand> BuildAll()
        {
            var commands = new List<CliCommand>
            {
            new CliCommand
            {
                Name = "raw",
                Arguments = "METHOD [--key value ...]",
                ArgumentLimit = 1,
                Summary = "Send an agent method directly",
                Description = "Debug escape hatch. Values that parse as JSON are sent as JSON; other values are strings. The agent's result is printed as JSON. Without METHOD, lists the methods the agent serves.",
                Seconds = 15,
                Execute = RawCommand.Execute,
                Build = RawCommand.Build,
            },
            new CliCommand
            {
                Name = "guide",
                Arguments = "[TOPIC]",
                ArgumentLimit = 1,
                Summary = "Read the operating rules and topic guides",
                Description = "Offline reference bundled into cts.exe. Bare `cts guide` lists the common jobs as command sequences, the safety rules and the topics; bare `cts guide TOPIC` prints a guide (a long one, its opening and a map of its sections: `--section TITLE` prints one, `--all` the whole); `--file NAME` reads a topic's bundled example or companion file. Use --json for the full machine payload. Topics: " + LocalCommands.TopicNames() + ".",
                Options = new[]
                {
                    CliOption.Text("--file", "file", "NAME", "Read one file shipped with the topic"),
                    CliOption.Text("--section", "section", "TITLE", "Print one section (its title, or a unique part of it) with its subsections"),
                    CliOption.Switch("--all", "all", "Print a long guide whole instead of its opening and its map of sections"),
                },
                LocalExecute = (options, host, work) => LocalCommands.Guide(options),
                Build = LocalCommands.GuideLine,
            },
            new CliCommand
            {
                Name = "config",
                Sub = "show",
                Summary = "Show the quick window key and where it comes from",
                Description = "The one setting is quick_key, the chord that opens the quick window: Alt+Q, or the user's own in defaults.json. The export's format has no settings. This is offline and does not need the IDE.",
                LocalExecute = (options, host, work) => LocalCommands.ConfigShow(),
                Build = LocalCommands.ConfigLine,
            },
            new CliCommand
            {
                Name = "new",
                Arguments = "KIND NAME",
                ArgumentLimit = 2,
                Summary = "Create a textual object in the project view, offline",
                Description = "Create a GVL, POU, DUT, or POU member in the sync folder's export view. This writes one .st file and does not need the IDE; cts import then creates it in the IDE. KIND is gvl, pou, dut, method, action or property: a POU takes --kind program|function|function-block, a DUT --kind struct|union|enum|alias. Members are named <POU>.<Member>. The object goes into the Application folder unless --parent names another folder; --parent . puts it at the project root, the POUs view, where code every application shares lives (the code a test application tests, cts guide tests).\n\n"
                    + "  cts new pou F_Lerp --kind function --return-type REAL --parent . --text \"VAR_INPUT a, b, t : REAL; END_VAR F_Lerp := a + (b - a) * t;\"\n"
                    + "  cts new gvl GVL_Io --text \"xStart : BOOL;\"",
                Options = NewObjectCommand.Options,
                LocalExecute = (options, host, work) => NewObjectCommand.Execute(options, work),
                Build = NewObjectCommand.Build,
            },
            new CliCommand
            {
                Name = "config",
                Sub = "set",
                Arguments = "KEY VALUE",
                ArgumentLimit = 2,
                Summary = "Choose the quick window key",
                Description = "cts config set quick_key Ctrl+Shift+Q stores the chord in this user's defaults.json, for every project: modifiers Ctrl, Alt and Shift, then a letter, a digit or F1-F12.",
                LocalExecute = (options, host, work) => LocalCommands.ConfigChange(options, false),
                Build = LocalCommands.ChangeLine,
            },
            new CliCommand
            {
                Name = "config",
                Sub = "unset",
                Arguments = "KEY",
                ArgumentLimit = 1,
                Summary = "Go back to the default quick window key",
                Description = "cts config unset quick_key removes the chord from this user's defaults.json: Alt+Q opens the quick window again.",
                LocalExecute = (options, host, work) => LocalCommands.ConfigChange(options, true),
                Build = LocalCommands.ChangeLine,
            },
            GitCommands.Branch,
            GitCommands.Log,
            GitCommands.Push,
            MergeCommand.Command,
            CommitCommand.Command,
            CheckoutCommand.Command,
            FsmCommand.Command,
            VerifyCommand.Command,
            ProjectUpdateCommand.Command,
            ProjectOpenCommand.Command,
            InstallCommand.Command,
            ToolCommand.Command,
            TeamGuard.Command,
            OpenCommand.Command,
            ReadCommand.Command,
            BuildCommand.Command,
            };
            commands.AddRange(SyncCommands);
            commands.AddRange(OnlineCommands);
            commands.AddRange(ProjectCommands);
            foreach (var command in SnapshooterCommand.Commands) commands.Add(command);
            foreach (var command in AnalyzeCommand.Commands) commands.Add(command);
            foreach (var command in VisuScreenCommands.Commands) commands.Add(command);
            foreach (var command in VisuSketchCommands.Commands) commands.Add(command);
            foreach (var command in VisuRenderCommands.Commands) commands.Add(command);
            foreach (var command in PlcCommand.Commands) commands.Add(command);
            commands.Add(DocsCommand.Command);
            commands.AddRange(LibCommand.Commands);
            return commands;
        }

        static Answer Devices(IDictionary<string, object> data)
        {
            var devices = Items(data, "devices").OfType<IDictionary<string, object>>().ToList();
            var apps = devices.SelectMany(device => Items(device, "applications").OfType<IDictionary<string, object>>()).ToList();
            var answer = new Answer().Add("devices", devices.Count).Add("online", apps.Count(app => Equals(Value(app, "online"), true)));
            foreach (var device in devices)
            {
                var words = new List<string> { Convert.ToString(Value(device, "path") ?? Value(device, "name"), CultureInfo.InvariantCulture) ?? "" };
                if (Value(device, "description") is IDictionary<string, object> description)
                    words.Add("[" + Value(description, "type") + " \"" + Value(description, "id") + "\" " + Value(description, "version") + "]");
                if (Equals(Value(device, "simulation"), true)) words.Add("simulation");
                foreach (var app in Items(device, "applications").OfType<IDictionary<string, object>>())
                {
                    var state = Equals(Value(app, "online"), true) ? Value(app, "application_state") : "offline";
                    words.Add((Convert.ToString(Value(app, "name"), CultureInfo.InvariantCulture) ?? "?") + (Equals(Value(app, "active"), true) ? "*" : "") + "=" + (Convert.ToString(state, CultureInfo.InvariantCulture) ?? "?"));
                }
                answer.Detail(string.Join(" ", words));
            }
            return answer;
        }

        // The command a command line runs, or null: `dialog answer` when the
        // word after `dialog` names its subcommand.
        public static CliCommand Find(IList<string> args)
        {
            var name = CliOptions.CommandOf(args);
            var word = CliOptions.WordAfterCommand(args);
            return All.FirstOrDefault(c => c.Name == name && c.Sub != null && c.Sub == word)
                ?? All.FirstOrDefault(c => c.Name == name && c.Sub == null);
        }

        // A command that is one agent call with the options as its parameters.
        static Func<CliCall, IDictionary<string, object>> Agent(string method)
        {
            return call => call.Call(method, call.Options.Params);
        }

        // The online commands share one line: what happened, to which
        // application, and the state it is in now.
        static Answer Plc(IDictionary<string, object> data)
        {
            return new Answer()
                .Add("state", Value(data, "state"))
                .Add("kind", Value(data, "kind"))
                .Add("application", Value(data, "application"))
                .Add("application_state", Value(data, "application_state"))
                .Add("changed", Value(data, "changed"))
                .Add("was_connected", Value(data, "was_connected"))
                .Detail(Value(data, "note"))
                .Detail(Value(data, "application_state_error"));
        }

        // What a dialog answer did, one line.
        static string Answered(IDictionary<string, object> data)
        {
            var parts = new List<string>
            {
                "answered [id " + Value(data, "id") + "]",
                "pressed [" + Value(data, "pressed") + "] (" + Value(data, "via") + ")",
            };
            var chosen = Items(data, "chosen").ToList();
            if (chosen.Count > 0) parts.Add("chose: " + string.Join(", ", chosen));
            var cleared = Items(data, "unchecked").ToList();
            if (cleared.Count > 0) parts.Add("cleared: " + string.Join(", ", cleared));
            var after = Convert.ToDouble(Value(data, "closed_after_s") ?? 0.0, CultureInfo.InvariantCulture).ToString("0.###", CultureInfo.InvariantCulture);
            parts.Add(Equals(Value(data, "closed"), true) ? "the dialog closed after " + after + " s"
                : Equals(Value(data, "covered"), true) ? "another dialog opened on top after " + after + " s"
                : "the dialog is STILL OPEN after " + after + " s");
            return string.Join("  ", parts);
        }

        // "PATH  (N objects)" for each object under *node* that holds others; a
        // path uses the object's own name, as --folder and project-view do.
        static IEnumerable<string> Containers(IDictionary<string, object> node, string path)
        {
            foreach (var child in Items(node, "children").OfType<IDictionary<string, object>>())
            {
                var name = Value(child, "object_name") as string ?? Value(child, "name") as string ?? "";
                var childPath = path.Length == 0 ? name : path + "/" + name;
                if (!Items(child, "children").Any()) continue;
                var below = Below(child);
                yield return childPath + "  (" + below + (below == 1 ? " object)" : " objects)");
                foreach (var line in Containers(child, childPath)) yield return line;
            }
        }

        static int Below(IDictionary<string, object> node)
            => Items(node, "children").OfType<IDictionary<string, object>>().Sum(child => 1 + Below(child));

        static int Count(object value)
        {
            return value is System.Collections.ICollection items ? items.Count : 0;
        }
    }
}
