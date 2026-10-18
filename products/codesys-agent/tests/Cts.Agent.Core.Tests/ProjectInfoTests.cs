using System;
using System.Collections.Generic;
using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    // The agent's half of the sync folder rule: the project carries only its
    // id, the folder names it, and this machine's registry remembers where the
    // folder is.
    public sealed class ProjectInfoTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-info-" + Guid.NewGuid().ToString("N"));
        readonly string _registry;

        public ProjectInfoTests()
        {
            Directory.CreateDirectory(_root);
            _registry = Path.Combine(_root, "projects.json");
        }

        public void Dispose()
        {
            Directory.Delete(_root, true);
        }

        string Folder(string name, string id)
        {
            var folder = Path.Combine(_root, name);
            Directory.CreateDirectory(folder);
            File.WriteAllText(Path.Combine(folder, "cds-text-sync.json"),
                id == null ? "{\"version\": 2}" : "{\"version\": 2, \"project_id\": \"" + id + "\"}");
            return folder;
        }

        void Register(string id, string folder)
        {
            File.WriteAllText(_registry, Json.Serialize(new Dictionary<string, object>
            {
                { "projects", new Dictionary<string, object> { { id, new Dictionary<string, object> { { "folder", folder } } } } },
            }));
        }

        [Fact]
        public void TheSourceLabelIsComparedWithoutWhenItWasWritten()
        {
            var value = ProjectInfo.Source("main@1a2b3c4d +uncommitted", "2026-10-16 14:02");
            Assert.Equal("main@1a2b3c4d +uncommitted · 2026-10-16 14:02", value);
            Assert.Equal("main@1a2b3c4d +uncommitted", ProjectInfo.SourceOf(value));
            Assert.Equal("", ProjectInfo.SourceOf(""));
            Assert.Equal("typed by hand", ProjectInfo.SourceOf("typed by hand"));
        }

        [Fact]
        public void KnownProjectsAreSortedAndMissingFoldersAreLeftOut()
        {
            var alpha = Folder("alpha", null);
            var beta = Folder("beta", null);
            Register("z", beta);
            File.WriteAllText(_registry, Json.Serialize(new Dictionary<string, object>
            {
                { "projects", new Dictionary<string, object>
                    {
                        { "z", new Dictionary<string, object> { { "folder", beta }, { "name", "beta" } } },
                        { "a", new Dictionary<string, object> { { "folder", alpha }, { "name", "Alpha" }, { "owner", true } } },
                        { "gone", new Dictionary<string, object> { { "folder", Path.Combine(_root, "gone") }, { "name", "Gone" } } },
                    } },
            }));

            var known = ProjectInfo.Known(_registry);
            Assert.Equal(new[] { "Alpha", "beta" }, new[] { known[0].Name, known[1].Name });
            Assert.Equal("a", known[0].Id);
            Assert.Equal(alpha, known[0].Folder);
            Assert.True(known[0].Owner);
            Assert.False(known[1].Owner);
        }

        [Fact]
        public void AKnownProjectUsesItsSingleTrackedProjectFile()
        {
            var folder = Folder("repo", null);
            GitRepository.Run(folder, "init -q");
            GitRepository.Run(folder, "config user.name Tester");
            GitRepository.Run(folder, "config user.email tester@example.invalid");
            var project = Path.Combine(folder, "nested", "main.project");
            Directory.CreateDirectory(Path.GetDirectoryName(project));
            File.WriteAllText(project, "project");
            GitRepository.Run(folder, "add nested/main.project");
            GitRepository.Run(folder, "commit -qm initial");
            Assert.Equal(Path.GetFullPath(project), ProjectInfo.ProjectFile(folder));

            File.WriteAllText(Path.Combine(folder, "other.project"), "project");
            GitRepository.Run(folder, "add other.project");
            GitRepository.Run(folder, "commit -qm second");
            Assert.Equal("", ProjectInfo.ProjectFile(folder));
        }

        [Fact]
        public void AProjectFileInsideItsCloneUsesThatClone()
        {
            var clone = Folder("plant", "A");
            Register("A", Folder("elsewhere", "A"));
            var file = Path.Combine(clone, "binary", "plant.project");
            Assert.Equal(clone, ProjectInfo.SyncFolder("A", file, _registry));
        }

        [Fact]
        public void TheSettingsAreTheFolderFilesTextOrNothing()
        {
            Assert.Equal("{\"version\": 2}", ProjectInfo.Settings(Folder("plant", null)));
            Assert.Equal("", ProjectInfo.Settings(_root));
        }

        [Fact]
        public void AProjectFileAnywhereElseUsesTheRegisteredFolder()
        {
            var clone = Folder("plant", "A");
            Register("A", clone);
            var file = Path.Combine(_root, "Downloads", "plant.project");
            Assert.Equal(clone, ProjectInfo.SyncFolder("A", file, _registry));
        }

        [Fact]
        public void AFolderThatNoLongerNamesTheProjectIsNotItsFolder()
        {
            Register("A", Folder("plant", "B"));
            Assert.Equal("", ProjectInfo.SyncFolder("A", Path.Combine(_root, "plant.project"), _registry));
            Register("A", Path.Combine(_root, "gone"));
            Assert.Equal("", ProjectInfo.SyncFolder("A", Path.Combine(_root, "plant.project"), _registry));
        }

        [Fact]
        public void AnotherProjectsCloneAroundTheFileIsNotItsFolder()
        {
            var other = Folder("other", "B");
            var clone = Folder("plant", "A");
            Register("A", clone);
            Assert.Equal(clone, ProjectInfo.SyncFolder("A", Path.Combine(other, "plant.project"), _registry));
        }

        [Fact]
        public void WithoutAnIdOrARegistryThereIsNoFolder()
        {
            var clone = Folder("plant", null);
            Assert.Equal("", ProjectInfo.SyncFolder("", Path.Combine(clone, "plant.project"), _registry));
            Assert.Equal("", ProjectInfo.SyncFolder("A", Path.Combine(_root, "plant.project"), _registry));
            File.WriteAllText(_registry, "not json");
            Assert.Equal("", ProjectInfo.SyncFolder("A", Path.Combine(_root, "plant.project"), _registry));
        }

        [Fact]
        public void StatusCarriesTheIdAndTheFolderWhenThereIsOne()
        {
            var clone = Folder("plant", "A");
            var info = new Dictionary<string, object>();
            ProjectInfo.AddSyncFolder(info, "A", Path.Combine(clone, "plant.project"), _registry);
            Assert.Equal("A", info["project_id"]);
            Assert.Equal(clone, info["sync_folder"]);
            Assert.False(info.ContainsKey("owner"));
            var unknown = new Dictionary<string, object>();
            ProjectInfo.AddSyncFolder(unknown, "", Path.Combine(clone, "plant.project"), _registry);
            Assert.Empty(unknown);
        }

        [Fact]
        public void StatusSaysWhenThisMachineOwnsTheProject()
        {
            var clone = Folder("plant", "A");
            File.WriteAllText(_registry, "{\"projects\": {\"A\": {\"folder\": " + Json.Serialize(clone) + ", \"owner\": true}}}");
            var info = new Dictionary<string, object>();
            ProjectInfo.AddSyncFolder(info, "A", Path.Combine(_root, "Downloads", "plant.project"), _registry);
            Assert.Equal(true, info["owner"]);
            Assert.Equal(clone, info["sync_folder"]);
        }

        [Fact]
        public void TheSuggestionIsTheEnclosingSyncRootElseAFolderBeside()
        {
            var clone = Folder("plant", null);
            Assert.Equal(clone, ProjectInfo.Suggested(Path.Combine(clone, "plant.project")));
            var loose = Path.Combine(_root, "loose");
            Directory.CreateDirectory(loose);
            Assert.Equal(Path.Combine(loose, "Line-2-cts"), ProjectInfo.Suggested(Path.Combine(loose, "Line 2.project")));
            Assert.Equal("", ProjectInfo.Suggested("Line 2.project"));
        }

        [Fact]
        public void AFolderNameDropsWhatWindowsForbids()
        {
            Assert.Equal("Line-2-cts", ProjectInfo.FolderName("Line  2"));
            Assert.Equal("ab-cts", ProjectInfo.FolderName("a:b?"));
            Assert.Equal("cts", ProjectInfo.FolderName(" . "));
        }

        [Fact]
        public void ARelativePathIsAnchoredToTheProjectFile()
        {
            var file = Path.Combine(_root, "work", "p.project");
            Assert.Equal(Path.Combine(_root, "sync"), ProjectInfo.Anchor("../sync", file));
            Assert.Equal(Path.Combine(_root, "abs"), ProjectInfo.Anchor(Path.Combine(_root, "x", "..", "abs"), file));
            var e = Assert.Throws<ProtocolException>(() => ProjectInfo.Anchor("sync", "p.project"));
            Assert.StartsWith("Cannot resolve a relative sync folder", e.Message);
            Assert.Equal(ErrorCodes.BadParams, Assert.Throws<ProtocolException>(() => ProjectInfo.Anchor("a\0b", file)).Code);
        }
    }
}
