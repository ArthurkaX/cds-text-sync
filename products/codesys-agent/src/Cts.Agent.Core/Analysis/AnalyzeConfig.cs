using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Analysis
{
    internal sealed class AnalyzeException : Exception
    {
        internal AnalyzeException(string message) : base(message) { }
    }

    // The "analyze" table of the sync folder's cds-text-sync.json:
    //   "analyze": {"fail_on": "suspicious", "incomplete": "warn",
    //     "rules": {"CTS0004": {"enabled": true, "severity": "danger", "options": {"min_occurrences": 2}}},
    //     "scopes": [{"path": "POUs/**", "enabled": true, "exclude": ["CTS0004"]}]}
    internal sealed class AnalyzeConfig
    {
        // In the catalog but off unless a project turns them on.
        static readonly HashSet<string> OffByDefault = new HashSet<string> { "CTS0034" };
        internal static readonly Regex RuleId = new Regex(@"^CTS\d{4}$");

        internal string FailOn = Severity.Suspicious, Incomplete = "warn";
        readonly Dictionary<string, IDictionary<string, object>> _rules = new Dictionary<string, IDictionary<string, object>>();
        readonly List<Tuple<Regex, bool, HashSet<string>>> _scopes = new List<Tuple<Regex, bool, HashSet<string>>>();

        internal static AnalyzeConfig Load(string syncFolder)
        {
            var config = new AnalyzeConfig();
            var path = Path.Combine(syncFolder, "cds-text-sync.json");
            if (!File.Exists(path)) return config;
            IDictionary<string, object> data;
            try { data = Json.Parse(File.ReadAllText(path)) as IDictionary<string, object>; }
            catch (JsonException error) { throw new AnalyzeException("cannot parse " + path + ": " + error.Message); }
            if (data == null || !data.TryGetValue("analyze", out var raw) || raw == null) return config;
            if (!(raw is IDictionary<string, object> analyze)) throw new AnalyzeException("\"analyze\" in " + path + " must be an object");
            if (analyze.TryGetValue("fail_on", out var failOn))
            {
                config.FailOn = Convert.ToString(failOn, CultureInfo.InvariantCulture).Trim().ToLowerInvariant();
                if (!Severity.IsValid(config.FailOn)) throw new AnalyzeException("analyze.fail_on must be one of danger|suspicious|style, got '" + config.FailOn + "'");
            }
            if (analyze.TryGetValue("incomplete", out var incomplete))
            {
                config.Incomplete = Convert.ToString(incomplete, CultureInfo.InvariantCulture).Trim().ToLowerInvariant();
                if (!new[] { "warn", "error", "ignore" }.Contains(config.Incomplete)) throw new AnalyzeException("analyze.incomplete must be one of warn|error|ignore, got '" + config.Incomplete + "'");
            }
            if (analyze.TryGetValue("rules", out var rules) && rules != null)
            {
                if (!(rules is IDictionary<string, object> table)) throw new AnalyzeException("analyze.rules must be an object");
                foreach (var entry in table)
                {
                    var id = entry.Key.Trim().ToUpperInvariant();
                    if (!RuleId.IsMatch(id)) throw new AnalyzeException("analyze.rules." + entry.Key + " is not a rule id");
                    if (RuleCatalog.All.All(rule => rule.Id != id)) throw new AnalyzeException("analyze.rules names an unknown rule: " + id);
                    if (!(entry.Value is IDictionary<string, object> rule)) throw new AnalyzeException("analyze.rules." + id + " must be an object");
                    if (rule.TryGetValue("severity", out var severity) && !Severity.IsValid(Convert.ToString(severity, CultureInfo.InvariantCulture).Trim().ToLowerInvariant()))
                        throw new AnalyzeException("analyze.rules." + id + ".severity must be one of danger|suspicious|style");
                    if (rule.TryGetValue("options", out var options) && !(options is IDictionary<string, object>)) throw new AnalyzeException("analyze.rules." + id + ".options must be an object");
                    config._rules[id] = rule;
                }
            }
            if (analyze.TryGetValue("scopes", out var scopes) && scopes != null)
            {
                var index = 0;
                foreach (var item in scopes as IList<object> ?? throw new AnalyzeException("analyze.scopes must be a list"))
                {
                    if (!(item is IDictionary<string, object> scope) || !(scope.TryGetValue("path", out var glob) && glob is string text && text.Length > 0))
                        throw new AnalyzeException("analyze.scopes[" + index + "] needs a \"path\" glob");
                    var exclude = scope.TryGetValue("exclude", out var list) && list is IList<object> ids ? ids.Select(id => Convert.ToString(id, CultureInfo.InvariantCulture).Trim().ToUpperInvariant()) : Enumerable.Empty<string>();
                    config._scopes.Add(Tuple.Create(Glob((string)scope["path"]), !scope.TryGetValue("enabled", out var enabled) || !Equals(enabled, false), new HashSet<string>(exclude)));
                    index++;
                }
            }
            return config;
        }

        internal string SeverityFor(string id, string declared) =>
            _rules.TryGetValue(id, out var rule) && rule.TryGetValue("severity", out var severity) ? Convert.ToString(severity, CultureInfo.InvariantCulture).Trim().ToLowerInvariant() : declared;

        // fallback null: the catalog's default (on, but for the opt-in rules).
        internal bool EnabledFor(string id, bool? fallback) =>
            _rules.TryGetValue(id, out var rule) && rule.TryGetValue("enabled", out var enabled) ? Equals(enabled, true) : fallback ?? !OffByDefault.Contains(id);

        internal IDictionary<string, object> OptionsFor(string id) =>
            _rules.TryGetValue(id, out var rule) && rule.TryGetValue("options", out var options) && options is IDictionary<string, object> table ? table : new Dictionary<string, object>();

        // A scope with enabled false turns every rule off for its paths.
        internal bool PathExcluded(string path) => _scopes.Any(scope => !scope.Item2 && scope.Item1.IsMatch(path));

        internal HashSet<string> RulesExcludedFor(string path) => new HashSet<string>(_scopes.Where(scope => scope.Item1.IsMatch(path)).SelectMany(scope => scope.Item3));

        // "**" any depth, "*" within a folder, "?" one character.
        static Regex Glob(string pattern)
        {
            var sb = new StringBuilder("^");
            for (var i = 0; i < pattern.Length; i++)
            {
                var c = pattern[i];
                if (c == '*' && i + 1 < pattern.Length && pattern[i + 1] == '*') { sb.Append(".*"); i++; }
                else if (c == '*') sb.Append("[^/]*");
                else if (c == '?') sb.Append("[^/]");
                else sb.Append(Regex.Escape(c.ToString()));
            }
            return new Regex(sb.Append('$').ToString());
        }
    }

    // Where one analysis reads and keeps its state: the sync folder, its view
    // folder, and .cts-analyze beside the view (the sync engine owns the view).
    internal sealed class AnalyzeWorkspace
    {
        internal string Root, View, StateDir;

        internal static AnalyzeWorkspace Resolve(string workspace, string projectView, string work)
        {
            if (!string.IsNullOrEmpty(workspace) && !string.IsNullOrEmpty(projectView)) throw new AnalyzeException("Pass either --workspace or --project-view, not both.");
            if (!string.IsNullOrEmpty(projectView))
            {
                var view = Path.GetFullPath(projectView);
                if (!Directory.Exists(view)) throw new AnalyzeException("project-view directory not found: " + view);
                return At(Path.GetDirectoryName(view), view);
            }
            if (!string.IsNullOrEmpty(workspace))
            {
                var folder = Path.GetFullPath(workspace).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                if (!Directory.Exists(folder)) throw new AnalyzeException("workspace directory not found: " + folder);
                if (Path.GetFileName(folder).Equals("project-view", StringComparison.OrdinalIgnoreCase)) return At(Path.GetDirectoryName(folder), folder);
                var view = ViewFolder.Of(folder);
                if (!Directory.Exists(view)) throw new AnalyzeException("project-view not found under workspace: " + view);
                return At(folder, view);
            }
            var around = ViewFolder.Around(work);
            if (around != null)
            {
                var view = ViewFolder.Of(around);
                if (Directory.Exists(view)) return At(around, view);
                if (Directory.Exists(Path.Combine(around, "project-view"))) return At(around, Path.Combine(around, "project-view"));
            }
            throw new AnalyzeException("No analysis workspace found. Pass --workspace <sync-folder> or --project-view <dir>, or run from a sync folder.");
        }

        static AnalyzeWorkspace At(string root, string view) => new AnalyzeWorkspace { Root = root, View = view, StateDir = Path.Combine(root, ".cts-analyze") };
    }
}
