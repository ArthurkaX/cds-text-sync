using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class DownloadCommandTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-download-" + Guid.NewGuid().ToString("N"));
        readonly CliCommand _command = CliCommands.All.Single(command => command.Name == "download");
        readonly List<string> _asked = new List<string>();
        bool _ideSaves;

        public DownloadCommandTests()
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
        public void StartZeroDownloadsWithoutStartingOrWaiting()
        {
            var data = _command.Execute(Call("download", "--start", "0"));
            Assert.Equal(new[] { "app.download" }, _asked);
            Assert.Null(data["ready"]);
            Assert.Contains("--start 0", (string)data["note"]);
            Assert.Equal("no sync base yet: run cts export first", ((IDictionary<string, object>)data["source"])["unrecorded"]);
            Assert.Equal(Verdict.Ok, _command.Build(data).Status);
        }

        [Fact]
        public void UncommittedChangesLeaveTheCommitUnrecorded()
        {
            Git("update-ref refs/cts/base HEAD");
            File.WriteAllText(Path.Combine(_root, "one.txt"), "local edit");
            var data = _command.Execute(Call("download", "--no-wait"));
            Assert.StartsWith("uncommitted changes in the sync folder", (string)((IDictionary<string, object>)data["source"])["unrecorded"]);
            Assert.Contains("cts commit them first", (string)((IDictionary<string, object>)data["source"])["unrecorded"]);
            Assert.DoesNotContain("stash", (string)((IDictionary<string, object>)data["source"])["unrecorded"]);
            Assert.DoesNotContain("app.crc", _asked);
            Assert.Equal("", GitRun.In(_root, "for-each-ref refs/cts/plc/").Output.Trim());
            var answer = _command.Build(data);
            Assert.Contains(answer.Pairs, pair => pair.Key == "commit" && Equals(pair.Value, "unrecorded"));
            Assert.Contains(answer.Details, line => line.StartsWith("commit unrecorded: uncommitted changes", StringComparison.Ordinal));
        }

        [Fact]
        public void ARepositoryWithoutACommitSaysSoOnce()
        {
            Git("update-ref refs/cts/base HEAD");
            Git("update-ref -d refs/heads/main");
            var data = _command.Execute(Call("download", "--no-wait"));
            Assert.Equal("the sync folder's repository has no commit yet: cts commit makes the first", ((IDictionary<string, object>)data["source"])["unrecorded"]);
        }

        // CODESYS saved the project on its own while it downloaded: the line says so.
        [Fact]
        public void AProjectTheIdeSavedDuringTheDownloadIsNamed()
        {
            File.WriteAllText(Path.Combine(_root, "sample.project"), "");
            File.SetLastWriteTimeUtc(Path.Combine(_root, "sample.project"), DateTime.UtcNow.AddMinutes(-5));
            Assert.False(_command.Execute(Call("download", "--no-wait")).ContainsKey("saved_by_ide"));
            _ideSaves = true;
            var answer = _command.Build(_command.Execute(Call("download", "--no-wait")));
            Assert.Contains(answer.Pairs, pair => pair.Key == "saved" && Equals(pair.Value, "by-ide"));
            Assert.Contains(answer.Details, line => line.StartsWith("the IDE saved the project during the download", StringComparison.Ordinal));
        }

        [Fact]
        public void AnApplicationThatDoesNotRunFailsWithTheReason()
        {
            var data = _command.Execute(Call("download", "--ready-timeout", "0"));
            Assert.Equal(false, data["ready"]);
            Assert.Equal("project.status", _asked.Last());
            var answer = _command.Build(data);
            Assert.Equal(Verdict.Error, answer.Status);
            Assert.Contains(answer.Details, line => line.StartsWith("not ready: the application did not reach run within 0s (last application state: stop)", StringComparison.Ordinal));
        }

        [Fact]
        public void TheLineNamesThePlcTheRecordedCommitAndTheIdeMessages()
        {
            var answer = _command.Build(new Dictionary<string, object>
            {
                { "downloaded", true }, { "started", true }, { "ready", true }, { "application", "Application" }, { "plc", "bench-plc" },
                { "source", new Dictionary<string, object> { { "branch", "main" }, { "commit", "0123456789abcdef" } } },
                { "messages", new List<object> { new Dictionary<string, object> { { "code", "C0373" }, { "text", "a warning" } } } },
            });
            Assert.Equal(Verdict.Ok, answer.Status);
            Assert.Contains(answer.Pairs, pair => pair.Key == "plc" && Equals(pair.Value, "bench-plc"));
            Assert.Contains(answer.Pairs, pair => pair.Key == "commit" && Equals(pair.Value, "01234567"));
            Assert.Equal(new[] { "[C0373] a warning" }, answer.Details);
        }

        [Fact]
        public void TheHelpSaysWhatAFullDownloadDoes()
        {
            Assert.Contains("Online -> Download", _command.Description);
            Assert.Contains("variables start from their initial values", _command.Description);
            Assert.Contains("--start 0 leaves it stopped", _command.Description);
        }

        CliCall Call(params string[] args)
        {
            var options = CliOptions.Parse(args, null, _command);
            var project = new Dictionary<string, object> { { "path", Path.Combine(_root, "sample.project") }, { "sync_folder", _root } };
            var hello = new Hello(32, new Dictionary<string, object> { { "project", project } });
            return new CliCall(_command, options, hello, 30, (method, parameters) =>
            {
                _asked.Add(method);
                object answer;
                if (method == "app.download" && _ideSaves) File.SetLastWriteTimeUtc(Path.Combine(_root, "sample.project"), DateTime.UtcNow);
                if (method == "app.download") answer = new Dictionary<string, object> { { "downloaded", true }, { "started", parameters["start"] }, { "application", "Application" } };
                else if (method == "project.status") answer = new Dictionary<string, object> { { "plc", new Dictionary<string, object> { { "online", true }, { "application_state", "stop" } } } };
                else throw new InvalidOperationException("unexpected agent call " + method);
                return (IDictionary<string, object>)Json.Parse(Json.Serialize(answer));
            });
        }

        void Git(string args) => GitRepository.Run(_root, args);

        public void Dispose()
        {
            try { Directory.Delete(_root, true); } catch (IOException) { }
        }
    }
}
