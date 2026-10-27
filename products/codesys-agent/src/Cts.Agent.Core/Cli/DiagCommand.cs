using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using Cts.Agent;
using Cts.Docs;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts diag`: the setup a maintainer needs to see, as versions, settings
    // and counts. A project's files, objects, branches and paths stay out, so
    // the report can go where everyone reads it.
    public static class DiagCommand
    {
        public static readonly CliCommand Command = new CliCommand
        {
            Name = "diag",
            Arguments = "[FOLDER]",
            ArgumentLimit = 1,
            Summary = "Report this PC's setup for a bug report, without project content",
            Description = "Prints what a bug report needs: the cts, Windows and git versions, the CODESYS installs that hold the cts menu entry "
                + "and whether it is up to date, the IDEs with an agent, and the sync folder's git state: line-ending settings, "
                + "the counts of tracked, changed and untracked files, branch and upstream, this PC's role. It names no file, object, "
                + "branch, project or path, so it is safe to post publicly; read it before sending all the same. FOLDER is the sync "
                + "folder (default: the current folder). It changes nothing and does not need the IDE.",
            LocalExecute = (options, host, work) => Execute(options, host, work),
            Build = BuildAnswer,
        };

        static IDictionary<string, object> Execute(CliOptions options, IAgentHost host, string work)
        {
            var folder = options.Arguments.Count > 0 ? Path.GetFullPath(Path.Combine(work, options.Arguments[0])) : work;
            var here = Directory.Exists(folder) ? folder : AppDomain.CurrentDomain.BaseDirectory;
            var git = FirstLine(here, "--version");
            return new Dictionary<string, object>
            {
                { "cts", CliRun.Build() },
                { "windows", System.Runtime.InteropServices.RuntimeInformation.OSDescription.Trim() },
                { "git", git ?? "not found" },
                { "git_lfs", git == null ? "not found" : FirstLine(here, "lfs version") ?? "not found" },
                { "script_dirs", InstallCommand.ScriptDirs().Select(dir => (object)ScriptDir(dir)).ToList() },
                { "agents", AgentChoice.Discover(host, 3).Select(entry => (object)Agent(entry)).ToList() },
                { "folder", git == null ? NoGit(folder) : Folder(folder) },
            };
        }

        // The first line git prints, or null when it fails or git is missing.
        static string FirstLine(string folder, string args)
        {
            try
            {
                var run = GitRun.In(folder, args);
                return run.ExitCode == 0 ? run.Output.Split('\n')[0].Trim() : null;
            }
            catch (InvalidOperationException) { return null; }
        }

        // A ScriptDir by the IDE it belongs to, not by its path, which holds
        // the user's name.
        static IDictionary<string, object> ScriptDir(string dir)
        {
            var ide = Path.GetDirectoryName(dir);
            var above = Path.GetDirectoryName(ide);
            var place = Same(above, Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData)) ? "user's " + Path.GetFileName(ide)
                : Same(above, Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData)) ? "machine's " + Path.GetFileName(ide)
                : Path.GetFileName(above);
            var data = new Dictionary<string, object> { { "ide", place }, { "installed", File.Exists(Path.Combine(dir, "cds-text-sync", "cds-text-sync.py")) } };
            var source = InstallCommand.Sources(AppDomain.CurrentDomain.BaseDirectory);
            if (!Equals(data["installed"], true) || source == null) return data;
            var check = InstallCommand.Install(source, dir, true, false, Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), DiagramView.Mermaid());
            data["differs_from_this_cts"] = ((IList<object>)check["written"]).Count;
            data["problems"] = ((IList<object>)check["problems"]).Count;
            return data;
        }

        static IDictionary<string, object> Agent(IDictionary<string, object> hello)
        {
            if (Value(hello, "error") is IDictionary<string, object> error)
                return new Dictionary<string, object> { { "error", Value(error, "code") } };
            return new Dictionary<string, object>
            {
                { "ide", Value(hello, "product") + " " + Value(hello, "product_version") },
                { "agent", Value(hello, "agent_version") },
                { "protocol", Value(hello, "protocol") },
                { "64bit", Value(hello, "is_64bit") },
                { "project_open", !string.IsNullOrEmpty(Value(Value(hello, "project") as IDictionary<string, object>, "path") as string) },
                { "ui_busy", Equals(Value(hello, "ui_busy"), true) },
                { "dialogs", Items(hello, "dialogs").Count() },
            };
        }

        static IDictionary<string, object> NoGit(string folder) =>
            new Dictionary<string, object> { { "exists", Directory.Exists(folder) }, { "git_state", "not checked: git not found" } };

        static IDictionary<string, object> Folder(string folder)
        {
            var data = new Dictionary<string, object> { { "exists", Directory.Exists(folder) } };
            if (!Directory.Exists(folder)) return data;
            var top = GitRun.In(folder, "rev-parse --show-toplevel");
            data["git_repository"] = top.ExitCode == 0;
            if (top.ExitCode != 0) return data;
            var root = Path.GetFullPath(top.Output.Trim());
            data["at_repository_root"] = Same(root, folder);
            var settings = Path.Combine(root, "cds-text-sync.json");
            data["settings"] = File.Exists(settings) ? string.Join(" ", Keys(settings)) : "none";
            data["this_pc"] = Role(root);
            data["core.autocrlf"] = Setting(root, "core.autocrlf");
            data["core.eol"] = Setting(root, "core.eol");
            data["text_attribute"] = Attribute(root, "text", "cds-text-sync.json");
            data["tmp_ignored"] = GitRun.In(root, "check-ignore -q --no-index -- ~cts-diag.tmp").ExitCode == 0;
            data["converts_line_endings"] = GitFolder.ConvertsLineEndings(root);
            var projects = Entries(root, "ls-files -z -- \"*.project\"");
            data["project_files"] = projects.Count;
            if (projects.Count == 1) data["project_file_filter"] = Attribute(root, "filter", projects[0]);
            data["tracked"] = Entries(root, "ls-files -z").Count;
            data["line_endings"] = string.Join(", ", Entries(root, "ls-files --eol -z").Select(Eol).GroupBy(eol => eol)
                .OrderBy(group => group.Key, StringComparer.Ordinal).Select(group => group.Key + " " + group.Count()));
            data["changed"] = Changed(root, "");
            data["changed_but_cr"] = Changed(root, " --ignore-cr-at-eol");
            data["changed_but_space"] = Changed(root, " -w");
            data["untracked"] = Entries(root, "ls-files --others --exclude-standard -z").Count;
            data["skip_worktree"] = Entries(root, "ls-files -v -z").Count(entry => entry.StartsWith("S ", StringComparison.Ordinal));
            data["head"] = GitRun.In(root, "symbolic-ref -q HEAD").ExitCode == 0 ? "branch" : "detached";
            data["branches"] = Lines(root, "for-each-ref --format=x refs/heads");
            var counts = GitRun.In(root, "rev-list --left-right --count @{upstream}...HEAD");
            data["upstream"] = counts.ExitCode == 0 ? "behind " + counts.Output.Trim().Replace("\t", ", ahead ") : "none";
            data["remotes"] = Lines(root, "remote");
            data["cts_refs"] = Lines(root, "for-each-ref --format=x refs/cts");
            var busy = new[] { "MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "index.lock" }.Where(name => GitPath(root, name)).ToList();
            data["in_progress"] = busy.Count == 0 ? "none" : string.Join(" ", busy);
            data["pre_push_hook"] = GitPath(root, "hooks/pre-push");
            return data;
        }

        static IEnumerable<string> Keys(string settings)
        {
            try
            {
                var keys = (Json.Parse(File.ReadAllText(settings)) as IDictionary<string, object>)?.Keys;
                return keys == null ? new[] { "(not an object)" } : keys.OrderBy(key => key, StringComparer.Ordinal).ToArray();
            }
            catch (FormatException) { return new[] { "(not JSON)" }; }
        }

        static string Role(string root)
        {
            var id = ProjectInfo.ProjectIdOf(root);
            if (id == "") return "no project id";
            var registered = ProjectInfo.RegistryFolder(id);
            if (registered == "") return "not registered";
            if (!Same(registered, root)) return "registered to another folder";
            return ProjectInfo.IsOwner(id) ? "owner" : "colleague";
        }

        static string Setting(string root, string key)
        {
            var run = GitRun.In(root, "config --show-scope --get " + key);
            return run.ExitCode == 0 ? run.Output.Trim().Replace('\t', ' ') : "unset";
        }

        static string Attribute(string root, string name, string path)
        {
            var output = GitRun.In(root, "check-attr " + name + " -- \"" + path + "\"").Output.Trim();
            return output.Substring(output.LastIndexOf(": ", StringComparison.Ordinal) + 2);
        }

        static List<string> Entries(string root, string args)
        {
            return GitRun.In(root, args).Output.Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries).ToList();
        }

        static int Lines(string root, string args)
        {
            return GitRun.In(root, args).Output.Split(new[] { '\n' }, StringSplitOptions.RemoveEmptyEntries).Length;
        }

        // "i/lf w/crlf": how git holds a file and how it lies on disk.
        static string Eol(string entry)
        {
            var tab = entry.IndexOf('\t');
            return string.Join(" ", (tab < 0 ? entry : entry.Substring(0, tab)).Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries)
                .Where(flag => flag.StartsWith("i/", StringComparison.Ordinal) || flag.StartsWith("w/", StringComparison.Ordinal)));
        }

        static string Changed(string root, string ignore)
        {
            var stat = GitRun.In(root, "diff --shortstat" + ignore).Output.Trim();
            return stat == "" ? "none" : stat;
        }

        static bool GitPath(string root, string name)
        {
            var path = GitRun.In(root, "rev-parse --git-path " + name).Output.Trim();
            path = Path.Combine(root, path);
            return File.Exists(path) || Directory.Exists(path);
        }

        static bool Same(string a, string b)
        {
            return string.Equals(Path.GetFullPath(a).TrimEnd('\\', '/'), Path.GetFullPath(b).TrimEnd('\\', '/'), StringComparison.OrdinalIgnoreCase);
        }

        static Answer BuildAnswer(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("cts", data["cts"]).Whole();
            foreach (var key in new[] { "windows", "git", "git_lfs" }) answer.Detail(key + ": " + data[key]);
            foreach (var dir in Items(data, "script_dirs").OfType<IDictionary<string, object>>()) answer.Detail("script dir: " + Pairs(dir));
            var agents = Items(data, "agents").OfType<IDictionary<string, object>>().ToList();
            if (agents.Count == 0) answer.Detail("agent: none (no IDE with the cts agent running)");
            foreach (var agent in agents) answer.Detail("agent: " + Pairs(agent));
            foreach (var pair in (IDictionary<string, object>)data["folder"]) answer.Detail("folder " + pair.Key + ": " + Text(pair.Value));
            return answer;
        }

        static string Pairs(IDictionary<string, object> data)
        {
            return string.Join("  ", data.Select(pair => pair.Key + "=" + Text(pair.Value)));
        }

        static string Text(object value)
        {
            return value is bool flag ? (flag ? "yes" : "no") : Convert.ToString(value, CultureInfo.InvariantCulture);
        }
    }
}
