using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        const string CleanProgram = "// Main program documentation.\nPROGRAM PRG_Main\nVAR\n    n : INT;\nEND_VAR\n// --- implementation ---\nn := n + 1;\n";
        const string CommentedCode = "// Main program documentation.\nPROGRAM PRG_Main\nVAR\n    n : INT;\nEND_VAR\n// --- implementation ---\nn := n + 1;\n// n := 0;\n";

        // A sync folder: its view, a git repository whose refs/cts/base is the
        // view, and the stamp that tells compare the IDE has not changed since.
        sealed class Plant : IDisposable
        {
            internal readonly string Root = Path.Combine(Path.GetTempPath(), "cts-verify-" + Guid.NewGuid().ToString("N"));
            internal readonly List<string> Asked = new List<string>();

            internal Plant(string program = CleanProgram)
            {
                Directory.CreateDirectory(Path.Combine(Root, "project-view", "POUs"));
                Write("project-view/POUs/PRG_Main.st", program);
            }

            internal void Write(string path, string text)
            {
                var full = Path.Combine(Root, path.Replace('/', Path.DirectorySeparatorChar));
                Directory.CreateDirectory(Path.GetDirectoryName(full));
                File.WriteAllText(full, text);
            }

            internal Plant Synced()
            {
                foreach (var args in new[] { "init -q -b main", "config user.name Test", "config user.email test@example.com", "add -A", "commit -q -m view" })
                    GitRepository.Run(Root, args);
                SyncBase.Record(Root, "project-view", new List<string>());
                var stamp = Path.Combine(Root, ".git", "cts", "ide-stamp.json");
                SyncBase.SaveStamp(stamp, Path.Combine(Root, "plant.project"), "stamp", GitRepository.Run(Root, "rev-parse refs/cts/base").Trim());
                return this;
            }

            // The IDE of this sync folder, answering *answer* for every method
            // but its hello.
            internal FakeHost Ide(Func<string, IDictionary<string, object>, object> answer)
            {
                var host = new FakeHost();
                host.Agents[1] = (method, parameters) =>
                {
                    if (method == "hello")
                        return new Dictionary<string, object>
                        {
                            { "protocol", "1.0" },
                            { "ide_stamp", "stamp" },
                            { "project", new Dictionary<string, object> { { "path", Path.Combine(Root, "plant.project") }, { "sync_folder", Root } } },
                            { "timeout_profile", new Dictionary<string, object> { { "default", 30L } } },
                        };
                    Asked.Add(method);
                    return answer(method, parameters);
                };
                return host;
            }

            public void Dispose()
            {
                try { Directory.Delete(Root, true); }
                catch (IOException) { }
                catch (UnauthorizedAccessException) { }
            }
        }

        static object Compiled(params object[] messages) => new Dictionary<string, object>
        {
            { "application", "App" }, { "compiled", true }, { "messages", messages.ToList() },
        };

        static object Message(string severity, string code, string text) => new Dictionary<string, object>
        {
            { "severity", severity }, { "code", code }, { "text", text }, { "object", "PRG_Main" },
        };

        static IDictionary<string, object> Report(string output) => (IDictionary<string, object>)Json.Parse(output);

        static IDictionary<string, object> Stage(IDictionary<string, object> report, string name)
            => ((IList<object>)report["stages"]).Cast<IDictionary<string, object>>().Single(stage => Equals(stage["stage"], name));

        [Fact]
        public void Verify_cannot_start_without_a_view_or_with_a_wrong_selection()
        {
            using (var plant = new Plant())
            {
                var empty = Path.Combine(plant.Root, "empty");
                Directory.CreateDirectory(empty);
                var (code, output, _) = RunLocal("verify", "--sync-folder", empty);
                Assert.Equal(2, code);
                Assert.StartsWith("error verify cause=\"no sync folder\"", output);
                Assert.Equal(2, RunLocal("verify", "--sync-folder", plant.Root, "--only", "analyze,lint").code);
                Assert.Equal(2, RunLocal("verify", "--sync-folder", plant.Root, "--only", ",").code);
                Assert.Equal(2, RunLocal("verify", "--sync-folder", plant.Root, "--deploy").code);
                var (deploy, said, _) = RunLocal("verify", "--sync-folder", plant.Root, "--deploy", "--ready-var", "GVL.n", "--only", "analyze");
                Assert.Equal(2, deploy);
                Assert.Contains("needs the build stage", said + RunLocal("verify", "--sync-folder", plant.Root, "--deploy", "--ready-var", "GVL.n", "--only", "analyze").error);
            }
        }

        [Fact]
        public void Verify_passes_a_clean_project_offline_and_names_the_stages_that_did_not_run()
        {
            using (var plant = new Plant())
            {
                var (code, output, _) = RunLocal("verify", "--sync-folder", Path.Combine(plant.Root, "project-view"));
                Assert.Equal(0, code);
                Assert.StartsWith("partial verify verdict=pass analyze=pass visu-sketch=skipped build=skipped\n", output);
                Assert.Contains("build skipped: no in-IDE agent answers", output);
                Assert.Contains("Incomplete: build delivered no verdict", output);
                Assert.Contains("Next: cts project open --path <project> --launch", output);

                var report = Report(RunLocal("verify", "--sync-folder", plant.Root, "--json").output);
                Assert.Equal(2, Convert.ToInt32(report["schema_version"]));
                Assert.Equal(false, report["complete"]);
                Assert.Equal("agent_unavailable", Stage(report, "build")["reason_code"]);
                Assert.DoesNotContain(((IList<object>)report["stages"]).Cast<IDictionary<string, object>>(), stage => Equals(stage["stage"], "test"));

                var (strict, _, _) = RunLocal("verify", "--sync-folder", plant.Root, "--incomplete", "error");
                Assert.Equal(3, strict);
                Assert.DoesNotContain("Incomplete:", RunLocal("verify", "--sync-folder", plant.Root, "--incomplete", "ignore").output);
            }
        }

        [Fact]
        public void Verify_fails_on_analysis_findings_unless_fail_on_raises_the_bar()
        {
            using (var plant = new Plant(CommentedCode))
            {
                var (code, output, _) = RunLocal("verify", "--sync-folder", plant.Root, "--only", "analyze");
                Assert.Equal(1, code);
                Assert.StartsWith("error verify verdict=fail analyze=fail\n", output);
                Assert.Contains("analyze: POUs/PRG_Main.st:8 [CTS0001] commented-out code: n := 0;", output);
                Assert.Contains("Next: cts analyze", output);
                Assert.Contains("\nanalyze: 1 finding(s), suspicious 1; fails on suspicious; most: CTS0001 x1\n", output);
                Assert.Contains("Next: cts analyze baseline create", output);
                Assert.Equal(0, RunLocal("verify", "--sync-folder", plant.Root, "--only", "analyze", "--fail-on", "danger").code);
            }
        }

        [Fact]
        public void Verify_lints_every_sketch_but_the_previews_and_caps_the_problems()
        {
            using (var plant = new Plant())
            {
                plant.Write(".visu/ok.svg", "<svg width=\"800\" height=\"480\"><rect x=\"8\" y=\"8\" width=\"80\" height=\"40\"/></svg>");
                plant.Write(".visu/ok.preview.svg", "not even xml");
                var (code, output, _) = RunLocal("verify", "--sync-folder", plant.Root, "--only", "visu-sketch");
                Assert.Equal(0, code);
                Assert.StartsWith("ok verify verdict=pass visu-sketch=pass", output);

                plant.Write(".visu/broken.svg", "<svg");
                plant.Write(".visu/screens/wide.svg", "<svg width=\"800\" height=\"480\">"
                    + string.Concat(Enumerable.Range(0, 25).Select(i => "<rect x=\"-8\" y=\"" + (16 * i) + "\" width=\"8\" height=\"8\"/>")) + "</svg>");
                var report = Report(RunLocal("verify", "--sync-folder", plant.Root, "--only", "visu-sketch", "--json").output);
                var sketches = Stage(report, "visu-sketch");
                Assert.Equal("fail", sketches["status"]);
                var problems = ((IList<object>)sketches["problems"]).Cast<IDictionary<string, object>>().ToList();
                // --json carries every problem; the text answer shows the first ones.
                Assert.True(problems.Count > 25);
                Assert.Equal(problems.Count, Convert.ToInt32(sketches["problem_count"]));
                Assert.Contains(" more, all of them in --json", RunLocal("verify", "--sync-folder", plant.Root, "--only", "visu-sketch").output);
                Assert.Equal("sketch-unreadable", problems[0]["rule"]);
                Assert.Equal(".visu/broken.svg", problems[0]["file"]);
                Assert.Contains(problems, problem => Equals(problem["rule"], "bounds") && Equals(problem["file"], ".visu/screens/wide.svg")
                    && Equals(problem["where"], "elem 0"));
                var summary = (IDictionary<string, object>)sketches["summary"];
                Assert.Equal(3, Convert.ToInt32(summary["sketches"]));
                Assert.Equal(1, Convert.ToInt32(summary["unreadable"]));
            }
        }

        [Fact]
        public void Verify_does_not_credit_a_build_when_the_ide_differs_from_the_disk()
        {
            using (var plant = new Plant().Synced())
            {
                plant.Write("project-view/POUs/PRG_Main.st", CommentedCode.Replace("// n := 0;\n", "n := 2;\n"));
                var host = plant.Ide((method, _) => method == "app.build" ? Compiled() : null);
                var (code, output, _) = Run(host, "verify", "--sync-folder", plant.Root, "--only", "build");
                Assert.Equal(0, code);
                Assert.StartsWith("partial verify verdict=pass build=skipped", output);
                Assert.Contains("build skipped: the IDE differs from the sync folder (", output);
                Assert.Contains("Next: cts compare", output);
                Assert.DoesNotContain("app.build", plant.Asked);
            }
        }

        [Fact]
        public void Verify_reports_the_compiler_errors_first_and_once_whatever_their_casing()
        {
            using (var plant = new Plant().Synced())
            {
                var host = plant.Ide((method, _) => method == "app.build"
                    ? Compiled(Message("Warning", "C0373", "a warning"), Message("error", "C0032", "Cannot convert type"), Message("Error", "C0032", "Cannot  convert type"), Message("Info", "", "Build started"))
                    : null);
                var report = Report(Run(host, "verify", "--sync-folder", plant.Root, "--only", "build", "--json").output);
                Assert.Equal("fail", report["verdict"]);
                Assert.Equal(1, Convert.ToInt32(report["exit_code"]));
                var build = Stage(report, "build");
                var problems = ((IList<object>)build["problems"]).Cast<IDictionary<string, object>>().ToList();
                Assert.Equal(new[] { "error", "warning" }, problems.Select(problem => problem["severity"]));
                Assert.Equal("C0032", problems[0]["rule"]);
                Assert.Equal("PRG_Main", problems[0]["where"]);
                Assert.Equal(2, Convert.ToInt32(((IDictionary<string, object>)build["summary"])["errors"]));
                Assert.Contains("cts build", string.Join("\n", (IList<object>)report["next"]));
            }
        }

        [Fact]
        public void Verify_credits_a_clean_build_and_keeps_an_incomplete_one_out_of_the_verdict()
        {
            using (var plant = new Plant().Synced())
            {
                var (code, output, _) = Run(plant.Ide((method, _) => method == "app.build" ? Compiled() : null),
                    "verify", "--sync-folder", plant.Root, "--only", "build");
                Assert.Equal(0, code);
                Assert.StartsWith("ok verify verdict=pass build=pass", output);

                var host = plant.Ide((method, _) => method == "app.build"
                    ? new Dictionary<string, object> { { "application", "App" }, { "compiled", false }, { "messages", new List<object>() } }
                    : null);
                var build = Stage(Report(Run(host, "verify", "--sync-folder", plant.Root, "--only", "build", "--json").output), "build");
                Assert.Equal("error", build["status"]);
                Assert.Equal("tool_error", build["reason_code"]);
                Assert.Equal(false, build["complete"]);
            }
        }

        [Fact]
        public void Verify_takes_an_agent_refusal_as_an_error_not_a_failure()
        {
            using (var plant = new Plant().Synced())
            {
                var host = plant.Ide((method, _) =>
                {
                    if (method == "app.build") throw new ProtocolException("no_application", "No active application");
                    return null;
                });
                var report = Report(Run(host, "verify", "--sync-folder", plant.Root, "--only", "build", "--json").output);
                Assert.Equal("pass", report["verdict"]);
                var build = Stage(report, "build");
                Assert.Equal("error", build["status"]);
                Assert.Equal("agent_refused", build["reason_code"]);
                Assert.Equal("No active application", build["reason"]);

                var slow = plant.Ide((method, _) =>
                {
                    if (method == "app.build") throw new ProtocolException("timeout", "app.build did not finish");
                    return null;
                });
                build = Stage(Report(Run(slow, "verify", "--sync-folder", plant.Root, "--only", "build", "--json").output), "build");
                Assert.Equal("skipped", build["status"]);
                Assert.Equal("agent_timeout", build["reason_code"]);
                Assert.Contains("--build-timeout N", (string)build["reason"]);
            }
        }

        [Fact]
        public void Verify_runs_the_test_plans_only_when_asked_and_after_a_good_build()
        {
            using (var plant = new Plant().Synced())
            {
                IDictionary<string, object> sent = null;
                var host = plant.Ide((method, parameters) =>
                {
                    if (method == "app.build") return Compiled();
                    if (method != TestPlans.Method) return null;
                    sent = parameters;
                    return new Dictionary<string, object>
                    {
                        { "status", "FAIL" }, { "ok", false },
                        { "summary", new Dictionary<string, object> { { "ok", 1L }, { "not_ok", 1L }, { "total", 2L }, { "files", 1L } } },
                        { "results", new List<object> { new Dictionary<string, object>
                        {
                            { "file", "motor.json" }, { "status", "FAIL" },
                            { "tests", new List<object>
                            {
                                new Dictionary<string, object> { { "name", "starts" }, { "status", "PASS" } },
                                new Dictionary<string, object> { { "name", "stops" }, { "status", "FAIL" }, { "error", "expected FALSE, read TRUE" } },
                            } },
                        } } },
                    };
                });
                var (code, output, _) = Run(host, "verify", "--sync-folder", plant.Root, "--only", "build", "--with-test");
                Assert.Equal(0, code);
                Assert.DoesNotContain(TestPlans.Method, plant.Asked);

                (code, output, _) = Run(host, "verify", "--sync-folder", plant.Root, "--with-test", "--test-file", "motor.json", "--only", "test,build");
                Assert.Equal(1, code);
                Assert.StartsWith("error verify verdict=fail build=pass test=fail", output);
                Assert.Contains("test: motor.json stops: expected FALSE, read TRUE", output);
                Assert.Equal(plant.Root, sent["folder"]);
                Assert.Equal("motor.json", sent["file"]);

                var failing = plant.Ide((method, _) => method == "app.build" ? Compiled(Message("Error", "C0032", "bad")) : null);
                var report = Report(Run(failing, "verify", "--sync-folder", plant.Root, "--only", "build,test", "--json").output);
                Assert.Equal("dependency_failed", Stage(report, "test")["reason_code"]);
            }
        }

        [Fact]
        public void Verify_takes_a_test_answer_without_a_verdict_as_incomplete()
        {
            using (var plant = new Plant().Synced())
            {
                var host = plant.Ide((method, _) => method == TestPlans.Method ? new Dictionary<string, object> { { "results", new List<object>() } } : null);
                var test = Stage(Report(Run(host, "verify", "--sync-folder", plant.Root, "--only", "test", "--json").output), "test");
                Assert.Equal("error", test["status"]);
                Assert.Equal("invalid_payload", test["reason_code"]);
            }
        }

        [Fact]
        public void Verify_deploys_only_after_a_run_with_nothing_failed()
        {
            using (var plant = new Plant(CommentedCode).Synced())
            {
                var host = plant.Ide((method, _) => method == "app.build" ? Compiled() : method == "app.download"
                    ? new Dictionary<string, object> { { "downloaded", true }, { "started", true }, { "application", "App" } }
                    : null);
                var report = Report(Run(host, "verify", "--sync-folder", plant.Root, "--deploy", "--ready-var", "GVL.n", "--json").output);
                Assert.Equal("dependency_failed", Stage(report, "deploy")["reason_code"]);
                Assert.DoesNotContain("app.download", plant.Asked);

                report = Report(Run(host, "verify", "--sync-folder", plant.Root, "--only", "build", "--deploy", "--ready-var", "GVL.n",
                    "--ready-timeout", "0", "--json").output);
                var deploy = Stage(report, "deploy");
                Assert.Contains("app.download", plant.Asked);
                Assert.Equal("fail", deploy["status"]);
                Assert.Contains("did not reach run within 0s", (string)deploy["reason"]);
                Assert.Equal(true, ((IDictionary<string, object>)deploy["summary"])["downloaded"]);
            }
        }
    }
}
