using Xunit;

namespace Cts.Agent.Tests
{
    // What the user typed on the caret's line reaches the object before a
    // method reads, writes or compiles it; other methods leave the editors be.
    public class OpenEditorsTests
    {
        [Theory]
        [InlineData("objects.texts")]
        [InlineData("objects.settext")]
        [InlineData("journal.take")]
        [InlineData("project.export")]
        [InlineData("project.save")]
        [InlineData("app.build")]
        [InlineData("app.download")]
        [InlineData("app.login")]
        public void ReadsWritesAndCompilesCommitTheEditorsFirst(string method)
        {
            Assert.True(OpenEditors.CommitFirst(method));
        }

        [Theory]
        [InlineData("vars.read")]
        [InlineData("vars.write")]
        [InlineData("app.logout")]
        [InlineData("dev.reflect")]
        public void OtherMethodsLeaveTheEditorsAlone(string method)
        {
            Assert.False(OpenEditors.CommitFirst(method));
        }
    }
}
