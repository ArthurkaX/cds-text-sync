using System;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class GitRunTests
    {
        [Fact]
        public void WaitForExitTimesOutWhenGitWaitsForInput()
        {
            System.Diagnostics.Process process;
            try
            {
                process = Cts.Agent.GitRun.Start(Environment.CurrentDirectory, "hash-object --stdin", null, true, true, true);
            }
            catch (InvalidOperationException error) when (error.Message.StartsWith("git could not run:", StringComparison.Ordinal))
            {
                return;
            }

            using (process)
            {
                var error = process.StandardError.ReadToEndAsync();
                var output = process.StandardOutput.ReadToEndAsync();
                var timeout = Assert.Throws<InvalidOperationException>(() => Cts.Agent.GitRun.WaitForExit(process, "hash-object --stdin", 1000));
                Assert.Equal("git did not finish in 1 s: git hash-object --stdin", timeout.Message);
                Assert.True(process.WaitForExit(10000));
            }
        }
    }
}
