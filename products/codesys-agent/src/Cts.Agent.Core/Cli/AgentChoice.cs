using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace Cts.Cli
{
    // What cts.exe needs of the machine to reach an agent; the real one lists
    // the pipes, a test gives fakes.
    public interface IAgentHost
    {
        // The IDEs with an agent pipe, CTS_IDE_PID applied.
        IList<int> Pids();

        // Throws AgentException when the pipe cannot be opened.
        AgentConnection Open(int pid);
    }

    // One agent's `hello`, with what a command needs of it.
    public sealed class Hello
    {
        public int Pid { get; private set; }
        public IDictionary<string, object> Data { get; private set; }

        public Hello(int pid, IDictionary<string, object> data)
        {
            Pid = pid;
            Data = data;
        }

        IDictionary<string, object> Project
        {
            get { return Data.TryGetValue("project", out var p) ? p as IDictionary<string, object> : null; }
        }

        public string ProjectPath
        {
            get { var p = Project; return p != null && p.TryGetValue("path", out var v) ? v as string : null; }
        }

        // The IDE's UI thread was too busy to say which project it has open.
        internal bool UiBusy
        {
            get { return Data.TryGetValue("ui_busy", out var busy) && Equals(busy, true); }
        }

        public string SyncFolder
        {
            get { var p = Project; return p != null && p.TryGetValue("sync_folder", out var v) ? v as string : null; }
        }

        // The project's name: its file name without `.project`.
        public string ProjectName
        {
            get
            {
                var path = ProjectPath;
                if (string.IsNullOrEmpty(path)) return null;
                var name = path.Replace('\\', '/').Split('/').Last();
                return name.EndsWith(".project", StringComparison.OrdinalIgnoreCase) ? name.Substring(0, name.Length - 8) : name;
            }
        }

        // The seconds the agent sizes *method* at (`timeout_profile`: its
        // `timeouts`, else its `default`), or null.
        public double? TimeoutFor(string method)
        {
            if (!Data.TryGetValue("timeout_profile", out var p) || !(p is IDictionary<string, object> profile)) return null;
            object v;
            if (!(profile.TryGetValue("timeouts", out var t) && t is IDictionary<string, object> timeouts && timeouts.TryGetValue(method, out v)))
                profile.TryGetValue("default", out v);
            if (v == null || v is bool) return null;
            var seconds = Convert.ToDouble(v, System.Globalization.CultureInfo.InvariantCulture);
            return seconds > 0 ? seconds : (double?)null;
        }

        // Whether --expect-project names this IDE's project: its name, its file
        // name or its path, case-insensitive.
        public bool HasProject(string expect)
        {
            var path = ProjectPath;
            if (string.IsNullOrEmpty(path)) return false;
            var wanted = expect.Trim().Replace('\\', '/').TrimEnd('/');
            var full = path.Replace('\\', '/').TrimEnd('/');
            var file = full.Split('/').Last();
            return new[] { ProjectName, file, full }.Any(n => string.Equals(n, wanted, StringComparison.OrdinalIgnoreCase));
        }
    }

    // Which agent a command talks to: the one --target names, else the only
    // one, else the one whose sync folder holds the work folder.
    public static class AgentChoice
    {
        const int HelloTimeoutMs = 3000;
        const string NoAgentNext = "cts project open --path <p> --launch";

        // The full discovery used by `cts agent list`; unlike Pick, this keeps
        // each pipe's failure beside the agents that answered.
        public static IList<IDictionary<string, object>> Discover(IAgentHost host, double seconds)
        {
            var entries = new List<IDictionary<string, object>>();
            var ms = (int)Math.Min(int.MaxValue, Math.Max(1, seconds * 1000));
            foreach (var pid in host.Pids())
            {
                AgentConnection conn = null;
                try
                {
                    conn = host.Open(pid);
                    var hello = conn.Call("hello", null, ms) as IDictionary<string, object>;
                    if (hello == null) throw new AgentException("bad_reply", "hello did not return an object");
                    var protocol = hello.TryGetValue("protocol", out var v) ? Convert.ToString(v) : "";
                    if (protocol.Split('.')[0] != Cts.Agent.Protocol.Version.Split('.')[0])
                        throw new AgentException("protocol", "agent speaks protocol " + (protocol.Length == 0 ? "?" : protocol));
                    var entry = new Dictionary<string, object>(hello) { ["pid"] = pid };
                    entries.Add(entry);
                }
                catch (AgentException e)
                {
                    entries.Add(new Dictionary<string, object> { ["pid"] = pid, ["error"] = new Dictionary<string, object> { ["code"] = e.Code, ["message"] = e.Message } });
                }
                finally { if (conn != null) conn.Dispose(); }
            }
            return entries;
        }

        // The chosen agent's connection and hello; throws CliFailure.
        public static KeyValuePair<AgentConnection, Hello> Pick(IAgentHost host, string command, int? target, string expect, string workFolder)
        {
            KeyValuePair<AgentConnection, Hello> chosen;
            if (target.HasValue)
            {
                var opened = TryOpen(host, target.Value);
                if (opened == null)
                    throw new CliFailure(command, "agent ide-" + target + " is not reachable", "agent ide-" + target + " is not reachable.", null, 1);
                chosen = opened.Value;
            }
            else
            {
                var alive = host.Pids().Select(pid => TryOpen(host, pid)).Where(o => o != null).Select(o => o.Value).ToList();
                if (alive.Count == 0)
                    throw new CliFailure(command, "no in-IDE agent answers",
                        "No in-IDE agent is running, so cts cannot reach the IDE. Start the IDE with 'cts project open --launch', "
                        + "or run cds-text-sync once from the CODESYS menu (Tools > Scripting > Scripts > C > cds-text-sync).", NoAgentNext, 2);
                var held = alive.Count == 1 ? alive : ByWorkFolder(alive, workFolder);
                foreach (var other in alive.Where(a => !held.Contains(a) || held.Count != 1)) other.Key.Dispose();
                if (held.Count != 1)
                    throw new CliFailure(command, "several agents, none for this folder",
                        "Several agents are running and none has its sync folder here; run cts in that project's sync folder "
                        + "or choose one with --target ide-<pid>. Available: "
                        + string.Join(", ", alive.Select(a => "ide-" + a.Value.Pid + " (" + (a.Value.SyncFolder ?? "no sync folder") + ")")), null, 2);
                chosen = held[0];
            }
            if (!string.IsNullOrEmpty(expect) && !chosen.Value.HasProject(expect))
            {
                chosen.Key.Dispose();
                throw new CliFailure(command, "project mismatch",
                    "project mismatch: expected '" + expect + "', but IDE ide-" + chosen.Value.Pid + " has '"
                    + (chosen.Value.ProjectPath ?? "no project") + "' open.", null, 2);
            }
            return chosen;
        }

        // The hello to name the project by after a command: an IDE that had
        // none open when the command began may have opened one meanwhile.
        internal static Hello Settled(AgentConnection conn, Hello hello)
        {
            if (hello.ProjectPath != null) return hello;
            try { return conn.Call("hello", null, HelloTimeoutMs) is IDictionary<string, object> fresh ? new Hello(hello.Pid, fresh) : hello; }
            catch (AgentException) { return hello; }
        }

        internal static KeyValuePair<AgentConnection, Hello>? TryOpen(IAgentHost host, int pid)
        {
            AgentConnection conn = null;
            try
            {
                conn = host.Open(pid);
                var hello = conn.Call("hello", null, HelloTimeoutMs) as IDictionary<string, object>;
                if (hello == null) throw new AgentException("bad_reply", "hello did not return an object");
                var version = hello.TryGetValue("protocol", out var v) ? Convert.ToString(v) : "";
                if (version.Split('.')[0] != Cts.Agent.Protocol.Version.Split('.')[0])
                    throw new AgentException("protocol", "agent speaks protocol " + version);
                return new KeyValuePair<AgentConnection, Hello>(conn, new Hello(pid, hello));
            }
            catch (AgentException)
            {
                if (conn != null) conn.Dispose();
                return null;
            }
        }

        // The agents whose sync folder holds the work folder; the deepest when
        // sync folders nest.
        static List<KeyValuePair<AgentConnection, Hello>> ByWorkFolder(List<KeyValuePair<AgentConnection, Hello>> alive, string workFolder)
        {
            var here = Key(workFolder);
            var holding = alive
                .Where(a => !string.IsNullOrEmpty(a.Value.SyncFolder))
                .Select(a => new { Agent = a, Root = Key(a.Value.SyncFolder) })
                .Where(x => here == x.Root || here.StartsWith(x.Root.TrimEnd('\\') + "\\", StringComparison.Ordinal))
                .ToList();
            if (holding.Count == 0) return holding.Select(x => x.Agent).ToList();
            var deepest = holding.Max(x => x.Root.Length);
            return holding.Where(x => x.Root.Length == deepest).Select(x => x.Agent).ToList();
        }

        static string Key(string path)
        {
            return Path.GetFullPath(path.Replace('/', '\\')).TrimEnd('\\').ToLowerInvariant();
        }
    }
}
