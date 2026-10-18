using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace Cts.Analysis
{
    // What a rule reads besides a unit's text. A rule that needs a parsed
    // declaration reports the units it cannot parse; one built on the whole
    // project is skipped when a .st file could not be read.
    internal static class Needs
    {
        internal const string StText = "st-text", Declarations = "declarations", BlockStructure = "block-structure",
            ProjectSymbols = "project-symbols", ExecutionGraph = "execution-graph", VisuXml = "visu-xml";
    }

    // One rule: its manifest and its check. A unit rule checks one unit at a
    // time; a project rule (PerUnit false) sees every visible unit at once.
    internal abstract class Rule
    {
        internal readonly string Id, Title, Severity, Topic, Summary;
        internal readonly HashSet<string> Kinds;
        internal string[] Requires = { Needs.StText };
        // "adjacent" merges findings on consecutive lines, "identical" the
        // ones that share anchor and context.
        internal string Merge;
        internal readonly Dictionary<string, object> Options = new Dictionary<string, object>();

        protected Rule(string id, string title, string severity, string topic, string summary, params string[] kinds)
        {
            Id = id;
            Title = title;
            Severity = severity;
            Topic = topic;
            Summary = summary;
            Kinds = Analysis.Kinds.Expand(kinds.Length == 0 ? new[] { "ANY" } : kinds);
        }

        internal virtual bool PerUnit => true;
        internal virtual IEnumerable<Finding> Check(Unit unit, RuleContext context) => Enumerable.Empty<Finding>();
        internal virtual IEnumerable<Finding> Check(RuleContext context) => Enumerable.Empty<Finding>();

        // A piece of code in a message: in single quotes, in double quotes
        // when it holds a string literal.
        protected static string Quoted(string value) => value.Contains("'") ? "\"" + value + "\"" : "'" + value + "'";

        // The rule's documentation, shipped inside the assembly.
        internal string Doc()
        {
            var name = typeof(Rule).Assembly.GetManifestResourceNames().FirstOrDefault(n => n.StartsWith("Cts.Analysis.Rules." + Id + "_", StringComparison.Ordinal));
            if (name == null) return "";
            using (var stream = typeof(Rule).Assembly.GetManifestResourceStream(name))
            using (var reader = new StreamReader(stream)) return reader.ReadToEnd().Replace("\r\n", "\n");
        }
    }

    // Everything a rule may read. Units is the one filtered set: paths a
    // scope turns off and rules a scope excludes are already gone.
    internal sealed class RuleContext
    {
        internal readonly Snapshot Snapshot;
        internal readonly AnalyzeConfig Config;
        internal Rule Active;
        readonly Dictionary<string, List<Unit>> _visible = new Dictionary<string, List<Unit>>();
        ExecutionGraph _graph;
        ExternalReferences _external;
        GlobalAccessIndex _globals;
        Dictionary<string, EnumType> _enums;

        internal RuleContext(Snapshot snapshot, AnalyzeConfig config)
        {
            Snapshot = snapshot;
            Config = config;
        }

        internal List<Unit> Units => Visible(Active);

        internal List<Unit> Visible(Rule rule)
        {
            if (rule == null) return Snapshot.Units;
            if (!_visible.TryGetValue(rule.Id, out var units))
                _visible[rule.Id] = units = Snapshot.Units.Where(unit => IsVisible(rule, unit.SourcePath)).ToList();
            return units;
        }

        internal bool IsVisible(Rule rule, string path) => !Config.PathExcluded(path) && !Config.RulesExcludedFor(path).Contains(rule.Id);

        internal ExecutionGraph Graph => _graph ?? (_graph = new ExecutionGraph(Snapshot));
        internal ExternalReferences External => _external ?? (_external = new ExternalReferences(Snapshot.Root));
        internal GlobalAccessIndex Globals => _globals ?? (_globals = new GlobalAccessIndex(Snapshot));
        internal Dictionary<string, EnumType> Enums => _enums ?? (_enums = EnumType.Read(Snapshot));

        // The active rule's option: the configured value when it has the
        // declared type, else the declared default.
        internal T Option<T>(string name)
        {
            if (!Active.Options.TryGetValue(name, out var declared)) throw new KeyNotFoundException(Active.Id + " declares no option " + name);
            var configured = Config.OptionsFor(Active.Id).TryGetValue(name, out var value) ? Coerce(value, declared) : null;
            return (T)Convert.ChangeType(configured ?? declared, typeof(T), System.Globalization.CultureInfo.InvariantCulture);
        }

        // value when it fits the declared default's type, else null.
        internal static object Coerce(object value, object declared)
        {
            if (value == null) return null;
            if (declared is bool) return value is bool ? value : null;
            if (declared is int) return value is long || value is int ? value : null;
            if (declared is double) return value is long || value is int || value is double ? value : null;
            if (declared is string) return value is string ? value : null;
            return null;
        }

        internal static string TypeName(object value) =>
            value is bool ? "bool" : value is long || value is int ? "int" : value is double ? "float" : value is string ? "str" : value == null ? "NoneType" : value is IDictionary<string, object> ? "dict" : "list";
    }
}
