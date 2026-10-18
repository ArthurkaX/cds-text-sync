using System.Collections;
using System.Collections.Generic;

namespace Cts.Agent
{
    // Right after a login CODESYS reports "Not logged in" for a new watch until
    // its first monitoring value arrives, although the application is logged in.
    public static class VarReadPolicy
    {
        public const int RetryForMs = 1000;
        public const int RetryPauseMs = 50;

        public static bool ShouldRetry(Dictionary<string, object> envelope)
        {
            object loggedIn;
            if (envelope == null || !envelope.TryGetValue("logged_in", out loggedIn) || !(loggedIn is bool) || !(bool)loggedIn)
                return false;
            object results;
            if (!envelope.TryGetValue("results", out results)) return false;
            foreach (var item in (IEnumerable)results)
            {
                var result = item as IDictionary;
                var error = result == null ? null : result["error"] as IDictionary;
                if (error != null && (error["code"] as string) == Vars.Codes.NotLoggedIn) return true;
            }
            return false;
        }
    }
}
