using Xunit;

namespace Cts.Agent.Tests
{
    public class TextEditTests
    {
        static Request Req(string json)
        {
            return Request.Parse(json);
        }

        static ProtocolException Fail(string json)
        {
            return Assert.Throws<ProtocolException>(() => TextEdit.From(Req(json)));
        }

        [Fact]
        public void ReadsBothParts()
        {
            var edit = TextEdit.From(Req("{\"method\":\"objects.settext\",\"params\":{\"declaration\":\"D\",\"implementation\":\"I\"}}"));
            Assert.True(edit.HasDeclaration);
            Assert.True(edit.HasImplementation);
            Assert.Equal("D", edit.Declaration);
            Assert.Equal("I", edit.Implementation);
        }

        [Fact]
        public void OnePartLeavesTheOtherUnset()
        {
            var edit = TextEdit.From(Req("{\"method\":\"objects.settext\",\"params\":{\"declaration\":\"D\"}}"));
            Assert.True(edit.HasDeclaration);
            Assert.False(edit.HasImplementation);
            Assert.Null(edit.Implementation);
        }

        [Fact]
        public void EmptyStringIsARealEdit()
        {
            var edit = TextEdit.From(Req("{\"method\":\"objects.settext\",\"params\":{\"implementation\":\"\"}}"));
            Assert.True(edit.HasImplementation);
            Assert.Equal("", edit.Implementation);
        }

        [Fact]
        public void NeitherPartIsBadParams()
        {
            Assert.Equal(ErrorCodes.BadParams, Fail("{\"method\":\"objects.settext\",\"params\":{}}").Code);
        }

        [Fact]
        public void NullPartCountsAsAbsent()
        {
            Assert.Equal(ErrorCodes.BadParams, Fail("{\"method\":\"objects.settext\",\"params\":{\"declaration\":null}}").Code);
        }

        [Fact]
        public void WrongTypeIsBadParams()
        {
            Assert.Equal(ErrorCodes.BadParams, Fail("{\"method\":\"objects.settext\",\"params\":{\"implementation\":7}}").Code);
        }
    }
}
