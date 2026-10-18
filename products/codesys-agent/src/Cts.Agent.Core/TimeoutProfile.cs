using System;
using System.Collections.Generic;
using System.IO;

namespace Cts.Agent
{
    // The hello's `timeout_profile`: the CLI picks a command's budget before it
    // sends the command, so the agent sizes the slow operations by the number
    // of ST files in the sync folder's project-view.
    public static class TimeoutProfile
    {
        const int DefaultTimeout = 30;
        // Without a project-view to count, never under-estimate.
        const int UnknownSizeTimeout = 600;

        // method -> fixed startup seconds, seconds per ST block, minimum seconds
        static readonly Dictionary<string, double[]> Rules = new Dictionary<string, double[]>
        {
            // Online/session lifecycle is not proportional to project size, but
            // it must never fall through to the 30 s default: a CODESYS login
            // may wait for an IDE dialog or a gateway response.
            { "connect_to_device", new[] { 60, 0.0, 60 } },
            { "read_variable", new[] { 25, 0.0, 25 } },
            { "write_variable", new[] { 25, 0.0, 25 } },
            { "read_log", new[] { 10, 0.0, 10 } },
            // Reads every entry a runtime logger holds over the online
            // connection: room for a logger of many thousands.
            { "plc_log", new[] { 30, 0.0, 60 } },
            { "build", new[] { 60, 0.55, 120 } },
            { "sync_export_text", new[] { 30, 0.35, 60 } },
            { "sync_compare_text", new[] { 20, 0.45, 60 } },
            { "download", new[] { 90, 0.55, 120 } },
            { "run_tests", new[] { 60, 0.55, 120 } },
            { "project_tree", new[] { 10, 0.03, 30 } },
        };

        public static Dictionary<string, object> Make(int? blockCount)
        {
            var timeouts = new Dictionary<string, object>();
            foreach (var rule in Rules)
            {
                var r = rule.Value;
                timeouts[rule.Key] = blockCount == null
                    ? Math.Max((int)r[2], UnknownSizeTimeout)
                    : Math.Max((int)r[2], (int)Math.Ceiling(r[0] + blockCount.Value * r[1]));
            }
            return new Dictionary<string, object>
            {
                { "block_count", blockCount },
                { "source", blockCount == null ? "unavailable" : "project-view/*.st" },
                { "timeouts", timeouts },
                { "default", blockCount == null ? UnknownSizeTimeout : DefaultTimeout },
            };
        }

        // The ST files under <syncFolder>/project-view, or null when there is
        // no such folder or it cannot be read.
        public static int? CountStBlocks(string syncFolder)
        {
            if (string.IsNullOrEmpty(syncFolder)) return null;
            var view = Path.Combine(syncFolder, "project-view");
            if (!Directory.Exists(view)) return null;
            try
            {
                var count = 0;
                foreach (var path in Directory.EnumerateFiles(view, "*", SearchOption.AllDirectories))
                    if (path.EndsWith(".st", StringComparison.OrdinalIgnoreCase)) count++;
                return count;
            }
            catch (IOException) { return null; }
            catch (UnauthorizedAccessException) { return null; }
        }
    }

    // One profile per sync folder for the agent's life, counted once; a folder with nothing to count yet is counted again
    // on the next hello, so a first export is picked up.
    public sealed class TimeoutProfileCache
    {
        readonly object _lock = new object();
        string _folder;
        Dictionary<string, object> _profile;

        public Dictionary<string, object> For(string syncFolder)
        {
            lock (_lock)
            {
                if (_profile != null && _profile["block_count"] != null && string.Equals(_folder, syncFolder, StringComparison.OrdinalIgnoreCase))
                    return _profile;
                _folder = syncFolder;
                _profile = TimeoutProfile.Make(TimeoutProfile.CountStBlocks(syncFolder));
                return _profile;
            }
        }

        // What the last hello said, for a hello that cannot ask the IDE.
        public Dictionary<string, object> Last
        {
            get { lock (_lock) return _profile; }
        }
    }
}
