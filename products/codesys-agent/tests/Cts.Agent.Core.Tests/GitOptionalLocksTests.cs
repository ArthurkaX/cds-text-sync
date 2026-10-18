using System;
using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    public class GitOptionalLocksTests
    {
        [Fact]
        public void Status_does_not_refresh_the_index()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-git-optional-locks-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            try
            {
                GitRepository.Run(folder, "init -q");
                File.WriteAllText(Path.Combine(folder, "tracked.txt"), "initial");
                GitRepository.Run(folder, "add tracked.txt");
                GitRepository.Run(folder, "-c user.name=Tester -c user.email=tester@example.invalid commit -qm initial");

                var index = Path.Combine(folder, ".git", "index");
                var contents = File.ReadAllBytes(index);
                var modified = File.GetLastWriteTimeUtc(Path.Combine(folder, "tracked.txt")).AddMinutes(2);
                File.SetLastWriteTimeUtc(Path.Combine(folder, "tracked.txt"), modified);
                var indexTime = File.GetLastWriteTimeUtc(index);

                var status = GitRun.In(folder, "status --porcelain");

                Assert.Equal(0, status.ExitCode);
                Assert.Equal(indexTime, File.GetLastWriteTimeUtc(index));
                Assert.Equal(contents, File.ReadAllBytes(index));
                Assert.False(File.Exists(index + ".lock"));
            }
            finally { Directory.Delete(folder, true); }
        }
    }
}
