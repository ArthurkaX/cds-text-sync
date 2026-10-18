using Xunit;

namespace Cts.Agent.Tests
{
    public class IdleRefreshTests
    {
        const long Quiet = IdleRefresh.QuietMs;

        [Fact]
        public void A_new_state_is_refreshed_once_while_nobody_works()
        {
            var refresh = new IdleRefresh();
            Assert.True(refresh.Due("s:3", Quiet, Quiet, false));
            refresh.Done("s:3");
            Assert.False(refresh.Due("s:3", Quiet, Quiet, false));
            Assert.True(refresh.Due("s:4", Quiet, Quiet, false));
        }

        [Fact]
        public void Input_a_command_or_a_dialog_puts_it_off()
        {
            var refresh = new IdleRefresh();
            Assert.False(refresh.Due("s:1", Quiet - 1, Quiet, false));
            Assert.False(refresh.Due("s:1", Quiet, Quiet - 1, false));
            Assert.False(refresh.Due("s:1", Quiet, Quiet, true));
        }
    }
}
