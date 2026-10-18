using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;
using Cts.Analysis;

namespace Cts.Cli
{
    // `cts analyze`: static analysis of the sync folder's Structured Text,
    // offline (no IDE, no PLC); rules, explain, baseline and triage beside it.
    internal static class AnalyzeCommand
    {
        static readonly CliOption[] WorkspaceOptions =
        {
            CliOption.Text("--workspace", "workspace", "DIR", "The sync folder (default: the one around the current folder)"),
            CliOption.Text("--project-view", "project_view", "DIR", "Analyse this view folder instead of a sync folder's"),
            CliOption.Many("--rule", "rule", "ID", "Only this rule (repeatable); names a rule that is off by default too"),
            CliOption.Choice("--fail-on", "fail_on", "Exit 1 on a finding this severe or worse (default: the config's, else suspicious); never: exit 0 whatever is found",
                Severity.All.Concat(new[] { Severity.Never }).ToArray()),
            CliOption.Choice("--incomplete", "incomplete", "An incomplete analysis: warn (default), error (exit 3) or ignore", "warn", "error", "ignore"),
        };

        const string About = "Reads only the .st files of the sync folder's view; the analysis never talks to the IDE or the PLC. "
            + "Settings live in cds-text-sync.json under \"analyze\" (fail_on, incomplete, rules.<ID>.enabled|severity|options, scopes[{path, enabled, exclude}]); "
            + "state (baseline.json, suppressions.json, session.json) in .cts-analyze beside the view. "
            + "A file opts out with a comment: // cts:ignore-file CTS0001 -- the reason. "
            + "Exit 0 policy passed, 1 a finding at or above fail_on, 2 the analysis cannot start, 3 incomplete with --incomplete error.";

        internal static IList<CliCommand> Commands => new[]
        {
            new CliCommand
            {
                Name = "analyze", Summary = "Static analysis of the Structured Text (offline)", Description = About,
                Options = WorkspaceOptions.Concat(new[]
                {
                    CliOption.Many("--path", "path", "PATH", "Only the findings in this file or folder of the view (repeatable); the whole project is still read"),
                    CliOption.Switch("--changed", "changed", "Only the findings in the view files git sees changed since the last commit (new ones too); the whole project is still read"),
                    CliOption.Text("--sarif", "sarif", "FILE", "Also write the findings as SARIF 2.1.0 (code scanning)"),
                }).ToArray(),
                LocalExecute = Analyze, Build = BuildAnalyze,
            },
            new CliCommand
            {
                Name = "analyze", Sub = "rules", Summary = "List the analysis rules",
                Description = "Every rule: id, severity, title, the object kinds it checks; with --workspace whether that sync folder's settings run it. "
                    + "--enable and --disable write rules.<ID>.enabled in the sync folder's cds-text-sync.json first.",
                Options = new[]
                {
                    CliOption.Text("--workspace", "workspace", "DIR", "Also say whether this sync folder's settings run each rule (enabled), and the folder (workspace)"),
                    CliOption.Switch("--doc", "doc", "Also each rule's documentation (as cts analyze explain shows it)"),
                    CliOption.Many("--enable", "enable", "ID", "Turn this rule on for the sync folder (repeatable)"),
                    CliOption.Many("--disable", "disable", "ID", "Turn this rule off for the sync folder (repeatable)"),
                },
                LocalExecute = Rules, Build = BuildRules,
            },
            new CliCommand
            {
                Name = "analyze", Sub = "explain", Summary = "Show one analysis rule's documentation", Description = "What the rule finds, why it matters, and examples.",
                Arguments = "ID", ArgumentLimit = 1, ArgumentHelp = "Rule id, e.g. CTS0001",
                LocalExecute = (options, host, work) => Explain(options), Build = BuildExplain,
            },
            new CliCommand
            {
                Name = "analyze", Sub = "baseline", Summary = "Record, rewrite or check the analysis baseline",
                Description = "create records the current findings as accepted (once); update rewrites the record; check names the findings not in it and the entries no finding matches.",
                Arguments = "{create,update,check}", ArgumentLimit = 1, ArgumentHelp = "What to do with .cts-analyze/baseline.json",
                Options = WorkspaceOptions, LocalExecute = Baseline, Build = BuildBaseline,
            },
            new CliCommand
            {
                Name = "analyze", Sub = "triage", Summary = "Apply suppress / fix-later / baseline decisions to findings",
                Description = "FILE is a JSON list of {\"fingerprint\": \"cts1:...\", \"action\": \"suppress|fix-later|baseline\", \"reason\": \"...\", \"note\": \"...\"}; suppress needs a reason. Every decision must match a finding of this run, or nothing is written.",
                Options = WorkspaceOptions.Concat(new[] { CliOption.Needed("--apply", "apply", "FILE", "The decisions file") }).ToArray(),
                LocalExecute = Triage, Build = BuildTriage,
            },
        };

        static CliFailure Failure(string verb, string message, int exitCode = 2) => new CliFailure(verb, "refused", message, "cts " + verb.Replace('-', ' ') + " --help", exitCode);

        static Tuple<AnalyzeWorkspace, AnalyzeConfig, AnalysisResult> Run(CliOptions options, string work, string verb, bool applyState)
        {
            try
            {
                var workspace = AnalyzeWorkspace.Resolve(options.Text("workspace"), options.Text("project_view"), work);
                var config = AnalyzeConfig.Load(workspace.Root);
                if (options.Text("fail_on") != null) config.FailOn = options.Text("fail_on");
                if (options.Text("incomplete") != null) config.Incomplete = options.Text("incomplete");
                var only = options.Params.TryGetValue("rule", out var rules) ? ((IEnumerable<object>)rules).Select(r => Convert.ToString(r, CultureInfo.InvariantCulture).Trim().ToUpperInvariant()).ToList() : null;
                var result = Runner.Run(Snapshot.Read(workspace.View), config, Runner.Select(config, only), Progress(options.Progress));
                if (applyState)
                {
                    var suppressed = AnalyzeState.Suppressions(workspace.StateDir).Where(e => !AnalyzeState.Expired(e)).Select(e => JsonMap.Text(e, "fingerprint")).ToList();
                    Runner.Filter(result, new HashSet<string>(suppressed), AnalyzeState.Fingerprints(AnalyzeState.Baseline(workspace.StateDir)));
                }
                return Tuple.Create(workspace, config, result);
            }
            catch (Exception error) when (error is AnalyzeException || error is ArgumentException || error is IOException || error is UnauthorizedAccessException)
            {
                throw Failure(verb, error.Message);
            }
        }

        // A rule's turn as a stage line on stderr, at most twice a second: a
        // big project's analysis shows where it is, a small one's says nothing.
        static Action<int, int, string> Progress(TextWriter progress)
        {
            var clock = Stopwatch.StartNew();
            var said = TimeSpan.Zero;
            return (number, count, rule) =>
            {
                if (clock.Elapsed - said < TimeSpan.FromMilliseconds(500)) return;
                said = clock.Elapsed;
                progress.WriteLine("progress: rule " + number + "/" + count + " " + rule);
            };
        }

        internal static IDictionary<string, object> Analyze(CliOptions options, IAgentHost host, string work)
        {
            var run = Run(options, work, "analyze", true);
            var within = Within(options, run.Item1.View, work);
            var changed = options.Params.ContainsKey("changed") ? Changed(run.Item1.View) : null;
            if (within.Count > 0 || changed != null)
            {
                bool Inside(Location location) => (within.Count == 0 || within.Any(path => path.Length == 0 || location.Path.Equals(path, StringComparison.OrdinalIgnoreCase) || location.Path.StartsWith(path + "/", StringComparison.OrdinalIgnoreCase)))
                    && (changed == null || changed.Contains(location.Path));
                run.Item3.Findings = run.Item3.Findings.Where(finding => Inside(finding.Location)).ToList();
                run.Item3.Diagnostics.RemoveAll(diagnostic => diagnostic.Location.Path.Length > 0 && !Inside(diagnostic.Location));
            }
            var data = run.Item3.ToJson();
            data["exit_code"] = Runner.ExitCode(run.Item3, run.Item2);
            data["fail_on"] = run.Item2.FailOn;
            data["workspace"] = run.Item1.Root;
            data["project_view"] = run.Item1.View;
            if (changed != null) data["changed_files"] = changed.Count;
            var sarif = options.Text("sarif");
            if (sarif != null)
            {
                File.WriteAllText(sarif, Json.Pretty(Sarif(run.Item3)) + "\n", new UTF8Encoding(false));
                data["sarif"] = Path.GetFullPath(sarif);
            }
            return data;
        }

        // Each --path as a view-relative path with '/': a file or folder on
        // disk inside the view (absolute or from the current folder), else a
        // path from the view itself. One that names nothing in the view is
        // refused, so a typo never reads as "no findings". A '"' is dropped:
        // PowerShell 5.1 passes 'Folder\' as Folder" (a quote after a
        // trailing backslash), and a Windows path never holds one.
        static List<string> Within(CliOptions options, string view, string work)
        {
            var paths = new List<string>();
            if (!options.Params.TryGetValue("path", out var given)) return paths;
            var root = Path.GetFullPath(view).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
            foreach (var text in ((IEnumerable<object>)given).Select(item => Convert.ToString(item, CultureInfo.InvariantCulture).Replace("\"", "")))
            {
                var full = Path.GetFullPath(Path.Combine(work, text)).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                var relative = (full + Path.DirectorySeparatorChar).StartsWith(root, StringComparison.OrdinalIgnoreCase) && (File.Exists(full) || Directory.Exists(full))
                    ? full.Substring(Math.Min(full.Length, root.Length)) : text;
                relative = relative.Replace('\\', '/').Trim('/');
                var onDisk = Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
                if (!File.Exists(onDisk) && !Directory.Exists(onDisk)) throw Failure("analyze", "--path " + text + " names no file or folder in the view " + view);
                paths.Add(relative);
            }
            return paths;
        }

        // The view files git sees changed against HEAD (modified, staged or
        // new and not ignored), view-relative with '/'; before the first
        // commit every file is new.
        static HashSet<string> Changed(string view)
        {
            try
            {
                var head = GitRun.In(view, "rev-parse -q --verify HEAD");
                if (head.ExitCode > 1) throw new InvalidOperationException(head.Message);
                var changed = Files(view, head.ExitCode == 0 ? "diff --name-only -z --relative HEAD --" : "ls-files -z --cached");
                changed.UnionWith(Files(view, "ls-files -z --others --exclude-standard"));
                return changed;
            }
            catch (InvalidOperationException error) { throw Failure("analyze", "--changed needs the view in a git repository: " + error.Message); }
        }

        static HashSet<string> Files(string view, string args) =>
            new HashSet<string>(GitRepository.Run(view, args).Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries), StringComparer.OrdinalIgnoreCase);

        // A run that exits non-zero (findings at --fail-on, an incomplete run under --incomplete error)
        // says error, so the line agrees with the exit code.
        static Answer Ended(Answer answer, IDictionary<string, object> data)
        {
            var code = JsonMap.Int(data, "exit_code");
            if (code != 0) answer.Failed();
            return answer.Whole().WithExitCode(code);
        }

        static Answer BuildAnalyze(IDictionary<string, object> data)
        {
            var findings = (IList<object>)data["findings"];
            var diagnostics = (IList<object>)data["diagnostics"];
            var summary = (IDictionary<string, object>)data["summary"];
            var bySeverity = (IDictionary<string, object>)summary["by_severity"];
            var answer = new Answer().Add("findings", findings.Count);
            foreach (var severity in Severity.All) answer.Add(severity, bySeverity[severity]);
            answer.Add("diagnostics", diagnostics.Count).Add("fail_on", data["fail_on"]);
            if (JsonMap.Int(summary, "suppressed") > 0) answer.Add("suppressed", summary["suppressed"]);
            if (JsonMap.Int(summary, "baselined") > 0) answer.Add("baselined", summary["baselined"]);
            if (JsonMap.Int(summary, "excluded_from_build") > 0) answer.Add("excluded", summary["excluded_from_build"]);
            if (data.ContainsKey("changed_files")) answer.Add("changed_files", data["changed_files"]);
            if (data.ContainsKey("sarif")) answer.Add("sarif", data["sarif"]);
            if (!Equals(data["complete"], true)) answer.Partial();
            foreach (IDictionary<string, object> f in findings)
            {
                var location = (IDictionary<string, object>)f["location"];
                var line = location.TryGetValue("line", out var l) ? Convert.ToString(l, CultureInfo.InvariantCulture) : "?";
                if (location.TryGetValue("end_line", out var end) && !Equals(end, l)) line += "-" + end;
                var column = location.TryGetValue("column", out var c) ? Convert.ToString(c, CultureInfo.InvariantCulture) : "?";
                answer.Detail("[" + f["rule_id"] + "] " + f["severity"] + "  " + location["path"] + ":" + line + ":" + column + "  " + f["message"]
                    + (f.TryGetValue("member_count", out var count) ? " (x" + count + ")" : ""));
            }
            foreach (IDictionary<string, object> d in diagnostics)
            {
                var location = (IDictionary<string, object>)d["location"];
                var path = Convert.ToString(location["path"], CultureInfo.InvariantCulture);
                answer.Detail("  diagnostic " + (path.Length == 0 ? "-" : path + ":" + (location.TryGetValue("line", out var line) ? line : "?")) + "  "
                    + (d.TryGetValue("rule_id", out var rule) ? "[" + rule + "] " : "") + d["kind"] + ": " + d["message"]);
            }
            var stale = ((IList<object>)summary["stale_suppressions"]).Count;
            if (stale > 0) answer.Detail(stale + " suppression(s) match no finding any more");
            // Last, where a long list ends: which rules to narrow to (--rule).
            var byRule = (IDictionary<string, object>)summary["by_rule"];
            if (byRule.Count > 1)
                answer.Detail("by rule: " + string.Join(", ", byRule.OrderByDescending(rule => JsonMap.Int(byRule, rule.Key)).ThenBy(rule => rule.Key, StringComparer.Ordinal).Select(rule => rule.Key + " " + rule.Value)));
            return Ended(answer, data);
        }

        static IDictionary<string, object> Rules(CliOptions options, IAgentHost host, string work)
        {
            AnalyzeConfig config = null;
            string root = null;
            var enable = Ids(options, "enable");
            var disable = Ids(options, "disable");
            var switching = enable.Concat(disable).ToList();
            var unknown = switching.FirstOrDefault(id => RuleCatalog.All.All(rule => rule.Id != id));
            if (unknown != null) throw Failure("analyze-rules", "unknown rule " + unknown + "; cts analyze rules lists them");
            var both = enable.Intersect(disable).FirstOrDefault();
            if (both != null) throw Failure("analyze-rules", both + " is both enabled and disabled");
            if (options.Text("workspace") != null || switching.Count > 0)
            {
                try
                {
                    root = AnalyzeWorkspace.Resolve(options.Text("workspace"), null, work).Root;
                    if (switching.Count > 0) Switch(root, enable, disable);
                    config = AnalyzeConfig.Load(root);
                }
                catch (Exception error) when (error is AnalyzeException || error is ArgumentException || error is IOException || error is UnauthorizedAccessException || error is JsonException)
                {
                    throw Failure("analyze-rules", error.Message);
                }
            }
            var data = new Dictionary<string, object>
            {
                ["rules"] = RuleCatalog.All.Select(rule =>
                {
                    var entry = new Dictionary<string, object>
                    {
                        ["id"] = rule.Id, ["title"] = rule.Title, ["severity"] = rule.Severity, ["topic"] = rule.Topic,
                        ["scope"] = rule.PerUnit ? "unit" : "project",
                        ["kinds"] = rule.Kinds.OrderBy(k => k, StringComparer.Ordinal).Cast<object>().ToList(),
                        ["requires"] = rule.Requires.OrderBy(r => r, StringComparer.Ordinal).Cast<object>().ToList(),
                        ["summary"] = rule.Summary,
                        ["default"] = new AnalyzeConfig().EnabledFor(rule.Id, null) ? "on" : "off",
                    };
                    if (config != null) entry["enabled"] = config.EnabledFor(rule.Id, null);
                    if (options.Params.ContainsKey("doc")) entry["doc"] = rule.Doc();
                    return (object)entry;
                }).ToList(),
            };
            if (root != null) data["workspace"] = root;
            if (switching.Count > 0) data["switched"] = switching.Cast<object>().ToList();
            return data;
        }

        static List<string> Ids(CliOptions options, string key) =>
            options.Params.TryGetValue(key, out var ids) ? ((IEnumerable<object>)ids).Select(id => Convert.ToString(id, CultureInfo.InvariantCulture).Trim().ToUpperInvariant()).ToList() : new List<string>();

        // rules.<ID>.enabled under "analyze" in *root*'s cds-text-sync.json;
        // the rest of the file stays as it is.
        static void Switch(string root, IEnumerable<string> enable, IEnumerable<string> disable)
        {
            var text = ProjectInfo.Settings(root);
            var data = text.Trim().Length == 0 ? new Dictionary<string, object>() : Json.Parse(text) as IDictionary<string, object>
                ?? throw new AnalyzeException("cds-text-sync.json is not a JSON object");
            var rules = Table(Table(data, "analyze"), "rules");
            foreach (var id in enable) Table(rules, id)["enabled"] = true;
            foreach (var id in disable) Table(rules, id)["enabled"] = false;
            ProjectInfo.SaveSettings(root, Json.Pretty(data) + "\n");
        }

        static IDictionary<string, object> Table(IDictionary<string, object> parent, string key)
        {
            if (parent.TryGetValue(key, out var value) && value is IDictionary<string, object> table) return table;
            if (value != null) throw new AnalyzeException(key + " in cds-text-sync.json is not an object");
            var made = new Dictionary<string, object>();
            parent[key] = made;
            return made;
        }

        static Answer BuildRules(IDictionary<string, object> data)
        {
            var rules = (IList<object>)data["rules"];
            var answer = new Answer().Add("rules", rules.Count);
            if (data.TryGetValue("switched", out var switched))
                foreach (var id in (IList<object>)switched)
                {
                    var rule = rules.Cast<IDictionary<string, object>>().First(r => Equals(r["id"], id));
                    answer.Add(Convert.ToString(id, CultureInfo.InvariantCulture), Equals(rule["enabled"], true) ? "on" : "off");
                }
            foreach (IDictionary<string, object> rule in rules)
                answer.Detail(rule["id"] + " [" + rule["severity"] + "] " + rule["title"] + (Equals(rule["default"], "off") ? " (off by default)" : "") + " -- " + rule["summary"]);
            return answer.Whole();
        }

        static IDictionary<string, object> Explain(CliOptions options)
        {
            var id = (options.Arguments.FirstOrDefault() ?? "").Trim().ToUpperInvariant();
            if (id.Length == 0) throw Failure("analyze-explain", "explain needs a rule id: cts analyze explain CTS0001");
            var rule = RuleCatalog.All.FirstOrDefault(r => r.Id == id) ?? throw Failure("analyze-explain", "unknown rule " + id + "; cts analyze rules lists them");
            return new Dictionary<string, object>
            {
                ["id"] = rule.Id, ["title"] = rule.Title, ["severity"] = rule.Severity, ["scope"] = rule.PerUnit ? "unit" : "project",
                ["kinds"] = rule.Kinds.OrderBy(k => k, StringComparer.Ordinal).Cast<object>().ToList(), ["doc"] = rule.Doc(),
            };
        }

        static Answer BuildExplain(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("rule", data["id"]).Add("severity", data["severity"]).Add("scope", data["scope"]);
            answer.Detail(data["id"] + " - " + data["title"]);
            answer.Detail("applies to: " + string.Join(", ", (IList<object>)data["kinds"]));
            foreach (var line in Convert.ToString(data["doc"], CultureInfo.InvariantCulture).Split('\n')) answer.Details.Add(line);
            return answer.Whole();
        }

        static IDictionary<string, object> Baseline(CliOptions options, IAgentHost host, string work)
        {
            var action = options.Arguments.FirstOrDefault() ?? "";
            if (!new[] { "create", "update", "check" }.Contains(action)) throw Failure("analyze-baseline", "baseline needs an action: create, update or check");
            var run = Run(options, work, "analyze-baseline", false);
            var stateDir = run.Item1.StateDir;
            List<IDictionary<string, object>> existing;
            try { existing = action == "update" && File.Exists(Path.Combine(stateDir, "baseline.json")) ? null : AnalyzeState.Baseline(stateDir); }
            catch (AnalyzeException error) { throw Failure("analyze-baseline", error.Message); }
            var findings = run.Item3.Findings;
            var entries = findings.Select(f => (IDictionary<string, object>)new Dictionary<string, object> { ["fingerprint"] = f.Fingerprint, ["rule_id"] = f.RuleId, ["unit_id"] = f.UnitId ?? "", ["message"] = f.Message }).ToList();
            if (action == "create")
            {
                if (existing.Count > 0) throw Failure("analyze-baseline", "a baseline already exists; cts analyze baseline update rewrites it");
                AnalyzeState.WriteBaseline(stateDir, entries, null);
                return new Dictionary<string, object> { ["action"] = action, ["entries"] = entries.Count, ["exit_code"] = 0 };
            }
            if (action == "update")
            {
                string created;
                try { created = AnalyzeState.BaselineCreated(stateDir); }
                catch (AnalyzeException) { created = null; }
                AnalyzeState.WriteBaseline(stateDir, entries, created);
                return new Dictionary<string, object> { ["action"] = action, ["entries"] = entries.Count, ["exit_code"] = 0 };
            }
            var known = AnalyzeState.Fingerprints(existing);
            var current = new HashSet<string>(findings.Select(f => f.Fingerprint));
            var fresh = findings.Where(f => !known.Contains(f.Fingerprint)).ToList();
            var bad = fresh.Any(f => Severity.Rank(f.Severity) <= Severity.Rank(run.Item2.FailOn));
            return new Dictionary<string, object>
            {
                ["action"] = action, ["total"] = findings.Count, ["baselined"] = known.Count, ["new"] = fresh.Count,
                ["stale"] = known.Count(k => !current.Contains(k)),
                ["new_findings"] = fresh.Select(f => (object)f.ToJson()).ToList(),
                ["stale_entries"] = known.Where(k => !current.Contains(k)).OrderBy(k => k, StringComparer.Ordinal).Cast<object>().ToList(),
                ["exit_code"] = bad ? 1 : 0,
            };
        }

        static Answer BuildBaseline(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("action", data["action"]);
            if (data.ContainsKey("entries")) return answer.Add("entries", data["entries"]);
            answer.Add("findings", data["total"]).Add("baselined", data["baselined"]).Add("new", data["new"]).Add("stale", data["stale"]);
            foreach (IDictionary<string, object> f in (IList<object>)data["new_findings"])
            {
                var location = (IDictionary<string, object>)f["location"];
                answer.Detail("  new " + f["rule_id"] + " " + location["path"] + ":" + (location.TryGetValue("line", out var line) ? line : "?") + " " + f["message"]);
            }
            foreach (var stale in (IList<object>)data["stale_entries"]) answer.Detail("  stale " + stale);
            return Ended(answer, data);
        }

        static IDictionary<string, object> Triage(CliOptions options, IAgentHost host, string work)
        {
            var run = Run(options, work, "analyze-triage", false);
            try
            {
                AnalyzeState.Baseline(run.Item1.StateDir);
                var summary = AnalyzeState.Triage(run.Item1.StateDir, run.Item3, options.Text("apply"));
                return new Dictionary<string, object> { ["applied"] = summary.Values.Sum(v => Convert.ToInt32(v, CultureInfo.InvariantCulture)), ["summary"] = summary };
            }
            catch (AnalyzeException error) { throw Failure("analyze-triage", error.Message); }
        }

        static Answer BuildTriage(IDictionary<string, object> data)
        {
            var summary = (IDictionary<string, object>)data["summary"];
            return new Answer().Add("applied", data["applied"]).Add("suppressed", summary["suppressed"]).Add("baselined", summary["baselined"]).Add("fix_later", summary["fix_later"]);
        }

        static readonly Dictionary<string, string> Levels = new Dictionary<string, string> { ["danger"] = "error", ["suspicious"] = "warning", ["style"] = "note" };

        // SARIF 2.1.0, for code scanning: one result per finding.
        static IDictionary<string, object> Sarif(AnalysisResult result)
        {
            var rules = result.Findings.GroupBy(f => f.RuleId).OrderBy(g => g.Key, StringComparer.Ordinal).Select(g =>
            {
                var f = g.First();
                var rule = RuleCatalog.All.First(r => r.Id == f.RuleId);
                return (object)new Dictionary<string, object>
                {
                    ["id"] = f.RuleId, ["name"] = f.RuleTitle, ["shortDescription"] = new Dictionary<string, object> { ["text"] = f.RuleTitle },
                    ["fullDescription"] = new Dictionary<string, object> { ["text"] = rule.Summary }, ["help"] = new Dictionary<string, object> { ["text"] = rule.Summary },
                    ["defaultConfiguration"] = new Dictionary<string, object> { ["level"] = Levels[f.Severity] },
                    ["properties"] = new Dictionary<string, object> { ["topic"] = rule.Topic, ["scope"] = rule.PerUnit ? "unit" : "project" },
                };
            }).ToList();
            var results = result.Findings.Select(f =>
            {
                var region = new Dictionary<string, object>();
                if (f.Location.Line.HasValue) region["startLine"] = f.Location.Line.Value;
                if (f.Location.Column.HasValue) region["startColumn"] = f.Location.Column.Value;
                if (f.Location.EndLine.HasValue) region["endLine"] = f.Location.EndLine.Value;
                if (f.Location.EndColumn.HasValue) region["endColumn"] = f.Location.EndColumn.Value;
                return (object)new Dictionary<string, object>
                {
                    ["ruleId"] = f.RuleId, ["level"] = Levels[f.Severity], ["message"] = new Dictionary<string, object> { ["text"] = f.Message },
                    ["partialFingerprints"] = new Dictionary<string, object> { ["ctsAnalyzeFingerprint"] = f.Fingerprint },
                    ["locations"] = new List<object> { new Dictionary<string, object> { ["physicalLocation"] = new Dictionary<string, object>
                    {
                        ["artifactLocation"] = new Dictionary<string, object> { ["uri"] = f.Location.Path }, ["region"] = region,
                    } } },
                };
            }).ToList();
            return new Dictionary<string, object>
            {
                ["$schema"] = "https://json.schemastore.org/sarif-2.1.0.json",
                ["version"] = "2.1.0",
                ["runs"] = new List<object>
                {
                    new Dictionary<string, object>
                    {
                        ["tool"] = new Dictionary<string, object> { ["driver"] = new Dictionary<string, object> { ["name"] = "cts analyze", ["rules"] = rules } },
                        ["results"] = results,
                        ["invocations"] = new List<object>
                        {
                            new Dictionary<string, object>
                            {
                                ["executionSuccessful"] = result.Complete,
                                ["toolExecutionNotifications"] = result.Diagnostics.Select(d => (object)new Dictionary<string, object>
                                {
                                    ["level"] = "warning", ["message"] = new Dictionary<string, object> { ["text"] = d.Message }, ["descriptor"] = new Dictionary<string, object> { ["id"] = d.Kind },
                                }).ToList(),
                            },
                        },
                    },
                },
            };
        }
    }
}
