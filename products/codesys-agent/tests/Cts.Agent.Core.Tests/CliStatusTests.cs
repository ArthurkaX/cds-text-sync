using System;
using System.Collections.Generic;
using System.IO;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        // A git repository in a fresh folder: one commit holding the project
        // file and a view file.
        static string Repository()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-status-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(root, ".project"));
            File.WriteAllText(Path.Combine(root, ".project", "plant.project"), "binary");
            File.WriteAllText(Path.Combine(root, "Main.st"), "PROGRAM Main\nEND_PROGRAM\n");
            foreach (var args in new[] { "init -q -b master", "add -A", "-c user.name=t -c user.email=t@t commit -q -m one" })
                GitRepository.Run(root, args);
            return root;
        }

        static Dictionary<string, object> ProjectStatus(string path, string folder, object online, string state = null)
        {
            var plc = new Dictionary<string, object> { { "online", online } };
            if (state != null) plc["application_state"] = state;
            var status = new Dictionary<string, object>
            {
                { "open", true }, { "path", path }, { "unsaved_changes", false }, { "plc", plc },
            };
            if (folder != null) status["sync_folder"] = folder;
            return status;
        }

        [Fact]
        public void Status_names_the_git_position_and_leaves_out_the_projects_own_file()
        {
            var root = Repository();
            var project = Path.Combine(root, ".project", "plant.project");
            File.WriteAllText(project, "saved again");
            File.WriteAllText(Path.Combine(root, "Main.st"), "PROGRAM Main\nVAR x : INT; END_VAR\nEND_PROGRAM\n");
            File.WriteAllText(Path.Combine(root, "New.st"), "PROGRAM New\nEND_PROGRAM\n");
            var host = new FakeHost();
            host.Agents[7144] = Agent(project, root, method =>
            {
                Assert.Equal("project.status", method);
                return ProjectStatus(project, root, false);
            });

            var (code, output, _) = Run(host, "status");

            var commit = GitRun.In(root, "rev-parse HEAD").Output.Trim();
            Directory.Delete(root, true);
            Assert.Equal(0, code);
            Assert.Equal("ok status ide=ide-7144 plc=offline edits=allowed unsaved=false\n"
                + "sync_folder " + root + "\n"
                + "git branch=master commit=" + commit.Substring(0, 8) + " uncommitted=2; the project file changed too, not counted: every IDE save changes it, and only its owner's cts commit --publish records it\n"
                + "project " + project + "\n"
                + "ide-7144 · plant\n", output);
        }

        // The project file was saved at the first commit; the folder moved on.
        [Fact]
        public void Status_says_how_far_the_project_file_is_behind_the_folder()
        {
            var root = Repository();
            var project = Path.Combine(root, ".project", "plant.project");
            var first = GitRun.In(root, "rev-parse HEAD").Output.Trim();
            File.WriteAllText(Path.Combine(root, "New.st"), "PROGRAM New\nEND_PROGRAM\n");
            foreach (var args in new[] { "add -A", "-c user.name=t -c user.email=t@t commit -q -m two" })
                GitRepository.Run(root, args);
            var host = new FakeHost();
            var label = "main@" + first.Substring(0, 8);
            host.Agents[7144] = Agent(project, root, method =>
            {
                var status = ProjectStatus(project, root, false);
                status["source"] = ProjectInfo.Source(label, "2026-10-21 09:00");
                return status;
            });

            var (_, output, _) = Run(host, "status");
            var json = (IDictionary<string, object>)Json.Parse(Run(host, "status", "--json").output);

            Directory.Delete(root, true);
            Assert.Contains("\nsource " + ProjectInfo.Source(label, "2026-10-21 09:00") + ", 1 commit(s) behind the folder's HEAD: the project file is older than the folder", output);
            Assert.Equal(1L, Convert.ToInt64(json["source_behind"]));
        }

        [Fact]
        public void Status_says_why_edits_are_blocked_and_what_a_folder_without_git_needs()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-nogit-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method => ProjectStatus(@"C:\p\plant.project", folder, true, "run"));

            var (_, output, _) = Run(host, "status");

            Directory.Delete(folder);
            Assert.StartsWith("ok status ide=ide-1 plc=online edits=blocked unsaved=false\n"
                + "sync_folder " + folder + "\n"
                + "git none: cts set-sync-folder sets the sync folder up\n", output);
            Assert.Contains("\nThe IDE is online with the PLC: cts read, write and the PLC commands work now; project edits (import, sync, fmt --write) are refused until cts disconnect, which ends the IDE's online session and leaves the PLC running.\n", output);
        }

        [Fact]
        public void Status_without_a_project_says_so_and_json_carries_the_hint()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method => new Dictionary<string, object> { { "open", false } });

            var (_, output, _) = Run(host, "status");
            var json = (IDictionary<string, object>)Json.Parse(Run(host, "status", "--json").output);

            Assert.Equal("ok status ide=ide-1 plc=unknown\n"
                + "No project is open in the IDE; project-scoped commands will fail (cts project open).\n"
                + "ide-1 · no project\n", output);
            Assert.Null(json["project"]);
            Assert.Null(json["edits_allowed"]);
            Assert.False(json.ContainsKey("git"));
        }

        [Fact]
        public void The_last_build_says_how_long_ago_it_ran()
        {
            var now = new DateTime(2026, 10, 13, 4, 36, 30, DateTimeKind.Utc);

            Assert.EndsWith(", 6 min ago", StatusCommands.When("2026-10-13T04:30:00Z", now));
            Assert.EndsWith(", just now", StatusCommands.When("2026-10-13T04:36:00Z", now));
            Assert.EndsWith(", 3 h ago", StatusCommands.When("2026-10-13T01:30:00Z", now));
            Assert.Equal("", StatusCommands.When(null, now));
        }

        [Fact]
        public void A_folder_that_is_not_there_has_no_repository()
        {
            Assert.Equal(new Dictionary<string, object> { { "repository", null } },
                FolderGit.Position(Path.Combine(Path.GetTempPath(), "cts-missing-" + Guid.NewGuid().ToString("N")), null));
        }

        // A clock that moves only when the wait sleeps.
        sealed class FakeClock
        {
            public double Now;
            public readonly List<double> Sleeps = new List<double>();

            public void Sleep(double seconds)
            {
                Sleeps.Add(seconds);
                Now += seconds;
            }
        }

        static Dictionary<string, object> Plc(object online, string state) => new Dictionary<string, object>
        {
            { "plc", new Dictionary<string, object> { { "online", online }, { "application_state", state } } },
        };

        [Fact]
        public void The_wait_ends_when_the_application_runs()
        {
            var clock = new FakeClock();
            var states = new Queue<string>(new[] { "stop", "stop", "run" });

            var result = ReadyWait.Run(() => Plc(true, states.Dequeue()), name => throw new InvalidOperationException(), 30, "", () => clock.Now, clock.Sleep);

            Assert.Equal(true, result["ready"]);
            Assert.Equal(3L, result["checks"]);
            Assert.Equal(1.0, result["ready_after_s"]);
        }

        [Fact]
        public void With_a_variable_the_wait_needs_it_to_change()
        {
            var clock = new FakeClock();
            var values = new Queue<string>(new[] { null, "5", "5", "6" });

            var result = ReadyWait.Run(() => Plc(true, "run"), name => values.Dequeue(), 30, "GVL.n", () => clock.Now, clock.Sleep);

            Assert.Equal(true, result["ready"]);
            Assert.Equal("GVL.n", result["ready_var"]);
            Assert.Equal("5", result["was"]);
            Assert.Equal("6", result["value"]);
            Assert.Equal(4L, result["checks"]);
        }

        [Fact]
        public void A_wait_that_runs_out_names_what_it_saw_last()
        {
            var clock = new FakeClock();

            var stopped = ReadyWait.Run(() => Plc(true, "stop"), name => null, 2, "", () => clock.Now, clock.Sleep);
            var constant = ReadyWait.Run(() => Plc(true, "run"), name => "7", 2, "GVL.n", () => clock.Now, clock.Sleep);
            var unreachable = ReadyWait.Run(() => throw new CliFailure("wait-ready", "busy", "IDE ide-1 is busy", null, 1), name => null, 1,
                "", () => clock.Now, clock.Sleep);

            Assert.Equal(false, stopped["ready"]);
            Assert.Equal("the application did not reach run within 2s (last application state: stop)", stopped["reason"]);
            Assert.Equal("the application is running, but GVL.n did not change within 2s (last value: '7'); it may be constant, "
                + "or the task may not be cycling", constant["reason"]);
            Assert.Equal("the application did not reach run within 1s (last application state: the agent is unreachable); "
                + "last agent error: IDE ide-1 is busy", unreachable["reason"]);
            Assert.All(clock.Sleeps, s => Assert.True(s <= 0.5));
        }

        [Fact]
        public void Wait_ready_polls_status_and_fails_with_the_reason_when_not_ready()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                if (method == "vars.read")
                {
                    Assert.Equal(new List<object> { "GVL.n" }, p["names"]);
                    return new Dictionary<string, object> { { "logged_in", true }, { "results", new List<object>
                        { new Dictionary<string, object> { { "ok", true }, { "text", "3" } } } } };
                }
                Assert.Equal("project.status", method);
                return ProjectStatus(@"C:\p\plant.project", null, true, "run");
            });

            var ready = Run(host, "wait-ready");
            var (code, output, _) = Run(host, "wait-ready", "--var", "GVL.n", "--timeout", "0.2");

            Assert.Equal(0, ready.code);
            Assert.StartsWith("ok wait-ready ready=true ready_after_s=", ready.output);
            Assert.Equal(1, code);
            Assert.StartsWith("error wait-ready ready=false ready_after_s=", output);
            Assert.Contains("ready_var=GVL.n\nthe application is running, but GVL.n did not change within 0.2s (last value: '3')", output);
        }
    }
}
