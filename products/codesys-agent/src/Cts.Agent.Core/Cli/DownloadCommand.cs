using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Cts.Agent;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts download`: the agent's full download (app.download), or with
    // --online-change its online change, then the
    // commit the PLC's new code came from recorded for cts plc-crc, then the
    // wait until the application runs. The wait is cts.exe's, as separate
    // short calls: inside the agent it would hold the IDE's UI thread.
    public static class DownloadCommand
    {
        const double DefaultReadyS = 30;
        const double CrcS = 30;

        public static IDictionary<string, object> Execute(CliCall call)
        {
            var options = call.Options.Params;
            var start = !Equals(Value(options, "start"), "0");
            var watch = ProjectFileWatch.Start(call.Hello.ProjectPath);
            var parameters = new Dictionary<string, object> { { "start", start }, { "online_change", options.ContainsKey("online_change") } };
            var data = new Dictionary<string, object>(call.Call("app.download", parameters));
            watch.Report(data);
            if (Equals(Value(data, "downloaded"), true)) data["source"] = Record(call);
            if (!start)
            {
                data["ready"] = null;
                data["note"] = "not started (--start 0), so readiness was not waited for";
                return data;
            }
            if (options.ContainsKey("no_wait"))
            {
                data["ready"] = null;
                data["note"] = "readiness was not waited for (--no-wait); the application may not be running yet";
                return data;
            }
            var budget = options.TryGetValue("ready_timeout", out var seconds) ? Convert.ToDouble(seconds, CultureInfo.InvariantCulture) : DefaultReadyS;
            foreach (var pair in StatusCommands.Ready(call, budget, Value(options, "ready_var") as string ?? "")) data[pair.Key] = pair.Value;
            return data;
        }

        // When the IDE held exactly the sync folder's commit, the ref
        // refs/cts/plc/<code id> on it: {branch, commit}; else {unrecorded:
        // why}. It never fails the download.
        static IDictionary<string, object> Record(CliCall call)
        {
            try
            {
                if (string.IsNullOrEmpty(call.Hello.SyncFolder)) return Unrecorded("the project has no sync folder");
                var folder = GitRepository.Repository(call.Hello.SyncFolder);
                IdeAtCommit.Require(call, folder);
                var code = Value(Value(call.Call("app.crc", new Dictionary<string, object>(), CrcS), "plc") as IDictionary<string, object>, "code") as string;
                if (string.IsNullOrEmpty(code)) return Unrecorded("the PLC reports no code id");
                var position = GitRepository.Position(folder);
                GitRepository.Run(folder, "update-ref refs/cts/plc/" + code + " " + position["commit"]);
                return position;
            }
            catch (Exception error) when (error is InvalidOperationException || error is ArgumentException || error is AgentException || error is CliFailure)
            {
                return Unrecorded(error.Message);
            }
        }

        internal const string SavedByIde = "the IDE saved the project during the download (cts did not ask it to): the file is now in this IDE's format";

        // After a login the IDE stays online, and the next project edit is refused.
        internal const string StaysOnline = "the IDE stays online: project edits (import, update-pou, delete-pou) are refused until cts disconnect, which leaves the PLC running";

        internal const string UpToDate = "the PLC already runs the code the IDE generated last: nothing to change (cts build first when the project changed since)";

        static IDictionary<string, object> Unrecorded(string why) => new Dictionary<string, object> { { "unrecorded", why } };

        public static Answer Build(IDictionary<string, object> data)
        {
            var answer = new Answer()
                .Add("downloaded", Value(data, "downloaded"))
                .Add("online_change", Value(data, "online_change"))
                .Add("started", Value(data, "started"))
                .Add("ready", Value(data, "ready"))
                .Add("ready_var", Value(data, "ready_var"))
                .Add("was", Value(data, "was"))
                .Add("value", Value(data, "value"))
                .Add("application", Value(data, "application"))
                .Add("plc", Value(data, "plc"));
            if (Equals(Value(data, "saved_by_ide"), true)) answer.Add("saved", "by-ide").Detail(SavedByIde);
            if (Value(data, "source") is IDictionary<string, object> source)
            {
                if (Value(source, "commit") is string commit && commit.Length > 0) answer.Add("commit", commit.Substring(0, Math.Min(8, commit.Length)));
                else answer.Add("commit", "unrecorded").Detail("commit unrecorded: " + Value(source, "unrecorded"));
            }
            if (Equals(Value(data, "online_change"), "up_to_date")) answer.Detail(UpToDate);
            if (Equals(Value(data, "app_created"), true)) answer.Detail("the PLC had no such application; the login created it");
            foreach (var message in (Value(data, "messages") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>())
                answer.Detail("[" + Value(message, "code") + "] " + Value(message, "text"));
            if (Equals(Value(data, "downloaded"), true)) answer.Detail(StaysOnline);
            return Equals(Value(data, "ready"), false) ? answer.Failed().Detail("not ready: " + Value(data, "reason")) : answer;
        }

    }
}
