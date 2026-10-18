using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Agent;

namespace Cts.Cli
{
    // `cts checkout TARGET`: switch git, then carry the clean difference into the IDE.
    public static class CheckoutCommand
    {
        public static readonly CliCommand Command = new CliCommand
        {
            Name = "checkout",
            Arguments = "TARGET",
            ArgumentLimit = 1,
            ArgumentHelp = "A local or remote branch, tag, or commit",
            Summary = "Switch the sync folder to a branch or commit and carry it into the IDE",
            Description = "Switches the sync folder with git and imports the resulting objects into the open IDE project. The project is saved when the import writes. Refused while the PLC is online, without an export base, with uncommitted sync-folder changes, or when the IDE and sync folder differ. --disk-only switches only the folder; cts compare shows the difference and cts import carries it.",
            TimeoutKey = "sync_compare_text",
            Options = new[]
            {
                CliOption.Switch("--disk-only", "disk_only", "Switch the sync folder only; the IDE is untouched"),
                CliOption.Text("--sync-folder", "sync_folder", "PATH", "Sync folder (must match the open project's folder; disk-only uses this folder directly)"),
            },
            LocalExecute = Disk,
            LocalWhen = options => options.Params.ContainsKey("disk_only"),
            Execute = Execute,
            Build = Build,
        };

        static IDictionary<string, object> Disk(CliOptions options, IAgentHost host, string work)
        {
            try
            {
                var folder = GitCommands.Folder(options, host, work);
                var before = GitRepository.Position(folder);
                GitRepository.Switch(folder, options.Arguments[0]);
                return Positions(before, GitRepository.Position(folder), true);
            }
            catch (Exception error) when (error is InvalidOperationException || error is ArgumentException || error is AgentException)
            {
                throw new CliFailure("checkout", "refused", error.Message, "cts checkout --help", 1);
            }
        }

        static IDictionary<string, object> Execute(CliCall call)
        {
            string folder;
            IDictionary<string, object> before;
            try
            {
                if (string.IsNullOrEmpty(call.Hello.SyncFolder)) throw new InvalidOperationException("no sync folder: cts set-sync-folder chooses one");
                folder = GitRepository.Repository(call.Hello.SyncFolder);
                if (call.Options.Params.TryGetValue("sync_folder", out var requested)
                    && !string.Equals(Path.GetFullPath(GitRepository.Repository(Convert.ToString(requested))), Path.GetFullPath(folder), StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("the open project's sync folder is " + folder + ", not " + requested);
                var status = call.Call("project.status", new Dictionary<string, object>(), 10);
                var plc = status.TryGetValue("plc", out var plcValue) ? plcValue as IDictionary<string, object> : null;
                if (plc != null && Equals(plc.TryGetValue("online", out var online) ? online : null, true))
                    throw new InvalidOperationException("The IDE is online with the PLC; editing the project while online is not supported. Run `cts disconnect`, then repeat `cts checkout`.");
                IdeAtCommit.Require(call, folder);
                before = GitRepository.Position(folder);
            }
            catch (CliFailure) { throw; }
            catch (Exception error) when (error is InvalidOperationException || error is ArgumentException || error is AgentException)
            {
                throw new CliFailure("checkout", "refused", error.Message, "cts checkout --help", 1);
            }
            var target = call.Options.Arguments[0];
            try { GitRepository.Switch(folder, target); }
            catch (InvalidOperationException error) { throw new CliFailure("checkout", "refused", error.Message, "cts checkout --help", 1); }
            IDictionary<string, object> imported;
            call.Options.Params["save"] = true;
            try { imported = ImportCommand.Run(call, false); }
            catch (CliFailure stopped)
            {
                GitRepository.Restore(folder, before);
                var untouched = false;
                try
                {
                    var restored = ComparePlanner.Plan(call)["summary"] as IDictionary<string, object>;
                    untouched = restored != null && !restored.Any(pair => pair.Key != "unchanged" && Convert.ToInt32(pair.Value) != 0);
                }
                catch (Exception error) when (error is CliFailure || error is InvalidOperationException || error is AgentException) { }
                if (untouched)
                    throw new CliFailure("checkout", stopped.Cause, "cannot carry " + target + " into the IDE: " + stopped.Cause + "; nothing was written and the sync folder is back on " + Where(before), "cts checkout --help", stopped.ExitCode, stopped.Note);
                GitRepository.Switch(folder, target);
                throw new CliFailure("checkout", stopped.Cause, "the import of " + target + " stopped part way: " + stopped.Cause + "; the sync folder is on it and cts import carries the rest", "cts checkout --help", stopped.ExitCode, stopped.Note);
            }
            if (Equals(imported.ContainsKey("partial") ? imported["partial"] : null, true))
            {
                var cause = Convert.ToString(imported.ContainsKey("partial_reason") ? imported["partial_reason"] : "the import stopped");
                imported["partial_reason"] = "the import of " + target + " stopped part way: " + cause + "; the sync folder is on it and cts import carries the rest";
            }
            foreach (var pair in Positions(before, GitRepository.Position(folder), false)) imported[pair.Key] = pair.Value;
            return imported;
        }

        static IDictionary<string, object> Positions(IDictionary<string, object> before, IDictionary<string, object> after, bool diskOnly)
        {
            var data = new Dictionary<string, object> { { "from", before }, { "to", after } };
            if (diskOnly) data["disk_only"] = true;
            return data;
        }

        static string Where(IDictionary<string, object> position) => Convert.ToString(position["branch"] ?? Convert.ToString(position["commit"]).Substring(0, 8));

        static Answer Build(IDictionary<string, object> data)
        {
            var to = data["to"] as IDictionary<string, object>;
            var branch = to["branch"] ?? "detached";
            var commit = Convert.ToString(to["commit"] ?? "");
            var answer = new Answer().Add("branch", branch).Add("commit", commit.Substring(0, Math.Min(8, commit.Length)));
            if (Equals(data.ContainsKey("disk_only") ? data["disk_only"] : null, true))
                return answer.Add("disk_only", true).Detail("the IDE is as it was: cts compare shows what the switch changed, Next: cts import carries it");
            var imported = ImportCommand.Build(data);
            foreach (var pair in imported.Pairs) answer.Add(pair.Key, pair.Value);
            foreach (var detail in imported.Details) answer.Detail(detail);
            return answer;
        }
    }
}
