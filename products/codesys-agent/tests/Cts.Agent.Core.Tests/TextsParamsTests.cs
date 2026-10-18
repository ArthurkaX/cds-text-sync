using Xunit;

namespace Cts.Agent.Tests
{
    public class TextsParamsTests
    {
        static Request Req(string paramsJson)
        {
            return Request.Parse("{\"id\":1,\"method\":\"objects.texts\",\"params\":" + paramsJson + "}");
        }

        [Fact]
        public void NoGuidsMeansTheWholeProject()
        {
            Assert.Null(TextsParams.Guids(Req("{}")));
        }

        [Fact]
        public void GuidsAreKeptInOrder()
        {
            var guids = TextsParams.Guids(Req("{\"guids\":[\"a\",\"b\"]}"));
            Assert.Equal(new[] { "a", "b" }, guids);
        }

        [Fact]
        public void AnEmptyGuidIsRefused()
        {
            var ex = Assert.Throws<ProtocolException>(() => TextsParams.Guids(Req("{\"guids\":[\"a\",\"\"]}")));
            Assert.Equal("bad_params", ex.Code);
        }

        [Fact]
        public void GuidsThatAreNotAnArrayAreRefused()
        {
            var ex = Assert.Throws<ProtocolException>(() => TextsParams.Guids(Req("{\"guids\":\"a\"}")));
            Assert.Equal("bad_params", ex.Code);
        }
    }
}
