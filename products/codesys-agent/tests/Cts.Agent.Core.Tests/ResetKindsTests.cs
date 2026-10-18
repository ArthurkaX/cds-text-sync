using Xunit;

namespace Cts.Agent.Tests
{
    public class ResetKindsTests
    {
        [Fact]
        public void EachKindIsItsResetOption()
        {
            Assert.Equal(0, ResetKinds.Option("", false));
            Assert.Equal(0, ResetKinds.Option(null, false));
            Assert.Equal(0, ResetKinds.Option("Warm", false));
            Assert.Equal(1, ResetKinds.Option(" cold ", false));
            Assert.Equal(2, ResetKinds.Option("origin", true));
        }

        [Fact]
        public void OriginNeedsForce()
        {
            var error = Assert.Throws<ProtocolException>(() => ResetKinds.Option("origin", false));
            Assert.Equal(ErrorCodes.BadParams, error.Code);
            Assert.Contains("--force", error.Message);
        }

        [Fact]
        public void AnUnknownKindNamesTheKnownOnes()
        {
            var error = Assert.Throws<ProtocolException>(() => ResetKinds.Option("hot", true));
            Assert.Contains("Use warm, cold, or origin", error.Message);
        }

        [Fact]
        public void OnlyOriginHasItsOwnDenyKey()
        {
            Assert.Equal("reset_plc", ResetKinds.KeyOf(0));
            Assert.Equal("reset_plc", ResetKinds.KeyOf(1));
            Assert.Equal("reset_plc --kind origin", ResetKinds.KeyOf(2));
            Assert.Equal("cold", ResetKinds.NameOf(1));
            Assert.Equal("origin", ResetKinds.NameOf(2));
            Assert.Equal("warm", ResetKinds.NameOf(0));
        }

        [Fact]
        public void AnOriginEntryRefusesOriginAlone()
        {
            const string config = "{\"deny\": [\"reset_plc --kind origin\"]}";
            Assert.True(DenyRules.Check(config, true, ResetKinds.KeyOf(1), out _));
            Assert.False(DenyRules.Check(config, true, ResetKinds.KeyOf(2), out _));
            Assert.False(DenyRules.Check("{\"deny\": [\"reset_plc\"]}", true, ResetKinds.KeyOf(2), out var reason));
            Assert.Contains("pattern 'reset_plc'", reason);
        }
    }
}
