using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    public class SafeFileTests
    {
        [Fact]
        public void Replace_moves_temporary_file_to_missing_target()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-safe-file-" + Path.GetRandomFileName());
            Directory.CreateDirectory(folder);
            try
            {
                var temporary = Path.Combine(folder, "file.tmp");
                var target = Path.Combine(folder, "file.txt");
                File.WriteAllText(temporary, "new");

                SafeFile.Replace(temporary, target);

                Assert.Equal("new", File.ReadAllText(target));
                Assert.False(File.Exists(temporary));
            }
            finally { Directory.Delete(folder, true); }
        }

        [Fact]
        public void Replace_replaces_existing_target()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-safe-file-" + Path.GetRandomFileName());
            Directory.CreateDirectory(folder);
            try
            {
                var temporary = Path.Combine(folder, "file.tmp");
                var target = Path.Combine(folder, "file.txt");
                File.WriteAllText(target, "old");
                File.WriteAllText(temporary, "new");

                SafeFile.Replace(temporary, target);

                Assert.Equal("new", File.ReadAllText(target));
                Assert.False(File.Exists(temporary));
            }
            finally { Directory.Delete(folder, true); }
        }
    }
}
