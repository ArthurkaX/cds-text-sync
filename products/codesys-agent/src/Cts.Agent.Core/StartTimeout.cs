// The `start_timeout_ms` parameter, one definition for every method that waits
// for the IDE's UI thread.
//
// The timeout bounds only how long the UI thread may take to *start* the call.  If
// it does not start in time the caller gets `busy` and the call is abandoned --
// it never runs late.  A caller that wants to wait for a slow but real operation
// (a login, a download) raises the timeout; the upper bound is the largest
// positive millisecond value the protocol can represent.
namespace Cts.Agent
{
    public static class StartTimeout
    {
        public const int DefaultMs = 10000;
        public const int MaxMs = int.MaxValue;

        // How long a call that has started may run before the agent stops
        // waiting for it: a backstop against a UI thread wedged inside a modal
        // loop.  The caller's own timeout bounds what the caller waits.
        public const int FinishBackstopMs = 600000;

        // The caller's `start_timeout_ms`, or the default; out of range is refused
        // before the IDE is touched.
        public static int Parse(Request req)
        {
            return Parse(req, DefaultMs);
        }

        // The same with a method's own default (a short one for a single-object
        // write, say), which the caller can still raise.
        public static int Parse(Request req, int defaultMs)
        {
            var ms = req.Int("start_timeout_ms", defaultMs);
            if (ms < 1 || ms > MaxMs)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "parameter 'start_timeout_ms' must be 1.." + MaxMs);
            return (int)ms;
        }
    }
}
