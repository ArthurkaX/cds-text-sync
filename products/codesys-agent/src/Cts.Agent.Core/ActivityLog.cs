// One human-readable line per agent request, for the agent log.
using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    public static class ActivityLog
    {
        // The CLI's poll, handshake and read traffic; every name is a
        // registered method.  These would drown the writes that matter, unless
        // one took a while: an export of the project is worth a line.
        static readonly HashSet<string> Skipped = new HashSet<string>(StringComparer.Ordinal)
        {
            "ping", "hello", "state", "methods", "subscribe", "unsubscribe",
            "subscriptions", "dialog.probe", "project.status", "project.tree",
            "objects.find", "objects.text", "objects.texts", "objects.fields", "objects.export", "project.export", "vars.read",
        };

        //: A request that took this long is shown, skipped or not, with its time.
        public const long SlowMs = 1000;

        public static bool IsSkipped(string method)
        {
            return method != null && Skipped.Contains(method);
        }

        public static bool IsReported(string method, long elapsedMs)
        {
            return elapsedMs >= SlowMs || !IsSkipped(method);
        }

        // `agent objects.create pou FB_X ok`, `agent objects.delete <guid> forbidden`,
        // `agent app.build ok 2.4 s` for one that took a while.
        public static string Format(string method, IDictionary<string, object> p, bool ok, string errorCode, long elapsedMs = 0)
        {
            var kind = Text(p, "kind");
            var name = Text(p, "name");
            var target = kind != null && name != null ? kind + " " + name : name;
            target = target ?? Text(p, "path") ?? Text(p, "guid");
            return "agent " + method + (target == null ? "" : " " + target)
                + " " + (ok ? "ok" : (string.IsNullOrEmpty(errorCode) ? "error" : errorCode))
                + (elapsedMs >= SlowMs ? " " + (elapsedMs / 1000.0).ToString("0.0", System.Globalization.CultureInfo.InvariantCulture) + " s" : "");
        }

        static string Text(IDictionary<string, object> p, string key)
        {
            object v;
            if (p == null || !p.TryGetValue(key, out v)) return null;
            var s = v as string;
            // One line to the log file: a newline would split it.
            return string.IsNullOrEmpty(s) ? null : s.Replace('\r', ' ').Replace('\n', ' ');
        }
    }
}
