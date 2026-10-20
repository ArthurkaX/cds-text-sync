using System.Collections.Generic;
using System.Linq;
using Cts.Agent;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    public static partial class CliCommands
    {
        // The commands that reach the IDE's agent and the PLC through it.
        static CliCommand[] OnlineCommands => new[]
        {
            new CliCommand
            {
                Name = "ping",
                Summary = "Check that the in-IDE agent answers; it does not wait for the IDE",
                Description = "Asks the in-IDE agent for a pong. The agent answers from its own thread, so a busy IDE or an open "
                    + "dialog does not delay it: `ok ping pong=true uptime_s=N` says the agent is up, not that the IDE is free "
                    + "(cts status says that).",
                TimeoutKey = "agent_ping",
                Execute = Agent("ping"),
                Build = data => new Answer().Add("pong", Value(data, "pong") ?? true).Add("uptime_s", Value(data, "uptime_s")),
            },
            new CliCommand
            {
                Name = "status",
                Summary = "Show the IDE, its project and sync folder, unsaved edits, the PLC and the last command's outcome",
                Description = "`ok status ide=ide-N plc=online|offline|unknown edits=allowed|blocked unsaved=true|false`, then "
                    + "the sync folder, where its git is (branch, commit, uncommitted files -- the project's own file does "
                    + "not count, a line says when it changed), the project file, what unsaved means, and the last build "
                    + "(and whether objects changed after it). edits=blocked says why and "
                    + "what to do: the IDE is online with the PLC, or its state could not be read. The agent answers even "
                    + "while a dialog is on screen, and a dead IDE fails fast.",
                Seconds = 4,
                Execute = StatusCommands.Status,
                Build = StatusCommands.StatusLine,
            },
            new CliCommand
            {
                Name = "wait-ready",
                Summary = "Wait until the PLC application is running (after a Login or a Download)",
                Description = "Waits until the application is in run. Use it after a Login or a Download done by hand in the "
                    + "CODESYS IDE, or after cts connect, instead of reading variables at once and racing the runtime.\n\n"
                    + "Readiness is polled with separate short requests, so the IDE stays free between them. With --var NAME "
                    + "the wait also needs that variable to change between two reads, which proves the task is cycling. "
                    + "--timeout is the whole wait. Exits 1 when the wait fails; the line under it says why (the last "
                    + "application state, or the last value of the variable).",
                Options = new[]
                {
                    CliOption.Text("--var", "var", "NAME", "Variable that must change between two reads before the PLC counts "
                        + "as ready (proves the task is cycling). Example: GVL_Bench.nHeartbeat"),
                },
                Execute = StatusCommands.WaitReady,
                Build = StatusCommands.ReadyLine,
            },
            new CliCommand
            {
                Name = "write",
                Arguments = "NAME VALUE [NAME VALUE ...]",
                Summary = "Write PLC variables, then read them back",
                Description = "The value is an IEC literal for the variable's type, read by the IDE's own parser: 5, 16#FF, WORD#7, "
                    + "1.5, TRUE, T#2s, 'text'. A STRING also takes bare text (cts write GVL.sName hello), an enum its member as "
                    + "E_Mode.Run, Run or E_Mode#Run. Needs an online session (cts connect).\n\n"
                    + "More NAME VALUE pairs are written together, in one PLC cycle, as the IDE's Write Values does; a value that "
                    + "cannot be written writes none of them. Each value is then read back until the PLC shows it (2 s at most): "
                    + "the line says confirmed=true, or false with the value the PLC still shows -- the program may overwrite it "
                    + "every cycle. written_as is the IDE's spelling of a value typed otherwise (16#AB is WORD#171).\n\n"
                    + "  cts write GVL.wData 16#AB\n"
                    + "  cts write GVL.nSetpoint -5 GVL.eMode Run",
                TimeoutKey = "write_variable",
                Execute = WriteCommand.Execute,
                Build = WriteCommand.Build,
            },
            new CliCommand
            {
                Name = "permissions",
                Summary = "Show the project's command permissions (deny list); a person changes them in the IDE's quick window",
                Description = "The commands the project's deny list blocks (`denied=N`); --json lists them. The list lives in the "
                    + "sync folder's settings and is changed by a person in the IDE's quick window, never by cts.",
                TimeoutKey = "permissions",
                Execute = Agent("project.permissions"),
                Build = data => new Answer()
                    .Add("denied", data.ContainsKey("deny") ? (object)Count(data["deny"]) : null)
                    .Add("poll_ms", Value(data, "poll_ms")),
            },
            new CliCommand
            {
                Name = "save",
                Summary = "Save the open CODESYS project",
                Description = "Saves the project the IDE has open to its .project file, with every edit the IDE holds unsaved "
                    + "(cts import and cts sync leave theirs unsaved). Saving is the user's call: run it when they ask.",
                TimeoutKey = "save_project",
                Execute = Agent("project.save"),
                Build = data => new Answer().Add("saved", Value(data, "saved")).Add("path", Value(data, "path")),
            },
            new CliCommand
            {
                Name = "connect",
                Summary = "Log in to the PLC without changing what it runs",
                Description = "Logs in to the active application's PLC without changing what it runs: no online change, no "
                    + "download over its application. The in-IDE agent answers the IDE's login questions itself. When the PLC "
                    + "runs other code than the project, it logs in anyway and says so; a PLC without the application gets it "
                    + "(app_created=true). When only a download over the PLC's application could log in (a change an online change "
                    + "cannot carry), it refuses and names the question -- `cts download` is the command that replaces it. --ip "
                    + "points the device at that PLC first, through the gateway, which is a project edit: it needs the project offline. "
                    + "plc= names the PLC the login reached: the runtime's name, its address, or simulation.",
                TimeoutKey = "connect_to_device",
                Options = new[]
                {
                    CliOption.Text("--ip", "ip", "IP", "PLC IP address"),
                    CliOption.Text("--gateway", "gateway", "NAME", "Gateway name (default: Gateway-1)"),
                },
                Execute = Agent("app.login"),
                Build = data =>
                {
                    var answer = new Answer()
                        .Add("state", Value(data, "state"))
                        .Add("application", Value(data, "application"))
                        .Add("plc", Value(data, "plc"))
                        .Add("ip", Value(data, "ip"))
                        .Add("app_created", Equals(Value(data, "app_created"), true) ? (object)true : null)
                        .Add("reused_session", Equals(Value(data, "reused_session"), true) ? (object)true : null);
                    if (Equals(Value(data, "app_created"), true)) answer.Detail("the PLC had no such application; login created it");
                    foreach (var prompt in Items(data, "prompts").OfType<IDictionary<string, object>>())
                        if (Equals(Value(prompt, "prompt"), "online_change")) answer.Detail(Value(prompt, "text"));
                    return answer.Detail(DownloadCommand.StaysOnline);
                },
            },
            new CliCommand
            {
                Name = "download",
                Summary = "Full download of the active application to the PLC",
                Description = "What the IDE's Online -> Download does, run by the in-IDE agent: the application stops and its "
                    + "variables start from their initial values, with no confirmation dialog. It needs no online session first: "
                    + "without one it logs in (logged_in=true), so the active application needs a reachable PLC gateway or "
                    + "simulation mode; plc= names the PLC it reached (the runtime's name, its address, or simulation). It sends what the IDE holds, saved or not (cts compare shows whether the sync folder holds the same). Build first: download pushes the last built code, and after adding a GVL/DUT/POU a full "
                    + "download is what makes its symbols readable.\n\n"
                    + "--start 1 (the default) starts the application afterwards; --start 0 leaves it stopped and does not wait "
                    + "for it. The download being finished is not the application being ready: cts then waits until the "
                    + "application is in run (--ready-timeout, default 30 s) rather than letting the next read race the runtime. "
                    + "With --ready-var NAME it also needs that variable to change between two reads, which proves the task is "
                    + "cycling. The line says ready, the two readings that differed (was=, value=) and, when the wait failed, why; the command then exits 1. --no-wait skips "
                    + "the wait. The deny list key is download, and start_plc too when it starts.\n\n"
                    + "When the IDE held exactly the sync folder (cts compare clean) and the folder had nothing uncommitted, the "
                    + "download records its commit (commit= on the line) for cts plc-crc; otherwise commit=unrecorded names why.",
                TimeoutKey = DenyRules.Download,
                Options = new[]
                {
                    CliOption.Choice("--start", "start", "Start after download: 1 yes (default), 0 no", "0", "1"),
                    CliOption.Text("--ready-var", "ready_var", "NAME", "Variable that must change between two reads before the PLC "
                        + "counts as ready (proves the task is cycling). Example: GVL_Bench.nHeartbeat"),
                    CliOption.Int("--ready-timeout", "ready_timeout", "Seconds to wait for readiness after the download (default: 30)"),
                    CliOption.Switch("--no-wait", "no_wait", "Do not wait for the application to be running; the next read may race "
                        + "the runtime"),
                },
                Execute = DownloadCommand.Execute,
                Build = DownloadCommand.Build,
            },
            new CliCommand
            {
                Name = "disconnect",
                Summary = "Log out of the PLC",
                Description = "Ends the IDE's online session; the PLC keeps running what it runs. With no session it says so "
                    + "(was_connected=false) and changes nothing.",
                TimeoutKey = "disconnect_from_device",
                Execute = Agent("app.logout"),
                Build = Plc,
            },
            new CliCommand
            {
                Name = "start",
                Summary = "Start the logged-in application on the PLC",
                Description = "Runs the application of the online session (cts connect or cts download first). changed=false: it "
                    + "was running already.",
                TimeoutKey = "start_plc",
                Execute = Agent("app.start"),
                Build = Plc,
            },
            new CliCommand
            {
                Name = "stop",
                Summary = "Stop the logged-in application on the PLC",
                Description = "Stops the application of the online session; it stays on the PLC and cts start runs it again. "
                    + "changed=false: it was stopped already.",
                TimeoutKey = "stop_plc",
                Execute = Agent("app.stop"),
                Build = Plc,
            },
            new CliCommand
            {
                Name = "boot-app",
                Summary = "Store the logged-in application on the PLC as its boot application",
                Description = "The PLC then starts this application when it powers up. Needs an online session (cts connect).",
                TimeoutKey = "create_boot_app",
                Execute = Agent("app.bootapp"),
                Build = Plc,
            },
            new CliCommand
            {
                Name = "reset",
                Summary = "Reset the logged-in application on the PLC",
                Description = "Resets the application of the online session: warm keeps retained variables, cold resets them too, "
                    + "origin erases the application from the PLC and needs --force.",
                TimeoutKey = "reset_plc",
                Options = new[]
                {
                    CliOption.Choice("--kind", "kind", "warm keeps retained variables, cold resets them too, origin erases "
                        + "the application from the PLC (default: warm)", "warm", "cold", "origin"),
                    CliOption.Switch("--force", "force", "Confirm an origin reset, which erases the application"),
                },
                Execute = Agent("app.reset"),
                Build = Plc,
            },
            new CliCommand
            {
                Name = "test",
                Summary = "Run the ST tests of the test application in simulation",
                Description = "Runs the tests a test application holds: a device in simulation with an application (TestApp, or "
                    + "--app) whose task calls tests on the POUs the applications share, counts them into a GVL TestResult "
                    + "(Done, Passed, Failed) and logs each one to the runtime's log (CTS|M|TEST_PASS|name|, CTS|M|TEST_FAIL|name|k=v; "
                    + "cts guide tests). cts makes that application the active one, downloads it to the simulation, starts it, "
                    + "waits for TestResult.Done, reads the counts and the simulation's log from the run's CTS|M|TEST_START| on, "
                    + "logs it out and makes the earlier application active again. The run's log is always saved: --output, else "
                    + "the sync folder's .git/cts/test/<application>.log. A device that is not in simulation is refused: tests "
                    + "never go to a PLC. Exit 0 when every test passed, 1 otherwise.",
                TimeoutKey = DenyRules.RunTests,
                Options = new[]
                {
                    CliOption.Text("--app", "application", "NAME", "The test application (default: " + AppTests.DefaultApplication + ")"),
                    CliOption.Int("--wait", "wait", "Seconds to wait for TestResult.Done after the start (default: 30)"),
                    CliOption.Text("--output", "output", "PATH", "Save the run's log here (a file, or a folder for <application>.log)"),
                },
                Execute = TestCommand.Execute,
                Build = TestCommand.Build,
            },
            new CliCommand
            {
                Name = "read-log",
                Summary = "Read the IDE's messages of one category (default: Build)",
                Description = "The messages the IDE's message view holds for one category, oldest first; the line counts them.",
                TimeoutKey = "read_log",
                Options = new[]
                {
                    CliOption.Int("--last", "last", "Read only the newest N messages"),
                    CliOption.Switch("--clear", "clear", "Clear the category after reading it"),
                    CliOption.Text("--category", "category", "NAME", "Message category: a GUID or one of the descriptions "
                        + "the IDE reports. Default: Build, the compiler's messages. The IDE adds a category when it first "
                        + "writes to it (Export/Import after an export), so an unknown name fails and lists the ones there are "
                        + "now."),
                },
                Execute = Agent("messages.read"),
                Build = data =>
                {
                    var category = Value(data, "category");
                    var answer = new Answer()
                        .Add("category", category is IDictionary<string, object> named ? Value(named, "description") : category)
                        .Add("messages", data.ContainsKey("messages") ? (object)Count(data["messages"]) : Value(data, "count"));
                    foreach (var message in Items(data, "messages")) answer.Detail(message);
                    return answer;
                },
            },
            new CliCommand
            {
                Name = "plc-log",
                Summary = "Read the PLC runtime log; pick out the CTS| event records",
                Description = "Reads the PLC runtime log (CmpLog) from the online device's logger service: what the device "
                    + "editor's Log page shows, wherever the runtime keeps its log file; the IDE may be offline. "
                    + "With no options it prints the last 20 entries of the default logger and includes the runtime's logger list. --loggers lists loggers only. --logger picks one (default: the runtime's first, its "
                    + "standard logger), --tail N prints its last N entries, --output PATH saves them all (after plc-log, "
                    + "--output is the file; the output format goes before the command or as --json). Each entry is the line "
                    + "the runtime's log file holds: '<time>, <cmpId>, <classId>, <errorId>, <infoId>, <text>', the time in UTC.\n\n"
                    + "--cts keeps only the entries whose text carries the generated 'CTS|<level>|<CODE>|<TAG>|k=v;k=v' marker; "
                    + "--json returns them parsed. --level and --code filter those records and imply --cts. A CTS line that "
                    + "does not parse is listed apart as malformed, with the reason, instead of being dropped.\n\n"
                    + "The PLC holds as many entries as its runtime keeps in memory. A file on the PLC is copied with "
                    + "`cts plc get FILE`.\n\n"
                    + "  cts plc-log                                   # last 20 entries of the default logger\n"
                    + "  cts plc-log --loggers                         # list loggers only\n"
                    + "  cts plc-log --tail 200                        # last 200 entries\n"
                    + "  cts plc-log --cts --level M                   # minimal (always-on) events\n"
                    + "  cts plc-log --cts --code ALM_RAISE            # one event code\n"
                    + "  cts plc-log --output C:/Temp/log --cts        # keep the entries too",
                TimeoutKey = "plc_log",
                Options = new[]
                {
                    CliOption.Text("--logger", "logger", "NAME", "Which runtime logger to read (default: the runtime's first)"),
                    CliOption.Switch("--loggers", "loggers", "List runtime loggers only"),
                    CliOption.Int("--tail", "tail", "Show or parse only the last N entries (0: all)"),
                    CliOption.Text("--output", "output", "PATH", "Save every entry to this file, or into this folder"),
                    CliOption.Switch("--cts", "cts", "Keep only the CTS| entries, parsed"),
                    CliOption.Choice("--level", "level", "Only records of this level (M minimal, V verbose); implies --cts", "M", "V"),
                    CliOption.Text("--code", "code", "CODE", "Only records with this event code; implies --cts"),
                },
                Execute = PlcLogCommand.Execute,
                Build = PlcLogCommand.Build,
            },
        };
    }
}
