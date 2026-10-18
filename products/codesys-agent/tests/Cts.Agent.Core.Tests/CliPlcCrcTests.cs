using System;
using System.Collections.Generic;
using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        [Fact]
        public void Plc_crc_names_the_commit_recorded_for_the_plc_code()
        {
            var repo = PlcRepository();
            try
            {
                var commit = GitRun.In(repo, "rev-parse HEAD").Output.Trim();
                Assert.Equal(0, GitRun.In(repo, "update-ref refs/cts/plc/code-7 " + ProcessArgs.Quote(commit)).ExitCode);
                Assert.Equal(0, GitRun.In(repo, "tag release-7 " + ProcessArgs.Quote(commit)).ExitCode);
                var host = new FakeHost();
                host.Agents[1] = Agent("demo.project", repo, (method, _) =>
                {
                    Assert.Equal("app.crc", method);
                    return new Dictionary<string, object>
                    {
                        { "match", true }, { "plc", new Dictionary<string, object> { { "code", "code-7" } } },
                        { "ide", new Dictionary<string, object> { { "code", "code-7" } } }, { "application", "Application" },
                    };
                });
                var (code, output, _) = Run(host, "plc-crc");
                Assert.Equal(0, code);
                Assert.Contains("ok plc-crc match=true plc=code-7 ide=code-7 application=Application commit=" + commit.Substring(0, 8) + " tag=release-7", output);
                Assert.Contains("first", output);
            }
            finally { Directory.Delete(repo, true); }
        }

        [Fact]
        public void Plc_crc_without_a_recorded_ref_reports_unrecorded()
        {
            var repo = PlcRepository();
            try
            {
                var host = new FakeHost();
                host.Agents[1] = Agent("demo.project", repo, (method, _) => new Dictionary<string, object>
                {
                    { "match", false }, { "plc", new Dictionary<string, object> { { "code", "new-code" } } },
                    { "ide", new Dictionary<string, object> { { "code", "ide-code" } } }, { "application", "Application" },
                });
                var (code, output, _) = Run(host, "plc-crc");
                Assert.Equal(0, code);
                Assert.Contains("commit=unrecorded", output);
                Assert.Contains("no download from a committed state", output);
            }
            finally { Directory.Delete(repo, true); }
        }

        static string PlcRepository()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-plc-crc-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            Assert.Equal(0, GitRun.In(folder, "init -q -b main").ExitCode);
            Assert.Equal(0, GitRun.In(folder, "config user.name Test").ExitCode);
            Assert.Equal(0, GitRun.In(folder, "config user.email test@example.com").ExitCode);
            File.WriteAllText(Path.Combine(folder, "source.txt"), "source\n");
            Assert.Equal(0, GitRun.In(folder, "add -A").ExitCode);
            Assert.Equal(0, GitRun.In(folder, "commit -q -m first").ExitCode);
            return folder;
        }
    }
}
