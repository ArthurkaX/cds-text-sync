using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Threading;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts status`, the four words that decide whether work may proceed, and
    // `cts wait-ready`, which polls it until the application runs.
    public static class StatusCommands
    {
        // One readiness request each: short, so a stuck poll is retried within
        // the wait's budget instead of holding it.
        const double StatusRequestS = 10;
        const double ReadRequestS = 20;

        static readonly Dictionary<string, object> NoParams = new Dictionary<string, object>();

        // What the agent's project.status says, the hint for what blocks
        // edits, and where the sync folder's git is.
        public static IDictionary<string, object> Status(CliCall call)
        {
            var answer = call.Call("project.status", NoParams);
            var path = Value(answer, "path") as string;
            if (path == "") path = null;
            var plc = Value(answer, "plc") as IDictionary<string, object> ?? new Dictionary<string, object>();
            var online = Value(plc, "online") as bool?;
            var data = new Dictionary<string, object>
            {
                { "ide", "ide-" + call.Hello.Pid },
                { "project", path },
                { "unsaved_changes", Value(answer, "unsaved_changes") },
                { "plc", plc },
                { "last_command", Value(answer, "last_command") },
                { "edits_allowed", online.HasValue ? (object)!online.Value : null },
            };
            foreach (var key in new[] { "sync_folder", "suggested_sync_folder", "project_id", "source" })
                if (Value(answer, key) is string text && text.Length > 0) data[key] = text;
            var hint = Hint(path, online);
            if (hint != null) data["hint"] = hint;
            if (data.ContainsKey("sync_folder"))
            {
                data["git"] = FolderGit.Position((string)data["sync_folder"], path);
                if (data.ContainsKey("source") && ProjectSource.Behind((string)data["sync_folder"], (string)data["source"]) is int behind && behind > 0)
                    data["source_behind"] = (long)behind;
            }
            return data;
        }

        // The one thing worth doing next, when something blocks project edits.
        static string Hint(string project, bool? online)
        {
            if (project == null) return "No project is open in the IDE; project-scoped commands will fail (cts project open).";
            if (online == true) return "The IDE is online with the PLC: cts read, write and the PLC commands work now; project edits (import, sync, fmt --write) are refused until cts disconnect, which ends the IDE's online session and leaves the PLC running.";
            if (online == null)
                return "The PLC state could not be read, so project edits are refused (a blind spot must not read as "
                    + "permission). Check the IDE: if it is logged in, run Online -> Logout, then repeat the edit.";
            return null;
        }

        public static Answer StatusLine(IDictionary<string, object> data)
        {
            var online = Value(data, "plc") is IDictionary<string, object> plc ? Value(plc, "online") as bool? : null;
            var edits = Value(data, "edits_allowed") as bool?;
            var answer = new Answer()
                .Add("ide", Value(data, "ide"))
                .Add("plc", online == true ? "online" : online == false ? "offline" : "unknown")
                .Add("edits", edits == true ? "allowed" : edits == false ? "blocked" : null)
                .Add("unsaved", Value(data, "unsaved_changes"));
            if (Value(data, "sync_folder") is string folder) answer.Detail("sync_folder " + folder);
            else if (Value(data, "project") is string)
                answer.Detail("sync_folder none on this machine: " + (Value(data, "suggested_sync_folder") is string suggested
                    ? "cts set-sync-folder takes " + suggested + " (a PATH picks another)" : "cts set-sync-folder chooses one"));
            if (Value(data, "git") is IDictionary<string, object> git) answer.Detail(GitLine(git));
            if (Value(data, "project") is string project) answer.Detail("project " + project);
            if (Value(data, "source") is string source) answer.Detail("source " + source + (Value(data, "source_behind") is long behind
                ? ", " + behind + " commit(s) behind the folder's HEAD: the project file is older than the folder (saved before the last import, or a pull came since); cts compare names what of those commits the IDE lacks and cts import brings it in, nothing to compare means they changed nothing the IDE holds"
                : " (the commit the IDE's code came from at its last import or commit; cts compare shows edits since)"));
            if (Equals(Value(data, "unsaved_changes"), true))
                answer.Detail("unsaved: the IDE holds edits its project file lacks; cts compare shows whether the folder has them, cts save saves the project");
            if (Value(data, "last_command") is IDictionary<string, object> last && Value(last, "method") is string method)
            {
                var ok = Value(last, "ok") as bool?;
                var parts = new List<string> { "last", method, ok == true ? "ok" : ok == false ? "failed" : "?" };
                parts.AddRange(new[] { "errors", "warnings" }.Where(last.ContainsKey).Select(k => k + "=" + Verdict.Quote(last[k])));
                parts.Add(When(Value(last, "recorded_at") as string, DateTime.UtcNow));
                var line = string.Join(" ", parts.Where(p => p.Length > 0));
                if (Equals(Value(last, "changed_after"), true)) line += "; objects changed after it, so it says nothing about them: cts build again";
                answer.Detail(line);
            }
            return edits == true ? answer : answer.Detail(Value(data, "hint"));
        }

        // Where the sync folder's git is: its branch and commit, and what is not committed.
        static string GitLine(IDictionary<string, object> git)
        {
            if (Value(git, "error") is string error) return "git " + error;
            if (!git.ContainsKey("commit")) return "git none: cts set-sync-folder sets the sync folder up";
            var commit = Value(git, "commit") as string;
            return "git branch=" + (Value(git, "branch") as string ?? "detached")
                + " commit=" + (string.IsNullOrEmpty(commit) ? "none" : commit.Substring(0, Math.Min(8, commit.Length)))
                + " uncommitted=" + Verdict.Quote(Value(git, "uncommitted"))
                + (Equals(Value(git, "project_file_changed"), true)
                    ? "; the project file changed too, not counted: every IDE save changes it, and only its owner's cts commit --publish records it"
                    : "");
        }

        // `at 21:59:49, 6 min ago` for a UTC stamp: a past build is told from
        // a current one, since the code may have changed after it.
        public static string When(string recordedAt, DateTime utcNow)
        {
            DateTime moment;
            if (!DateTime.TryParseExact(recordedAt ?? "", "yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture,
                    DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out moment))
                return "";
            var minutes = (int)Math.Floor((utcNow - moment).TotalMinutes);
            var ago = minutes < 1 ? "just now" : minutes < 120 ? minutes + " min ago" : minutes / 60 + " h ago";
            return "at " + moment.ToLocalTime().ToString("HH:mm:ss", CultureInfo.InvariantCulture) + ", " + ago;
        }

        // `cts wait-ready`: the command's budget is the wait's.
        public static IDictionary<string, object> WaitReady(CliCall call) =>
            Ready(call, call.Seconds, Value(call.Options.Params, "var") as string ?? "");

        // The readiness wait of *budget* seconds, with *variable* ("" for
        // none) that must change between two reads.
        internal static IDictionary<string, object> Ready(CliCall call, double budget, string variable)
        {
            var watch = Stopwatch.StartNew();
            return ReadyWait.Run(
                () => call.Call("project.status", NoParams, StatusRequestS),
                name => ReadValue(call, name),
                budget, variable, () => watch.Elapsed.TotalSeconds, s => Thread.Sleep(TimeSpan.FromSeconds(s)));
        }

        // The variable as the IDE spells it; null when it cannot be read.
        static string ReadValue(CliCall call, string name)
        {
            IDictionary<string, object> answer;
            try { answer = call.Call("vars.read", new Dictionary<string, object> { { "names", new List<object> { name } } }, ReadRequestS); }
            catch (CliFailure) { return null; }
            if (!Equals(Value(answer, "logged_in"), true)) return null;
            var result = (Value(answer, "results") as IEnumerable<object>)?.OfType<IDictionary<string, object>>().FirstOrDefault();
            if (result == null || !Equals(Value(result, "ok"), true)) return null;
            return Value(result, "text") as string ?? Convert.ToString(Value(result, "value"), CultureInfo.InvariantCulture);
        }

        public static Answer ReadyLine(IDictionary<string, object> data)
        {
            var answer = new Answer()
                .Add("ready", Value(data, "ready"))
                .Add("ready_after_s", Value(data, "ready_after_s"))
                .Add("checks", Value(data, "checks"))
                .Add("ready_var", Value(data, "ready_var"))
                .Add("was", Value(data, "was"))
                .Add("value", Value(data, "value"));
            return Equals(Value(data, "ready"), true) ? answer : answer.Failed().Detail(Value(data, "reason"));
        }

    }

    // Readiness: the application is in run, and with a variable named, its
    // value changed between two reads -- the task is cycling, not merely
    // labelled run. The polls are separate short calls, so the IDE is free
    // between them; a wait inside the agent would hold its UI thread.
    public static class ReadyWait
    {
        const double PollS = 0.5;

        // *status* is one project.status call (a CliFailure is retried),
        // *read* one read of the variable (null when unreadable).
        public static IDictionary<string, object> Run(Func<IDictionary<string, object>> status, Func<string, string> read,
            double budget, string variable, Func<double> clock, Action<double> sleep)
        {
            var started = clock();
            var checks = 0;
            string previous = null, lastState, lastError;
            var sawValue = false;
            while (true)
            {
                checks++;
                bool running;
                try
                {
                    var plc = status().TryGetValue("plc", out var p) ? p as IDictionary<string, object> : null;
                    running = Running(plc);
                    lastState = StateText(plc);
                    lastError = null;
                }
                catch (CliFailure f)
                {
                    running = false;
                    lastState = "the agent is unreachable";
                    lastError = f.Message;
                }
                if (running)
                {
                    if (variable.Length == 0) return Ready(clock() - started, checks, null, null, null);
                    var value = read(variable);
                    if (value != null)
                    {
                        if (sawValue && value != previous) return Ready(clock() - started, checks, variable, previous, value);
                        previous = value;
                        sawValue = true;
                    }
                }
                var elapsed = clock() - started;
                if (elapsed >= budget)
                    return NotReady(elapsed, checks, budget, variable, running, lastState, previous, sawValue, lastError);
                sleep(Math.Min(PollS, Math.Max(0, budget - elapsed)));
            }
        }

        // The agent's `running` when it could read one, else the state's word;
        // an unreadable block is never running.
        static bool Running(IDictionary<string, object> plc)
        {
            if (plc == null) return false;
            if (plc.TryGetValue("running", out var running) && Equals(running, true)) return true;
            var state = (plc.TryGetValue("application_state", out var s) ? Convert.ToString(s, CultureInfo.InvariantCulture) : "").Trim().ToLowerInvariant();
            return state == "run" || state == "running";
        }

        static string StateText(IDictionary<string, object> plc)
        {
            if (plc == null) return "unknown";
            var state = (plc.TryGetValue("application_state", out var s) ? Convert.ToString(s, CultureInfo.InvariantCulture) : "").Trim();
            if (state.Length > 0) return state;
            plc.TryGetValue("online", out var online);
            return Equals(online, false) ? "offline" : Equals(online, true) ? "online, state unreadable" : "unknown";
        }

        static Dictionary<string, object> Ready(double elapsed, int checks, string variable, string was, string value)
        {
            var payload = new Dictionary<string, object> { { "ready", true }, { "ready_after_s", Math.Round(elapsed, 2) }, { "checks", (long)checks } };
            if (variable == null) return payload;
            payload["ready_var"] = variable;
            payload["was"] = was;
            payload["value"] = value;
            return payload;
        }

        static Dictionary<string, object> NotReady(double elapsed, int checks, double budget, string variable, bool running,
            string lastState, string previous, bool sawValue, string lastError)
        {
            var seconds = budget.ToString("0.###", CultureInfo.InvariantCulture) + "s";
            string reason;
            if (!running) reason = "the application did not reach run within " + seconds + " (last application state: " + lastState + ")";
            else if (!sawValue) reason = "the application is running, but " + variable + " could not be read within " + seconds;
            else reason = "the application is running, but " + variable + " did not change within " + seconds + " (last value: '"
                + previous + "'); it may be constant, or the task may not be cycling";
            if (lastError != null) reason += "; last agent error: " + lastError;
            var payload = new Dictionary<string, object>
            {
                { "ready", false }, { "ready_after_s", Math.Round(elapsed, 2) }, { "checks", (long)checks }, { "reason", reason },
            };
            if (variable.Length > 0) payload["ready_var"] = variable;
            return payload;
        }
    }
}
