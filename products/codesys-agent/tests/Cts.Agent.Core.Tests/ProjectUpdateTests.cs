using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class ProjectUpdateTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-project-update-" + Guid.NewGuid().ToString("N"));
        readonly string _other = Path.Combine(Path.GetTempPath(), "cts-project-update-peer-" + Guid.NewGuid().ToString("N"));
        readonly CliCommand _command = CliCommands.All.Single(command => command.Name == "project" && command.Sub == "update");

        public ProjectUpdateTests()
        {
            Directory.CreateDirectory(_root);
            Git("init -q -b main");
            Git("config user.name Test");
            Git("config user.email test@example.com");
            File.WriteAllText(Path.Combine(_root, "one.txt"), "one");
            Git("add -A");
            Git("commit -q -m start");
        }

        [Fact]
        public void RefusesWhilePlcIsOnline()
        {
            var failure = Assert.Throws<CliFailure>(() => _command.Execute(Call(true)));
            Assert.Contains("cts disconnect", failure.Message);
        }

        [Fact]
        public void VerdictNamesTheCommandAsItsWords()
        {
            var answer = _command.Build(new Dictionary<string, object>
            {
                { "to", new Dictionary<string, object> { { "branch", "main" }, { "commit", "1234567890" } } },
                { "pulled", new Dictionary<string, object> { { "from", "1234567890" }, { "to", "1234567890" } } },
            });
            Assert.StartsWith("ok project-update ", Verdict.Line(answer.Status, _command.Verb, answer.Pairs));
        }

        [Fact]
        public void OwnerWithoutAnUpstreamIsRefused()
        {
            var failure = Assert.Throws<CliFailure>(() => ProjectUpdateCommand.RequireUpstream(_root));
            Assert.Contains("git branch --set-upstream-to=origin/<branch>", failure.Message);
        }

        [Fact]
        public void RefusesIdeChangesWhenTheCompareHasABase()
        {
            var compare = new Dictionary<string, object>
            {
                { "base", true },
                { "summary", new Dictionary<string, object> { { "ide_changed", 1 }, { "both", 0 } } },
            };
            var failure = Assert.Throws<InvalidOperationException>(() => ProjectUpdateCommand.CheckNoIdeChanges(compare));
            Assert.Contains("the IDE changed 1 object(s)", failure.Message);
            Assert.Contains("cts commit takes them into the branch first", failure.Message);
        }

        [Fact]
        public void PullFastForwardsFromABareRemote()
        {
            var remote = Remote();
            Git("remote add origin " + ProcessArgs.Quote(remote));
            Git("push -u origin main");
            ClonePeer(remote);
            Peer("checkout main");
            File.WriteAllText(Path.Combine(_other, "one.txt"), "team");
            Peer("commit -q -am team");
            Peer("push origin main");

            var pulled = ProjectUpdateCommand.Pull(_root);

            Assert.NotNull(pulled);
            Assert.NotEqual(pulled["from"], pulled["to"]);
            Assert.Equal("team", File.ReadAllText(Path.Combine(_root, "one.txt")));
        }

        [Fact]
        public void APullConflictLeavesTheMergeToTheGitProgram()
        {
            var remote = Remote();
            Git("remote add origin " + ProcessArgs.Quote(remote));
            Git("push -u origin main");
            ClonePeer(remote);
            Peer("checkout main");
            File.WriteAllText(Path.Combine(_other, "one.txt"), "team");
            Peer("commit -q -am team");
            Peer("push origin main");
            File.WriteAllText(Path.Combine(_root, "one.txt"), "local");
            Git("commit -q -am local");

            var failure = Assert.Throws<InvalidOperationException>(() => ProjectUpdateCommand.Pull(_root));

            Assert.Contains("one.txt", failure.Message);
            Assert.Contains("resolve the files in your git program (cts open)", failure.Message);
            Git("merge --abort");
        }

        CliCall Call(bool online)
        {
            var options = CliOptions.Parse(new[] { "project", "update" }, null, _command);
            var project = new Dictionary<string, object> { { "path", Path.Combine(_root, "sample.project") }, { "sync_folder", _root } };
            var hello = new Hello(32, new Dictionary<string, object> { { "project", project }, { "sync_folder", _root } });
            return new CliCall(_command, options, hello, 30, (method, parameters) => (IDictionary<string, object>)Json.Parse(Json.Serialize(
                method == "project.status" ? new Dictionary<string, object> { { "plc", new Dictionary<string, object> { { "online", online } } } }
                : throw new InvalidOperationException("unexpected agent call " + method))));
        }

        void Git(string args) => GitRepository.Run(_root, args);

        void Peer(string args) => GitRepository.Run(_other, args);

        string Remote()
        {
            var path = Path.Combine(_root, "remote.git");
            Git("init --bare -q " + ProcessArgs.Quote(path));
            return path;
        }

        void ClonePeer(string remote)
        {
            var clone = GitRun.In(_root, "clone -q " + ProcessArgs.Quote(remote) + " " + ProcessArgs.Quote(_other));
            Assert.NotNull(clone);
            Assert.Equal(0, clone.ExitCode);
            Peer("config user.name Test");
            Peer("config user.email test@example.com");
        }

        public void Dispose()
        {
            try { Directory.Delete(_root, true); } catch (IOException) { }
            try { Directory.Delete(_other, true); } catch (IOException) { }
        }
    }
}
