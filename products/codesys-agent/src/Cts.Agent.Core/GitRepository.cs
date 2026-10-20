using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace Cts.Agent
{
    // Git operations on a sync folder. The folder is the repository root.
    public static class GitRepository
    {
        internal sealed class Facts
        {
            internal string Root { get; set; }
            internal string GitDir { get; set; }
            internal string ObjectFormat { get; set; }
            internal string BaseCommit { get; set; }
        }

        internal static Facts ReadFacts(string folder)
        {
            if (string.IsNullOrWhiteSpace(folder)) throw new InvalidOperationException(" is not a git repository. Run 'cts set-sync-folder' with it to make one.");
            folder = Path.GetFullPath(folder);
            if (!Directory.Exists(folder)) throw new InvalidOperationException(folder + " is not a git repository. Run 'cts set-sync-folder' with it to make one.");
            var result = GitRun.In(folder, "rev-parse --show-cdup --absolute-git-dir --show-object-format -q --verify refs/cts/base^{commit}");
            var lines = result.Output.Replace("\r", "").Split('\n');
            if (lines.Length < 3 || lines[1].Trim().Length == 0 || result.ExitCode != 0 && result.ExitCode != 1)
                throw new InvalidOperationException(folder + " is not a git repository. Run 'cts set-sync-folder' with it to make one.");
            var root = RootOf(folder, lines[0]);
            RequireRoot(root, folder);
            return new Facts { Root = root, GitDir = lines[1].Trim(), ObjectFormat = lines[2].Trim(), BaseCommit = result.ExitCode == 0 && lines.Length > 3 && lines[3].Trim().Length > 0 ? lines[3].Trim() : null };
        }

        public static string Repository(string folder)
        {
            if (string.IsNullOrWhiteSpace(folder)) throw new InvalidOperationException(" is not a git repository. Run 'cts set-sync-folder' with it to make one.");
            folder = Path.GetFullPath(folder);
            if (!Directory.Exists(folder)) throw new InvalidOperationException(folder + " is not a git repository. Run 'cts set-sync-folder' with it to make one.");
            var top = GitRun.In(folder, "rev-parse --show-cdup");
            if (top.ExitCode != 0) throw new InvalidOperationException(folder + " is not a git repository. Run 'cts set-sync-folder' with it to make one.");
            var root = RootOf(folder, top.Output);
            RequireRoot(root, folder);
            return root;
        }

        // The root of the repository that holds *folder*, from git's
        // --show-cdup there, in the spelling of *folder*: git's own
        // --show-toplevel resolves a mapped drive to its UNC path and a
        // link to its target, which no path the user gave matches.
        internal static string RootOf(string folder, string cdup) => Path.GetFullPath(Path.Combine(folder, cdup.Trim(), "."));

        // Refuses a sync folder that lies inside the repository at *root* but is not its root.
        internal static void RequireRoot(string root, string folder)
        {
            var comparison = Path.DirectorySeparatorChar == '\\' ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
            if (!string.Equals(root.TrimEnd(Path.DirectorySeparatorChar), Path.GetFullPath(folder).TrimEnd(Path.DirectorySeparatorChar), comparison))
                throw new InvalidOperationException("The sync folder " + folder + " is inside the repository at " + root + ", not at its root. Run 'git init' in the sync folder itself, or move the repository there.");
        }

        public static IDictionary<string, object> Position(string folder)
        {
            var branch = GitRun.In(folder, "symbolic-ref -q --short HEAD");
            var head = GitRun.In(folder, "rev-parse -q --verify HEAD");
            if (head.ExitCode != 0 && head.Message.Length > 0 && !head.Message.Contains("Needed a single revision")) throw new InvalidOperationException(head.Message);
            return new Dictionary<string, object> { { "branch", branch.ExitCode == 0 ? branch.Output.Trim() : null }, { "commit", head.ExitCode == 0 ? head.Output.Trim() : null } };
        }

        public static IList<string> Branches(string folder) => Lines(Run(folder, "for-each-ref --format=%(refname:short) refs/heads")).OrderBy(x => x, StringComparer.Ordinal).ToList();
        public static IList<string> Tags(string folder) => Lines(Run(folder, "for-each-ref --sort=-creatordate --format=%(refname:short) refs/tags")).ToList();

        // Creates branch *name* at HEAD and checks it out; returns the name
        // git got: spaces become dashes ("some changes" is some-changes),
        // and a name git still refuses is refused with git's own rule.
        public static string Create(string folder, string name)
        {
            var branch = System.Text.RegularExpressions.Regex.Replace(name.Trim(), @"\s+", "-");
            var valid = GitRun.In(folder, "check-ref-format --branch " + ProcessArgs.Quote(branch));
            if (valid.ExitCode != 0) throw new InvalidOperationException("'" + name + "' cannot name a branch: use letters, digits, - _ . / and no .. ~ ^ : ? * [ \\");
            Run(folder, "switch -c " + ProcessArgs.Quote(branch));
            return branch;
        }

        public static void Switch(string folder, string target)
        {
            var branch = GitRun.In(folder, "show-ref --verify --quiet " + ProcessArgs.Quote("refs/heads/" + target));
            if (branch.ExitCode == 0)
            {
                Run(folder, "switch " + ProcessArgs.Quote(target));
                return;
            }
            var commit = GitRun.In(folder, "rev-parse --verify --quiet " + ProcessArgs.Quote(target + "^{commit}"));
            if (commit.ExitCode == 0)
            {
                Run(folder, "switch --detach " + ProcessArgs.Quote(target));
                return;
            }
            Run(folder, "switch " + ProcessArgs.Quote(target));
        }

        public static void Restore(string folder, IDictionary<string, object> position)
        {
            var branch = position["branch"] as string;
            Run(folder, branch == null ? "switch --detach " + ProcessArgs.Quote(Convert.ToString(position["commit"])) : "switch " + ProcessArgs.Quote(branch));
        }

        public static IDictionary<string, object> Push(string folder)
        {
            var position = Position(folder);
            var branch = position["branch"] as string;
            if (branch == null) throw new InvalidOperationException("no branch is checked out: cts branch NAME starts one");
            var upstream = GitRun.In(folder, "rev-parse --abbrev-ref --symbolic-full-name @{u}");
            string remote, target; int ahead; var setup = "";
            if (upstream.ExitCode == 0)
            {
                target = upstream.Output.Trim();
                remote = Run(folder, "config branch." + branch + ".remote").Trim();
                ahead = int.Parse(Run(folder, "rev-list --count @{u}..HEAD"), System.Globalization.CultureInfo.InvariantCulture);
            }
            else
            {
                var remotes = Lines(Run(folder, "remote")).ToList();
                if (remotes.Count != 1) throw new InvalidOperationException("the branch has no upstream and the repository " + (remotes.Count == 0 ? "has no remote" : "has several remotes") + ": git push -u <remote> " + branch + " names it");
                remote = remotes[0]; target = remote + "/" + branch; setup = "-u ";
                ahead = int.Parse(Run(folder, "rev-list --count HEAD --not --remotes=" + remote), System.Globalization.CultureInfo.InvariantCulture);
            }
            var attributes = GitRun.In(folder, "grep -q filter=lfs HEAD -- .gitattributes");
            if (attributes.ExitCode == 0) Run(folder, "lfs push " + ProcessArgs.Quote(remote) + " " + ProcessArgs.Quote(branch));
            var pushed = GitRun.In(folder, "push " + setup + ProcessArgs.Quote(remote) + " " + ProcessArgs.Quote(branch));
            if (pushed.ExitCode != 0)
            {
                var message = pushed.Message;
                if (message.Contains("rejected")) message = target + " has commits this branch lacks: pull them first (cts project update), then push; " + message;
                throw new InvalidOperationException(message);
            }
            return new Dictionary<string, object> { { "branch", branch }, { "upstream", target }, { "commits", ahead } };
        }

        public static IList<IDictionary<string, object>> History(string folder, int limit, bool every)
        {
            var downloaded = new HashSet<string>(Lines(Run(folder, "for-each-ref --format=%(objectname) refs/cts/plc/")), StringComparer.Ordinal);
            var scope = every ? " --branches --tags" : " HEAD";
            var args = "log -n " + limit + " \"--date=format:%Y-%m-%d %H:%M\" --decorate-refs=HEAD --decorate-refs=refs/heads --decorate-refs=refs/tags \"--format=%H%x09%cd%x09%D%x09%s\"" + scope;
            var entries = new List<IDictionary<string, object>>();
            foreach (var line in Lines(Run(folder, args)))
            {
                var fields = line.Split(new[] { '\t' }, 4);
                if (fields.Length < 4) continue;
                var branches = new List<string>(); var tags = new List<string>(); var isHead = false;
                foreach (var reference in fields[2].Split(new[] { ", " }, StringSplitOptions.RemoveEmptyEntries))
                {
                    if (reference.StartsWith("tag: ", StringComparison.Ordinal)) tags.Add(reference.Substring(5));
                    else if (reference.StartsWith("HEAD", StringComparison.Ordinal)) { isHead = true; if (reference.StartsWith("HEAD -> ", StringComparison.Ordinal)) branches.Add(reference.Substring(8)); }
                    else branches.Add(reference);
                }
                entries.Add(new Dictionary<string, object> { { "commit", fields[0] }, { "date", fields[1] }, { "subject", fields[3] }, { "branches", branches }, { "tags", tags }, { "head", isHead }, { "downloaded", downloaded.Contains(fields[0]) } });
            }
            return entries;
        }

        // The environment of a git command on one of cts's own index files
        // under .git/cts. A lock left there (a git that died, or a delete the
        // file system refused) would stop every later command on that index;
        // no cts command holds one for minutes, so an old one is dropped.
        internal static Dictionary<string, string> PrivateIndex(string index)
        {
            var stale = index + ".lock";
            if (File.Exists(stale) && DateTime.UtcNow - File.GetLastWriteTimeUtc(stale) > TimeSpan.FromMinutes(10)) File.Delete(stale);
            return new Dictionary<string, string> { { "GIT_INDEX_FILE", index } };
        }

        internal static string Run(string folder, string args, IDictionary<string, string> env = null)
        {
            var result = GitRun.In(folder, args, env);
            if (result.ExitCode != 0) throw new InvalidOperationException(result.Message);
            return result.Output;
        }
        // A git command that reads *input* on stdin: lists of paths go there,
        // since Windows refuses a command line longer than 32K characters.
        internal static string RunWithInput(string folder, string args, IDictionary<string, string> env, string input)
        {
            using (var process = GitRun.Start(folder, args, env, true, true, true))
            {
                var error = process.StandardError.ReadToEndAsync();
                var output = process.StandardOutput.ReadToEndAsync();
                using (var stream = process.StandardInput.BaseStream)
                {
                    var bytes = new System.Text.UTF8Encoding(false).GetBytes(input);
                    stream.Write(bytes, 0, bytes.Length);
                }
                process.WaitForExit();
                if (process.ExitCode != 0) throw new InvalidOperationException(string.Join(" ", error.Result.Split((char[])null, StringSplitOptions.RemoveEmptyEntries)));
                return output.Result;
            }
        }
        // `add -A` for one folder of the work tree into *env*'s index. git refuses a
        // path that matches nothing, which a view a new sync folder has not
        // written yet is: then the folder leaves that index.
        internal static void StageFolder(string folder, string path, IDictionary<string, string> env)
        {
            if (Directory.Exists(Path.Combine(folder, path.Replace('/', Path.DirectorySeparatorChar))))
                Run(folder, "add -A -- " + ProcessArgs.Quote(path), env);
            else Run(folder, "rm -r -q --cached --ignore-unmatch -- " + ProcessArgs.Quote(path), env);
        }
        static IEnumerable<string> Lines(string text) => text.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries);
    }
}
