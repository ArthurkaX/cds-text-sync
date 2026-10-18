using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class ProcessArgsTests
    {
        [Theory]
        [InlineData(new[] { "commit", "-m", "fix the valve" }, "commit -m \"fix the valve\"")]
        [InlineData(new[] { "commit", "-m", "say \"hi\"" }, "commit -m \"say \\\"hi\\\"\"")]
        [InlineData(new[] { "a b\\", "" }, "\"a b\\\\\" \"\"")]
        [InlineData(new[] { "c:\\x\\y", "x\\\"y" }, "c:\\x\\y \"x\\\\\\\"y\"")]
        public void EachArgumentIsReadBackWhole(string[] args, string line)
        {
            Assert.Equal(line, ProcessArgs.Join(args));
        }

        [Fact]
        public void APathKeepsItsBackslashes()
        {
            Assert.Equal("\"C:\\team\\fx 2\\\\\"", ProcessArgs.Quote("C:\\team\\fx 2\\"));
            Assert.Equal("C:\\team\\fx2", ProcessArgs.Quote("C:\\team\\fx2"));
        }
    }
}
