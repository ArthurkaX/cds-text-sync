using System;
using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    public class PrivateIndexTests
    {
        [Fact]
        public void An_old_lock_on_a_private_index_is_dropped_and_a_fresh_one_kept()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-private-index-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            try
            {
                var index = Path.Combine(folder, "base-index");
                var stale = index + ".lock";
                File.WriteAllText(stale, "");
                Assert.Equal(index, GitRepository.PrivateIndex(index)["GIT_INDEX_FILE"]);
                Assert.True(File.Exists(stale));
                File.SetLastWriteTimeUtc(stale, DateTime.UtcNow.AddMinutes(-11));
                GitRepository.PrivateIndex(index);
                Assert.False(File.Exists(stale));
            }
            finally { Directory.Delete(folder, true); }
        }
    }
}
