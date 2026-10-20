using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Cli
{
    // The command line of one cts run: the command, its own options, and the
    // global flags, which work before or after the command.
    public sealed class CliOptions
    {
        // short (the verdict line), json (the whole payload) or text (a readable dump).
        public string Output { get; private set; } = "short";
        public string Target { get; private set; }
        public string ExpectProject { get; private set; }
        public bool Help { get; private set; }
        public double? Timeout { get; private set; }
        string _verb;
        // The agent's parameters the command's own options set.
        public Dictionary<string, object> Params { get; } = new Dictionary<string, object>();
        // The words after the command's name, for a command that takes them.
        public List<string> Arguments { get; } = new List<string>();
        // Where a command run here names its stages ("progress: ..."): stderr.
        internal TextWriter Progress { get; set; } = TextWriter.Null;

        // An option's value as text; *fallback* when the command line left it out.
        internal string Text(string key, string fallback = null)
            => Params.TryGetValue(key, out var value) ? Convert.ToString(value, CultureInfo.InvariantCulture) ?? fallback : fallback;

        // A whole-number option's value; *fallback* when left out or not a number.
        internal int Number(string key, int fallback)
            => int.TryParse(Text(key), NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) ? value : fallback;

        // The global flags that take a value; the command's name is the first
        // word that is neither a flag nor such a value.
        static readonly Regex Negative = new Regex(@"^-\d");

        static readonly HashSet<string> ValueFlags = new HashSet<string>(StringComparer.Ordinal)
        {
            "--output", "--target", "--expect-project",
        };

        // The command a command line runs, or null (`cts`, `cts --help`).
        public static string CommandOf(IList<string> args)
        {
            var at = CommandAt(args);
            return at < 0 ? null : args[at];
        }

        // The word right after the command (`answer` of `cts dialog answer`), or null.
        public static string WordAfterCommand(IList<string> args)
        {
            var at = CommandAt(args);
            return at >= 0 && at + 1 < args.Count ? args[at + 1] : null;
        }

        static int CommandAt(IList<string> args)
        {
            for (var i = 0; i < args.Count; i++)
            {
                if (ValueFlags.Contains(args[i])) { i++; continue; }
                if (!args[i].StartsWith("-", StringComparison.Ordinal)) return i;
            }
            return -1;
        }

        // Parses the command line of a command cts.exe serves. *target* is
        // CTS_TARGET, which --target overrides. Throws CliFailure (exit 2) on
        // an option the command does not have, or one it needs and lacks.
        public static CliOptions Parse(IList<string> args, string target, CliCommand command)
        {
            var verb = command.Verb;
            var o = new CliOptions { Target = string.IsNullOrEmpty(target) ? null : target, _verb = verb };
            var words = 0;
            for (var i = 0; i < args.Count; i++)
            {
                var arg = args[i];
                var eq = arg.IndexOf('=');
                var name = arg.StartsWith("--", StringComparison.Ordinal) && eq > 0 ? arg.Substring(0, eq) : arg;
                Func<string> value = () =>
                {
                    if (eq > 0 && name != arg) return arg.Substring(eq + 1);
                    if (i + 1 >= args.Count) throw Usage(verb, command, name + " needs a value");
                    return args[++i];
                };
                // After the command, the command's own option wins over a
                // global flag of the same name (plc-log's --output file).
                var own = words > 0 ? command.Options.FirstOrDefault(x => x.Flag == name) : null;
                if (own != null)
                {
                    Take(o, verb, command, own, value);
                    continue;
                }
                if (command.Name == "raw" && o.Arguments.Count > 0 && arg.StartsWith("--", StringComparison.Ordinal)
                    && name != "--timeout")
                {
                    if (!(o.Params.TryGetValue("raw_params", out var raw) && raw is Dictionary<string, object> parameters))
                        o.Params["raw_params"] = parameters = new Dictionary<string, object>();
                    var key = name.Substring(2).Replace('-', '_');
                    string rawValue;
                    if (eq > 0) rawValue = arg.Substring(eq + 1);
                    else if (i + 1 < args.Count && (!args[i + 1].StartsWith("--", StringComparison.Ordinal) || Negative.IsMatch(args[i + 1]))) rawValue = args[++i];
                    else { parameters[key] = true; continue; }
                    try { parameters[key] = Cts.Agent.Json.Parse(rawValue); }
                    catch (Cts.Agent.JsonException) { parameters[key] = rawValue; }
                    continue;
                }
                switch (name)
                {
                    case "--json": o.Output = "json"; break;
                    case "--pretty": case "-p": o.Output = "text"; break;
                    case "-h": case "--help": o.Help = true; break;
                    case "--output":
                        var output = value();
                        if (output != "short" && output != "json" && output != "text")
                            throw Usage(verb, command, "--output takes short, json or text, not " + output);
                        o.Output = output;
                        break;
                    case "--target": o.Target = value(); break;
                    case "--expect-project": o.ExpectProject = value(); break;
                    case "--timeout":
                        double seconds;
                        var text = value();
                        if (!double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out seconds) || seconds <= 0)
                            throw Usage(verb, command, "--timeout takes seconds, not " + text);
                        o.Timeout = seconds;
                        break;
                    default:
                        // A negative number is a word, not a flag (cts write GVL.n -5).
                        if (!arg.StartsWith("-", StringComparison.Ordinal) || (words > 0 && command.Arguments != null && Negative.IsMatch(arg)))
                        {
                            // The command's name, then the subcommand's word.
                            if (words == 0 || (words == 1 && arg == command.Sub)) { words++; break; }
                            if (command.Arguments == null)
                            {
                                // A bare word where the command still needs one flag is that flag's value
                                // (cts project open P, cts visu list Motor1).
                                var needed = command.Options.Where(x => x.Required && !o.Params.ContainsKey(x.Key)).ToList();
                                if (needed.Count != 1) throw Usage(verb, command, UnknownArgument(command, arg));
                                Take(o, verb, command, needed[0], () => arg);
                                break;
                            }
                            o.Arguments.Add(arg);
                            break;
                        }
                        var option = command.Options.FirstOrDefault(x => x.Flag == name);
                        if (option == null) throw Usage(verb, command, UnknownArgument(command, arg));
                        Take(o, verb, command, option, value);
                        break;
                }
            }
            if (!o.Help)
            {
                if (command.ArgumentLimit > 0 && o.Arguments.Count > command.ArgumentLimit)
                    throw Usage(verb, command, "takes at most " + command.ArgumentLimit + " argument" + (command.ArgumentLimit == 1 ? "" : "s"));
                foreach (var needed in command.Options.Where(x => x.Required && !o.Params.ContainsKey(x.Key)))
                    throw Usage(verb, command, needed.Flag + " is required: " + needed.Help);
            }
            return o;
        }

        static void Take(CliOptions o, string verb, CliCommand command, CliOption option, Func<string> value)
        {
            if (option.Metavar == null) o.Params[option.Key] = true;
            else if (option.Repeats)
            {
                if (!(o.Params.TryGetValue(option.Key, out var seen) && seen is List<object> list)) o.Params[option.Key] = list = new List<object>();
                list.Add(value());
            }
            else o.Params[option.Key] = Typed(verb, command, option, value());
        }

        static object Typed(string verb, CliCommand command, CliOption option, string text)
        {
            if (option.Number)
            {
                long n;
                if (!long.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out n) || n < 0)
                    throw Usage(verb, command, option.Flag + " takes a whole number, not " + text);
                return n;
            }
            if (option.Choices != null && !option.Choices.Contains(text))
                throw Usage(verb, command, option.Flag + " takes " + string.Join(", ", option.Choices) + ", not " + text);
            return text;
        }

        static CliFailure Usage(string verb, CliCommand command, string message)
        {
            return new CliFailure(verb, "usage", message, "cts " + command.Words + " --help", 2);
        }

        static string UnknownArgument(CliCommand command, string argument)
        {
            var subcommands = CliCommands.All.Where(item => item.Name == command.Name && item.Sub != null).Select(item => item.Sub).ToList();
            if (command.Sub != null || subcommands.Count == 0) return "unrecognized argument " + argument;
            var bare = CliCommands.All.FirstOrDefault(item => item.Name == command.Name && item.Sub == null);
            return "unrecognized argument " + argument + "; " + (bare == null ? "" : "plain `cts " + command.Name + "`: " + bare.Summary.TrimEnd('.') + "; ")
                + "subcommands: " + string.Join(", ", subcommands.Select(sub => "`cts " + command.Name + " " + sub + "`"));
        }

        // The IDE --target names, as a pid: `ide-3684` or `3684`.
        public int? TargetPid()
        {
            if (Target == null) return null;
            var text = Target.Trim();
            if (text.StartsWith("ide-", StringComparison.OrdinalIgnoreCase)) text = text.Substring(4);
            int pid;
            if (!int.TryParse(text, NumberStyles.None, CultureInfo.InvariantCulture, out pid) || pid <= 0)
                throw new CliFailure(_verb, "bad target", "Invalid target '" + Target + "': expected 'ide-<pid>' or an integer PID", null, 2);
            return pid;
        }
    }

    // A command that stops before it has an answer: its verdict line names the
    // cause, the message goes to stderr, and the process exits with ExitCode.
    public sealed class CliFailure : Exception
    {
        public string CommandName { get; private set; }
        public string Cause { get; private set; }
        public string Next { get; private set; }
        public int ExitCode { get; private set; }
        // A line for stderr after the message (the dialog a refusal saw), or null.
        public string Note { get; internal set; }
        // The agent ran the call and refused it: nothing of it happened and the
        // connection still serves the next call, so a caller may note the
        // refusal and go on. False for a failure whose outcome is unknown (no
        // reply in time, a broken connection) or that blocks every call (a
        // dialog, a busy IDE): the command ends there.
        public bool Declined { get; internal set; }

        public CliFailure(string command, string cause, string message, string next, int exitCode, string note = null) : base(message)
        {
            CommandName = command;
            Cause = cause;
            Next = next;
            ExitCode = exitCode;
            Note = note;
        }
    }
}
