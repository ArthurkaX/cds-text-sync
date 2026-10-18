using System;
using System.IO;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class ViewFolderTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-settings-" + Guid.NewGuid().ToString("N"));

        public ViewFolderTests() => Directory.CreateDirectory(Path.Combine(_root, "project-view", "POUs"));

        public void Dispose() => Directory.Delete(_root, true);

        [Fact]
        public void A_sync_folder_is_found_from_inside_its_view_and_named_by_its_view()
        {
            Assert.Equal(_root, ViewFolder.Around(Path.Combine(_root, "project-view", "POUs")));
            Assert.Equal(_root, ViewFolder.Named(Path.Combine(_root, "project-view") + Path.DirectorySeparatorChar));
            Assert.Equal(_root, ViewFolder.Named(_root));
        }

        [Fact]
        public void The_view_is_the_project_view_whatever_an_old_settings_file_says()
        {
            File.WriteAllText(Path.Combine(_root, "cds-text-sync.json"), "{\"layout\": \"root-view\", \"view_root\": \"elsewhere\"}");
            Assert.Equal(Path.Combine(_root, "project-view"), ViewFolder.Of(_root));
        }
    }
}
