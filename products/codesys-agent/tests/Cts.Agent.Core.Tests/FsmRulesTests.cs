using Xunit;

namespace Cts.Agent.Tests
{
    public class FsmRulesTests
    {
        [Theory]
        [InlineData("NEXT_STATE", "STATE")]
        [InlineData("p.act_step", "p.next_step")]
        [InlineData("_newFsmState", "FSMSTATE")]
        public void NamesInTheSamePhaseFamilyMatch(string lhs, string head)
        {
            Assert.True(FsmRules.SameFamily(lhs, head));
        }

        [Theory]
        [InlineData("impact", "reactor")]
        [InlineData("p.state", "q.state")]
        public void UnrelatedNamesStayApart(string lhs, string head)
        {
            Assert.False(FsmRules.SameFamily(lhs, head));
        }
    }
}
