// The analysis window's model: the findings `cts analyze --json` answers, the
// rules `cts analyze rules --doc --json` lists, the lines of a file around a
// finding, and the decisions file `cts analyze triage --apply` takes.  The
// window (AnalysisView) only shows them.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using Cts.Analysis;
using static Cts.Agent.JsonMap;

namespace Cts.Agent
{
    public sealed class AnalysisFinding
    {
        public string RuleId { get; internal set; }
        public string RuleTitle { get; internal set; }
        public string Severity { get; internal set; }
        public string Message { get; internal set; }
        //: The .st file, relative to the project view.
        public string Path { get; internal set; }
        public int? Line { get; internal set; }
        public int? EndLine { get; internal set; }
        //: Every line the finding occupies: a merged finding's members, else its own line.
        public List<int> Lines { get; } = new List<int>();
        public string Fingerprint { get; internal set; }

        //: `POUs/Main.st:42`, `:42-45` for a span, `:42 (x3)` for a merged finding.
        public string Where
        {
            get
            {
                if (Line == null) return Path;
                var at = Path + ":" + Line.Value.ToString(CultureInfo.InvariantCulture);
                if (Lines.Count > 1) at += " (x" + Lines.Count.ToString(CultureInfo.InvariantCulture) + ")";
                else if (EndLine > Line) at += "-" + EndLine.Value.ToString(CultureInfo.InvariantCulture);
                return at;
            }
        }
    }

    public sealed class AnalysisRule
    {
        public string Id { get; internal set; }
        public string Title { get; internal set; }
        public string Severity { get; internal set; }
        public string Summary { get; internal set; }
        public string Doc { get; internal set; }
        public bool Enabled { get; internal set; }
    }

    public sealed class AnalysisRun
    {
        public List<AnalysisFinding> Findings { get; } = new List<AnalysisFinding>();
        //: The sync folder whose settings ran the analysis.
        public string Workspace { get; internal set; }
        //: The folder the findings' paths are relative to.
        public string View { get; internal set; }
        public bool Complete { get; internal set; }
        public int Diagnostics { get; internal set; }
        public int Suppressed { get; internal set; }
        public int Baselined { get; internal set; }

        //: `12 findings: danger 2 · suspicious 7 · style 3`, then what the run left out.
        public string Summary
        {
            get
            {
                var text = Findings.Count + " finding(s)";
                var counts = AnalysisReport.Severities.Select(severity => Tuple.Create(severity, Findings.Count(f => f.Severity == severity)))
                    .Where(count => count.Item2 > 0).Select(count => count.Item1 + " " + count.Item2).ToList();
                if (counts.Count > 0) text += ": " + string.Join(" · ", counts);
                if (Suppressed > 0) text += ", " + Suppressed + " suppressed";
                if (Baselined > 0) text += ", " + Baselined + " baselined";
                if (!Complete) text += ", incomplete (" + Diagnostics + " diagnostic(s): cts analyze lists them)";
                return text;
            }
        }
    }

    public static class AnalysisReport
    {
        //: The most severe first, as the analyzer ranks them.
        public static IReadOnlyList<string> Severities => Severity.All;

        public static AnalysisRun Parse(string json)
        {
            var data = Json.Parse(json) as IDictionary<string, object> ?? throw new JsonException("cts analyze answered no object");
            var summary = Field(data, "summary");
            var run = new AnalysisRun
            {
                Workspace = Text(data, "workspace"),
                View = Text(data, "project_view"),
                Complete = Equals(Value(data, "complete"), true),
                Diagnostics = (Value(data, "diagnostics") as IList<object>)?.Count ?? 0,
                Suppressed = Number(summary, "suppressed") ?? 0,
                Baselined = Number(summary, "baselined") ?? 0,
            };
            foreach (var item in (Value(data, "findings") as IList<object>) ?? new List<object>())
            {
                var entry = item as IDictionary<string, object>;
                if (entry == null) continue;
                var location = Field(entry, "location");
                var finding = new AnalysisFinding
                {
                    RuleId = Text(entry, "rule_id"),
                    RuleTitle = Text(entry, "rule_title"),
                    Severity = Text(entry, "severity"),
                    Message = Text(entry, "message"),
                    Path = Text(location, "path"),
                    Line = Number(location, "line"),
                    EndLine = Number(location, "end_line"),
                    Fingerprint = Text(entry, "fingerprint"),
                };
                var members = Value(entry, "member_lines") as IList<object>;
                if (members != null) finding.Lines.AddRange(members.Select(line => Convert.ToInt32(line, CultureInfo.InvariantCulture)));
                else if (finding.Line != null) finding.Lines.Add(finding.Line.Value);
                run.Findings.Add(finding);
            }
            return run;
        }

        public static List<AnalysisRule> Rules(string json)
        {
            var data = Json.Parse(json) as IDictionary<string, object> ?? throw new JsonException("cts analyze rules answered no object");
            return ((Value(data, "rules") as IList<object>) ?? new List<object>()).OfType<IDictionary<string, object>>().Select(entry => new AnalysisRule
            {
                Id = Text(entry, "id"),
                Title = Text(entry, "title"),
                Severity = Text(entry, "severity"),
                Summary = Text(entry, "summary"),
                Doc = Body(Text(entry, "doc")),
                Enabled = Equals(Value(entry, "enabled"), true),
            }).ToList();
        }

        // The findings of *severity* (null: all) whose rule, place or message
        // holds *filter*, the most severe first, else in the analyzer's order.
        public static List<AnalysisFinding> Shown(IEnumerable<AnalysisFinding> findings, string severity, string filter)
        {
            var text = (filter ?? "").Trim();
            return findings.Where(f => (severity == null || f.Severity == severity)
                && (text.Length == 0 || new[] { f.RuleId, f.RuleTitle, f.Path, f.Message }.Any(field => (field ?? "").IndexOf(text, StringComparison.OrdinalIgnoreCase) >= 0)))
                .OrderBy(f => Severity.Rank(f.Severity)).ToList();
        }

        // The lines of a file around *wanted* (1-based), each numbered, the
        // wanted ones marked `>`; windows that touch merge, a skip between
        // two shows as `...`.
        public static string Excerpt(IList<string> lines, IEnumerable<int> wanted, int radius)
        {
            var marked = new HashSet<int>(wanted.Where(line => line >= 1 && line <= lines.Count));
            if (marked.Count == 0) return "";
            var shown = new SortedSet<int>(marked.SelectMany(line => Enumerable.Range(Math.Max(1, line - radius), Math.Min(lines.Count, line + radius) - Math.Max(1, line - radius) + 1)));
            var width = shown.Max.ToString(CultureInfo.InvariantCulture).Length;
            var text = new StringBuilder();
            var last = 0;
            foreach (var line in shown)
            {
                if (last > 0 && line > last + 1) text.Append("...\n");
                text.Append(marked.Contains(line) ? "> " : "  ").Append(line.ToString(CultureInfo.InvariantCulture).PadLeft(width)).Append("  ")
                    .Append(lines[line - 1].TrimEnd('\r')).Append('\n');
                last = line;
            }
            return text.ToString();
        }

        // The decisions file for `cts analyze triage --apply`: *action*
        // (suppress, fix-later or baseline) for each finding, with *reason*.
        public static string Decisions(IEnumerable<AnalysisFinding> findings, string action, string reason)
        {
            return Json.Pretty(findings.Select(f =>
            {
                var entry = new Dictionary<string, object> { ["fingerprint"] = f.Fingerprint, ["action"] = action };
                if (!string.IsNullOrWhiteSpace(reason)) entry["reason"] = reason.Trim();
                return (object)entry;
            }).ToList());
        }

        // A rule document without its front matter (`---` title, since, related `---`).
        static string Body(string doc)
        {
            var text = doc.Replace("\r\n", "\n");
            if (!text.StartsWith("---\n", StringComparison.Ordinal)) return text;
            var end = text.IndexOf("\n---\n", 3, StringComparison.Ordinal);
            return end < 0 ? text : text.Substring(end + 5).TrimStart('\n');
        }

        static IDictionary<string, object> Field(IDictionary<string, object> data, string key) => Value(data, key) as IDictionary<string, object>;

        static int? Number(IDictionary<string, object> data, string key) => Value(data, key) is object value ? Convert.ToInt32(value, CultureInfo.InvariantCulture) : (int?)null;
    }
}
