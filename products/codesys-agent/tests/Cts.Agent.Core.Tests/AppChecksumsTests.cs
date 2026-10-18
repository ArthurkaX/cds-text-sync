using System;
using Xunit;

namespace Cts.Agent.Tests
{
    public class AppChecksumsTests
    {
        [Fact]
        public void TheChecksumIsTheIdsFirstField()
        {
            Assert.Equal(0x4a4f987cu, AppChecksums.OfId(new Guid("4a4f987c-0000-0000-0000-000000000000")));
            Assert.Equal(0u, AppChecksums.OfId(Guid.Empty));
        }

        [Fact]
        public void EqualChecksumsMatch()
        {
            var answer = AppChecksums.Compare("Application", 0x4a4f987c, 0xb87abd54, 0x4a4f987c, 0xb87abd54);
            Assert.Equal(true, answer["match"]);
            var plc = (System.Collections.Generic.Dictionary<string, object>)answer["plc"];
            Assert.Equal("4a4f987c", plc["code"]);
            Assert.Equal("b87abd54", plc["data"]);
            Assert.False(answer.ContainsKey("note"));
        }

        [Fact]
        public void ADifferentDataChecksumIsAMismatch()
        {
            Assert.Equal(false, AppChecksums.Compare("A", 1, 2, 1, 3)["match"]);
        }

        [Fact]
        public void NoApplicationOnThePlcHasNothingToMatch()
        {
            var answer = AppChecksums.Compare("A", 0, 0, 1, 2);
            Assert.Null(answer["plc"]);
            Assert.Null(answer["match"]);
            Assert.Contains("cts download", (string)answer["note"]);
        }

        [Fact]
        public void NoCodeGeneratedHasNothingToMatch()
        {
            var answer = AppChecksums.Compare("A", 1, 2, 0, 0);
            Assert.Null(answer["ide"]);
            Assert.Null(answer["match"]);
            Assert.Contains("generated no code", (string)answer["note"]);
        }
    }
}
