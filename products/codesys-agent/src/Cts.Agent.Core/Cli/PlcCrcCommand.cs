using System;
using System.Collections.Generic;
using Cts.Agent;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    internal static class PlcCrcCommand
    {
        internal static IDictionary<string, object> Execute(CliCall call)
        {
            var data = new Dictionary<string, object>(call.Call("app.crc", new Dictionary<string, object>()))
            {
                ["source"] = new Dictionary<string, object> { ["unrecorded"] = "the project has no sync folder" },
            };
            var plc = data.TryGetValue("plc", out var value) ? value as IDictionary<string, object> : null;
            var code = plc != null && plc.TryGetValue("code", out value) ? value as string : null;
            if (string.IsNullOrEmpty(code))
            {
                data["source"] = new Dictionary<string, object> { ["unrecorded"] = "the PLC reports no code id" };
                return data;
            }
            if (string.IsNullOrEmpty(call.Hello.SyncFolder)) return data;
            try
            {
                var folder = GitRepository.Repository(call.Hello.SyncFolder);
                var reference = "refs/cts/plc/" + code;
                var resolved = GitRun.In(folder, "rev-parse -q --verify " + ProcessArgs.Quote(reference + "^{commit}"));
                var commit = resolved.ExitCode == 0 ? resolved.Output.Trim() : "";
                if (commit.Length == 0) data["source"] = new Dictionary<string, object> { ["unrecorded"] = "no download from a committed state of the sync folder generated this code" };
                else
                {
                    var subject = GitRepository.Run(folder, "log -1 --format=%s " + ProcessArgs.Quote(commit)).Trim();
                    var tags = GitRepository.Run(folder, "tag --points-at " + ProcessArgs.Quote(commit)).Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
                    data["source"] = new Dictionary<string, object> { ["commit"] = commit, ["subject"] = subject, ["tags"] = tags };
                }
            }
            catch (Exception error) when (error is InvalidOperationException || error is ArgumentException || error is AgentException || error is CliFailure)
            { data["source"] = new Dictionary<string, object> { ["unrecorded"] = error.Message }; }
            return data;
        }

        internal static Answer Build(IDictionary<string, object> data)
        {
            var plc = data.TryGetValue("plc", out var p) ? p as IDictionary<string, object> : null;
            var ide = data.TryGetValue("ide", out var i) ? i as IDictionary<string, object> : null;
            var source = data.TryGetValue("source", out var s) ? s as IDictionary<string, object> : null;
            var answer = new Answer().Add("match", Value(data, "match")).Add("plc", Value(plc, "code"))
                .Add("ide", Value(ide, "code")).Add("application", Value(data, "application"));
            if (Value(data, "note") is string note && note.Length > 0) answer.Detail(note);
            if (source != null && source.TryGetValue("commit", out var commit))
            {
                var id = Convert.ToString(commit) ?? "";
                answer.Add("commit", id.Substring(0, Math.Min(8, id.Length)));
                if (source.TryGetValue("tags", out var tags) && tags is IEnumerable<string> names)
                { using (var iterator = names.GetEnumerator()) if (iterator.MoveNext()) answer.Add("tag", iterator.Current); }
                if (source.TryGetValue("subject", out var subject) && subject is string text && text.Length > 0) answer.Detail(text);
            }
            else if (source != null)
            { answer.Add("commit", "unrecorded"); answer.Detail("commit unrecorded: " + Value(source, "unrecorded")); }
            return answer;
        }

    }
}
