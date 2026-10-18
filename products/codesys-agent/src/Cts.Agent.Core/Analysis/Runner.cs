using System;
using System.Collections.Generic;
using System.Linq;
using Cts.Agent;

namespace Cts.Analysis
{
    // Runs the enabled rules over a snapshot. A rule that throws or cannot get
    // what it needs becomes a diagnostic and marks the run incomplete; it never
    // stops the run. The order of findings is the same on every run.
    internal static class Runner
    {
        static readonly string[] NeedRead = { Needs.BlockStructure, Needs.Declarations, Needs.ExecutionGraph, Needs.ProjectSymbols };

        // The rules to run: the enabled ones, or those named (an explicit name
        // turns on a rule that is off by default; the config can still turn
        // it off).
        internal static List<Rule> Select(AnalyzeConfig config, ICollection<string> only)
        {
            var catalog = RuleCatalog.All;
            if (only != null && only.Count > 0)
            {
                var unknown = only.Where(id => catalog.All(rule => rule.Id != id)).OrderBy(id => id, StringComparer.Ordinal).ToList();
                if (unknown.Count > 0) throw new ArgumentException("unknown analysis rule(s): " + string.Join(", ", unknown));
                return catalog.Where(rule => only.Contains(rule.Id) && config.EnabledFor(rule.Id, true)).ToList();
            }
            return catalog.Where(rule => config.EnabledFor(rule.Id, null)).ToList();
        }

        // *step* hears each rule as it starts: its number, how many run, its id.
        internal static AnalysisResult Run(Snapshot snapshot, AnalyzeConfig config, List<Rule> rules, Action<int, int, string> step)
        {
            var result = new AnalysisResult { Files = snapshot.Directives.Count, ExcludedFromBuild = snapshot.Units.Count(unit => unit.ExcludedFromBuild) };
            snapshot = snapshot.Built();
            var context = new RuleContext(snapshot, config);
            result.RulesRun = rules.Select(rule => rule.Id).OrderBy(id => id, StringComparer.Ordinal).ToList();
            var unreadable = snapshot.Diagnostics.FirstOrDefault(d => d.Kind == "project-read" && d.Location.Path.EndsWith(".st", StringComparison.Ordinal));
            var skipped = new HashSet<string>();
            foreach (var rule in rules)
            {
                if (context.Visible(rule).Count == 0) continue;
                CheckOptions(rule, config, result);
                var missing = rule.Requires.Where(NeedRead.Contains).OrderBy(need => need, StringComparer.Ordinal).FirstOrDefault();
                if (unreadable != null && missing != null)
                {
                    skipped.Add(rule.Id);
                    result.Incomplete(new Diagnostic(missing, "cannot read .st file(s) (e.g. " + unreadable.Location.Path + "); declarations and project symbols are incomplete", ruleId: rule.Id));
                }
            }
            var running = rules.Where(rule => !skipped.Contains(rule.Id) && context.Visible(rule).Count > 0).ToList();
            for (var number = 0; number < running.Count; number++)
            {
                var rule = running[number];
                step(number + 1, running.Count, rule.Id);
                context.Active = rule;
                if (rule.Requires.Contains(Needs.Declarations) || rule.Requires.Contains(Needs.ProjectSymbols))
                    foreach (var unit in context.Visible(rule).Where(unit => unit.Kind == Kinds.Unknown))
                        result.Incomplete(new Diagnostic("st-parse", "cannot parse declarations of " + unit.Id, new Location(unit.SourcePath), rule.Id, unit.Id));
                if (rule.PerUnit)
                {
                    foreach (var unit in context.Visible(rule).Where(unit => rule.Kinds.Contains(unit.Kind)))
                        Collect(rule, () => rule.Check(unit, context), result, config, unit);
                }
                else Collect(rule, () => rule.Check(context), result, config, null);
            }
            MergeFindings(result, config, rules);
            FingerprintAll(result.Findings);
            result.Unfiltered = new HashSet<string>(result.Findings.Select(f => f.Fingerprint));
            ApplyDirectives(result, snapshot);
            result.Sort();
            return result;
        }

        static void CheckOptions(Rule rule, AnalyzeConfig config, AnalysisResult result)
        {
            var configured = config.OptionsFor(rule.Id);
            foreach (var name in configured.Keys.OrderBy(k => k, StringComparer.Ordinal))
            {
                if (!rule.Options.TryGetValue(name, out var declared))
                {
                    var known = rule.Options.Keys.OrderBy(k => k, StringComparer.Ordinal).ToList();
                    result.Incomplete(new Diagnostic("rule-option", rule.Id + ": unknown option '" + name + "' (declared: " + (known.Count == 0 ? "none" : string.Join(", ", known)) + ")", ruleId: rule.Id));
                }
                else if (RuleContext.Coerce(configured[name], declared) == null)
                    result.Incomplete(new Diagnostic("rule-option", rule.Id + ": option '" + name + "' has type " + RuleContext.TypeName(configured[name]) + ", expected " + RuleContext.TypeName(declared) + "; using default " + Json.Serialize(declared), ruleId: rule.Id));
            }
        }

        // The one place a rule's output lands: identity and the configured
        // severity are stamped here, from the catalog.
        static void Collect(Rule rule, Func<IEnumerable<Finding>> check, AnalysisResult result, AnalyzeConfig config, Unit unit)
        {
            List<Finding> found;
            try { found = check().Where(f => f != null).ToList(); }
            catch (Exception error)
            {
                result.Incomplete(unit == null
                    ? new Diagnostic("rule-error", rule.Id + " failed: " + error.Message, ruleId: rule.Id)
                    : new Diagnostic("rule-error", rule.Id + " failed on " + unit.Id + ": " + error.Message, new Location(unit.SourcePath), rule.Id, unit.Id));
                return;
            }
            foreach (var finding in found)
            {
                finding.RuleId = rule.Id;
                finding.RuleTitle = rule.Title;
                finding.Severity = config.SeverityFor(rule.Id, rule.Severity);
                result.Findings.Add(finding);
            }
        }

        // Findings a rule declares to be one problem become their first
        // member widened over the group, so its fingerprint stays the one that
        // member had alone.
        static void MergeFindings(AnalysisResult result, AnalyzeConfig config, List<Rule> rules)
        {
            var merged = new List<Finding>();
            foreach (var group in result.Findings.GroupBy(f => f.RuleId + "\n" + f.UnitId))
            {
                var rule = rules.FirstOrDefault(r => r.Id == group.First().RuleId);
                var enabled = rule != null && rule.Merge != null && (!rule.Options.TryGetValue("merge", out var declared) || (bool)(RuleContext.Coerce(config.OptionsFor(rule.Id).TryGetValue("merge", out var value) ? value : null, declared) ?? declared));
                if (!enabled) merged.AddRange(group);
                else if (rule.Merge == "adjacent") merged.AddRange(MergeAdjacent(group.ToList()));
                else merged.AddRange(group.GroupBy(Identity).Select(members => Collapse(members.ToList(), false)));
            }
            result.Findings = merged;
        }

        static IEnumerable<Finding> MergeAdjacent(List<Finding> group)
        {
            var merged = group.Where(f => !f.Location.Line.HasValue).ToList();
            var lined = group.Where(f => f.Location.Line.HasValue).OrderBy(f => f.Location.Line.Value).ThenBy(f => f.Location.Column ?? 0).ToList();
            if (lined.Count == 0) return merged;
            var current = new List<Finding> { lined[0] };
            foreach (var finding in lined.Skip(1))
            {
                var previous = current[current.Count - 1].Location;
                if (finding.Location.Line.Value <= (previous.EndLine ?? previous.Line ?? 0) + 1) current.Add(finding);
                else { merged.Add(Collapse(current, true)); current = new List<Finding> { finding }; }
            }
            merged.Add(Collapse(current, true));
            return merged;
        }

        static Finding Collapse(List<Finding> members, bool span)
        {
            var first = members[0];
            if (members.Count == 1) return first;
            var last = members[members.Count - 1];
            if (span)
            {
                first.Location.EndLine = last.Location.EndLine ?? last.Location.Line;
                first.Location.EndColumn = last.Location.EndColumn ?? last.Location.Column;
            }
            first.MemberCount = members.Count;
            first.MemberLines = members.Where(m => m.Location.Line.HasValue && m.Location.Line.Value != 0).Select(m => m.Location.Line.Value).ToList();
            return first;
        }

        static string Identity(Finding f) => f.RuleId + "\n" + f.UnitId + "\n" + (string.IsNullOrEmpty(f.Anchor) ? f.Message : f.Anchor) + "\n" + Fingerprints.NormalizeContext(f.Context);

        // Exact duplicates are numbered in document order; the first keeps the
        // plain identity, so a baseline written before stays valid.
        static void FingerprintAll(List<Finding> findings)
        {
            foreach (var group in findings.Where(f => string.IsNullOrEmpty(f.Fingerprint)).GroupBy(Identity))
            {
                var members = group.Count() > 1 ? group.OrderBy(f => f.Location.Line ?? 0).ThenBy(f => f.Location.Column ?? 0).ToList() : group.ToList();
                for (var occurrence = 0; occurrence < members.Count; occurrence++)
                {
                    var f = members[occurrence];
                    f.Fingerprint = Fingerprints.Of(f.RuleId, f.UnitId, string.IsNullOrEmpty(f.Anchor) ? f.Message : f.Anchor, f.Context, occurrence);
                }
            }
        }

        // "cts:ignore-file" directives: their findings go, their mistakes are reported.
        static void ApplyDirectives(AnalysisResult result, Snapshot snapshot)
        {
            var firstUnit = new Dictionary<string, Unit>(StringComparer.Ordinal);
            foreach (var unit in snapshot.Units) if (!firstUnit.ContainsKey(unit.SourcePath)) firstUnit[unit.SourcePath] = unit;
            foreach (var file in snapshot.Directives)
            {
                var unitId = firstUnit.TryGetValue(file.Key, out var unit) ? unit.Id : null;
                foreach (var issue in file.Value.Issues)
                    result.Diagnostics.Add(new Diagnostic(issue.Item1, issue.Item2 + " in cts:ignore-file directive", new Location(file.Key, issue.Item3, 1), unitId: unitId));
                foreach (var id in file.Value.Rules.Where(id => id != "*" && RuleCatalog.All.All(rule => rule.Id != id)).OrderBy(id => id, StringComparer.Ordinal))
                    result.Diagnostics.Add(new Diagnostic("directive-unknown-rule", "unknown rule " + id + " in cts:ignore-file directive", new Location(file.Key, 1, 1), id, unitId));
            }
            var kept = result.Findings.Where(f => !(snapshot.Directives.TryGetValue(f.Location.Path, out var directives) && (directives.Rules.Contains("*") || directives.Rules.Contains(f.RuleId)))).ToList();
            var ignored = result.Findings.Count - kept.Count;
            result.Findings = kept;
            result.Suppressed += ignored;
            result.SuppressedByDirective += ignored;
        }

        // Suppressed and baselined findings leave the result; entries that
        // match no finding of this run are reported stale.
        internal static void Filter(AnalysisResult result, ICollection<string> suppressed, ICollection<string> baselined)
        {
            result.StaleSuppressions = suppressed.Where(s => !result.Unfiltered.Contains(s)).Distinct().OrderBy(s => s, StringComparer.Ordinal).ToList();
            result.StaleBaselined = baselined.Where(s => !result.Unfiltered.Contains(s)).Distinct().OrderBy(s => s, StringComparer.Ordinal).ToList();
            var bySuppression = result.Findings.Count(f => suppressed.Contains(f.Fingerprint));
            result.Baselined = result.Findings.Count(f => !suppressed.Contains(f.Fingerprint) && baselined.Contains(f.Fingerprint));
            result.Findings = result.Findings.Where(f => !suppressed.Contains(f.Fingerprint) && !baselined.Contains(f.Fingerprint)).ToList();
            result.Suppressed = result.SuppressedByDirective + bySuppression;
            result.Sort();
        }

        // 3 incomplete under incomplete=error, 1 a finding at or above
        // fail_on, else 0.
        internal static int ExitCode(AnalysisResult result, AnalyzeConfig config)
        {
            if (config.Incomplete == "error" && !result.Complete) return 3;
            return result.Findings.Any(f => Severity.Rank(f.Severity) <= Severity.Rank(config.FailOn)) ? 1 : 0;
        }
    }
}
