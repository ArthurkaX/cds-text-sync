using System;
using System.IO;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    // A colleague's PC in git: the project file skipped, the default branch
    // and the project file refused at push.
    [Collection("Local command settings")]
    public sealed class TeamGuardTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-team-guard-" + Guid.NewGuid().ToString("N"));
        readonly string _oldXdg = Environment.GetEnvironmentVariable("XDG_DATA_HOME");
        readonly string _clone;
        const string Id = "0d3f5b1e-team-guard";

        public TeamGuardTests()
        {
            Directory.CreateDirectory(_root);
            Environment.SetEnvironmentVariable("XDG_DATA_HOME", Path.Combine(_root, "xdg"));
            var owner = Path.Combine(_root, "owner");
            Directory.CreateDirectory(Path.Combine(owner, ".project"));
            Git(_root, "init -q --bare -b main remote.git");
            Git(owner, "init -q -b main");
            File.WriteAllText(Path.Combine(owner, "cds-text-sync.json"), "{\"project_id\": \"" + Id + "\"}\n");
            File.WriteAllText(Path.Combine(owner, ".project", "plant.project"), "v1");
            File.WriteAllText(Path.Combine(owner, "Main.st"), "PROGRAM Main\n");
            Commit(owner, "the published project");
            Git(owner, "push -q " + Quote(Path.Combine(_root, "remote.git")) + " main");
            Git(_root, "clone -q remote.git colleague");
            _clone = Path.Combine(_root, "colleague");
        }

        public void Dispose()
        {
            Environment.SetEnvironmentVariable("XDG_DATA_HOME", _oldXdg);
            Directory.Delete(_root, true);
        }

        [Fact]
        public void AColleaguesGitSkipsTheProjectFileAndRunsTheHook()
        {
            var applied = TeamGuard.Apply(_clone, false, "C:\\cts\\cts.exe");

            Assert.Equal(1, applied["skipped"]);
            Assert.Equal("installed", applied["hook"]);
            File.WriteAllText(Path.Combine(_clone, ".project", "plant.project"), "saved by CODESYS");
            Assert.Equal("", Git(_clone, "status --porcelain"));
            var hook = File.ReadAllText(Path.Combine(_clone, ".git", "hooks", "pre-push"));
            Assert.Contains("cts=\"C:/cts/cts.exe\"", hook);
            Assert.Contains("git lfs pre-push", hook);
            Assert.Equal("current", TeamGuard.Apply(_clone, false, "C:\\cts\\cts.exe")["hook"]);

            Assert.Equal(0, TeamGuard.Apply(_clone, true, "C:\\cts\\cts.exe")["skipped"]);
            Assert.Contains(".project/plant.project", Git(_clone, "status --porcelain"));
        }

        [Fact]
        public void EveryPCsGitMergesTheViewXmlThroughCts()
        {
            File.WriteAllText(Path.Combine(_clone, ".gitattributes"), "*.xml -merge\n");
            Assert.Equal("installed", TeamGuard.Apply(_clone, true, "C:\\cts\\cts.exe")["merge_driver"]);
            Assert.Equal("current", TeamGuard.Apply(_clone, true, "C:\\cts\\cts.exe")["merge_driver"]);
            Assert.Equal("\"C:/cts/cts.exe\" hook merge-driver %O %A %B %P >/dev/null", Git(_clone, "config --get merge.cts.driver"));
            Assert.EndsWith("merge: cts", Git(_clone, "check-attr merge -- \"project-view/Task Configuration/Task.xml\""));
            Assert.EndsWith("merge: unspecified", Git(_clone, "check-attr merge -- Main.st"));
        }

        [Fact]
        public void TheDriverMergesIntoOursOrLeavesItForAConflict()
        {
            string Write(string name, string text) { var path = Path.Combine(_root, name); File.WriteAllText(path, text); return path; }
            const string b = "<r>\n  <a>1</a>\n  <b>1</b>\n</r>\n";
            var ours = Write("ours", "<r>\n  <a>2</a>\n  <b>1</b>\n</r>\n");
            var merged = MergeDriver.Run(new[] { "merge-driver", Write("base", b), ours, Write("theirs", "<r>\n  <a>1</a>\n  <b>3</b>\n</r>\n"), "Task.xml" });
            Assert.Equal("Task.xml", merged["merged"]);
            Assert.Equal("<r>\n  <a>2</a>\n  <b>3</b>\n</r>\n", File.ReadAllText(ours));

            var conflict = Assert.Throws<CliFailure>(() => MergeDriver.Run(new[] { "merge-driver", Write("base", b), ours, Write("theirs", "<r>\n  <a>4</a>\n  <b>1</b>\n</r>\n"), "Task.xml" }));
            Assert.Equal(1, conflict.ExitCode);
            Assert.Contains("Task.xml: both sides changed a differently", conflict.Message);
            Assert.Equal("<r>\n  <a>2</a>\n  <b>3</b>\n</r>\n", File.ReadAllText(ours));
        }

        [Fact]
        public void GitLfsHookGivesWayAndAHookOfTheUsersOwnStays()
        {
            var hooks = Path.Combine(_clone, ".git", "hooks");
            Directory.CreateDirectory(hooks);
            File.WriteAllText(Path.Combine(hooks, "pre-push"), "#!/bin/sh\ncommand -v git-lfs >/dev/null 2>&1 || { exit 2; }\ngit lfs pre-push \"$@\"\n");
            Assert.Equal("installed", TeamGuard.Apply(_clone, false, "cts.exe")["hook"]);
            File.WriteAllText(Path.Combine(hooks, "pre-push"), "#!/bin/sh\nexec ./check-before-push\n");
            Assert.Equal("kept", TeamGuard.Apply(_clone, false, "cts.exe")["hook"]);
        }

        [Fact]
        public void AColleagueDoesNotPushTheDefaultBranchOrTheProjectFile()
        {
            Git(_clone, "checkout -q -b feature");
            File.WriteAllText(Path.Combine(_clone, "Main.st"), "PROGRAM Main\n// feature\n");
            Commit(_clone, "a feature");
            var head = Git(_clone, "rev-parse HEAD");
            const string zero = "0000000000000000000000000000000000000000";

            var feature = TeamGuard.PrePush(new[] { "pre-push", "origin" }, _clone, "refs/heads/feature " + head + " refs/heads/feature " + zero + "\n");
            Assert.Equal("colleague", feature["role"]);
            Git(_root, "init -q --bare -b main empty.git");
            Git(_clone, "remote add team " + Quote(Path.Combine(_root, "empty.git")));
            Assert.Equal("colleague", TeamGuard.PrePush(new[] { "pre-push", "team" }, _clone, "refs/heads/feature " + head + " refs/heads/feature " + zero + "\n")["role"]);
            var main = Assert.Throws<CliFailure>(() => TeamGuard.PrePush(new[] { "pre-push", "origin" }, _clone, "refs/heads/feature " + head + " refs/heads/main " + zero + "\n"));
            Assert.Contains("the owner pushes main", main.Message);

            File.WriteAllText(Path.Combine(_clone, ".project", "plant.project"), "saved by CODESYS");
            Commit(_clone, "the project too");
            var withProject = Git(_clone, "rev-parse HEAD");
            var project = Assert.Throws<CliFailure>(() => TeamGuard.PrePush(new[] { "pre-push", "origin" }, _clone, "refs/heads/feature " + withProject + " refs/heads/feature " + zero + "\n"));
            Assert.Contains("change the project file", project.Message);

            var both = Assert.Throws<CliFailure>(() => TeamGuard.PrePush(new[] { "pre-push", "origin" }, _clone, "refs/heads/feature " + withProject + " refs/heads/main " + zero + "\n"));
            var lines = both.Message.Split('\n');
            Assert.Equal(3, lines.Length);
            Assert.Equal("this PC is a colleague's (Alt+Q, Settings, This PC), so nothing was pushed:", lines[0]);
            Assert.StartsWith("- the owner pushes main", lines[1]);
            Assert.StartsWith("- 1 commit(s) for refs/heads/main change the project file", lines[2]);

            ProjectInfo.Record(Id, _clone, "plant", true);
            Assert.Equal("owner", TeamGuard.PrePush(new[] { "pre-push", "origin" }, _clone, "refs/heads/feature " + withProject + " refs/heads/main " + zero + "\n")["role"]);
        }

        static void Commit(string folder, string message)
        {
            Git(folder, "add -A");
            Git(folder, "-c user.name=Fixture -c user.email=fixture@localhost commit -qm " + Quote(message));
        }

        static string Quote(string value) => "\"" + value + "\"";

        static string Git(string folder, string args) => GitRepository.Run(folder, args).Trim();
    }
}
