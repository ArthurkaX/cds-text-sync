using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace Cts.Agent
{
    public static class GitFolder
    {
        static readonly string[] Ignore = { ".cts-docs/", "*.~u", "*.~u~", "*.opt", "*.precompilecache", "*.compileinfo", "*.compileinfo~", "*.bootinfo", "*.bootinfo_guids" };

        public static IDictionary<string, object> Prepare(string syncFolder, string projectId)
        {
            var folder = Path.GetFullPath(syncFolder);
            // A cds-text-sync 3.x folder is not carried over: this version starts in a new one.
            if (File.Exists(Path.Combine(folder, ".dump", "manifest.json")))
                throw new InvalidOperationException("it holds a cds-text-sync 3.x export (.dump/manifest.json), which this version does not take over: choose a new folder and cts export the project into it");
            var existing = folder;
            while (!Directory.Exists(existing) && Path.GetDirectoryName(existing) != existing) existing = Path.GetDirectoryName(existing);
            var rootRun = GitRun.In(existing, "rev-parse --show-cdup");
            var root = rootRun.ExitCode == 0 ? GitRepository.RootOf(existing, rootRun.Output) : "";
            if (root != "") GitRepository.RequireRoot(root, folder);
            var initialized = root == "";
            Directory.CreateDirectory(folder);
            if (initialized) Run(folder, "init --quiet");
            var added = new Dictionary<string, object>
            {
                { ".gitignore", Append(folder, ".gitignore", Ignore) },
                { ".gitattributes", Append(folder, ".gitattributes", new[] { "*.xml -merge" }) },
            };
            var settings = Path.Combine(folder, "cds-text-sync.json");
            var created = !File.Exists(settings);
            if (created) ProjectInfo.SaveSettings(folder, "{}\n");
            var claimed = ProjectInfo.Claim(folder, projectId);
            string commit = null;
            if (initialized)
            {
                Run(folder, "add -- .gitignore .gitattributes cds-text-sync.json");
                var identity = GitRun.In(folder, "config user.name");
                var email = GitRun.In(folder, "config user.email");
                if (identity.ExitCode != 0 || email.ExitCode != 0)
                {
                    Run(folder, "-c user.name=cts -c user.email=cts@localhost commit --quiet --no-verify -m \"cts: set up the sync folder\"");
                }
                else Run(folder, "commit --quiet --no-verify -m \"cts: set up the sync folder\"");
                commit = Run(folder, "rev-parse HEAD").Output.Trim();
            }
            return new Dictionary<string, object> { { "repository", folder }, { "initialized", initialized }, { "commit", commit }, { "added", added }, { "settings_created", created }, { "project_id_added", claimed } };
        }

        static IList<string> Append(string folder, string name, IEnumerable<string> lines)
        {
            var path = Path.Combine(folder, name);
            var existing = File.Exists(path) ? File.ReadAllText(path, Encoding.UTF8) : "";
            var present = new HashSet<string>(existing.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries).Select(x => x.Trim()), StringComparer.Ordinal);
            var missing = lines.Where(x => !present.Contains(x)).ToList();
            if (missing.Count > 0) File.AppendAllText(path, (existing.Length == 0 || existing.EndsWith("\n", StringComparison.Ordinal) ? "" : "\n") + string.Join("\n", missing) + "\n", new UTF8Encoding(false));
            return missing;
        }

        static GitRun Run(string folder, string args)
        {
            var result = GitRun.In(folder, args);
            if (result.ExitCode != 0) throw new InvalidOperationException("git failed in " + folder + ": " + result.Message);
            return result;
        }
    }
}
