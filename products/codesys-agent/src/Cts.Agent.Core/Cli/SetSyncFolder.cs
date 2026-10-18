using System;
using System.Collections.Generic;
using Cts.Agent;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    public static class SetSyncFolder
    {
        public static IDictionary<string, object> Execute(CliCall call)
        {
            var parameters = new Dictionary<string, object> { { "dry_run", true } };
            if (call.Options.Arguments.Count > 0) parameters["path"] = call.Options.Arguments[0];
            var planned = call.Call("project.syncfolder", parameters);
            var folder = Text(planned, "sync_folder");
            var oldId = Text(planned, "project_id");
            if (folder == "") throw new InvalidOperationException("The agent did not suggest a sync folder");
            string id;
            IDictionary<string, object> git;
            try
            {
                id = ProjectInfo.ChooseId(oldId, folder, call.Options.Params.ContainsKey("new_id"));
                git = GitFolder.Prepare(folder, id);
                if (call.Options.Params.ContainsKey("owner") && call.Options.Params.ContainsKey("colleague")) throw new ArgumentException("--owner or --colleague, not both");
                if (call.Options.Params.ContainsKey("colleague") && id != oldId) throw new ArgumentException("the machine that gives the project its id is its owner");
                ProjectInfo.Record(id, folder, Text(planned, "name"),
                    call.Options.Params.ContainsKey("colleague") ? false : call.Options.Params.ContainsKey("owner") || id != oldId ? true : (bool?)null);
            }
            catch (Exception e)
            {
                throw new CliFailure("set-sync-folder", "refused", "cannot use " + folder + " as the sync folder, nothing was stored: " + e.Message, null, 1);
            }
            var data = call.Call("project.syncfolder", new Dictionary<string, object>
            {
                { "id", id }, { "save", call.Options.Params.ContainsKey("save") },
            });
            data["git"] = git;
            data["role"] = ProjectInfo.IsOwner(id) ? "owner" : "colleague";
            try { data["guard"] = TeamGuard.Apply(folder, ProjectInfo.IsOwner(id), TeamGuard.Exe); }
            catch (InvalidOperationException e) { data["guard_error"] = e.Message; }
            return data;
        }

        public static Answer Build(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("folder", Value(data, "sync_folder") ?? Value(data, "path")).Add("saved", Value(data, "saved"))
                .Add("role", Value(data, "role"));
            var git = Value(data, "git") as IDictionary<string, object>;
            if (git != null)
            {
                var added = Value(git, "added") as IDictionary<string, object>;
                answer.Add("git", Equals(Value(git, "initialized"), true) ? "created" : "repository")
                    .Add("commit", (Text(git, "commit").Length > 8 ? Text(git, "commit").Substring(0, 8) : Text(git, "commit")) is string commit && commit != "" ? commit : null)
                    .Add("ignore_added", added != null && Value(added, ".gitignore") is System.Collections.ICollection lines ? (object)(long)lines.Count : 0L);
            }
            var guard = Value(data, "guard") as IDictionary<string, object>;
            if (guard != null) answer.Add("hook", Value(guard, "hook"));
            if (Text(guard, "hook") == "kept") answer.Detail("the repository has a pre-push hook of its own, kept: cts' check (cts hook --help) is not installed");
            if (Value(data, "guard_error") != null) answer.Detail("the git part of this PC's role was not set: " + Text(data, "guard_error"));
            return answer;
        }

    }
}
