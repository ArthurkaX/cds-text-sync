using System;
using System.IO;
using System.Threading.Tasks;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class FolderLockTests : IDisposable
    {
        readonly string _folder = Path.Combine(Path.GetTempPath(), "cts-folder-lock-" + Guid.NewGuid().ToString("N"));

        public FolderLockTests()
        {
            Directory.CreateDirectory(_folder);
            Assert.Equal(0, Cts.Agent.GitRun.In(_folder, "init -q").ExitCode);
        }

        [Fact]
        public async Task SecondRunWaitsUntilFirstReleasesLock()
        {
            var first = FolderLock.Acquire(_folder, TextWriter.Null, TimeSpan.FromSeconds(2));
            var second = Task.Run(() => FolderLock.Acquire(_folder, TextWriter.Null, TimeSpan.FromSeconds(2)));
            await Task.Delay(300);
            Assert.False(second.IsCompleted);
            first.Dispose();
            using (await second) { }
        }

        [Fact]
        public void TimeoutRefusesWithFolderInMessage()
        {
            using (FolderLock.Acquire(_folder, TextWriter.Null, TimeSpan.FromSeconds(1)))
            {
                var error = new StringWriter();
                var failure = Assert.Throws<InvalidOperationException>(() => FolderLock.Acquire(_folder, error, TimeSpan.FromMilliseconds(250)));
                Assert.Contains("another cts run is still working in " + _folder, failure.Message);
                Assert.Contains("progress: waiting for another cts run in this folder", error.ToString());
            }
        }

        public void Dispose()
        {
            if (Directory.Exists(_folder)) Directory.Delete(_folder, true);
        }
    }
}
