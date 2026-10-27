// What makes the problem report (WidgetReport) safe to post: the names the
// agent knows -- the project's objects and files, branches, folders, the
// user and the PC -- become placeholders, and so do paths, addresses,
// e-mails and text in single quotes, where messages put a name.  A cts command keeps its command words and flag
// names, never their values.  Free text may still hold a name the agent did
// not know, so a person reads the report before sending it.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Cli;

namespace Cts.Agent
{
    public sealed class Redaction
    {
        //: Names every CODESYS project has: they say nothing about this one.
        static readonly HashSet<string> Common = new HashSet<string>(new[]
        {
            "Application", "Device", "Plc Logic", "PLC_PRG", "MainTask", "Task Configuration", "Library Manager",
            "Project Settings", "Project Information", "main", "master", "develop", "origin", "HEAD",
        }, StringComparer.OrdinalIgnoreCase);

        static readonly Regex Url = new Regex(@"\b[a-z][a-z0-9+.-]*://[^\s""'<>]+|\b[\w.-]+@[\w.-]+:[^\s""'<>]+", RegexOptions.IgnoreCase);
        static readonly Regex Email = new Regex(@"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b");
        static readonly Regex QuotedPath = new Regex(@"(?<q>[""'])(?:[A-Za-z]:|\\\\)[\\/][^""'\r\n]*\k<q>");
        static readonly Regex Path = new Regex(@"(?:\b[A-Za-z]:|\\\\[^\\\s]+)[\\/][^\s""'<>|*?]*");
        static readonly Regex File = new Regex(@"[\w.\-/\\]*[\w\-]\.(?:st|xml|project|projectarchive|library|compiled-library|exp)\b", RegexOptions.IgnoreCase);
        //: An IPv4 address; one of a single digit first (3.5.22.40) is a version.
        static readonly Regex Address = new Regex(@"\b(?:[1-9]\d|1\d\d|2[0-5]\d)(?:\.\d{1,3}){3}(?::\d+)?\b");
        static readonly Regex Quoted = new Regex(@"'(?<text>[^'\r\n]+)'");
        static readonly Regex Placeholder = new Regex(@"^(?:\s*(?:<\w+>|--?[\w-]+|…)\s*)+$");

        readonly Regex _names;
        readonly Dictionary<string, string> _kinds;

        // *names* are (name, kind) pairs: "Pump_FB" -> "object" puts
        // <object> where Pump_FB was.  Names of fewer than three characters
        // and those every project has stay.
        public Redaction(IEnumerable<KeyValuePair<string, string>> names)
        {
            _kinds = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var pair in names)
            {
                var name = (pair.Key ?? "").Trim();
                if (name.Length < 3 || Common.Contains(name) || _kinds.ContainsKey(name)) continue;
                _kinds[name] = pair.Value;
            }
            _names = _kinds.Count == 0 ? null : new Regex(@"(?<![\w])(?:" + string.Join("|",
                _kinds.Keys.OrderByDescending(name => name.Length).Select(Regex.Escape)) + @")(?![\w])", RegexOptions.IgnoreCase);
        }

        public string Text(string text)
        {
            if (string.IsNullOrEmpty(text)) return text ?? "";
            text = Url.Replace(text, "<url>");
            text = Email.Replace(text, "<email>");
            text = QuotedPath.Replace(text, match => match.Groups["q"].Value + "<path>" + match.Groups["q"].Value);
            text = Path.Replace(text, "<path>");
            text = File.Replace(text, "<file>");
            text = Address.Replace(text, "<address>");
            if (_names != null) text = _names.Replace(text, match => "<" + _kinds[match.Value] + ">");
            return Quoted.Replace(text, match => Placeholder.IsMatch(match.Groups["text"].Value) ? match.Value : "'…'");
        }

        // A cts command line: the command words (`project update`) and the
        // flag names stay, every value becomes <arg>.
        public static string Command(IList<string> args)
        {
            var kept = 0;
            if (args.Count > 0 && CliCommands.All.Any(command => command.Name == args[0]))
            {
                kept = 1;
                if (args.Count > 1 && CliCommands.All.Any(command => command.Name == args[0] && command.Sub == args[1])) kept = 2;
            }
            return string.Join(" ", args.Select((arg, i) =>
            {
                if (i < kept) return arg;
                if (!arg.StartsWith("-", StringComparison.Ordinal) || arg.Length < 2 || char.IsDigit(arg[1])) return "<arg>";
                var equals = arg.IndexOf('=');
                return equals < 0 ? arg : arg.Substring(0, equals) + "=<arg>";
            }));
        }
    }
}
