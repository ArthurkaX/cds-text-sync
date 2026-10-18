using System;
using System.IO;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    // A team project's Library Manager is its owner's: another PC's IDE
    // (other library versions) does not write it to disk.
    [Collection("Local command settings")]
    public sealed class OwnerKeepsTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-owner-keeps-" + Guid.NewGuid().ToString("N"));
        readonly string _oldXdg = Environment.GetEnvironmentVariable("XDG_DATA_HOME");
        readonly string _fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
        const string Libraries = "project-view/POUs/Library Manager.xml";

        public OwnerKeepsTests()
        {
            Directory.CreateDirectory(_root);
            Environment.SetEnvironmentVariable("XDG_DATA_HOME", Path.Combine(_root, "xdg"));
            Git("init --quiet");
            File.Copy(Path.Combine(_fixture, "cds-text-sync.json"), Path.Combine(_root, "cds-text-sync.json"));
            Git("add -A");
            Git("-c user.name=Fixture -c user.email=fixture@localhost commit -qm \"set up the sync folder\"");
            ExportCommand.WriteToDisk(Path.Combine(_fixture, "snapshot.xml"), _root, "C:\\projects\\demo.project", false);
            // The branch holds the owner's libraries, other than this IDE's.
            var file = Path.Combine(_root, Libraries);
            File.WriteAllText(file, File.ReadAllText(file).Replace("CAA FB Factory, 3.5.19.0", "CAA FB Factory, 3.5.20.0"));
            Git("add -A");
            Git("-c user.name=Fixture -c user.email=fixture@localhost commit -qm \"the owner's libraries\"");
            Cts.Sync.SyncBase.Record(_root, "project-view", new string[0]);
        }

        public void Dispose()
        {
            Environment.SetEnvironmentVariable("XDG_DATA_HOME", _oldXdg);
            Directory.Delete(_root, true);
        }

        [Fact]
        public void AColleaguesExportPutsTheOwnersLibraryManagerBack()
        {
            var result = ExportCommand.WriteToDisk(Path.Combine(_fixture, "snapshot.xml"), _root, "C:\\projects\\demo.project", false);

            Assert.Equal(new[] { "POUs/Library Manager.xml" }, result.OwnerKept);
            Assert.Contains("CAA FB Factory, 3.5.20.0", File.ReadAllText(Path.Combine(_root, Libraries)));
            Assert.Equal("", Git("status --porcelain -- project-view"));
        }

        [Fact]
        public void TheOwnersExportWritesItsLibraryManager()
        {
            ProjectInfo.Record(ProjectInfo.ProjectIdOf(_root), _root, "demo", true);

            var result = ExportCommand.WriteToDisk(Path.Combine(_fixture, "snapshot.xml"), _root, "C:\\projects\\demo.project", false);

            Assert.Empty(result.OwnerKept);
            Assert.Contains("CAA FB Factory, 3.5.19.0", File.ReadAllText(Path.Combine(_root, Libraries)));
        }

        [Fact]
        public void TheOwnerKeepsTheLibrariesAndTheProjectSettingsOnly()
        {
            var expected = Path.Combine(_fixture, "expected", "POUs");
            Assert.True(ProjectInfo.OwnerKeeps(_root, File.ReadAllBytes(Path.Combine(expected, "Library Manager.xml"))));
            Assert.True(ProjectInfo.OwnerKeeps(_root, File.ReadAllBytes(Path.Combine(expected, "Project Settings.xml"))));
            Assert.False(ProjectInfo.OwnerKeeps(_root, File.ReadAllBytes(Path.Combine(expected, "Project Information.xml"))));
            ProjectInfo.Record(ProjectInfo.ProjectIdOf(_root), _root, "demo", true);
            Assert.False(ProjectInfo.OwnerKeeps(_root, File.ReadAllBytes(Path.Combine(expected, "Project Settings.xml"))));
        }

        string Git(string args) => GitRepository.Run(_root, args).Trim();
    }
}
