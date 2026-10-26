using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class SyncFolderTests
    {
        [Fact]
        public void RegistryFilesUsePythonSortedAsciiBytes()
        {
            var root = Temp();
            var registry = Path.Combine(root, "projects.json");
            ProjectInfo.Record("id", Path.Combine(root, "café"), "café", true, registry);
            Assert.Equal("{\n  \"projects\": {\n    \"id\": {\n      \"folder\": \"" + Path.Combine(root, "caf") + "\\u00e9\",\n      \"name\": \"caf\\u00e9\",\n      \"owner\": true\n    }\n  },\n  \"version\": 1\n}\n", File.ReadAllText(registry));
        }

        [Fact]
        public void PrepareInitializesAndCommitsTheThreeSetupFiles()
        {
            var root = Temp();
            var oldConfig = Environment.GetEnvironmentVariable("XDG_CONFIG_HOME");
            Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", Path.Combine(root, "config"));
            var folder = Path.Combine(root, "sync");
            try
            {
                var result = GitFolder.Prepare(folder, "id") as IDictionary<string, object>;
                Assert.Equal(true, result["initialized"]);
                Assert.Equal(true, result["settings_created"]);
                Assert.Equal(true, result["project_id_added"]);
                Assert.True(File.Exists(Path.Combine(folder, "cds-text-sync.json")));
                Assert.Equal("id", ProjectInfo.ProjectIdOf(folder));
                Assert.NotNull(result["commit"]);
                Assert.Equal("{\n  \"project_id\": \"id\"\n}\n", File.ReadAllText(Path.Combine(folder, "cds-text-sync.json")));
            }
            finally { Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", oldConfig); }
        }

        [Fact]
        public void PrepareRefusesA3xFolderAndWritesNothing()
        {
            var folder = Path.Combine(Temp(), "old");
            Directory.CreateDirectory(Path.Combine(folder, ".dump"));
            File.WriteAllText(Path.Combine(folder, ".dump", "manifest.json"), "{}");
            var refusal = Assert.Throws<InvalidOperationException>(() => GitFolder.Prepare(folder, "id"));
            Assert.Contains("3.x export (.dump/manifest.json)", refusal.Message);
            Assert.Equal(new[] { ".dump" }, Directory.GetFileSystemEntries(folder).Select(Path.GetFileName));
        }

        [Fact]
        public void VerdictsMatchTheFolderAndRepositoryCases()
        {
            var newFolder = new Dictionary<string, object>
            {
                { "sync_folder", "P:\\p" }, { "saved", false },
                { "git", new Dictionary<string, object>
                    {
                        { "initialized", true }, { "commit", "0123456789ab" },
                        { "added", new Dictionary<string, object> { { ".gitignore", new List<object> { "*.opt" } } } },
                    }
                },
            };
            Assert.Equal("ok set-sync-folder folder=P:\\p saved=false git=created commit=01234567 ignore_added=1",
                Verdict.Line(SetSyncFolder.Build(newFolder).Status, "set-sync-folder", SetSyncFolder.Build(newFolder).Pairs));

            var existing = new Dictionary<string, object>
            {
                { "path", "P:\\p" }, { "saved", true },
                { "git", new Dictionary<string, object>
                    {
                        { "initialized", false }, { "commit", null },
                        { "added", new Dictionary<string, object> { { ".gitignore", new List<object>() } } },
                    }
                },
            };
            Assert.Equal("ok set-sync-folder folder=P:\\p saved=true git=repository ignore_added=0",
                Verdict.Line(SetSyncFolder.Build(existing).Status, "set-sync-folder", SetSyncFolder.Build(existing).Pairs));
        }

        [Fact]
        public void CommandHelpAndPathUsageAreDeclaredInTheDotnetCli()
        {
            var command = CliCommands.Find(new[] { "set-sync-folder" });
            Assert.NotNull(command);
            Assert.Contains("usage: cts set-sync-folder [PATH] [--new-id] [--owner] [--colleague] [--save]", CliRun.Help(command));
            Assert.Contains("Absolute path, or ./path relative to the CODESYS project file.", CliRun.Help(command));
            Assert.Throws<CliFailure>(() => CliOptions.Parse(new[] { "set-sync-folder", "one", "two" }, null, command));
        }

        [Fact]
        public void RegistryChoosesIdsAndKeepsOwnerState()
        {
            var root = Temp();
            var folder = Path.Combine(root, "sync");
            Directory.CreateDirectory(folder);
            ProjectInfo.SaveSettings(folder, "{\"project_id\":\"existing\",\"deny\":[\"write\"]}");
            Assert.Equal("existing", ProjectInfo.ChooseId("", folder, false, Path.Combine(root, "projects.json")));
            var registry = Path.Combine(root, "projects.json");
            ProjectInfo.Record("existing", folder, "demo", true, registry);
            ProjectInfo.Record("existing", folder, "demo", null, registry);
            Assert.Equal(Path.GetFullPath(folder), ProjectInfo.RegistryFolder("existing", registry));
            Assert.True(ProjectInfo.IsOwner("existing", registry));
            ProjectInfo.Record("existing", folder, "demo", false, registry);
            Assert.False(ProjectInfo.IsOwner("existing", registry));
            ProjectInfo.Claim(folder, "next");
            Assert.Equal("next", ProjectInfo.ProjectIdOf(folder));
            Assert.Contains("\"deny\": [\n    \"write\"\n  ]", File.ReadAllText(Path.Combine(folder, "cds-text-sync.json")));
        }

        // A copy of the project's folder still names its id: --new-id takes it
        // while the project's own folder is elsewhere, never that folder itself.
        [Fact]
        public void NewIdTakesACopiedFolderButNotTheOriginal()
        {
            var root = Temp();
            var registry = Path.Combine(root, "projects.json");
            var original = Path.Combine(root, "original");
            var copy = Path.Combine(root, "copy");
            foreach (var folder in new[] { original, copy })
            {
                Directory.CreateDirectory(folder);
                ProjectInfo.SaveSettings(folder, "{\"project_id\":\"existing\"}");
            }
            ProjectInfo.Record("existing", original, "demo", true, registry);

            var id = ProjectInfo.ChooseId("existing", copy, true, registry);

            Assert.NotEqual("existing", id);
            Assert.Contains("already belongs to project existing", Assert.Throws<InvalidOperationException>(() => ProjectInfo.ChooseId("existing", original, true, registry)).Message);
            Assert.Contains("already belongs to project existing", Assert.Throws<InvalidOperationException>(() => ProjectInfo.ChooseId("other", copy, true, registry)).Message);
        }

        // A shell in a copy's folder whose IDE works on the original's.
        [Fact]
        public void AWorkFolderInsideAnotherSyncFolderIsNamed()
        {
            var root = Temp();
            var original = Path.Combine(root, "original");
            var copy = Path.Combine(root, "copy");
            foreach (var folder in new[] { original, copy })
            {
                Directory.CreateDirectory(Path.Combine(folder, "project-view"));
                ProjectInfo.SaveSettings(folder, "{\"project_id\":\"existing\"}");
            }

            Assert.Equal(copy, ProjectInfo.OtherSyncFolder(Path.Combine(copy, "project-view"), original));
            Assert.Equal("", ProjectInfo.OtherSyncFolder(Path.Combine(original, "project-view"), original));
            Assert.Equal("", ProjectInfo.OtherSyncFolder(root, original));
        }

        [Fact]
        public void ExistingRepositoryGetsMissingRulesWithoutAnInitialCommit()
        {
            var root = Temp();
            var folder = Path.Combine(root, "sync");
            Directory.CreateDirectory(folder);
            GitRepository.Run(folder, "init --quiet");
            var result = GitFolder.Prepare(folder, "id");
            Assert.Equal(false, result["initialized"]);
            Assert.Null(result["commit"]);
            var added = result["added"] as IDictionary<string, object>;
            Assert.Equal(new[] { ".cts-docs/", "*.~u", "*.~u~", "*.opt", "*.precompilecache", "*.compileinfo", "*.compileinfo~", "*.bootinfo", "*.bootinfo_guids", "~cts-*.tmp" },
                Assert.IsType<List<string>>(added[".gitignore"]));
        }

        // A clone git checked out with CRLF (core.autocrlf true) lists every
        // file cts writes again with LF as changed: set-sync-folder keeps the
        // files as written and gives those git converted their LF back; a
        // file committed with CRLF keeps it.
        [Fact]
        public void ACloneWithConvertedLineEndingsGetsItsFilesAsCommitted()
        {
            var root = Temp();
            var team = Path.Combine(root, "team");
            Directory.CreateDirectory(team);
            GitRepository.Run(team, "init --quiet");
            File.WriteAllText(Path.Combine(team, "a.st"), "PROGRAM P\nEND_PROGRAM\n");
            File.WriteAllText(Path.Combine(team, "b.st"), "PROGRAM Q\r\nEND_PROGRAM\r\n");
            File.WriteAllText(Path.Combine(team, "c.st"), "PROGRAM R\nEND_PROGRAM\n");
            GitRepository.Run(team, "add .");
            GitRepository.Run(team, "-c user.name=t -c user.email=t@t commit --quiet -m files");
            var clone = Path.Combine(root, "clone");
            GitRepository.Run(root, "clone --quiet -c core.autocrlf=true team clone");
            Assert.Equal("PROGRAM P\r\nEND_PROGRAM\r\n", File.ReadAllText(Path.Combine(clone, "a.st")));
            Assert.True(GitFolder.ConvertsLineEndings(clone));
            File.WriteAllText(Path.Combine(clone, "c.st"), "PROGRAM R\r\nx := 1;\r\nEND_PROGRAM\r\n");
            var result = GitFolder.Prepare(clone, "id");
            Assert.Equal(2, result["lf_restored"]);
            Assert.Contains("* -text", (IList<string>)((IDictionary<string, object>)result["added"])[".gitattributes"]);
            Assert.Equal("PROGRAM P\nEND_PROGRAM\n", File.ReadAllText(Path.Combine(clone, "a.st")));
            Assert.Equal("PROGRAM Q\r\nEND_PROGRAM\r\n", File.ReadAllText(Path.Combine(clone, "b.st")));
            // An edit is left to its author, unstaged.
            Assert.Equal(" M c.st", GitRepository.Run(clone, "status --porcelain -- *.st").TrimEnd());
            Assert.Equal("PROGRAM R\nx := 1;\nEND_PROGRAM\n", File.ReadAllText(Path.Combine(clone, "c.st")));
            Assert.False(GitFolder.ConvertsLineEndings(clone));
            // A file still with git's CRLF after the rule came (a colleague pulled it) is asked about again.
            File.WriteAllText(Path.Combine(clone, "a.st"), "PROGRAM P\r\nEND_PROGRAM\r\n");
            Assert.True(GitFolder.ConvertsLineEndings(clone));
        }

        // A sync folder reached through another spelling of the repository's
        // root (a mapped drive on Windows, a link here) is that root: git's
        // --show-toplevel names the target, and the folder keeps its own path.
        [Fact]
        public void RepositoryRootReachedThroughALinkIsTheSyncFolder()
        {
            var root = Temp();
            var target = Path.Combine(root, "share");
            Directory.CreateDirectory(target);
            GitRepository.Run(target, "init --quiet");
            var link = Path.Combine(root, "mapped");
            Directory.CreateSymbolicLink(link, target);
            Assert.Equal(false, GitFolder.Prepare(link, "id")["initialized"]);
            Assert.Equal(link, GitRepository.Repository(link));
            Assert.Equal(link, GitRepository.ReadFacts(link).Root);
            var inside = Path.Combine(link, "sub");
            Directory.CreateDirectory(inside);
            var refusal = Assert.Throws<InvalidOperationException>(() => GitRepository.Repository(inside));
            Assert.Contains("is inside the repository at " + link + ", not at its root. Use the repository's root (cts set-sync-folder \"" + link + "\")", refusal.Message);
        }

        static string Temp()
        {
            var path = Path.Combine(Path.GetTempPath(), "cts-sync-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(path);
            return path;
        }
    }
}
