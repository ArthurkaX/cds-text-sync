using System;
using System.Diagnostics;
using System.Text;
using System.Collections.Generic;

namespace Cts.Agent
{
    // One git command in a folder, with what it printed. git never asks for
    // input here, and a GIT_DIR or GIT_WORK_TREE the caller's environment
    // carries does not change which repository it reads.
    public sealed class GitRun
    {
        public int ExitCode { get; private set; }
        public string Output { get; private set; }
        public string Error { get; private set; }

        // Refused when git cannot be started (not installed, not on PATH).

        public static GitRun In(string folder, string args, IDictionary<string, string> environment = null)
        {
            try
            {
                using (var process = Process.Start(Info(folder, args, environment, false, true, true)))
                {
                    var error = process.StandardError.ReadToEndAsync();
                    var output = process.StandardOutput.ReadToEnd();
                    process.WaitForExit();
                    return new GitRun { ExitCode = process.ExitCode, Output = output, Error = error.Result };
                }
            }
            catch (System.ComponentModel.Win32Exception) { throw Missing(); }
        }

        // The started git, its redirected streams UTF-8; refused when git cannot be started.
        public static Process Start(string folder, string args, IDictionary<string, string> environment, bool redirectInput, bool redirectOutput, bool redirectError)
        {
            try
            {
                return Process.Start(Info(folder, args, environment, redirectInput, redirectOutput, redirectError));
            }
            catch (System.ComponentModel.Win32Exception)
            {
                throw Missing();
            }
        }

        static InvalidOperationException Missing() => new InvalidOperationException("git could not run: is it installed?");

        static ProcessStartInfo Info(string folder, string args, IDictionary<string, string> environment, bool redirectInput, bool redirectOutput, bool redirectError)
        {
            var info = new ProcessStartInfo("git", ProcessArgs.Join(new[] { "-C", folder }) + " " + args)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardInput = redirectInput,
                RedirectStandardOutput = redirectOutput,
                RedirectStandardError = redirectError,
                StandardOutputEncoding = redirectOutput ? Encoding.UTF8 : null,
                StandardErrorEncoding = redirectError ? Encoding.UTF8 : null,
            };
            foreach (var key in new[] { "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY" }) info.EnvironmentVariables.Remove(key);
            info.EnvironmentVariables["GIT_OPTIONAL_LOCKS"] = "0";
            if (environment != null) foreach (var item in environment) info.EnvironmentVariables[item.Key] = item.Value;
            info.EnvironmentVariables["GIT_TERMINAL_PROMPT"] = "0";
            return info;
        }

        // git's own words for a failure, on one line.
        public string Message => string.Join(" ", (Error ?? "").Split((char[])null, StringSplitOptions.RemoveEmptyEntries));
    }
}
