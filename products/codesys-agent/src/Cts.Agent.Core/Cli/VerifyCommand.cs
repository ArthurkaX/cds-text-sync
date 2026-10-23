using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Cts.Analysis;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts verify`: every check that applies, cheapest first, reduced to one
    // verdict and one exit code, so an agent asks one question instead of
    // running four checks and weighing four answers. A stage that could not
    // run is skipped or error -- incomplete, never fail: an agent with no IDE
    // open must not be told it broke the project. The offline stages only
    // read; build updates the IDE; test and --deploy reach the PLC.
    internal static partial class VerifyCommand
    {
        const string Pass = "pass", Fail = "fail", Skipped = "skipped", Error = "error", NothingToCheck = "nothing_to_check";
        const int SchemaVersion = 2;
        // Per stage in the text answer: three hundred findings in an agent's
        // context make the verdict less useful, not more; --json carries them all.
        const int MaxProblems = 20;
        // A reason is read by an agent: the first line, capped.
        const int MaxReason = 200;
        // A test run gets this much when the agent sizes nothing.
        const double TestSeconds = 120;
        const string SketchFolder = ".visu";
        static readonly string[] Stages = { "analyze", "visu-sketch", "build", "test" };
        // The compare counts that mean the IDE and the sync folder differ.
        static readonly string[] Differs = { "modified", "added", "deleted", "not_importable", "ide_changed" };

        internal static readonly CliCommand Command = new CliCommand
        {
            Name = "verify",
            Summary = "Run every applicable check and return one verdict",
            Description = "Runs the offline checks -- analyze (static analysis of the view's .st files) and visu-sketch (design lint "
                + "of every SVG sketch in .visu/) -- then build, the compiler, when an in-IDE agent answers, and reduces them to "
                + "one verdict with one exit code. --with-test also runs the JSON test plans of .test/ against the PLC (cts guide "
                + "tests); --deploy follows a run with no failed stage with cts download: download, start, and the wait until "
                + "--ready-var changes.\n\n"
                + "A stage is pass, fail (it found real problems), skipped (it could not run) or error (the stage or the agent "
                + "failed), with a stable reason_code beside its reason. The verdict is fail only when a stage failed; skipped and "
                + "error leave it alone and make the run incomplete. The build stage first compares the sync folder with the IDE "
                + "as cts compare does: when they differ it is skipped (stale_ide) rather than credit a build of text that is not "
                + "on disk.\n\n"
                + "Exit 0 pass, 1 a stage failed, 2 verify could not start (no sync folder or view), 3 incomplete with "
                + "--incomplete error.\n\n"
                + "  cts verify --sync-folder C:\\Projects\\Plant\n"
                + "  cts verify --only analyze,visu-sketch\n"
                + "  cts verify --with-test\n"
                + "  cts verify --deploy --ready-var GVL_Bench.nHeartbeat",
            Options = new[]
            {
                CliOption.Text("--sync-folder", "sync_folder", "PATH", "The sync folder or its view (default: the one around the current folder)"),
                CliOption.Text("--only", "only", "LIST", "Only these stages, comma-separated: " + string.Join(", ", Stages)),
                CliOption.Switch("--with-test", "with_test", "Also run the .test/ plans (connects to the PLC and starts code; cts guide tests)"),
                CliOption.Text("--test-file", "test_file", "NAME", "Run this plan of .test/ instead of every plan"),
                CliOption.Switch("--deploy", "deploy", "When no stage failed: download, start, and wait until ready"),
                CliOption.Text("--ready-var", "ready_var", "NAME", "With --deploy: the variable that must change (proves the task is cycling)"),
                CliOption.Int("--ready-timeout", "ready_timeout", "With --deploy: seconds to wait for readiness (default: 30)"),
                CliOption.Int("--download-timeout", "download_timeout", "With --deploy: the download's budget in seconds (default: sized by the agent)"),
                CliOption.Choice("--incomplete", "incomplete", "An incomplete run: warn (default), error (exit 3) or ignore", "warn", "error", "ignore"),
                CliOption.Choice("--fail-on", "fail_on", "The analysis severity that fails the analyze stage (default: the config's, else suspicious)",
                    Severity.All),
                CliOption.Int("--build-timeout", "build_timeout", "The build's budget in seconds (default: sized by the agent)"),
                CliOption.Int("--test-timeout", "test_timeout", "The test run's budget in seconds (default: sized by the agent, else 120)"),
            },
            LocalExecute = Execute,
            Build = Build,
        };

        static IDictionary<string, object> Execute(CliOptions options, IAgentHost host, string work)
        {
            var selected = Select(options.Text("only"), options.Params.ContainsKey("with_test"));
            var deploy = options.Params.ContainsKey("deploy");
            if (deploy && string.IsNullOrEmpty(options.Text("ready_var"))) throw Refused("--deploy needs --ready-var NAME");
            if (deploy && !selected.Contains("build")) throw Refused("--deploy needs the build stage; do not leave it out with --only");
            var folder = options.Text("sync_folder");
            AnalyzeWorkspace workspace;
            try
            {
                workspace = AnalyzeWorkspace.Resolve(folder, null, work);
            }
            catch (AnalyzeException error)
            {
                throw new CliFailure("verify", "no sync folder",
                    (folder == null ? "No sync folder with a project view here; pass --sync-folder or run from a sync folder." : error.Message)
                    + " Export the project once (cts export) to create the view.", "cts export", 2);
            }
            using (var run = new Run(options, host, workspace))
            {
                foreach (var name in selected) run.Stage(name);
                if (deploy) run.Deploy();
                return run.Report(selected);
            }
        }

        // The stages to run: --only's, in the registry's order, not the order
        // typed: the cheap offline checks run before the one that holds the IDE.
        static IList<string> Select(string only, bool withTest)
        {
            if (string.IsNullOrEmpty(only)) return Stages.Where(stage => stage != "test" || withTest).ToList();
            var wanted = only.Split(',').Select(name => name.Trim()).Where(name => name.Length > 0).ToList();
            if (wanted.Count == 0) throw Refused("--only names no stage");
            var unknown = wanted.Where(name => !Stages.Contains(name)).ToList();
            if (unknown.Count > 0) throw Refused("unknown stage(s): " + string.Join(", ", unknown) + ". Stages: " + string.Join(", ", Stages));
            return Stages.Where(wanted.Contains).ToList();
        }

        static CliFailure Refused(string message) => new CliFailure("verify", "refused", message, "cts verify --help", 2);

        static string Brief(string text)
        {
            var head = (text ?? "").Trim().Split('\n')[0].Trim();
            return head.Length > MaxReason ? head.Substring(0, MaxReason - 3) + "..." : head;
        }

        // One thing to fix, in the one shape every stage reports: the analyzer's
        // rule and line, the sketch lint's element, the compiler's code and object.
        static IDictionary<string, object> Problem(string message, string severity, string rule = null, string file = null, object line = null,
            string where = null)
        {
            var problem = new Dictionary<string, object> { { "message", message } };
            if (!string.IsNullOrEmpty(severity)) problem["severity"] = severity;
            if (!string.IsNullOrEmpty(rule)) problem["rule"] = rule;
            if (!string.IsNullOrEmpty(file)) problem["file"] = file;
            if (!string.IsNullOrEmpty(where)) problem["where"] = where;
            if (line != null) problem["line"] = line;
            return problem;
        }

        sealed class StageResult
        {
            internal string Name, Status, Reason = "", ReasonCode = "";
            internal bool Complete = true;
            internal long? Ms;
            internal readonly Dictionary<string, object> Summary = new Dictionary<string, object>();
            internal readonly List<IDictionary<string, object>> Problems = new List<IDictionary<string, object>>();

            internal StageResult(string name, string status, string reason = "", string reasonCode = "")
            {
                Name = name;
                Status = status;
                Reason = reason;
                ReasonCode = reasonCode;
            }

            // A stage that ran and covered only part of the project (a file the
            // analyzer could not read) is incomplete too, not a pass. A stage
            // with nothing to check owes no verdict.
            internal bool Incomplete => (Status == Skipped && ReasonCode != NothingToCheck) || Status == Error || !Complete;

            internal IDictionary<string, object> ToJson()
            {
                var data = new Dictionary<string, object> { { "stage", Name }, { "status", Status } };
                if (Ms != null) data["duration_ms"] = Ms;
                if (!Complete) data["complete"] = false;
                if (Reason.Length > 0) data["reason"] = Reason;
                if (ReasonCode.Length > 0) data["reason_code"] = ReasonCode;
                if (Summary.Count > 0) data["summary"] = Summary;
                if (Problems.Count > 0)
                {
                    data["problems"] = Problems.Cast<object>().ToList();
                    data["problem_count"] = Problems.Count;
                }
                return data;
            }
        }

        // The line: the verdict and each stage's status; under it what did not
        // pass, the problems, and the next commands.
        static Answer Build(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("verdict", data["verdict"]);
            var stages = Maps(data, "stages").ToList();
            foreach (var stage in stages) answer.Add(Convert.ToString(stage["stage"], CultureInfo.InvariantCulture), stage["status"]);
            foreach (var stage in stages)
            {
                var name = Convert.ToString(stage["stage"], CultureInfo.InvariantCulture);
                if (Value(stage, "reason") is string reason) answer.Detail(name + " " + stage["status"] + ": " + reason);
                if (name == "analyze" && Value(stage, "summary") is IDictionary<string, object> found && Value(found, "by_severity") is IDictionary<string, object> bySeverity
                    && Int(found, "findings") > 0)
                    answer.Detail("analyze: " + found["findings"] + " finding(s), " + string.Join(", ", Severity.All.Where(level => Int(bySeverity, level) > 0).Select(level => level + " " + bySeverity[level]))
                        + "; fails on " + found["fail_on"] + "; most: " + string.Join(", ", ((IDictionary<string, object>)found["by_rule"]).Take(4).Select(rule => rule.Key + " x" + rule.Value)));
                foreach (var problem in Maps(stage, "problems").Take(MaxProblems)) answer.Detail(name + ": " + Line(problem));
                if (Int(stage, "problem_count") > MaxProblems)
                    answer.Detail(name + ": ... and " + (Int(stage, "problem_count") - MaxProblems) + " more, all of them in --json");
            }
            answer.Detail(Value(data, "note"));
            foreach (var step in (Value(data, "next") as IEnumerable<object> ?? new object[0])) answer.Detail("Next: " + step);
            if (Equals(data["verdict"], Fail)) answer.Failed();
            else if (!Equals(data["complete"], true)) answer.Partial();
            return answer.WithExitCode(Int(data, "exit_code"));
        }

        // `file:line elem 3 [rule] message`.
        static string Line(IDictionary<string, object> problem)
        {
            var head = Convert.ToString(Value(problem, "file"), CultureInfo.InvariantCulture) ?? "";
            if (head.Length > 0 && Value(problem, "line") != null) head += ":" + Convert.ToString(problem["line"], CultureInfo.InvariantCulture);
            if (Value(problem, "where") is string where) head = head.Length == 0 ? where : head + " " + where;
            var parts = new List<string>();
            if (head.Length > 0) parts.Add(head);
            if (Value(problem, "rule") is string rule) parts.Add("[" + rule + "]");
            parts.Add(Convert.ToString(problem["message"], CultureInfo.InvariantCulture));
            return string.Join(" ", parts);
        }
    }
}
