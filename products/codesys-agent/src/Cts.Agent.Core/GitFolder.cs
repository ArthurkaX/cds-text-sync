using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace Cts.Agent
{
    public static class GitFolder
    {
        static readonly string[] Ignore = { ".cts-docs/", "*.~u", "*.~u~", "*.opt", "*.precompilecache", "*.compileinfo", "*.compileinfo~", "*.bootinfo", "*.bootinfo_guids", "~cts-*.tmp" };

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
                { ".gitattributes", Append(folder, ".gitattributes", new[] { "*.xml -merge", AsWritten }) },
            };
            var lf = initialized ? 0 : RestoreLf(folder);
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
            return new Dictionary<string, object> { { "repository", folder }, { "initialized", initialized }, { "commit", commit }, { "added", added }, { "lf_restored", lf }, { "settings_created", created }, { "project_id_added", claimed } };
        }

        // git keeps every file as cts wrote it: a PC whose core.autocrlf
        // checks files out with CRLF would list each one cts writes again
        // with LF as changed, its content the same.
        const string AsWritten = "* -text";

        // Does git on this PC change the line endings of *folder*'s files
        // (core.autocrlf true, no rule keeping them as written), or did it
        // before the rule came, leaving files with CRLF that git holds with LF?
        public static bool ConvertsLineEndings(string folder)
        {
            var text = GitRun.In(folder, "check-attr text -- cds-text-sync.json");
            if (text.ExitCode != 0) return false;
            if (text.Output.TrimEnd().EndsWith(": unset", StringComparison.Ordinal)) return Converted(folder).Count > 0;
            var autocrlf = GitRun.In(folder, "config --type=bool --get core.autocrlf");
            return autocrlf.ExitCode == 0 && autocrlf.Output.Trim() == "true";
        }

        // The files kept as written that git checked out with CRLF where it holds LF.
        static List<string> Converted(string folder)
        {
            var files = new List<string>();
            foreach (var entry in Run(folder, "ls-files --eol -z").Output.Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries))
            {
                var tab = entry.IndexOf('\t');
                var flags = tab < 0 ? new string[0] : entry.Substring(0, tab).Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                if (flags.Contains("i/lf") && flags.Contains("w/crlf") && flags.Contains("attr/-text")) files.Add(entry.Substring(tab + 1));
            }
            return files;
        }

        // Those files get LF back, what they had before git converted them: their number.
        // git's index still holds their CRLF size, by which git calls them
        // changed unread: the ones whose content is the committed one are
        // added, which only records their size.
        static int RestoreLf(string folder)
        {
            var files = Converted(folder);
            foreach (var file in files)
            {
                var path = Path.Combine(folder, file.Replace('/', Path.DirectorySeparatorChar));
                var bytes = File.ReadAllBytes(path);
                File.WriteAllBytes(path, bytes.Where((b, i) => b != (byte)'\r' || i + 1 >= bytes.Length || bytes[i + 1] != (byte)'\n').ToArray());
            }
            var edited = new HashSet<string>(Run(folder, "diff --name-only -z").Output.Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries), StringComparer.Ordinal);
            var same = files.Where(file => !edited.Contains(file)).ToList();
            if (same.Count > 0) GitRepository.RunWithInput(folder, "--literal-pathspecs add --pathspec-from-file=- --pathspec-file-nul", null, string.Join("\0", same));
            return files.Count;
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
