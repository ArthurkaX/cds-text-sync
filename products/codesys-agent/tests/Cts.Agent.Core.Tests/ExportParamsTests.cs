using System;
using Xunit;

namespace Cts.Agent.Tests
{
    public class ExportParamsTests
    {
        static Request Req(string paramsJson)
        {
            return Request.Parse("{\"id\":1,\"method\":\"objects.export\",\"params\":" + paramsJson + "}");
        }

        [Fact]
        public void NoKnownMeansEveryObjectIsExported()
        {
            Assert.Empty(ExportParams.Known(Req("{\"guids\":[]}")));
        }

        [Fact]
        public void KnownMapsAGuidToItsTimeStamp()
        {
            var known = ExportParams.Known(Req("{\"known\":{\"6f9dac99-8de1-4efe-a3b5-a6dbf0a8ce30\":638900000000000000}}"));
            Assert.Equal(638900000000000000L, known[new Guid("6f9dac99-8de1-4efe-a3b5-a6dbf0a8ce30")]);
        }

        [Fact]
        public void AKeyThatIsNotAGuidIsRefused()
        {
            var ex = Assert.Throws<ProtocolException>(() => ExportParams.Known(Req("{\"known\":{\"FB_Motor\":1}}")));
            Assert.Equal("bad_params", ex.Code);
        }

        [Fact]
        public void ATimeStampThatIsNotAnIntegerIsRefused()
        {
            var ex = Assert.Throws<ProtocolException>(() => ExportParams.Known(Req("{\"known\":{\"6f9dac99-8de1-4efe-a3b5-a6dbf0a8ce30\":\"1\"}}")));
            Assert.Equal("bad_params", ex.Code);
        }

        [Fact]
        public void KnownThatIsNotAnObjectIsRefused()
        {
            var ex = Assert.Throws<ProtocolException>(() => ExportParams.Known(Req("{\"known\":[1]}")));
            Assert.Equal("bad_params", ex.Code);
        }
    }
}
