using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class FmtReviewTests
    {
        const string Answer = @"{""objects"": 2, ""to_fix"": 1, ""lines"": 2, ""items"": [
            {""guid"": ""g1"", ""label"": ""FB_Valve.Init"", ""timestamp"": 1234567890123, ""lines"": 2,
             ""declaration"": {""before"": ""METHOD Init\r\nVAR\r\nEND_VAR"", ""after"": ""METHOD Init\r\nVAR\r\nEND_VAR""},
             ""implementation"": {""before"": ""x:=1;"", ""after"": ""x := 1;""}},
            {""guid"": ""g2"", ""label"": ""GVL_Main"", ""timestamp"": 7, ""lines"": 0}]}";

        [Fact]
        public void TheAnswerReadsAsObjectsWithTheirTextsBeforeAndAfter()
        {
            var items = FmtReview.Parse(Answer);
            Assert.Equal(new[] { "FB_Valve.Init", "GVL_Main" }, items.Select(item => item.Label));
            Assert.Equal(1234567890123L, items[0].Timestamp);
            Assert.Equal(2, items[0].Lines);
            Assert.Equal("METHOD Init\nVAR\nEND_VAR\n\nx:=1;", items[0].Before);
            Assert.Equal("METHOD Init\nVAR\nEND_VAR\n\nx := 1;", items[0].After);
            Assert.Equal("", items[1].Before);
            Assert.Throws<JsonException>(() => FmtReview.Parse(@"{""ok"": true}"));
        }

        [Fact]
        public void TheNextObjectToFixSkipsThoseTheFormatterLeaves()
        {
            var items = FmtReview.Parse(Answer);
            Assert.Equal(0, FmtReview.NextToFix(items, -1));
            Assert.Equal(-1, FmtReview.NextToFix(items, 0));
            FmtReview.Written(items[0]);
            Assert.Equal(0, items[0].Lines);
            Assert.Equal(items[0].After, items[0].Before);
            Assert.Equal(-1, FmtReview.NextToFix(items, -1));
        }

        [Fact]
        public void ALineTheFormatterAddsKeepsTheLinesAfterItBesideTheirOwn()
        {
            var diff = FmtReview.Changed("IF a THEN\nb := 1;\nEND_IF\nc:=2;", "IF a\nTHEN\nb := 1;\nEND_IF\nc := 2;");
            Assert.Equal(new[] { 0, 3 }, diff.Left);
            Assert.Equal(new[] { 0, 1, 4 }, diff.Right);
            Assert.Equal(new[] { 0, 0, 1, 2, 3 }, diff.LeftOf);
        }

        [Fact]
        public void ChangesAreVisitedRunByRun()
        {
            var changed = new[] { 1, 2, 3, 7, 10, 11 };
            Assert.Equal(new[] { 1, 7, 10 }, FmtReview.Runs(changed));
            Assert.Equal(1, FmtReview.NextChange(changed, -1, true));
            Assert.Equal(7, FmtReview.NextChange(changed, 1, true));
            Assert.Equal(-1, FmtReview.NextChange(changed, 10, true));
            Assert.Equal(7, FmtReview.NextChange(changed, 10, false));
            Assert.Equal(-1, FmtReview.NextChange(changed, 1, false));
        }
    }
}
