using System.Collections.Generic;
using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    public class TimeoutProfileTests
    {
        static string NewFolder()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-timeouts-" + System.Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            return folder;
        }

        static IDictionary<string, object> Timeouts(IDictionary<string, object> profile)
        {
            return (IDictionary<string, object>)profile["timeouts"];
        }

        [Fact]
        public void CountsStFilesInNestedProjectViewFolders()
        {
            var folder = NewFolder();
            var deep = Path.Combine(folder, "project-view", "deep", "deeper");
            Directory.CreateDirectory(deep);
            File.WriteAllText(Path.Combine(folder, "project-view", "one.st"), "");
            File.WriteAllText(Path.Combine(deep, "two.ST"), "");
            File.WriteAllText(Path.Combine(deep, "note.txt"), "");
            File.WriteAllText(Path.Combine(folder, "outside.st"), "");

            Assert.Equal(2, TimeoutProfile.CountStBlocks(folder));
            Assert.Null(TimeoutProfile.CountStBlocks(Path.Combine(folder, "nowhere")));
            Assert.Null(TimeoutProfile.CountStBlocks(null));
            Directory.Delete(folder, true);
        }

        [Fact]
        public void SizesEachOperationByTheBlockCount()
        {
            var profile = TimeoutProfile.Make(2);
            Assert.Equal(2, profile["block_count"]);
            Assert.Equal(30, profile["default"]);
            Assert.Equal(60, Timeouts(profile)["connect_to_device"]);
            Assert.Equal(120, Timeouts(profile)["build"]);
            Assert.Equal(60 + 1000 * 0.55, (int)Timeouts(TimeoutProfile.Make(1000))["build"]);
        }

        [Fact]
        public void UnknownSizeNeverUnderEstimates()
        {
            var profile = TimeoutProfile.Make(null);
            Assert.Null(profile["block_count"]);
            Assert.Equal(600, profile["default"]);
            foreach (var value in Timeouts(profile).Values) Assert.Equal(600, value);
        }

        [Fact]
        public void CacheCountsOncePerFolderButRetriesAnEmptyOne()
        {
            var folder = NewFolder();
            var cache = new TimeoutProfileCache();
            Assert.Null(cache.Last);
            Assert.Null(cache.For(folder)["block_count"]);

            var view = Path.Combine(folder, "project-view");
            Directory.CreateDirectory(view);
            File.WriteAllText(Path.Combine(view, "a.st"), "");
            Assert.Equal(1, cache.For(folder)["block_count"]);

            File.WriteAllText(Path.Combine(view, "b.st"), "");
            Assert.Equal(1, cache.For(folder)["block_count"]);
            Assert.Same(cache.Last, cache.For(folder));
            Assert.Null(cache.For(null)["block_count"]);
            Directory.Delete(folder, true);
        }
    }
}
