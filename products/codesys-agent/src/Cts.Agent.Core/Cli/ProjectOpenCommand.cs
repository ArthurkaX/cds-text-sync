using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;
using Cts.Agent;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts project open --path P`: the running IDE's agent opens the file;
    // with --launch cts starts CODESYS with the menu stub as its startup
    // script, waits until the agent of that IDE answers, and has it open the
    // file -- so a dialog the load raises is one `cts dialog` answers.
    public static class ProjectOpenCommand
    {
        const string Verb = "project-open";
        const string Stub = "cds-text-sync.py";
        const int LoadSeconds = 180;
        const int DefaultWaitSeconds = 90;

        public static readonly CliCommand Command = new CliCommand
        {
            Name = "project",
            Sub = "open",
            Summary = "Open a project file in CODESYS, or start CODESYS on it",
            Description = "Without --launch the running IDE's agent opens the file as its primary project; a file already open "
                + "answers already_open=true. Another project open in that IDE is closed first when it is saved and offline "
                + "(closed=NAME), as the IDE's File > Open does; unsaved edits or a login are refused. --launch starts CODESYS with the installed "
                + "cds-text-sync.py as its startup script, so the agent comes up with no click, then has that agent open the file: a "
                + "dialog the load raises (a project saved by a newer CODESYS, a missing compiler version) ends the wait with exit 3 "
                + "and the `cts dialog answer` line, as for any command. An IDE whose agent already has the file open is used instead of a second one. CODESYS is the "
                + "newest installed under Program Files unless --codesys names one; its installation's profile is passed when it ships "
                + "exactly one, else --profile picks it.",
            Options = new[]
            {
                CliOption.Needed("--path", "path", "P", "Project file"),
                CliOption.Switch("--launch", "launch", "Start CODESYS on --path instead of asking a running IDE"),
                CliOption.Text("--codesys", "codesys", "EXE", "For --launch: CODESYS.exe (default: the newest installed)"),
                CliOption.Text("--profile", "profile", "NAME", "For --launch: the CODESYS profile, passed as --profile=\"NAME\""),
                CliOption.Text("--runscript", "runscript", "PY", "For --launch: the startup script (default: the installed cds-text-sync.py)"),
                CliOption.Switch("--no-runscript", "no_runscript", "For --launch: start the IDE with the project only, no agent"),
                CliOption.Int("--wait", "wait", "For --launch: seconds to wait for the agent (default: 90)"),
            },
            Execute = call => call.Call("project.open", new Dictionary<string, object> { { "path", Path.GetFullPath(Convert.ToString(call.Options.Params["path"])) } }, LoadSeconds),
            LocalExecute = Launch,
            LocalWhen = options => options.Params.ContainsKey("launch"),
            Build = data => new Answer()
                .Add("opened", Value(data, "opened"))
                .Add("already_open", Value(data, "already_open"))
                .Add("closed", Value(data, "closed"))
                .Add("launched", Value(data, "launched"))
                .Add("agent", Value(data, "agent"))
                .Add("project", Value(data, "project"))
                .Add("profile", Value(data, "profile"))
                .Detail(Value(data, "codesys") == null ? null : "codesys " + Value(data, "codesys"))
                .Detail(Value(data, "runscript") == null ? null : "runscript " + Value(data, "runscript")),
        };

        static IDictionary<string, object> Launch(CliOptions options, IAgentHost host, string work)
        {
            var path = Path.GetFullPath(Path.Combine(work, Convert.ToString(options.Params["path"])));
            if (!File.Exists(path)) throw Refused("no project file at " + path);
            var running = OpenIn(host, path);
            if (running != null)
                return new Dictionary<string, object> { { "launched", false }, { "already_open", true }, { "agent", "ide-" + running.Pid }, { "project", path } };

            // Session 0 (an ssh login, a service) has no desktop: a CODESYS
            // started there never shows and its agent never answers.
            if (Path.DirectorySeparatorChar == '\\' && Process.GetCurrentProcess().SessionId == 0)
                throw Refused("cts runs in Windows session 0 (an ssh login or a service), which has no desktop: a CODESYS started from here "
                    + "would never answer. Start CODESYS on the user's desktop, then run cts project open without --launch");
            var codesys = options.Params.TryGetValue("codesys", out var given) ? Path.GetFullPath(Convert.ToString(given))
                : Newest(Executables(ProgramFiles()));
            if (codesys == null) throw Refused("no CODESYS.exe under Program Files; name it with --codesys");
            if (!File.Exists(codesys)) throw Refused("no CODESYS.exe at " + codesys);
            string script = null;
            if (!options.Params.ContainsKey("no_runscript"))
            {
                script = options.Params.TryGetValue("runscript", out var named) ? Path.GetFullPath(Convert.ToString(named))
                    : InstalledStub(ScriptDirs());
                if (script == null)
                    throw Refused("no installed " + Stub + ", so the IDE would start without the agent; run cts install, "
                        + "or pass --runscript PY or --no-runscript");
                if (!File.Exists(script)) throw Refused("no startup script at " + script);
            }
            var profile = options.Params.TryGetValue("profile", out var p) ? Convert.ToString(p) : InstallProfile(codesys);

            // Through the shell, so the IDE inherits none of cts's handles: a
            // caller reading cts's output to its end would wait for the IDE to
            // close. It inherits the environment, and with it CTS_LAUNCHED: the
            // stub reports into the message view instead of a box that would
            // hold the startup script until somebody clicks.
            Environment.SetEnvironmentVariable("CTS_LAUNCHED", "1");
            var start = new ProcessStartInfo(codesys, CommandLine(path, script, profile)) { UseShellExecute = true };
            Process ide;
            try { ide = Process.Start(start); }
            catch (Exception e) when (e is System.ComponentModel.Win32Exception || e is InvalidOperationException)
            {
                throw new CliFailure(Verb, "launch failed", "CODESYS did not start: " + e.Message, null, 1);
            }
            var data = new Dictionary<string, object>
            {
                { "launched", true }, { "pid", ide.Id }, { "project", path }, { "profile", profile }, { "codesys", codesys }, { "runscript", script },
            };
            if (script == null) return data;
            var wait = options.Params.TryGetValue("wait", out var w) ? Convert.ToInt32(w, CultureInfo.InvariantCulture) : DefaultWaitSeconds;
            var hello = AwaitAgent(host, ide, wait);
            data["agent"] = "ide-" + hello.Pid;
            using (var conn = host.Open(hello.Pid))
                new CliCall(conn, host, Command, options, hello, LoadSeconds).Call("project.open", new Dictionary<string, object> { { "path", path } });
            return data;
        }

        // The one profile an installation ships (CODESYS\Profiles beside Common):
        // with several versions installed CODESYS asks which, even when the
        // CODESYS.exe started belongs to one of them.
        internal static string InstallProfile(string codesys)
        {
            var profiles = Path.Combine(Path.GetDirectoryName(Path.GetDirectoryName(codesys)) ?? "", "Profiles");
            if (!Directory.Exists(profiles)) return null;
            var found = Directory.GetFiles(profiles, "*.profile.xml");
            return found.Length == 1 ? Path.GetFileName(found[0]).Substring(0, Path.GetFileName(found[0]).Length - ".profile.xml".Length) : null;
        }

        // CODESYS reads its own command line: it takes the profile only as
        // --profile="NAME", the quotes inside the argument, not around it.
        internal static string ProfileArgument(string profile)
        {
            return "--profile=\"" + profile + "\"";
        }

        // The project goes on the command line only when no agent will open
        // it: CODESYS runs the startup script after the project has loaded,
        // so a dialog of that load would hold the agent back.
        internal static string CommandLine(string project, string script, string profile)
        {
            var rest = ProcessArgs.Join(new[] { script == null ? "--project=" + project : "--runscript=" + script });
            return string.IsNullOrEmpty(profile) ? rest : ProfileArgument(profile) + " " + rest;
        }

        // The agent of the launched IDE once it answers.
        static Hello AwaitAgent(IAgentHost host, Process ide, int seconds)
        {
            var deadline = DateTime.UtcNow.AddSeconds(Math.Max(0, seconds));
            while (true)
            {
                if (host.Pids().Contains(ide.Id))
                {
                    var opened = AgentChoice.TryOpen(host, ide.Id);
                    if (opened != null)
                    {
                        opened.Value.Key.Dispose();
                        return opened.Value.Value;
                    }
                }
                if (ide.HasExited)
                    throw new CliFailure(Verb, "IDE exited", "CODESYS exited with code " + ide.ExitCode + " before its agent answered.", null, 1);
                if (DateTime.UtcNow >= deadline)
                    throw new CliFailure(Verb, "agent did not answer",
                        "CODESYS (pid " + ide.Id + ") is running, but after " + seconds + " s its agent has not answered; "
                        + "the script may not have run, check the IDE.", "cts --target ide-" + ide.Id + " status", 1);
                Thread.Sleep(1000);
            }
        }

        // The running agent with *project* open, or null.
        static Hello OpenIn(IAgentHost host, string project)
        {
            foreach (var pid in host.Pids())
            {
                var opened = AgentChoice.TryOpen(host, pid);
                if (opened == null) continue;
                opened.Value.Key.Dispose();
                if (ProjectFiles.SamePath(opened.Value.Value.ProjectPath, project)) return opened.Value.Value;
            }
            return null;
        }

        // Both Program Files folders; a 32-bit cts.exe sees the 64-bit one
        // only as ProgramW6432.
        internal static IEnumerable<string> ProgramFiles()
        {
            return new[]
                {
                    Environment.GetEnvironmentVariable("ProgramW6432"),
                    Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                    Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86),
                }
                .Where(root => !string.IsNullOrEmpty(root)).Distinct(StringComparer.OrdinalIgnoreCase);
        }

        // Every `CODESYS *\CODESYS\Common\CODESYS.exe` under *roots*.
        internal static IEnumerable<string> Executables(IEnumerable<string> roots)
        {
            return roots.Where(Directory.Exists)
                .SelectMany(root => Directory.GetDirectories(root, "CODESYS *"))
                .Select(dir => Path.Combine(dir, "CODESYS", "Common", "CODESYS.exe"))
                .Where(File.Exists);
        }

        // The one of the highest version in its install folder's name
        // (`CODESYS 3.5.22.30`), or null.
        internal static string Newest(IEnumerable<string> executables)
        {
            return executables.OrderByDescending(InstallVersion).FirstOrDefault();
        }

        internal static Version InstallVersion(string executable)
        {
            var folder = Path.GetFileName(Path.GetDirectoryName(Path.GetDirectoryName(Path.GetDirectoryName(executable))));
            return Version.TryParse(folder.Substring(folder.IndexOf(' ') + 1), out var version) ? version : new Version(0, 0);
        }

        // The ScriptDirs CODESYS reads, the ones a user install writes first:
        // beside this cts.exe when it is the agent's copy, then the user's,
        // the machine's and each install's.
        static IEnumerable<string> ScriptDirs()
        {
            var beside = Path.GetDirectoryName(Path.GetDirectoryName(AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/')));
            if (beside != null) yield return beside;
            foreach (var dir in InstallCommand.ScriptDirs()) yield return dir;
        }

        // The first `cds-text-sync\cds-text-sync.py` in *scriptDirs*, or null.
        internal static string InstalledStub(IEnumerable<string> scriptDirs)
        {
            return scriptDirs.Select(dir => Path.Combine(dir, "cds-text-sync", Stub)).FirstOrDefault(File.Exists);
        }

        static CliFailure Refused(string message)
        {
            return new CliFailure(Verb, "refused", message, "cts project open --help", 2);
        }

    }
}
