using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using Cts.Agent;

namespace Cts.Analysis
{
    internal static class Severity
    {
        internal const string Danger = "danger", Suspicious = "suspicious", Style = "style";
        internal static readonly string[] All = { Danger, Suspicious, Style };
        // A --fail-on no finding reaches: the exit code stays 0.
        internal const string Never = "never";

        // Lower is more severe.
        internal static int Rank(string severity) => severity == Never ? -1 : Array.IndexOf(All, severity) is var index && index >= 0 ? index : 3;
        internal static bool IsValid(string value) => All.Contains(value);
    }

    // A place in a project-view file. Line and column are 1-based and for
    // display only: they never take part in a finding's identity.
    internal sealed class Location
    {
        internal string Path;
        internal int? Line, Column, EndLine, EndColumn;

        internal Location(string path, int? line = null, int? column = null)
        {
            Path = path ?? "";
            Line = line;
            Column = column;
        }

        // A range of a unit's text.
        internal static Location In(Unit unit, int? offset, int? endOffset)
        {
            var location = new Location(unit.SourcePath);
            if (offset.HasValue) { var at = StText.LineColumn(unit.Text, offset.Value); location.Line = at.Key + unit.LineBase; location.Column = at.Value; }
            if (endOffset.HasValue) { var at = StText.LineColumn(unit.Text, endOffset.Value); location.EndLine = at.Key + unit.LineBase; location.EndColumn = at.Value; }
            return location;
        }

        internal Dictionary<string, object> ToJson()
        {
            var data = new Dictionary<string, object> { ["path"] = Path };
            if (Line.HasValue) data["line"] = Line.Value;
            if (Column.HasValue) data["column"] = Column.Value;
            if (EndLine.HasValue) data["end_line"] = EndLine.Value;
            if (EndColumn.HasValue) data["end_column"] = EndColumn.Value;
            return data;
        }
    }

    // A problem a rule found. Rule identity (id, title, severity) is stamped
    // by the runner, never by the rule.
    internal sealed class Finding
    {
        internal string RuleId = "", RuleTitle = "", Severity = "", Message, UnitId, Anchor, Context, Fingerprint;
        internal Location Location;
        internal int? MemberCount;
        internal List<int> MemberLines;

        internal static Finding In(Unit unit, string message, int? offset = null, int? endOffset = null, string anchor = null, string context = null) =>
            new Finding { Message = message, Location = Location.In(unit, offset, endOffset), UnitId = unit.Id, Anchor = anchor, Context = context };

        internal Dictionary<string, object> ToJson()
        {
            var data = new Dictionary<string, object>
            {
                ["rule_id"] = RuleId, ["rule_title"] = RuleTitle, ["severity"] = Severity, ["message"] = Message, ["location"] = Location.ToJson(),
            };
            if (!string.IsNullOrEmpty(UnitId)) data["unit_id"] = UnitId;
            if (!string.IsNullOrEmpty(Anchor)) data["anchor"] = Anchor;
            if (!string.IsNullOrEmpty(Context)) data["context"] = Context;
            if (MemberCount.HasValue) data["member_count"] = MemberCount.Value;
            if (MemberLines != null) data["member_lines"] = MemberLines.Cast<object>().ToList();
            if (!string.IsNullOrEmpty(Fingerprint)) data["fingerprint"] = Fingerprint;
            return data;
        }
    }

    // The analysis could not give what it declares for a part of the
    // project: the result is then incomplete, never silently clean.
    internal sealed class Diagnostic
    {
        internal string Kind, Message, RuleId, UnitId;
        internal Location Location;

        internal Diagnostic(string kind, string message, Location location = null, string ruleId = null, string unitId = null)
        {
            Kind = kind;
            Message = message;
            Location = location ?? new Location("");
            RuleId = ruleId;
            UnitId = unitId;
        }

        internal Dictionary<string, object> ToJson()
        {
            var data = new Dictionary<string, object> { ["kind"] = Kind, ["message"] = Message, ["location"] = Location.ToJson() };
            if (!string.IsNullOrEmpty(RuleId)) data["rule_id"] = RuleId;
            if (!string.IsNullOrEmpty(UnitId)) data["unit_id"] = UnitId;
            return data;
        }
    }

    internal sealed class AnalysisResult
    {
        internal const int SchemaVersion = 1;
        internal bool Complete = true;
        internal List<Finding> Findings = new List<Finding>();
        internal readonly List<Diagnostic> Diagnostics = new List<Diagnostic>();
        internal int Files, Suppressed, SuppressedByDirective, Baselined, ExcludedFromBuild;
        internal List<string> StaleSuppressions = new List<string>(), StaleBaselined = new List<string>(), RulesRun = new List<string>();
        // Every fingerprint before suppressions and the baseline took theirs.
        internal HashSet<string> Unfiltered = new HashSet<string>();

        internal void Incomplete(Diagnostic diagnostic)
        {
            Complete = false;
            Diagnostics.Add(diagnostic);
        }

        // path, position, rule, fingerprint: the same order on every run.
        internal void Sort()
        {
            Findings = Findings.OrderBy(f => f.Location.Path, StringComparer.Ordinal).ThenBy(f => f.Location.Line ?? 0).ThenBy(f => f.Location.Column ?? 0)
                .ThenBy(f => f.RuleId, StringComparer.Ordinal).ThenBy(f => f.Fingerprint ?? "", StringComparer.Ordinal).ThenBy(f => f.Message, StringComparer.Ordinal).ToList();
            var diagnostics = Diagnostics.OrderBy(d => d.Location.Path, StringComparer.Ordinal).ThenBy(d => d.Location.Line ?? 0).ThenBy(d => d.Location.Column ?? 0)
                .ThenBy(d => d.Kind, StringComparer.Ordinal).ThenBy(d => d.Message, StringComparer.Ordinal).ToList();
            Diagnostics.Clear();
            Diagnostics.AddRange(diagnostics);
        }

        internal Dictionary<string, int> BySeverity() => Severity.All.ToDictionary(s => s, s => Findings.Count(f => f.Severity == s));

        internal Dictionary<string, object> ToJson()
        {
            Sort();
            return new Dictionary<string, object>
            {
                ["schema_version"] = SchemaVersion,
                ["complete"] = Complete,
                ["findings"] = Findings.Select(f => (object)f.ToJson()).ToList(),
                ["diagnostics"] = Diagnostics.Select(d => (object)d.ToJson()).ToList(),
                ["summary"] = new Dictionary<string, object>
                {
                    ["files"] = Files,
                    ["excluded_from_build"] = ExcludedFromBuild,
                    ["total"] = Findings.Count,
                    ["by_severity"] = BySeverity().ToDictionary(p => p.Key, p => (object)p.Value),
                    ["by_rule"] = Findings.GroupBy(f => f.RuleId).OrderBy(g => g.Key, StringComparer.Ordinal).ToDictionary(g => g.Key, g => (object)g.Count()),
                    ["suppressed"] = Suppressed,
                    ["suppressed_by_directive"] = SuppressedByDirective,
                    ["baselined"] = Baselined,
                    ["stale_suppressions"] = StaleSuppressions.Cast<object>().ToList(),
                    ["stale_baselined"] = StaleBaselined.Cast<object>().ToList(),
                    ["rules_run"] = RulesRun.Cast<object>().ToList(),
                    ["diagnostics"] = Diagnostics.Count,
                },
            };
        }
    }

    // A finding's identity: rule, unit, the rule's anchor and its context
    // with whitespace and case folded. Path and line never take part, so a
    // reindent or a line inserted above keeps the baseline and every
    // suppression valid. Byte-identical with what cts 3.4.1 wrote, so its
    // baselines and suppressions keep matching.
    internal static class Fingerprints
    {
        internal const int Schema = 1;

        internal static string NormalizeContext(string text) =>
            StText.Squeezed(text).ToLowerInvariant();

        internal static string Of(string ruleId, string unitId, string anchor, string context, int occurrence)
        {
            var payload = new StringBuilder("{");
            payload.Append("\"anchor\": ").Append(Quote(anchor ?? ""));
            payload.Append(", \"context\": ").Append(Quote(NormalizeContext(context)));
            if (occurrence != 0) payload.Append(", \"occurrence\": ").Append(occurrence.ToString(CultureInfo.InvariantCulture));
            payload.Append(", \"rule\": ").Append(Quote(ruleId));
            payload.Append(", \"schema\": ").Append(Schema.ToString(CultureInfo.InvariantCulture));
            payload.Append(", \"unit\": ").Append(Quote(unitId ?? "")).Append('}');
            using (var sha = SHA256.Create())
            {
                var digest = sha.ComputeHash(Encoding.UTF8.GetBytes(payload.ToString()));
                return "cts" + Schema.ToString(CultureInfo.InvariantCulture) + ":" + string.Concat(digest.Take(20).Select(b => b.ToString("x2", CultureInfo.InvariantCulture)));
            }
        }

        // A JSON string with non-ASCII characters kept as they are.
        internal static string Quote(string text)
        {
            var sb = new StringBuilder();
            Cts.Agent.Json.WriteString(sb, text, Cts.Agent.Json.Nothing);
            return sb.ToString();
        }
    }
}
