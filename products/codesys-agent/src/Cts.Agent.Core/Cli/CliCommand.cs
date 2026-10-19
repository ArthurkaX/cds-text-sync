using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading.Tasks;
using Cts.Agent;

namespace Cts.Cli
{
    // What a command answers under its verdict line: the line's pairs and the
    // detail lines worth showing; a partial or failed answer exits 1.
    public sealed class Answer
    {
        public string Status { get; private set; } = Verdict.Ok;
        public List<KeyValuePair<string, object>> Pairs { get; } = new List<KeyValuePair<string, object>>();
        public List<string> Details { get; } = new List<string>();
        // Every detail line is shown, not the first few: the lines are what
        // the command was asked for (a log's tail).
        public bool Uncapped { get; private set; }
        public int? ExitCode { get; private set; }

        public Answer Add(string key, object value)
        {
            Pairs.Add(Verdict.Pair(key, value));
            return this;
        }

        public Answer Detail(object line)
        {
            var text = Convert.ToString(line, CultureInfo.InvariantCulture);
            if (!string.IsNullOrEmpty(text)) Details.Add(text);
            return this;
        }

        public Answer Partial()
        {
            Status = Verdict.Partial;
            return this;
        }

        public Answer Whole()
        {
            Uncapped = true;
            return this;
        }

        public Answer Failed()
        {
            Status = Verdict.Error;
            return this;
        }

        public Answer WithExitCode(int code)
        {
            ExitCode = code;
            return this;
        }
    }

    // One option of a command: a switch (no metavar), or a value the agent's
    // parameter *Key* takes -- a whole number, one of *Choices*, text, or a
    // list of texts when it repeats.
    public sealed class CliOption
    {
        public string Flag { get; private set; }
        public string Key { get; private set; }
        public string Metavar { get; private set; }
        public string Help { get; private set; }
        public IList<string> Choices { get; private set; }
        public bool Number { get; private set; }
        public bool Repeats { get; private set; }
        public bool Required { get; private set; }

        CliOption(string flag, string key, string metavar, string help)
        {
            Flag = flag;
            Key = key;
            Metavar = metavar;
            Help = help;
        }

        public static CliOption Switch(string flag, string key, string help) => new CliOption(flag, key, null, help);

        public static CliOption Int(string flag, string key, string help) => new CliOption(flag, key, "N", help) { Number = true };

        public static CliOption Text(string flag, string key, string metavar, string help) => new CliOption(flag, key, metavar, help);

        public static CliOption Many(string flag, string key, string metavar, string help) => new CliOption(flag, key, metavar, help) { Repeats = true };

        public static CliOption Needed(string flag, string key, string metavar, string help) => new CliOption(flag, key, metavar, help) { Required = true };

        public static CliOption Choice(string flag, string key, string help, params string[] choices)
            => new CliOption(flag, key, "{" + string.Join(",", choices) + "}", help) { Choices = choices };
    }

    // One cts command: what it asks the agent, and the line its answer makes.
    public sealed class CliCommand
    {
        public string Name { get; internal set; }
        // The word after the name a subcommand needs (`dialog answer`), or null.
        public string Sub { get; internal set; }
        public string Summary { get; internal set; }
        public string Description { get; internal set; }
        // The key of the hello's timeout_profile that sizes the command, or
        // null for a fixed Seconds.
        public string TimeoutKey { get; internal set; }
        public double Seconds { get; internal set; } = 30;
        public IList<CliOption> Options { get; internal set; } = new CliOption[0];
        // The words after the name the command takes (`NAME VALUE [NAME VALUE ...]`
        // for its usage line), or null: then a word is an error.
        public string Arguments { get; internal set; }
        public string ArgumentHelp { get; internal set; }
        public int ArgumentLimit { get; internal set; }
        public Func<CliCall, IDictionary<string, object>> Execute { get; internal set; }
        public Func<CliOptions, IAgentHost, string, IDictionary<string, object>> LocalExecute { get; internal set; }
        public Func<CliOptions, bool> LocalWhen { get; internal set; }
        // A machine-wide command discovers and answers all agents itself.
        public Func<IAgentHost, CliOptions, IList<IDictionary<string, object>>> Discover { get; internal set; }
        public Func<IDictionary<string, object>, Answer> Build { get; internal set; }

        // `dialog answer`: what a person types, and the verdict's word.
        public string Words => Sub == null ? Name : Name + " " + Sub;
        public string Verb => Sub == null ? Name : Name + "-" + Sub;
    }

    // One run of a command against the agent it picked: its options, its
    // budget, and the calls it makes.
    public sealed class CliCall
    {
        readonly AgentConnection _conn;
        readonly IAgentHost _host;
        readonly Func<string, IDictionary<string, object>, IDictionary<string, object>> _callOverride;

        internal CliCall(AgentConnection conn, IAgentHost host, CliCommand command, CliOptions options, Hello hello, double seconds)
        {
            _conn = conn;
            _host = host;
            Command = command;
            Options = options;
            Hello = hello;
            Seconds = seconds;
        }

        internal CliCall(CliCommand command, CliOptions options, Hello hello, double seconds, Func<string, IDictionary<string, object>, IDictionary<string, object>> call)
        {
            Command = command;
            Options = options;
            Hello = hello;
            Seconds = seconds;
            _callOverride = call;
        }

        public CliCommand Command { get; private set; }
        public CliOptions Options { get; private set; }
        public Hello Hello { get; private set; }
        public double Seconds { get; private set; }

        // One agent call within the command's budget; the agent waits as long
        // for the IDE to start it. A failure ends the command (CliFailure)
        // unless the caller goes on after a Declined one.
        public IDictionary<string, object> Call(string method, IDictionary<string, object> parameters)
        {
            return Call(method, parameters, Seconds);
        }

        // The same, within *seconds* of its own: one of many short calls.
        public IDictionary<string, object> Call(string method, IDictionary<string, object> parameters, double seconds)
        {
            var ms = (int)Math.Min(int.MaxValue, Math.Max(1, seconds * 1000));
            var request = new Dictionary<string, object>(parameters ?? new Dictionary<string, object>()) { ["start_timeout_ms"] = (long)ms };
            object result;
            try { result = _callOverride != null ? _callOverride(method, parameters) : Watched(method, request, ms); }
            catch (AgentException e) { throw Failure(method, e); }
            return result as IDictionary<string, object> ?? new Dictionary<string, object> { { "result", result } };
        }

        // The call, with the dialog watch beside it (DialogWatch). A dialog.*
        // call is about the dialogs on screen and bounds its own wait, so the
        // dialog still under the one it answers does not end it.
        object Watched(string method, IDictionary<string, object> request, int ms)
        {
            if (method.StartsWith("dialog.", StringComparison.Ordinal)) return _conn.Call(method, request, ms);
            var call = Task.Run(() => _conn.Call(method, request, ms));
            try { return DialogWatch.Await(call, Probe, method); }
            catch (AgentException e) when (e.Code == "dialog_opened")
            {
                _conn.Dispose();
                throw;
            }
        }

        // The dialogs on screen, asked over a connection of its own; none
        // when the agent does not answer.
        IReadOnlyList<ModalWindow> Probe()
        {
            try
            {
                using (var probe = _host.Open(Hello.Pid))
                    return Dialogs.Of(probe.Call("dialog.probe", null, ProbeMs) as IDictionary<string, object>, "dialogs");
            }
            catch (AgentException)
            {
                return new List<ModalWindow>();
            }
        }

        // A healthy agent answers dialog.probe from memory; a slow one must
        // not become the delay the watch is there to remove.
        const int ProbeMs = 600;

        // What the line names when a call failed, and the way out: busy never
        // ran (safe to retry), a dialog stopped it, a timeout or a dropped pipe
        // left the outcome unknown, any other code is the agent's own refusal.
        CliFailure Failure(string method, AgentException e)
        {
            var failure = Described(method, e);
            failure.Declined = !Unsettled.Contains(e.Code);
            return failure;
        }

        // The codes of a failure that is not the agent's refusal of the call.
        static readonly HashSet<string> Unsettled = new HashSet<string> { "busy", "dialog_blocked", "dialog_opened", "timeout", "transport" };

        CliFailure Described(string method, AgentException e)
        {
            var pid = Hello.Pid;
            var message = e.Message.Split('\n')[0].Trim();
            string cause = message, next = null;
            var dialogs = Dialogs.Of(e.Detail, "dialogs");
            switch (e.Code)
            {
                case "busy": cause = "IDE ide-" + pid + " is busy and did not start " + method; next = "cts status"; break;
                case "dialog_blocked":
                    if (dialogs.Count == 0 && e.Detail != null && e.Detail.ContainsKey("gone"))
                        return new CliFailure(Command.Verb, e.Code,
                            Command.Words + " did not run: " + ModalErrors.GoneLine(Dialogs.Of(e.Detail, "gone"))
                                + "; nothing is open now, so run the command again",
                            "cts " + Command.Words, 3, null);
                    return new CliFailure(Command.Verb, e.Code,
                        Command.Words + " did not run: a dialog is open in the IDE; answer it, then run the command again",
                        dialogs.Count > 0 ? DialogWatch.AnswerLine(dialogs[0]) : "cts dialog", 3,
                        dialogs.Count > 0 ? ModalErrors.BlockLine(dialogs) : null);
                case "dialog_opened":
                    return new CliFailure(Command.Verb, e.Code, e.Message, DialogWatch.AnswerLine(dialogs[0]), 3, ModalErrors.BlockLine(dialogs));
                case "timeout": cause = "IDE ide-" + pid + " did not answer " + method + " in time; outcome unknown"; next = "cts status"; break;
                case "transport": cause = "the connection to IDE ide-" + pid + " broke; outcome unknown"; next = "cts status"; break;
                default:
                    if (message.Contains(OnlineMarker))
                    {
                        cause = "The IDE is online with the PLC; editing the project while online is not supported. "
                            + "Run `cts disconnect`, then repeat `cts " + Command.Words + "`.";
                        next = "cts disconnect";
                    }
                    else if (message.Contains("No project is open")) next = "cts project open --path <p>";
                    break;
            }
            return new CliFailure(Command.Verb, cause, e.Message, next, 1, dialogs.Count > 0 ? ModalErrors.BlockLine(dialogs) : null);
        }

        // The agent's refusal of a project edit while the IDE is online.
        const string OnlineMarker = "the project is online";
    }

    // The dialogs of a reply (dialog.probe, dialog.answer's `next`, a
    // refusal's data), as the agent's own windows, for its one-line rendering.
    static class Dialogs
    {
        public static IReadOnlyList<ModalWindow> Of(IDictionary<string, object> data, string key)
        {
            var windows = new List<ModalWindow>();
            if (data == null || !data.TryGetValue(key, out var list) || !(list is IEnumerable<object> items)) return windows;
            foreach (var item in items.OfType<IDictionary<string, object>>()) windows.Add(ModalWindow.FromData(item));
            return windows;
        }
    }
}
