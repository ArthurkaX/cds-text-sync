using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Cli;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class ExportFastPathTests
    {
        static readonly string Fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");

        [Fact]
        public void Fast_export_skips_the_agent_and_matches_a_full_export_for_disk_changes()
        {
            var root = CreateRepo("fast");
            try
            {
                var calls = 0;
                var first = Execute(root, "C:\\projects\\demo.project", "session:0", null, (method, args) =>
                {
                    Assert.Equal("project.export", method);
                    calls++;
                    File.Copy(Path.Combine(Fixture, "snapshot.xml"), (string)args["path"]);
                    return new Dictionary<string, object> { { "objects", 10 } };
                });
                Assert.Equal("exported", first["ide"]);
                var saved = SyncBase.ReadStamp(StampPath(root));
                Assert.NotNull(saved);
                Assert.Equal("C:\\projects\\demo.project", saved.Project);
                Assert.Equal("session:0", saved.Value);
                Assert.Equal(GitRun.In(root, "rev-parse refs/cts/base").Output.Trim(), saved.Base);

                var view = Path.Combine(root, "project-view");
                File.WriteAllText(Path.Combine(view, "PLC_Stabur", "Plc Logic", "Application", "MAIN.st"), "edited on disk\n");
                File.Delete(Path.Combine(view, "PLC_Stabur", "Plc Logic", "Application", "FB_Valve.st"));
                File.WriteAllText(Path.Combine(view, "POUs", "Added.st"), "PROGRAM Added\nEND_PROGRAM\n");
                var baseBefore = GitRun.In(root, "rev-parse refs/cts/base").Output.Trim();
                var gitDir = GitRun.In(root, "rev-parse --absolute-git-dir").Output.Trim();
                var nativesPath = Path.Combine(gitDir, "cts", "same-natives.json");
                var nativesBefore = File.ReadAllBytes(nativesPath);

                var fast = Execute(root, "C:\\projects\\demo.project", "session:0", null, (method, args) =>
                {
                    calls++;
                    throw new Exception("fast path called the agent");
                });
                Assert.Equal("unchanged", fast["ide"]);
                Assert.Equal(1, calls);
                Assert.Equal(baseBefore, GitRun.In(root, "rev-parse refs/cts/base").Output.Trim());
                Assert.Equal(nativesBefore, File.ReadAllBytes(nativesPath));

                var full = Execute(root, "C:\\projects\\demo.project", "session:0", new[] { "--full" }, (method, args) =>
                {
                    Assert.Equal("project.export", method);
                    calls++;
                    File.Copy(Path.Combine(Fixture, "snapshot.xml"), (string)args["path"]);
                    return new Dictionary<string, object> { { "objects", 10 } };
                });
                Assert.Equal("exported", full["ide"]);
                Assert.Equal(2, calls);
                Assert.Equal(Paths(fast, "pending_import"), Paths(full, "pending_import"));
                Assert.Equal(Paths(fast, "kept"), Paths(full, "kept"));
                Assert.Contains(Paths(fast, "pending_import"), path => path.EndsWith("MAIN.st", StringComparison.Ordinal));
                Assert.Contains(Paths(fast, "pending_import"), path => path.EndsWith("FB_Valve.st", StringComparison.Ordinal));
                Assert.Contains(Paths(fast, "kept"), path => path.EndsWith("Added.st", StringComparison.Ordinal));
            }
            finally { Directory.Delete(root, true); }
        }

        [Theory]
        [InlineData("stamp")]
        [InlineData("project")]
        [InlineData("base")]
        [InlineData("full")]
        [InlineData("force")]
        public void Mismatch_or_explicit_full_option_walks_the_agent(string cause)
        {
            var root = CreateRepo("mismatch-" + cause);
            try
            {
                var calls = 0;
                IDictionary<string, object> Export(string method, IDictionary<string, object> args)
                {
                    Assert.Equal("project.export", method);
                    calls++;
                    File.Copy(Path.Combine(Fixture, "snapshot.xml"), (string)args["path"]);
                    return new Dictionary<string, object>();
                }
                Execute(root, "C:\\projects\\demo.project", "session:0", null, Export);
                var project = "C:\\projects\\demo.project";
                var stamp = "session:0";
                var options = cause == "full" ? new[] { "--full" } : cause == "force" ? new[] { "--force" } : null;
                if (cause == "stamp") stamp = "session:1";
                if (cause == "project") project = "C:\\projects\\other.project";
                if (cause == "base")
                {
                    GitRun.In(root, "-c user.name=test -c user.email=test@example.com commit --allow-empty -m move");
                    GitRun.In(root, "update-ref refs/cts/base HEAD");
                    // As cts's own move would leave it: the stamp's base is stale.
                    File.WriteAllText(Path.Combine(root, ".git", "cts", "base.own"), GitRun.In(root, "rev-parse HEAD").Output.Trim());
                }
                Execute(root, project, stamp, options, Export);
                Assert.Equal(2, calls);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Failed_export_removes_the_saved_stamp()
        {
            var root = CreateRepo("failure");
            try
            {
                var path = StampPath(root);
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                SyncBase.SaveStamp(path, "C:\\projects\\demo.project", "session:0", "base");
                Assert.Throws<CliFailure>(() => Execute(root, "C:\\projects\\demo.project", "session:0", null,
                    (method, args) => throw new InvalidOperationException("export failed")));
                Assert.False(File.Exists(path));
            }
            finally { Directory.Delete(root, true); }
        }

        static IDictionary<string, object> Execute(string root, string projectPath, string stamp, string[] options,
            Func<string, IDictionary<string, object>, IDictionary<string, object>> fake)
        {
            var command = CliCommands.All.Single(item => item.Name == "export");
            var args = new[] { "export" }.Concat(options ?? Array.Empty<string>()).ToArray();
            var parsed = CliOptions.Parse(args, null, command);
            var project = new Dictionary<string, object> { { "path", projectPath }, { "sync_folder", root } };
            var helloData = new Dictionary<string, object> { { "project", project }, { "ide_stamp", stamp } };
            var call = new CliCall(command, parsed, new Hello(1, helloData), 30, fake);
            return ExportCommand.Execute(call);
        }

        static string[] Paths(IDictionary<string, object> result, string key) => result.ContainsKey(key)
            ? ((IList<string>)result[key]).ToArray() : Array.Empty<string>();

        static string StampPath(string root)
        {
            var result = GitRun.In(root, "rev-parse --absolute-git-dir");
            return Path.Combine(result.Output.Trim(), "cts", "ide-stamp.json");
        }

        static string CreateRepo(string name)
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-export-fast-" + name + "-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            File.Copy(Path.Combine(Fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
            GitRepository.Run(root, "init --quiet");
            return root;
        }
    }
}
