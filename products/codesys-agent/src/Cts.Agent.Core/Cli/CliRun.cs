using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;
using Cts.Sync;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // One run of a command cts.exe serves: pick the agent, call it, print the
    // answer in the asked form, return the exit code.
    public static class CliRun
    {
        const double DefaultTimeoutS = 30;
        // The detail lines under a verdict: the actionable ones, not a report.
        const int MaxDetailLines = 20;

        public static int Run(CliCommand command, IList<string> args, IAgentHost host, string ctsTarget, string workFolder, TextWriter output, TextWriter error)
        {
            if (command == null) return NoCommand(args, output, error);
            var format = "short";
            try
            {
                var options = CliOptions.Parse(args, ctsTarget, command);
                format = options.Output;
                if (options.Help)
                {
                    output.WriteLine(Help(command));
                    return 0;
                }
                if (command.Discover != null)
                {
                    if (args.Any(a => a == "agent") && CliOptions.WordAfterCommand(args) != "list")
                        throw new CliFailure("agent", "usage", "expected list", "cts agent list --help", 2);
                    return PrintDiscovery(command, command.Discover(host, options), format, output, error);
                }
                if (command.LocalExecute != null && (command.LocalWhen == null || command.LocalWhen(options)))
                {
                    options.Progress = error;
                    var data = command.LocalExecute(options, host, workFolder);
                    if (data.TryGetValue("raw_body", out var rawBody))
                    {
                        output.WriteLine(Convert.ToString(rawBody));
                        return command.Build(data).ExitCode ?? 0;
                    }
                    var answer = command.Build(data);
                    if (format == "json") output.WriteLine(Json.Pretty(data));
                    else if (format == "text") { output.WriteLine("── " + command.Words + " ──"); Dump(data, 0, output); }
                    else
                    {
                        output.WriteLine(Verdict.Line(answer.Status, command.Verb, answer.Pairs));
                        foreach (var line in answer.Details) output.WriteLine(line);
                    }
                    return answer.ExitCode ?? (answer.Status == Verdict.Ok ? 0 : 1);
                }
                var picked = AgentChoice.Pick(host, command.Verb, options.TargetPid(), options.ExpectProject, workFolder);
                using (var conn = picked.Key)
                {
                    var hello = picked.Value;
                    ReportOtherBuild(hello, error);
                    ReportUserChanges(conn, hello, error);
                    ReportOtherFolder(options, hello, workFolder, error);
                    var data = Execute(command, options, conn, host, hello, error);
                    if (data.TryGetValue("info", out var info) && info is IEnumerable<string> lines)
                        foreach (var line in lines) error.WriteLine("[INFO] " + line);
                    data.Remove("info");
                    if (data.ContainsKey("raw_body"))
                    {
                        output.Write(Convert.ToString(data["raw_body"]));
                        if (!Convert.ToString(data["raw_body"]).EndsWith("\n", StringComparison.Ordinal)) output.WriteLine();
                        return 0;
                    }
                    return Print(command, data, AgentChoice.Settled(conn, hello), format, output);
                }
            }
            catch (CliFailure f)
            {
                if (format == "json")
                {
                    var answer = new Dictionary<string, object> { { "ok", false }, { "command", f.CommandName }, { "error", f.Cause }, { "message", f.Message } };
                    if (f.Next != null) answer["next"] = f.Next;
                    output.WriteLine(Json.Pretty(answer));
                }
                else if (format == "short")
                    output.WriteLine(Verdict.ErrorLine(f.CommandName, f.Cause, f.Next));
                error.WriteLine("[ERROR] " + f.Message);
                if (f.Note != null) error.WriteLine(f.Note);
                return f.ExitCode;
            }
            // A failure no command foresaw still ends in the error line, not a
            // crash: a caller reading the verdict learns it failed, and where.
            catch (Exception e) when (!(e is OutOfMemoryException))
            {
                var verb = command.Verb;
                if (format == "json")
                    output.WriteLine(Json.Pretty(new Dictionary<string, object> { { "ok", false }, { "command", verb }, { "error", "internal" }, { "message", e.Message } }));
                else if (format == "short")
                    output.WriteLine(Verdict.ErrorLine(verb, "internal", null));
                var frame = (e.StackTrace ?? "").Split('\n').Select(line => line.Trim()).FirstOrDefault(line => line.Length > 0);
                error.WriteLine("[ERROR] " + e.Message + " (" + e.GetType().Name + (frame == null ? "" : " " + frame) + ")");
                if (WritesIde(command))
                    error.WriteLine("It stopped part way: the IDE may hold some of its changes, unsaved, and the sync folder some of its files. cts compare shows where the IDE and the folder stand.");
                return 1;
            }
        }

        // The command's answer from the agent on *conn*, within its budget and
        // its folder's lock; cts verify runs several on one connection.
        internal static IDictionary<string, object> Execute(CliCommand command, CliOptions options, AgentConnection conn, IAgentHost host, Hello hello,
            TextWriter error)
        {
            var seconds = options.Timeout
                ?? (command.TimeoutKey == null ? command.Seconds : hello.TimeoutFor(command.TimeoutKey) ?? DefaultTimeoutS);
            var call = new CliCall(conn, host, command, options, hello, seconds);
            using (AcquireFolderLock(command, options, hello, error))
            {
                IDictionary<string, object> data;
                try { data = command.Execute(call); }
                catch (CliFailure failure) when (call.Seen.Count > 0)
                {
                    // A dialog the failure itself names is not repeated.
                    var named = failure.Message + "\n" + failure.Note;
                    var unnamed = call.Seen.Where(window => !named.Contains(window.Fingerprint));
                    failure.Note = string.Join("\n", new[] { failure.Note }.Concat(SeenLines(unnamed)).Where(line => !string.IsNullOrEmpty(line)));
                    throw;
                }
                if (call.Seen.Count == 0) return data;
                return new Dictionary<string, object>(data) { ["dialogs_seen"] = call.Seen.Select(window => (object)window.ToData()).ToList() };
            }
        }

        // One line per dialog the IDE showed while the command ran.
        static IEnumerable<string> SeenLines(IEnumerable<ModalWindow> windows) => windows.Select(window => "dialog seen meanwhile " + window.Snapshot());

        // An agent of another build than this cts.exe: what one of them has
        // the other may lack, so a command can fail for no reason it names.
        static void ReportOtherBuild(Hello hello, TextWriter error)
        {
            var agent = Value(hello.Data, "agent_version") as string;
            if (agent == null || agent == Build()) return;
            var scriptDir = Value(hello.Data, "script_dir") as string;
            error.WriteLine("[WARN] The IDE's agent is " + agent + (scriptDir == null ? "" : " from the ScriptDir " + scriptDir) + ", this cts is " + Build()
                + ": close CODESYS and run `cts install" + (scriptDir == null ? "" : " --script-dir \"" + scriptDir + "\"")
                + "` from the cts you use, so both are one build.");
        }

        // A command run in another sync folder still works on the IDE's
        // project and its folder: said, so a copy's shell does not act on the
        // original unawares.
        static void ReportOtherFolder(CliOptions options, Hello hello, string workFolder, TextWriter error)
        {
            if (options.Params.ContainsKey("sync_folder")) return;
            var here = ProjectInfo.OtherSyncFolder(workFolder, hello.SyncFolder);
            if (here != "")
                error.WriteLine("[WARN] This command works on " + hello.SyncFolder + ", the sync folder of the project ide-" + hello.Pid
                    + " has open, not on " + here + " around the current folder. When that IDE holds a copy of the project, "
                    + "`cts set-sync-folder " + here + " --new-id` gives the copy that folder; another IDE is chosen with --target.");
        }

        // What the IDE changed outside cts since the last cts command (the
        // agent's journal empties on take), so the caller does not act on a
        // picture the user has since edited.
        internal static void ReportUserChanges(AgentConnection conn, Hello hello, TextWriter error)
        {
            if (!(Value(hello.Data, "user_changes") is long count && count > 0)) return;
            object answer;
            try { answer = conn.Call("journal.take", null, 3000); }
            catch (AgentException) { return; }
            var named = (Value(answer as IDictionary<string, object>, "changes") as IList<object> ?? new List<object>())
                .OfType<IDictionary<string, object>>()
                .Select(change => (Value(change, "name") ?? Value(change, "guid")) + " ("
                    + string.Join("/", (Value(change, "kinds") as IList<object> ?? new List<object>()).Select(Convert.ToString)) + ")")
                .ToList();
            if (named.Count > 0)
                error.WriteLine("[INFO] The IDE changed outside cts since the last cts command: " + string.Join(", ", named)
                    + ". cts sync carries text changes to disk.");
        }

        // The commands that write the open project and the sync folder, so a
        // failure part way can leave some of their changes in either.
        static bool WritesIde(CliCommand command)
            => command.Name == "import" || command.Name == "sync" || command.Name == "checkout"
                || command.Name == "project" && command.Sub == "update";

        // The commands that read or write a sync folder's work tree, base or
        // refs/cts run one at a time per folder; null for any other command.
        static FolderLock AcquireFolderLock(CliCommand command, CliOptions options, Hello hello, TextWriter error)
        {
            if (command.Name != "compare" && command.Name != "export" && command.Name != "import" && command.Name != "sync" && command.Name != "commit" && command.Name != "checkout" && command.Name != "download" && !(command.Name == "project" && command.Sub == "update")) return null;
            var folder = options.Params.ContainsKey("sync_folder") ? Convert.ToString(options.Params["sync_folder"]) : hello.SyncFolder;
            if (string.IsNullOrWhiteSpace(folder)) return null;
            try { return FolderLock.Acquire(folder, error, TimeSpan.FromSeconds(120)); }
            catch (InvalidOperationException failure)
            {
                throw new CliFailure(command.Verb, "refused", failure.Message, "cts " + command.Words + " --help", 1);
            }
        }

        static int PrintDiscovery(CliCommand command, IList<IDictionary<string, object>> entries, string format, TextWriter output, TextWriter error)
        {
            var answered = entries.Where(e => !e.ContainsKey("error")).ToList();
            if (format == "json") output.WriteLine(Json.Pretty(entries));
            else
            {
                var details = new List<string>();
                foreach (var entry in entries)
                {
                    var pid = Convert.ToString(Value(entry, "pid"), CultureInfo.InvariantCulture) ?? "?";
                    if (entry.TryGetValue("error", out var err) && err is IDictionary<string, object> failure)
                        details.Add("ide-" + pid + "  unreachable: " + Value(failure, "code") + ": " + Value(failure, "message"));
                    else
                    {
                        var project = Value(entry, "project") as IDictionary<string, object>;
                        var path = Value(project, "path") as string;
                        var where = path ?? (Equals(Value(entry, "ui_busy"), true) ? "(UI busy, project unknown)" : "(no project)");
                        details.Add("ide-" + pid + "  " + (Value(entry, "product") ?? "?") + " " + (Value(entry, "product_version") ?? "?")
                            + "  agent " + (Value(entry, "agent_version") ?? "?") + "  protocol " + (Value(entry, "protocol") ?? "?") + "  " + where);
                        foreach (var window in Dialogs.Of(entry, "dialogs"))
                            details.Add("ide-" + pid + "  blocked by a dialog " + window.Snapshot() + "\nNext: "
                                + DialogWatch.AnswerLine(window) + (entries.Count > 1 ? " --target ide-" + pid : ""));
                    }
                }
                if (entries.Count > 0)
                {
                    output.WriteLine(Verdict.Line(answered.Count == 0 ? Verdict.Error : Verdict.Ok, command.Verb,
                        new[] { Verdict.Pair("agents", entries.Count), Verdict.Pair("answered", answered.Count) }));
                    foreach (var detail in details) output.WriteLine(detail);
                }
                if (entries.Count == 0) error.WriteLine("No in-IDE agent found (no cts-agent-* pipe).");
            }
            if (entries.Count == 0) return 2;
            return answered.Count == 0 ? 1 : 0;
        }

        // Prints the answer; the exit code is 1 for a partial or failed one.
        static int Print(CliCommand command, IDictionary<string, object> data, Hello hello, string format, TextWriter output)
        {
            var answer = command.Build(data);
            if (format == "json")
            {
                var payload = new Dictionary<string, object>(data) { ["instance"] = Instance(hello) };
                if (answer.Status == Verdict.Error)
                {
                    payload["ok"] = false;
                    payload["command"] = command.Verb;
                    var cause = Value(data, "cause") ?? answer.Pairs.FirstOrDefault(p => p.Key == "cause").Value;
                    payload["error"] = cause ?? "command failed";
                }
                output.WriteLine(Json.Pretty(payload));
            }
            else
            {
                if (format == "text")
                {
                    output.WriteLine("── " + command.Words + " ──");
                    Dump(data, 0, output);
                }
                else
                {
                    output.WriteLine(Verdict.Line(answer.Status, command.Verb, answer.Pairs));
                    var shown = answer.Uncapped ? answer.Details.Count : MaxDetailLines;
                    foreach (var line in answer.Details.Take(shown)) output.WriteLine(line);
                    if (answer.Details.Count > shown) output.WriteLine("... and " + (answer.Details.Count - shown) + " more");
                    foreach (var line in SeenLines(Dialogs.Of(data, "dialogs_seen"))) output.WriteLine(line);
                }
                output.WriteLine("ide-" + hello.Pid + " · " + (hello.ProjectName ?? (hello.UiBusy ? "project not read: the IDE was busy" : "no project")));
            }
            return answer.ExitCode ?? (answer.Status == Verdict.Ok ? 0 : 1);
        }

        static Dictionary<string, object> Instance(Hello hello)
        {
            var instance = new Dictionary<string, object> { { "id", "ide-" + hello.Pid } };
            if (hello.ProjectPath != null)
                instance["project"] = new Dictionary<string, object> { { "name", hello.ProjectName }, { "path", hello.ProjectPath } };
            return instance;
        }

        // The readable form: `key: value`, nested blocks indented.
        static void Dump(IDictionary<string, object> data, int depth, TextWriter output)
        {
            foreach (var item in data)
            {
                var pad = new string(' ', 2 * depth);
                if (item.Value is IDictionary<string, object> nested)
                {
                    output.WriteLine(pad + item.Key + ":");
                    Dump(nested, depth + 1, output);
                }
                else if (item.Value is IList list && !(item.Value is string))
                {
                    output.WriteLine(pad + item.Key + ":");
                    foreach (var element in list) output.WriteLine(pad + "  - " + Scalar(element));
                }
                else output.WriteLine(pad + item.Key + ": " + Scalar(item.Value));
            }
        }

        static string Scalar(object value)
        {
            if (value == null) return "null";
            if (value is bool b) return b ? "true" : "false";
            if (value is string s) return s;
            if (value is IDictionary || value is IList) return Json.Serialize(value);
            return Convert.ToString(value, CultureInfo.InvariantCulture);
        }

        public static string Help(CliCommand command)
        {
            var timeout = command.TimeoutKey == null
                ? "Timeout in seconds (default: " + command.Seconds.ToString(CultureInfo.InvariantCulture) + ")"
                : "Timeout in seconds (default: sized by the in-IDE agent)";
            var optionRows = command.Options
                .Select(o => new { Key = o.Metavar == null ? o.Flag : o.Flag + " " + o.Metavar, o.Help, o.Required }).ToList();
            // Only asking agents has a budget: a command that never does
            // (analyze, config, git, visu) has no --timeout.
            var asks = command.Execute != null || command.Discover != null;
            var timeoutRows = new[] { new { Key = "--timeout SECONDS", Help = timeout, Required = false } }.Take(asks ? 1 : 0).ToList();
            var rows = optionRows
                .Concat(command.ArgumentHelp == null
                    ? new[] { new { Key = "", Help = "", Required = false } }.Take(0)
                    : new[] { new { Key = command.Arguments.Trim('[', ']'), Help = command.ArgumentHelp, Required = false } })
                .Concat(timeoutRows)
                .Concat(new[] { new { Key = "-h, --help", Help = "show this help message and exit", Required = false } }).ToList();
            var width = rows.Max(r => r.Key.Length) + 2;
            var usage = string.Concat(optionRows.Concat(timeoutRows).Select(r => r.Required ? " " + r.Key : " [" + r.Key + "]"));
            return "usage: cts " + command.Words + (command.Arguments == null ? "" : " " + command.Arguments) + usage + "\n\n"
                + command.Summary + ".\n\n" + Wrap(command.Description, HelpWidth) + "\n\n"
                + "options:\n"
                + string.Concat(rows.Select(r => "  " + r.Key.PadRight(width)
                    + Wrap(r.Help, HelpWidth - 2 - width).Replace("\n", "\n" + new string(' ', 2 + width)) + "\n")) + "\n"
                + "The global flags --json, --pretty/-p, --output {short,json,text}, --target and\n"
                + "--expect-project work before or after the command.";
        }

        const int HelpWidth = 100;

        // Paragraphs wrapped at *width*; an indented line (an example, a sample
        // of output) stays as written.
        static string Wrap(string text, int width)
        {
            var lines = new List<string>();
            foreach (var paragraph in text.Split('\n'))
            {
                if (paragraph.StartsWith("  ", StringComparison.Ordinal)) { lines.Add(paragraph); continue; }
                var line = "";
                foreach (var word in paragraph.Split(' '))
                {
                    if (line.Length > 0 && line.Length + 1 + word.Length > width) { lines.Add(line); line = word; }
                    else line = line.Length == 0 ? word : line + " " + word;
                }
                lines.Add(line);
            }
            return string.Join("\n", lines);
        }

        // A command line that names no command cts serves: `cts --help`,
        // `cts --version`, or a word that is no command.
        static int NoCommand(IList<string> args, TextWriter output, TextWriter error)
        {
            var name = CliOptions.CommandOf(args);
            if (name == "agent")
            {
                error.WriteLine("usage: cts agent list [--timeout SECONDS] [--json]");
                return 2;
            }
            var group = CliCommands.All.Where(c => c.Name == name && c.Sub != null).ToList();
            if (group.Count > 0)
            {
                var word = CliOptions.WordAfterCommand(args);
                var width = group.Max(c => c.Words.Length) + 2;
                var help = "usage: cts " + name + " SUBCOMMAND [options]   (cts " + name + " SUBCOMMAND --help: its options)\n\n"
                    + string.Join("\n", group.Select(c => "  " + c.Words.PadRight(width) + c.Summary));
                if (args.Any(a => a == "-h" || a == "--help"))
                {
                    output.WriteLine(help);
                    return 0;
                }
                error.WriteLine((word == null ? "[ERROR] cts " + name + " needs a subcommand." : "[ERROR] unknown subcommand '" + name + " " + word + "'.") + "\n" + help);
                return 2;
            }
            if (name != null)
            {
                var meant = CliCommands.All.Where(c => c.Sub == name).Select(c => "`cts " + c.Words + "`").ToList();
                error.WriteLine("[ERROR] unknown command '" + name + "'. "
                    + (meant.Count > 0 ? "Did you mean " + string.Join(" or ", meant) + "? " : "") + "`cts --help` lists the commands.");
                return 2;
            }
            if (args.Contains("--version"))
            {
                output.WriteLine("cts " + Build());
                return 0;
            }
            output.WriteLine(TopHelp());
            return args.Count == 0 || args.Any(a => a == "-h" || a == "--help") ? 0 : 2;
        }

        // `cts`, `cts --help`: the commands, the global options and how the
        // pieces fit (Cli/TopHelp.txt).
        public static string TopHelp()
        {
            var width = CliCommands.All.Max(c => c.Words.Length) + 2;
            string rest;
            using (var stream = typeof(CliRun).Assembly.GetManifestResourceStream("Cts.Cli.TopHelp.txt"))
            using (var reader = new StreamReader(stream, Encoding.UTF8)) rest = reader.ReadToEnd().Replace("\r\n", "\n");
            return "usage: cts [global options] COMMAND [options]\n\n"
                + "CODESYS text sync CLI. Talks to the agent that cds-text-sync.py starts in CODESYS\n"
                + "(Tools > Scripting > Scripts > C > cds-text-sync).\n\n"
                + "Start here:\n"
                + "  cts status    what CODESYS has open, the PLC state, unsaved changes, the folder's git state\n"
                + "  cts guide     the operating rules and the command reference (agents: read it first)\n"
                + "  cts compare   what differs between the folder and the IDE\n"
                + "  cts verify    whether the project is shippable: one verdict, read-only\n\n"
                + string.Join("\n\n", HelpGroups().Select(group => group.Key + ":\n"
                    + string.Join("\n", group.Value.Select(c => "  " + c.Words.PadRight(width) + c.Summary)))) + "\n\n"
                + rest.TrimEnd('\n');
        }

        // The commands of `cts --help` by what they are for; a command no
        // group names lands in "other commands".
        static readonly KeyValuePair<string, string[]>[] Groups =
        {
            Group("IDE and its state", "ping", "status", "agent list", "dialog", "dialog answer", "read-log", "permissions", "project new", "project open", "project close", "project list"),
            Group("folder and IDE", "export", "compare", "import", "sync", "save", "set-sync-folder", "new", "fmt", "tool"),
            Group("git", "branch", "checkout", "commit", "merge", "push", "log", "project update", "open", "hook"),
            Group("project", "project-tree", "read-object", "project list-devices", "project device-types", "project change-device", "project simulate", "project set-credentials", "lib", "lib set", "lib add", "lib redirect", "lib remove"),
            Group("PLC trend (cts guide trend)", "trend", "trend set", "trend on", "trend off", "trend pull", "trend query"),
            Group("build and PLC", "build", "verify", "test", "scan", "connect", "download", "disconnect", "start", "stop", "reset", "boot-app", "wait-ready", "plc-log", "plc-crc", "plc-crc-headless",
                "plc info", "plc ls", "plc get", "plc put", "plc rm", "plc mkdir", "plc mv"),
            Group("variables", "read", "write", "snapshooter tree", "snapshooter take", "snapshooter diff", "snapshooter restore"),
            Group("analysis and documentation", "analyze", "analyze rules", "analyze explain", "analyze baseline", "analyze triage", "fsm", "docs", "diagram classes", "diagram calls", "diagram view"),
            Group("HMI screens (cts guide visu-svg)", "visu new", "visu lint", "visu bind", "visu preview", "visu from-svg", "visu to-svg", "visu create-screen", "visu add",
                "visu list", "visu describe", "visu check", "visu types", "visu capture-frame"),
            Group("setup and reference", "guide", "install", "diag", "config show", "config set", "config unset", "raw"),
        };

        static KeyValuePair<string, string[]> Group(string title, params string[] words) => new KeyValuePair<string, string[]>(title, words);

        internal static List<KeyValuePair<string, List<CliCommand>>> HelpGroups()
        {
            var byWords = CliCommands.All.ToDictionary(c => c.Words);
            var groups = Groups.Select(group => new KeyValuePair<string, List<CliCommand>>(group.Key,
                group.Value.Where(byWords.ContainsKey).Select(words => byWords[words]).ToList())).ToList();
            var named = new HashSet<string>(Groups.SelectMany(group => group.Value));
            var other = CliCommands.All.Where(c => !named.Contains(c.Words)).ToList();
            if (other.Count > 0) groups.Add(new KeyValuePair<string, List<CliCommand>>("other commands", other));
            return groups;
        }

        // The release (Directory.Build.props) and the commit it was built
        // from: `cts --version` says it, the agent's hello carries it.
        public static string Build()
        {
            var assembly = typeof(CliRun).Assembly;
            var info = (System.Reflection.AssemblyInformationalVersionAttribute)Attribute.GetCustomAttribute(
                assembly, typeof(System.Reflection.AssemblyInformationalVersionAttribute));
            return FormatVersion(info?.InformationalVersion ?? assembly.GetName().Version.ToString(3));
        }

        // "4.0.0-beta.1+<sha>" is "4.0.0-beta.1 (commit <8 of sha>)": a pre-release keeps its suffix.
        internal static string FormatVersion(string informationalVersion)
        {
            var plus = informationalVersion.IndexOf('+');
            if (plus < 0) return informationalVersion;
            var commit = informationalVersion.Substring(plus + 1);
            var version = informationalVersion.Substring(0, plus);
            return commit.Length < 8 ? version : version + " (commit " + commit.Substring(0, 8) + ")";
        }
    }
}
