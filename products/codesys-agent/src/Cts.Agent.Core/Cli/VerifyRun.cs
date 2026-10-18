using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Xml;
using Cts.Agent;
using Cts.Analysis;
using Cts.Visu;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{

    internal static partial class VerifyCommand
    {
        // One run of the gate: its stages' results, and the agent the build,
        // test and deploy share -- asked for once, so a missing IDE costs one
        // probe, not one per stage.
        sealed class Run : IDisposable
        {
            readonly CliOptions _options;
            readonly IAgentHost _host;
            readonly string _root, _view;
            readonly List<StageResult> _stages = new List<StageResult>();
            KeyValuePair<AgentConnection, Hello>? _agent;
            string _noAgent;

            internal Run(CliOptions options, IAgentHost host, AnalyzeWorkspace workspace)
            {
                _options = options;
                _host = host;
                _root = workspace.Root;
                _view = workspace.View;
            }

            public void Dispose()
            {
                if (_agent != null) _agent.Value.Key.Dispose();
            }

            StageResult Find(string name) => _stages.FirstOrDefault(stage => stage.Name == name);

            static bool Credited(StageResult build) => build != null && build.Status == Pass && build.Complete;

            internal void Stage(string name)
            {
                // Tests of an application this run just failed to build say nothing.
                if (name == "test" && Find("build") is StageResult build && !Credited(build))
                {
                    _stages.Add(new StageResult("test", Skipped, "test needs a complete passing build in this run", "dependency_failed"));
                    return;
                }
                var clock = Stopwatch.StartNew();
                StageResult result;
                // A stage that breaks is reported as error; the others' verdicts stand.
                try
                {
                    result = name == "analyze" ? Analyze() : name == "visu-sketch" ? Sketches() : name == "build" ? Compile() : Test();
                }
                catch (Exception error) when (!(error is OutOfMemoryException))
                {
                    result = new StageResult(name, Error, Brief(error.GetType().Name + ": " + error.Message), "tool_error");
                }
                result.Ms = clock.ElapsedMilliseconds;
                _stages.Add(result);
            }

            StageResult Analyze()
            {
                var command = AnalyzeCommand.Commands[0];
                // --incomplete ignore keeps the stage's answer about the code;
                // the report judges incompleteness.
                var args = new List<string> { "analyze", "--workspace", _root, "--incomplete", "ignore" };
                if (_options.Text("fail_on") is string failOn) args.AddRange(new[] { "--fail-on", failOn });
                IDictionary<string, object> data;
                try
                {
                    data = AnalyzeCommand.Analyze(CliOptions.Parse(args, null, command), _host, _root);
                }
                catch (CliFailure failure)
                {
                    return new StageResult("analyze", Error, Brief(failure.Message), "tool_error");
                }
                var complete = Equals(data["complete"], true);
                var result = new StageResult("analyze", Int(data, "exit_code") == 0 ? Pass : Fail,
                    complete ? "" : "analysis incomplete: " + Maps(data, "diagnostics").Count() + " diagnostic(s)") { Complete = complete };
                // The most severe first, so the shown ones are the ones to read.
                foreach (var finding in Maps(data, "findings").OrderBy(finding => Severity.Rank(Convert.ToString(finding["severity"], CultureInfo.InvariantCulture))))
                {
                    var location = (IDictionary<string, object>)finding["location"];
                    result.Problems.Add(Problem(Convert.ToString(finding["message"], CultureInfo.InvariantCulture),
                        Convert.ToString(finding["severity"], CultureInfo.InvariantCulture), Convert.ToString(finding["rule_id"], CultureInfo.InvariantCulture),
                        Convert.ToString(Value(location, "path"), CultureInfo.InvariantCulture), Value(location, "line")));
                }
                var summary = (IDictionary<string, object>)data["summary"];
                result.Summary["findings"] = summary["total"];
                result.Summary["by_severity"] = summary["by_severity"];
                result.Summary["files"] = summary["files"];
                result.Summary["fail_on"] = data["fail_on"];
                result.Summary["by_rule"] = Maps(data, "findings").GroupBy(finding => Convert.ToString(finding["rule_id"], CultureInfo.InvariantCulture))
                    .OrderByDescending(group => group.Count()).ThenBy(group => group.Key, StringComparer.Ordinal)
                    .ToDictionary(group => group.Key, group => (object)group.Count());
                return result;
            }

            // The design lint of every sketch in .visu/; a generated preview is
            // the build's output, not a source.
            StageResult Sketches()
            {
                var folder = Path.Combine(_root, SketchFolder);
                var sketches = Directory.Exists(folder)
                    ? Directory.GetFiles(folder, "*.svg", SearchOption.AllDirectories)
                        .Where(path => path.EndsWith(".svg", StringComparison.OrdinalIgnoreCase)
                            && !path.EndsWith(".preview.svg", StringComparison.OrdinalIgnoreCase))
                        .OrderBy(path => path, StringComparer.Ordinal).ToList()
                    : new List<string>();
                if (sketches.Count == 0) return new StageResult("visu-sketch", Skipped, "no sketches in " + SketchFolder + "/", NothingToCheck);
                var result = new StageResult("visu-sketch", Pass);
                int errors = 0, unreadable = 0, unopened = 0;
                foreach (var path in sketches)
                {
                    var file = path.Substring(_root.Length).TrimStart('\\', '/').Replace('\\', '/');
                    string source;
                    try
                    {
                        source = File.ReadAllText(path);
                    }
                    catch (Exception error) when (error is IOException || error is UnauthorizedAccessException)
                    {
                        // A locked file is a check that could not look, not a design finding.
                        if (unopened++ == 0) result.Reason = Brief("could not lint " + file + ": " + error.Message);
                        continue;
                    }
                    IList<SketchLinter.Finding> findings;
                    try
                    {
                        findings = SketchLinter.Find(Sketch.Parse(source, _view, null, null, null));
                    }
                    catch (Exception error) when (error is XmlException || error is VisuException)
                    {
                        // A sketch that does not parse is a defect of the authored SVG.
                        unreadable++;
                        errors++;
                        result.Problems.Add(Problem("could not lint sketch: " + error.Message, "error", "sketch-unreadable", file));
                        continue;
                    }
                    foreach (var finding in findings)
                    {
                        // Only an error fails the gate, as cts visu lint without --strict.
                        if (finding.Severity == "error") errors++;
                        result.Problems.Add(Problem(finding.Message, finding.Severity, finding.Rule, file,
                            where: "elem " + finding.Index.ToString(CultureInfo.InvariantCulture)));
                    }
                }
                result.Summary["sketches"] = sketches.Count;
                result.Summary["findings"] = result.Problems.Count;
                result.Summary["errors"] = errors;
                if (unreadable > 0) result.Summary["unreadable"] = unreadable;
                if (unopened > 0) result.Summary["tool_errors"] = unopened;
                if (errors > 0) result.Status = Fail;
                else if (unopened > 0) result.Status = Error;
                if (unopened > 0)
                {
                    result.ReasonCode = "tool_error";
                    result.Complete = false;
                }
                return result;
            }

            // The agent for this sync folder, picked once; false with the reason
            // when none answers.
            bool Agent(out string why)
            {
                if (_agent == null && _noAgent == null)
                {
                    try
                    {
                        _agent = AgentChoice.Pick(_host, "verify", _options.TargetPid(), _options.ExpectProject, _root);
                        CliRun.ReportUserChanges(_agent.Value.Key, _agent.Value.Value, Console.Error);
                    }
                    catch (CliFailure failure)
                    {
                        _noAgent = failure.Cause;
                    }
                }
                why = _noAgent;
                return _agent != null;
            }

            IDictionary<string, object> Ask(params string[] args)
            {
                var command = CliCommands.Find(args);
                return CliRun.Execute(command, CliOptions.Parse(args, null, command), _agent.Value.Key, _host, _agent.Value.Value, Console.Error);
            }

            // What an agent call that broke means for a stage: a timeout or a lost
            // connection learned nothing (skipped); a refusal is the agent's error.
            static StageResult Broke(string stage, CliFailure failure, string budgetFlag)
            {
                return failure.Next == "cts status"
                    ? new StageResult(stage, Skipped, Brief(failure.Message) + " Raise the budget with " + budgetFlag + " N; cts status says when the IDE is done.",
                        "agent_timeout")
                    : new StageResult(stage, Error, Brief(failure.Message), "agent_refused");
            }

            // The build is credited to this sync folder only when the IDE holds
            // what the folder holds: an edit the IDE has not imported, or one
            // not synced to disk, would be compiled in its other text.
            StageResult Compile()
            {
                if (!Agent(out var why)) return new StageResult("build", Skipped, why, "agent_unavailable");
                var stale = Stale();
                if (stale != null) return stale;
                var budget = _options.Text("build_timeout");
                IDictionary<string, object> data;
                try
                {
                    data = budget == null ? Ask("build") : Ask("build", "--timeout", budget);
                }
                catch (CliFailure failure)
                {
                    return Broke("build", failure, "--build-timeout");
                }
                var result = new StageResult("build", Pass);
                var problems = new List<IDictionary<string, object>>();
                foreach (var message in BuildCommand.DistinctRows(Maps(data, "messages")))
                {
                    var severity = (Convert.ToString(Value(message, "severity"), CultureInfo.InvariantCulture) ?? "").ToLowerInvariant();
                    var kind = severity.Contains("error") ? "error" : severity.Contains("warning") ? "warning" : null;
                    if (kind == null) continue;
                    problems.Add(Problem(Convert.ToString(Value(message, "text"), CultureInfo.InvariantCulture) ?? "", kind,
                        Convert.ToString(Value(message, "code"), CultureInfo.InvariantCulture), Convert.ToString(Value(message, "file"), CultureInfo.InvariantCulture),
                        Value(message, "line"), Convert.ToString(Value(message, "object"), CultureInfo.InvariantCulture)));
                }
                result.Problems.AddRange(problems.Where(problem => Equals(problem["severity"], "error")));
                result.Problems.AddRange(problems.Where(problem => !Equals(problem["severity"], "error")));
                var errors = Int(data, "errors");
                result.Summary["application"] = Value(data, "application") ?? "";
                result.Summary["errors"] = errors;
                result.Summary["warnings"] = Value(data, "warnings") ?? 0;
                if (Value(data, "elapsed_seconds") is object elapsed) result.Summary["elapsed_seconds"] = elapsed;
                if (errors > 0) result.Status = Fail;
                if (Equals(Value(data, "diagnostics_complete"), false))
                {
                    // Without every message a clean count proves nothing.
                    result.Summary["diagnostics_complete"] = false;
                    result.Complete = false;
                    result.Reason = "compiler diagnostics are incomplete";
                    result.ReasonCode = "tool_error";
                    if (errors == 0) result.Status = Error;
                }
                return result;
            }

            StageResult Stale()
            {
                IDictionary<string, object> data;
                try
                {
                    data = Ask("compare", "--sync-folder", _root);
                }
                catch (CliFailure failure)
                {
                    return new StageResult("build", Skipped, Brief("cannot tell whether the IDE holds this sync folder: " + failure.Message), "identity_unknown");
                }
                var counts = Value(data, "summary") as IDictionary<string, object> ?? new Dictionary<string, object>();
                var differs = Differs.Where(key => Int(counts, key) > 0)
                    .ToDictionary(key => key, key => counts[key]);
                if (differs.Count == 0) return null;
                var result = new StageResult("build", Skipped, "the IDE differs from the sync folder ("
                    + string.Join(" ", differs.Select(pair => pair.Key + "=" + pair.Value)) + "); see cts compare, then cts import or cts sync", "stale_ide");
                result.Summary["differs"] = differs;
                return result;
            }

            // The JSON test plans of .test/, through the agent's test.run.
            StageResult Test()
            {
                if (!Agent(out var why)) return new StageResult("test", Skipped, why, "agent_unavailable");
                var parameters = new Dictionary<string, object> { { "folder", _root } };
                if (!string.IsNullOrEmpty(_options.Text("test_file"))) parameters["file"] = _options.Text("test_file");
                var hello = _agent.Value.Value;
                var seconds = _options.Text("test_timeout") is string budget
                    ? double.Parse(budget, CultureInfo.InvariantCulture)
                    : hello.TimeoutFor(DenyRules.RunTests) ?? TestSeconds;
                IDictionary<string, object> data;
                try
                {
                    data = new CliCall(_agent.Value.Key, _host, VerifyCommand.Command, _options, hello, seconds).Call(TestPlans.Method, parameters);
                }
                catch (CliFailure failure)
                {
                    return Broke("test", failure, "--test-timeout");
                }
                var status = Convert.ToString(Value(data, "status"), CultureInfo.InvariantCulture);
                var result = new StageResult("test", status == "SUCCESS" ? Pass : Fail);
                foreach (var plan in Maps(data, "results"))
                {
                    var file = Convert.ToString(Value(plan, "file"), CultureInfo.InvariantCulture);
                    if (Value(plan, "error") is object error) result.Problems.Add(Problem(Convert.ToString(error, CultureInfo.InvariantCulture), "error", file: file));
                    foreach (var test in Maps(plan, "tests").Where(test => Equals(Value(test, "status"), "FAIL")))
                        result.Problems.Add(Problem(Value(test, "name") + ": " + (Value(test, "error") ?? "failed"), "error", file: file));
                }
                if (Value(data, "summary") is IDictionary<string, object> summary)
                    foreach (var pair in summary) result.Summary[pair.Key] = pair.Value;
                result.Summary["status"] = status;
                if (status != "SUCCESS" && status != "FAIL")
                {
                    result.Status = Error;
                    result.Reason = "the agent's test run answered no verdict";
                    result.ReasonCode = "invalid_payload";
                    result.Complete = false;
                }
                else if (result.Status == Fail && result.Problems.Count == 0) result.Problems.Add(Problem("one or more tests failed", "error"));
                return result;
            }

            // cts download after a run with nothing failed: code this very run
            // rejected never goes to the PLC.
            internal void Deploy()
            {
                var failed = _stages.Where(stage => stage.Status == Fail).Select(stage => stage.Name).ToList();
                if (failed.Count > 0)
                {
                    _stages.Add(new StageResult("deploy", Skipped, "download skipped because these stages failed: " + string.Join(", ", failed),
                        "dependency_failed"));
                    return;
                }
                if (!Credited(Find("build")))
                {
                    _stages.Add(new StageResult("deploy", Skipped, "download skipped because the build did not deliver a complete pass", "build_not_ready"));
                    return;
                }
                var clock = Stopwatch.StartNew();
                var args = new List<string> { "download", "--ready-var", _options.Text("ready_var") };
                if (_options.Text("ready_timeout") is string ready) args.AddRange(new[] { "--ready-timeout", ready });
                if (_options.Text("download_timeout") is string budget) args.AddRange(new[] { "--timeout", budget });
                StageResult result;
                try
                {
                    var data = Ask(args.ToArray());
                    var isReady = Equals(Value(data, "ready"), true);
                    result = new StageResult("deploy", isReady ? Pass : Fail,
                        isReady ? "" : Convert.ToString(Value(data, "reason") ?? "the application did not become ready", CultureInfo.InvariantCulture));
                    foreach (var key in new[] { "downloaded", "started", "ready", "ready_after_s", "ready_var", "value" })
                        if (data.ContainsKey(key)) result.Summary[key] = data[key];
                }
                catch (CliFailure failure)
                {
                    result = new StageResult("deploy", Fail, Brief(failure.Message));
                    result.Summary["downloaded"] = false;
                    result.Summary["ready"] = false;
                }
                result.Ms = clock.ElapsedMilliseconds;
                _stages.Add(result);
            }

            internal IDictionary<string, object> Report(IList<string> selected)
            {
                var verdict = _stages.Any(stage => stage.Status == Fail) ? Fail : Pass;
                var complete = _stages.Count > 0 && !_stages.Any(stage => stage.Incomplete);
                var incomplete = _options.Text("incomplete") ?? "warn";
                var data = new Dictionary<string, object>
                {
                    { "schema_version", SchemaVersion },
                    { "verdict", verdict },
                    { "complete", complete },
                    { "exit_code", verdict == Fail ? 1 : incomplete == "error" && !complete ? 3 : 0 },
                    { "sync_folder", _root },
                    { "stages", _stages.Select(stage => (object)stage.ToJson()).ToList() },
                };
                var next = Next(selected, verdict);
                if (next.Count > 0) data["next"] = next.Cast<object>().ToList();
                if (!complete && incomplete == "warn")
                    data["note"] = "Incomplete: " + string.Join(", ", _stages.Where(stage => stage.Incomplete).Select(stage => stage.Name))
                        + " delivered no verdict. --incomplete error makes this fatal (exit 3).";
                return data;
            }

            // What to run next: the gate advises, not only judges.
            List<string> Next(IList<string> selected, string verdict)
            {
                var steps = new List<string>();
                foreach (var stage in _stages.Where(stage => stage.Status == Fail))
                {
                    if (stage.Name == "analyze")
                    {
                        steps.Add("cts analyze                 # every finding with its place");
                        steps.Add("cts analyze baseline create # the engineer's call: accept today's findings, fail only on new ones");
                    }
                    else if (stage.Name == "visu-sketch") steps.Add("cts visu lint --svg <sketch> --fix   # snaps the mechanical findings");
                    else if (stage.Name == "build") steps.Add("cts build                   # the compiler's messages");
                    else if (stage.Name == "test") steps.Add("cts verify --only test --json   # every failed test");
                }
                var build = Find("build");
                if (build != null && build.Status == Skipped)
                {
                    if (build.ReasonCode == "stale_ide" || build.ReasonCode == "identity_unknown")
                    {
                        steps.Add("cts compare                 # which objects differ, and on which side");
                        steps.Add("cts import                  # disk edits into the IDE; cts sync also brings IDE edits to disk");
                    }
                    else if (build.ReasonCode == "agent_unavailable")
                        steps.Add("cts project open --path <project> --launch   # an IDE, for the compiler's verdict");
                }
                if (!selected.Contains("test") && verdict != Fail && Directory.Exists(Path.Combine(_root, TestPlans.Folder)))
                    steps.Add("cts verify --with-test      # also run the .test/ plans");
                return steps;
            }
        }
    }
}
