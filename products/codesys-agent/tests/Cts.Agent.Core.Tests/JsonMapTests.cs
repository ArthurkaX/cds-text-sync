using System.Collections.Generic;
using Xunit;

namespace Cts.Agent.Tests
{
    public class JsonMapTests
    {
        [Fact]
        public void ReadsTextWithFallback()
        {
            var map = new Dictionary<string, object> { ["null"] = null, ["number"] = 12L };
            Assert.Equal("fallback", JsonMap.Text(map, "missing", "fallback"));
            Assert.Equal("fallback", JsonMap.Text(map, "null", "fallback"));
            Assert.Equal("12", JsonMap.Text(map, "number", "fallback"));
        }

        [Fact]
        public void ReadsNumberOrNumericStringWithFallback()
        {
            var map = new Dictionary<string, object> { ["null"] = null, ["number"] = 12.5, ["string"] = "2.5", ["bad"] = "no" };
            Assert.Equal(7, JsonMap.Number(map, "missing", 7));
            Assert.Equal(7, JsonMap.Number(map, "null", 7));
            Assert.Equal(12.5, JsonMap.Number(map, "number", 7));
            Assert.Equal(2.5, JsonMap.Number(map, "string", 7));
            Assert.Equal(7, JsonMap.Number(map, "bad", 7));
        }
    }
}
