using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading;
using Cts.Agent;

namespace Cts.Cli
{
    // Reads a PLC application's .crc file through a CODESYS or Astra process
    // started for it with headless/plc_crc.py: no agent, no open project, and
    // nothing written to the PLC.
    internal static class HeadlessCrcCommand
    {
        const string Credentials = "Credentials: set CDS_CRC_PLC_USERNAME and CDS_CRC_PLC_PASSWORD for a single target; their values never reach "
            + "JSON, arguments or output. A batch target names its own with credentials.username_env and credentials.password_env.";

        internal static readonly CliCommand Command = new CliCommand
        {
            Name = "plc-crc-headless",
            Summary = "Read a PLC application's .crc file through a temporary read-only IDE",
            Description = "Starts CODESYS/Astra without UI, reads the deployed .crc file of each target and prints it as Base64; "
                + "never downloads, updates, starts or stops a PLC. " + Credentials,
            Options = new[]
            {
                CliOption.Text("--ip", "ip", "IP", "PLC IPv4 address (single target)"),
                CliOption.Text("--input", "input", "FILE", "JSON batch: a targets array, or {\"targets\": [...]}"),
                CliOption.Text("--application", "application", "NAME", "Application whose .crc file to read (default: Application)"),
                CliOption.Text("--gateway", "gateway", "NAME", "Gateway name (default: Gateway-1)"),
                CliOption.Text("--ide", "ide", "EXE", "IDE executable (default: each installed CODESYS/Astra in turn)"),
                CliOption.Text("--profile", "profile", "NAME", "IDE profile (default: the newest beside the IDE)"),
                CliOption.Text("--timeout", "timeout", "SECONDS", "Time the IDE gets for the batch (default: 300)"),
                CliOption.Text("--host-root", "host_root", "DIR", "Folder holding headless/plc_crc.py"),
                CliOption.Switch("--watch", "watch", "Keep one IDE running and repeat the batch"),
                CliOption.Text("--interval", "interval", "SECONDS", "Seconds between watch rounds (default: 60)"),
                CliOption.Text("--watch-output", "watch_output", "FILE", "JSONL file each watch round appends to (required with --watch)"),
                CliOption.Text("--watch-control", "watch_control", "FILE", "New file; writing {\"action\": \"stop\"} into it stops the watch"),
                CliOption.Text("--startup-timeout", "startup_timeout", "SECONDS", "Time the watch script gets to report ready (default: 60)"),
            },
            LocalExecute = (options, host, work) => Execute(options),
            Build = data => new Answer().WithExitCode(JsonMap.Int(data, "exit_code")),
        };

        static IDictionary<string, object> Execute(CliOptions options)
        {
            IList<object> targets;
            string script;
            double timeout;
            try
            {
                targets = Targets(options);
                script = Script(options.Text("host_root", ""));
                timeout = Seconds(options, "timeout", 300);
                if (options.Params.ContainsKey("watch")) return Watch(options, targets, script);
            }
            catch (Exception error) when (error is ArgumentException || error is IOException || error is JsonException || error is UnauthorizedAccessException)
            {
                return Raw(Failure("invalid_request", error.Message, null), 2);
            }

            var explicitIde = options.Params.ContainsKey("ide");
            var candidates = Candidates(options);
            if (candidates.Count == 0) return Raw(Failure("ide_not_found", "no CODESYS/Astra IDE found", null), 2);
            var attempts = new List<object>();
            foreach (var ide in candidates)
            {
                if (ide.Profile.Length == 0)
                {
                    attempts.Add(new Dictionary<string, object> { ["exe"] = ide.Exe, ["error"] = Error("profile_required", NoProfile(explicitIde)) });
                    continue;
                }
                IDictionary<string, object> payload;
                try
                {
                    payload = Probe(ide, targets, script, timeout);
                }
                catch (Exception error) when (error is IOException || error is Win32Exception || error is TimeoutException || error is JsonException || error is UnauthorizedAccessException)
                {
                    attempts.Add(new Dictionary<string, object> { ["exe"] = ide.Exe, ["profile"] = ide.Profile, ["error"] = Error("ide_failed", error.Message) });
                    continue;
                }
                // A result for every target proves this IDE ran the script: a
                // PLC that did not answer is no reason to replay the batch in
                // every other IDE.
                var ok = Equals(payload.TryGetValue("ok", out var flag) ? flag : null, true);
                if (ok || explicitIde || (payload.TryGetValue("results", out var results) && results is IList<object> rows && rows.Count == targets.Count))
                    return Raw(payload, ok ? 0 : 1);
                attempts.Add(new Dictionary<string, object> { ["exe"] = ide.Exe, ["profile"] = ide.Profile, ["result"] = payload });
            }
            return Raw(Failure("all_ides_failed", "no candidate IDE completed the operation", attempts), 1);
        }

        internal sealed class Ide
        {
            internal string Exe;
            internal string Profile;
        }

        // --ide with --profile, else CDS_CRC_CODESYS_EXE and _PROFILE, then
        // every CODESYS (newest first) and Astra under Program Files; a
        // profile not given is the newest beside the executable.
        static List<Ide> Candidates(CliOptions options)
        {
            var profile = options.Text("profile", "");
            IEnumerable<string> executables;
            if (options.Params.ContainsKey("ide")) executables = new[] { options.Text("ide", "") };
            else
            {
                var roots = ProjectOpenCommand.ProgramFiles().ToList();
                var astra = roots.Select(root => Path.Combine(root, "AstraRegul")).Where(Directory.Exists)
                    .SelectMany(folder => Directory.GetDirectories(folder))
                    .Select(install => Path.Combine(install, "Astra.IDE", "Common", "Astra.IDE.exe"))
                    .Where(File.Exists);
                var named = Environment.GetEnvironmentVariable("CDS_CRC_CODESYS_EXE");
                if (!string.IsNullOrEmpty(named) && profile.Length == 0) profile = Environment.GetEnvironmentVariable("CDS_CRC_CODESYS_PROFILE") ?? "";
                executables = (string.IsNullOrEmpty(named) ? new string[0] : new[] { named })
                    .Concat(ProjectOpenCommand.Executables(roots).OrderByDescending(ProjectOpenCommand.InstallVersion))
                    .Concat(astra);
            }
            return executables.Distinct(StringComparer.OrdinalIgnoreCase)
                .Select(exe => new Ide { Exe = exe, Profile = profile.Length > 0 ? profile : Profile(exe) })
                .ToList();
        }

        static string NoProfile(bool explicitIde)
        {
            return explicitIde ? "no profile beside the IDE given with --ide; pass --profile" : "a discovered IDE has no profile; pass --profile";
        }

        // The newest `NAME.profile.xml` in the Profiles folder nearest the
        // executable, or "" when there is none.
        internal static string Profile(string exe)
        {
            const string Suffix = ".profile.xml";
            for (var folder = new DirectoryInfo(Path.GetDirectoryName(Path.GetFullPath(exe))); folder != null; folder = folder.Parent)
            {
                var profiles = Path.Combine(folder.FullName, "Profiles");
                if (!Directory.Exists(profiles)) continue;
                var newest = Directory.GetFiles(profiles, "*" + Suffix).Select(Path.GetFileName)
                    .OrderByDescending(name => Regex.Replace(name, @"\d+", number => number.Value.PadLeft(10, '0')), StringComparer.OrdinalIgnoreCase)
                    .FirstOrDefault();
                if (newest != null) return newest.Substring(0, newest.Length - Suffix.Length);
            }
            return "";
        }

        // The targets the IDE script checks; a batch row it cannot use fails
        // there on its own, so one bad row does not stop the other PLCs.
        internal static IList<object> Targets(CliOptions options)
        {
            var gateway = options.Text("gateway", "Gateway-1");
            var application = options.Text("application", "Application");
            if (options.Params.ContainsKey("input"))
            {
                var parsed = Json.Parse(File.ReadAllText(options.Text("input", "")));
                var list = parsed is IDictionary<string, object> wrapper && wrapper.TryGetValue("targets", out var inner) ? inner as IList<object> : parsed as IList<object>;
                if (list == null || list.Count == 0) throw new ArgumentException("batch input must contain a non-empty targets array");
                return list.Select((item, index) =>
                {
                    var row = item is IDictionary<string, object> fields ? new Dictionary<string, object>(fields) : new Dictionary<string, object> { ["value"] = item };
                    if (!row.ContainsKey("gateway")) row["gateway"] = gateway;
                    if (!row.ContainsKey("request_id")) row["request_id"] = (index + 1).ToString(CultureInfo.InvariantCulture);
                    if (!row.ContainsKey("application")) row["application"] = application;
                    return (object)row;
                }).ToList();
            }
            var ip = options.Text("ip", "");
            if (ip.Length == 0) throw new ArgumentException("one of --ip or --input is required");
            var target = new Dictionary<string, object> { ["ip"] = ip, ["gateway"] = gateway, ["request_id"] = "1", ["application"] = application };
            // The request names the variables; their values stay in the
            // environment the IDE inherits.
            if (Environment.GetEnvironmentVariable("CDS_CRC_PLC_USERNAME") != null || Environment.GetEnvironmentVariable("CDS_CRC_PLC_PASSWORD") != null)
                target["credentials"] = new Dictionary<string, object> { ["username_env"] = "CDS_CRC_PLC_USERNAME", ["password_env"] = "CDS_CRC_PLC_PASSWORD" };
            return new List<object> { target };
        }

        // headless/plc_crc.py under --host-root or CDS_CODESYS_HOST_ROOT, else
        // the first products/codesys-host or codesys-host above this cts.exe.
        internal static string Script(string hostRoot)
        {
            var root = hostRoot.Length > 0 ? hostRoot : Environment.GetEnvironmentVariable("CDS_CODESYS_HOST_ROOT") ?? "";
            if (root.Length > 0)
            {
                var named = Path.GetFullPath(Path.Combine(root, "headless", "plc_crc.py"));
                if (File.Exists(named)) return named;
            }
            for (var folder = new DirectoryInfo(AppDomain.CurrentDomain.BaseDirectory); folder != null; folder = folder.Parent)
                foreach (var host in new[] { Path.Combine("products", "codesys-host"), "codesys-host" })
                {
                    var candidate = Path.Combine(folder.FullName, host, "headless", "plc_crc.py");
                    if (File.Exists(candidate)) return candidate;
                }
            throw new ArgumentException("headless/plc_crc.py was not found; pass --host-root");
        }

        // One IDE run over the batch: the script writes its result file, a
        // run without one reports the IDE's stderr.
        static IDictionary<string, object> Probe(Ide ide, IList<object> targets, string script, double timeout)
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-plc-crc-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            try
            {
                var request = Path.Combine(folder, "targets.json");
                var result = Path.Combine(folder, "result.json");
                File.WriteAllText(request, Json.Serialize(new Dictionary<string, object> { ["targets"] = targets }));
                var start = Start(ide, script, new Dictionary<string, string> { ["CDS_HEADLESS_CRC_INPUT"] = request, ["CDS_HEADLESS_CRC_OUTPUT"] = result });
                start.RedirectStandardOutput = true;
                start.RedirectStandardError = true;
                using (var process = Process.Start(start))
                {
                    // Read, not shown: the answer is the result file.
                    _ = process.StandardOutput.ReadToEndAsync();
                    var stderr = process.StandardError.ReadToEndAsync();
                    if (!process.WaitForExit((int)(timeout * 1000)))
                    {
                        process.Kill();
                        throw new TimeoutException("the IDE did not finish within " + timeout.ToString(CultureInfo.InvariantCulture) + " s");
                    }
                    process.WaitForExit();
                    return Result(File.Exists(result) ? File.ReadAllText(result) : null, stderr.Result, process.ExitCode, ide);
                }
            }
            finally
            {
                Directory.Delete(folder, true);
            }
        }

        internal static IDictionary<string, object> Result(string written, string stderr, int code, Ide ide)
        {
            var payload = written != null ? Json.Parse(written) as IDictionary<string, object> : null;
            if (payload == null)
                payload = Failure("ide_failed", stderr.Trim().Length > 0 ? stderr.Trim() : "IDE did not produce a result", null);
            if (!payload.ContainsKey("host")) payload["host"] = new Dictionary<string, object> { ["exe"] = ide.Exe, ["profile"] = ide.Profile };
            payload["process"] = new Dictionary<string, object> { ["returncode"] = code };
            return payload;
        }

        static ProcessStartInfo Start(Ide ide, string script, IDictionary<string, string> environment)
        {
            var arguments = ProjectOpenCommand.ProfileArgument(ide.Profile) + " " + ProcessArgs.Join(new[] { "--runscript=" + script, "--noUI", "--textPrompts" });
            var start = new ProcessStartInfo(ide.Exe, arguments)
            {
                UseShellExecute = false, CreateNoWindow = true,
            };
            foreach (var pair in environment) start.EnvironmentVariables[pair.Key] = pair.Value;
            return start;
        }

        // One IDE kept running: the script appends a JSONL event per round
        // until the control file asks it to stop. cts waits for the IDE and
        // on Ctrl+C writes that stop itself.
        static IDictionary<string, object> Watch(CliOptions options, IList<object> targets, string script)
        {
            var interval = Seconds(options, "interval", 60);
            var startup = Seconds(options, "startup_timeout", 60);
            var (output, control) = WatchPaths(options.Text("watch_output", ""), options.Text("watch_control", ""));
            var explicitIde = options.Params.ContainsKey("ide");
            var candidates = Candidates(options);
            if (candidates.Count == 0) return Raw(Failure("ide_not_found", "no CODESYS/Astra IDE found", null), 2);
            var attempts = new List<object>();
            foreach (var ide in candidates)
            {
                if (ide.Profile.Length == 0)
                {
                    attempts.Add(new Dictionary<string, object> { ["exe"] = ide.Exe, ["error"] = Error("profile_required", NoProfile(explicitIde)) });
                    continue;
                }
                var session = Guid.NewGuid().ToString("N");
                var folder = Path.Combine(Path.GetTempPath(), "cts-plc-crc-watch-" + session);
                Directory.CreateDirectory(folder);
                try
                {
                    var request = Path.Combine(folder, "targets.json");
                    File.WriteAllText(request, Json.Serialize(new Dictionary<string, object> { ["targets"] = targets }));
                    var start = Start(ide, script, new Dictionary<string, string>
                    {
                        ["CDS_HEADLESS_CRC_INPUT"] = request, ["CDS_HEADLESS_CRC_WATCH"] = "1",
                        ["CDS_HEADLESS_CRC_WATCH_OUTPUT"] = output, ["CDS_HEADLESS_CRC_WATCH_CONTROL"] = control,
                        ["CDS_HEADLESS_CRC_WATCH_INTERVAL"] = interval.ToString(CultureInfo.InvariantCulture), ["CDS_HEADLESS_CRC_WATCH_SESSION"] = session,
                    });
                    using (var process = Process.Start(start))
                    {
                        var deadline = DateTime.UtcNow.AddSeconds(startup);
                        while (!WatchStarted(output, session))
                        {
                            if (process.HasExited) throw new InvalidOperationException("IDE exited before the watch script became ready");
                            if (DateTime.UtcNow > deadline)
                            {
                                Stop(process, control, session);
                                throw new TimeoutException("IDE watch script did not become ready before --startup-timeout");
                            }
                            Thread.Sleep(100);
                        }
                        Console.WriteLine(Json.Serialize(new Dictionary<string, object>
                        {
                            ["ok"] = true, ["event"] = "watch_started", ["session_id"] = session, ["watch_output"] = output, ["watch_control"] = control,
                            ["interval_seconds"] = interval, ["host"] = new Dictionary<string, object> { ["exe"] = ide.Exe, ["profile"] = ide.Profile },
                        }));
                        Console.Out.Flush();
                        var interrupted = false;
                        ConsoleCancelEventHandler cancel = (sender, args) => { args.Cancel = true; interrupted = true; };
                        Console.CancelKeyPress += cancel;
                        try
                        {
                            while (!process.WaitForExit(200))
                                if (interrupted) Stop(process, control, session);
                        }
                        finally
                        {
                            Console.CancelKeyPress -= cancel;
                            RemoveControl(control, session);
                        }
                        var code = process.ExitCode;
                        return Raw(new Dictionary<string, object>
                        {
                            ["ok"] = code == 0, ["event"] = "watch_stopped", ["session_id"] = session, ["process"] = new Dictionary<string, object> { ["returncode"] = code },
                        }, code == 0 ? 0 : 1);
                    }
                }
                catch (Exception error) when (error is IOException || error is Win32Exception || error is TimeoutException || error is InvalidOperationException || error is UnauthorizedAccessException)
                {
                    attempts.Add(new Dictionary<string, object> { ["exe"] = ide.Exe, ["profile"] = ide.Profile, ["error"] = Error("ide_failed", error.Message) });
                    if (explicitIde) return Raw(Failure("ide_failed", error.Message, attempts), 1);
                }
                finally
                {
                    Directory.Delete(folder, true);
                }
            }
            return Raw(Failure("all_ides_failed", "no candidate IDE completed startup", attempts), 1);
        }

        // The output and control paths, full; an existing control file may
        // belong to a running watch, so it is refused.
        internal static (string Output, string Control) WatchPaths(string output, string control)
        {
            if (output.Length == 0) throw new ArgumentException("--watch-output is required with --watch");
            var full = Path.GetFullPath(output);
            var controlPath = Path.GetFullPath(control.Length > 0 ? control : full + ".control.json");
            if (File.Exists(controlPath) || Directory.Exists(controlPath))
                throw new ArgumentException("--watch-control already exists; it may belong to a running watch process. Stop that process or remove its stale control file.");
            return (full, controlPath);
        }

        static bool WatchStarted(string output, string session)
        {
            if (!File.Exists(output)) return false;
            try
            {
                using (var stream = new FileStream(output, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
                using (var reader = new StreamReader(stream))
                    for (var line = reader.ReadLine(); line != null; line = reader.ReadLine())
                    {
                        if (!(Parsed(line) is IDictionary<string, object> item)) continue;
                        if (Equals(item.TryGetValue("event", out var name) ? name : null, "started") && Equals(item.TryGetValue("session_id", out var id) ? id : null, session))
                            return true;
                    }
            }
            catch (IOException)
            {
            }
            return false;
        }

        static object Parsed(string line)
        {
            try { return Json.Parse(line); }
            catch (JsonException) { return null; }
        }

        // Asks the script to stop, then ends the IDE if it has not within 15 s.
        static void Stop(Process process, string control, string session)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(control));
            File.WriteAllText(control, Json.Serialize(new Dictionary<string, object> { ["action"] = "stop", ["session_id"] = session }));
            if (process.WaitForExit(15000)) return;
            process.Kill();
            process.WaitForExit();
        }

        // Removes this session's stop request, never a newer watch's.
        static void RemoveControl(string control, string session)
        {
            try
            {
                if (!File.Exists(control)) return;
                var command = Parsed(File.ReadAllText(control)) as IDictionary<string, object>;
                var owner = command != null && command.TryGetValue("session_id", out var id) ? Convert.ToString(id, CultureInfo.InvariantCulture) : "";
                if (string.IsNullOrEmpty(owner) || owner == session) File.Delete(control);
            }
            catch (IOException)
            {
            }
        }

        static double Seconds(CliOptions options, string key, double fallback)
        {
            if (!options.Params.ContainsKey(key)) return fallback;
            var text = options.Text(key, "");
            if (!double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var seconds) || seconds <= 0)
                throw new ArgumentException("--" + key.Replace('_', '-') + " must be a number of seconds greater than zero, not " + text);
            return seconds;
        }

        static IDictionary<string, object> Error(string code, string message)
        {
            return new Dictionary<string, object> { ["code"] = code, ["message"] = message };
        }

        static IDictionary<string, object> Failure(string code, string message, IList<object> attempts)
        {
            var payload = new Dictionary<string, object> { ["ok"] = false, ["error"] = Error(code, message), ["results"] = new List<object>() };
            if (attempts != null) payload["attempts"] = attempts;
            return payload;
        }

        static IDictionary<string, object> Raw(IDictionary<string, object> payload, int code)
        {
            return new Dictionary<string, object> { ["raw_body"] = Json.Serialize(payload), ["exit_code"] = code };
        }
    }
}
