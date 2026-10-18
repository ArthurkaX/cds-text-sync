// When the cached variable watches stop being trustworthy.
//
// A watch (IVarRef + IOnlineVarRef for one expression) survives as long as the
// online session and the application do.  Two things end that:
//
//   * the session moves -- a login or logout makes the online application a
//     different one, and CODESYS itself warns that a watch built before a
//     download answers "Invalid expression" afterwards;
//   * a different ActiveApplication appears -- another project, or the same one
//     reopened, which never hits a watch keyed on the old GUID anyway.
//
// A plain run/stop state change is deliberately not on the list: it churns
// often and the watches stay valid across it.
//
// The policy is here, not in the IDE-facing file, so it is tested without an IDE.
using System;

namespace Cts.Agent
{
    public sealed class VarWatchPolicy
    {
        //: Protocol event names after which the watches must be dropped.
        public static readonly string[] SessionMoves =
        {
            "online.application_login",
            "online.application_logout",
            "online.device_login",
            "online.device_logout",
            "online.before_download",
            "online.after_download",
        };

        readonly VarCache _cache;
        string _application;

        public VarWatchPolicy(VarCache cache)
        {
            if (cache == null) throw new ArgumentNullException("cache");
            _cache = cache;
        }

        //: How many times the policy dropped the cache (diagnostics/tests).
        public int Invalidations { get; private set; }

        // True when an online event means the watches are stale.
        public static bool WatchesAreStale(string onlineEvent)
        {
            if (onlineEvent == null) return false;
            foreach (var move in SessionMoves)
                if (move == onlineEvent) return true;
            return false;
        }

        public void OnOnlineEvent(string onlineEvent)
        {
            if (WatchesAreStale(onlineEvent)) Invalidate();
        }

        // The application a call resolved to; a change means a different project.
        public void OnApplication(string application)
        {
            var next = application ?? "";
            if (next == (_application ?? "")) return;
            _application = next;
            Invalidate();
        }

        public void Invalidate()
        {
            _cache.Clear();
            Invalidations++;
        }
    }
}
