using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class CheckoutCommandTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-checkout-" + Guid.NewGuid().ToString("N"));
        readonly CliCommand _command = CliCommands.All.Single(command => command.Name == "checkout");

        public CheckoutCommandTests()
        {
            Directory.CreateDirectory(_root);
            Git("init -q -b main");
            Git("config user.name Test");
            Git("config user.email test@example.com");
            File.WriteAllText(Path.Combine(_root, "one.txt"), "one");
            Git("add -A");
            Git("commit -q -m start");
            Git("switch -q -c feature");
            File.WriteAllText(Path.Combine(_root, "one.txt"), "feature");
            Git("commit -q -am feature");
            Git("switch -q main");
        }

        [Fact]
        public void DiskOnlySwitchesAnExplicitFolderWithoutAnAgent()
        {
            var options = CliOptions.Parse(new[] { "checkout", "feature", "--disk-only", "--sync-folder", _root }, null, _command);
            var result = _command.LocalExecute(options, null, _root);
            Assert.Equal("feature", GitRepository.Position(_root)["branch"]);
            Assert.Equal(true, result["disk_only"]);
            Assert.Equal("main", ((IDictionary<string, object>)result["from"])["branch"]);
        }

        [Fact]
        public void UncommittedChangesRefuseBeforeTheSwitch()
        {
            Git("update-ref refs/cts/base HEAD");
            File.WriteAllText(Path.Combine(_root, "one.txt"), "local edit");
            var failure = Assert.Throws<CliFailure>(() => _command.Execute(Call(new[] { "checkout", "feature" })));
            Assert.Contains("uncommitted changes", failure.Message);
            Assert.Equal("main", GitRepository.Position(_root)["branch"]);
        }

        [Fact]
        public void MissingBaseRefusesBeforeCompareOrSwitch()
        {
            var failure = Assert.Throws<CliFailure>(() => _command.Execute(Call(new[] { "checkout", "feature" })));
            Assert.Contains("no sync base yet", failure.Message);
            Assert.Equal("main", GitRepository.Position(_root)["branch"]);
        }

        CliCall Call(string[] args)
        {
            var options = CliOptions.Parse(args, null, _command);
            var project = new Dictionary<string, object> { { "path", Path.Combine(_root, "sample.project") }, { "sync_folder", _root } };
            var hello = new Hello(32, new Dictionary<string, object> { { "project", project } });
            return new CliCall(_command, options, hello, 30, (method, parameters) => (IDictionary<string, object>)Json.Parse(Json.Serialize(
                method == "project.status" ? new Dictionary<string, object> { { "plc", new Dictionary<string, object> { { "online", false } } } }
                : throw new InvalidOperationException("unexpected agent call " + method))));
        }

        void Git(string args) => GitRepository.Run(_root, args);

        public void Dispose()
        {
            try { Directory.Delete(_root, true); } catch (IOException) { }
        }
    }
}
