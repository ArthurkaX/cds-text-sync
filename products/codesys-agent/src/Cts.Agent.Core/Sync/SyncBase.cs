using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;

namespace Cts.Sync
{
    // Git state owned by cts export: its base and overwritten refs, native
    // cache, and the IDE stamp that proves when the base describes the IDE.
    public static class SyncBase
    {
        internal const string BaseRef = "refs/cts/base";
        const string OverwrittenRef = "refs/cts/overwritten";

        public sealed class Stamp
        {
            public string Project;
            public string Value;
            public string Base;
        }

        public static Stamp ReadStamp(string path)
        {
            try
            {
                var value = Json.Parse(File.ReadAllText(path)) as IDictionary<string, object>;
                return value == null ? null : new Stamp
                {
                    Project = value.ContainsKey("project") ? value["project"] as string : null,
                    Value = value.ContainsKey("stamp") ? value["stamp"] as string : null,
                    Base = value.ContainsKey("base") ? value["base"] as string : null,
                };
            }
            catch (IOException) { return null; }
            catch (ArgumentException) { return null; }
            catch (JsonException) { return null; }
        }

        public static void SaveStamp(string path, string project, string stamp, string baseCommit)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllText(path, Json.Pretty(new Dictionary<string, object>
            {
                { "project", project }, { "stamp", stamp }, { "base", baseCommit },
            }) + "\n", new UTF8Encoding(false));
        }

        // The view as the disk has it, but for *keep* (repository paths), which
        // keeps the base's entry. With *stamps*, a view file someone changed
        // while cts ran (ViewStamps) keeps it too, or takes what cts wrote
        // there last, which the IDE holds: the next compare shows that change.
        // A file Git's ignore rules match keeps its entry unless it is one of
        // *carried* (repository paths an import gave the IDE).
        internal static string Record(string repo, string view, IList<string> keep, ViewStamps stamps = null, ICollection<string> carried = null)
        {
            var gitDir = GitRepository.Run(repo, "rev-parse --absolute-git-dir").Trim();
            var index = Path.Combine(gitDir, "cts", "base-index");
            Directory.CreateDirectory(Path.GetDirectoryName(index));
            var env = GitRepository.PrivateIndex(index);
            if (!File.Exists(index)) GitRepository.Run(repo, "read-tree --empty", env);
            var parent = OwnRef(repo, BaseRef);
            var paths = new[] { view, "cds-text-sync.json" }.Where(p => File.Exists(Path.Combine(repo, p.Replace('/', Path.DirectorySeparatorChar))) || Directory.Exists(Path.Combine(repo, p.Replace('/', Path.DirectorySeparatorChar)))).ToArray();
            if (paths.Length > 0) GitRepository.Run(repo, "add -A -- " + string.Join(" ", paths.Select(ProcessArgs.Quote)), env);
            var source = parent ?? (GitRun.In(repo, "rev-parse -q --verify HEAD^{commit}") is var head && head.ExitCode == 0 ? head.Output.Trim() : null);
            if (source != null)
            {
                var ignored = Ignored(repo, view, env, source).ToList();
                var taken = ignored.Where(path => carried != null && carried.Contains(path)).ToList();
                if (taken.Count > 0) GitRepository.Run(repo, "add -f -- " + string.Join(" ", taken.Select(ProcessArgs.Quote)), env);
                keep = keep.Concat(ignored.Except(taken)).Distinct(StringComparer.Ordinal).ToList();
            }
            var pinned = new Dictionary<string, byte[]>(StringComparer.Ordinal);
            var unknown = new List<string>();
            if (stamps != null)
            {
                var prefix = view == "." ? "" : view.TrimEnd('/') + "/";
                var kept = new HashSet<string>(keep, StringComparer.OrdinalIgnoreCase);
                // Looked at once the view is in the index: a change after that is not in it.
                foreach (var path in stamps.Recheck().Where(path => !kept.Contains(prefix + path)))
                {
                    if (stamps.Wrote(path, out var bytes)) pinned[prefix + path] = bytes;
                    else if (source != null) keep = keep.Concat(new[] { prefix + path }).ToList();
                    else unknown.Add(prefix + path);
                }
            }
            if (source != null && keep.Count > 0) RestoreBaseEntries(repo, env, source, keep);
            Pin(repo, env, Path.Combine(gitDir, "cts"), pinned);
            Drop(repo, env, unknown.Concat(pinned.Where(item => item.Value == null).Select(item => item.Key)).ToList());
            return CommitBase(repo, env, parent, "cts base: export");
        }

        // *pinned*'s bytes as the entries of their repository paths (null: none), hashed
        // with the path's own attributes, as git add would have them from the disk.
        static void Pin(string repo, IDictionary<string, string> env, string scratch, IDictionary<string, byte[]> pinned)
        {
            var file = Path.Combine(scratch, "pinned-" + Guid.NewGuid().ToString("N"));
            var input = new StringBuilder();
            try
            {
                foreach (var item in pinned.Where(item => item.Value != null))
                {
                    File.WriteAllBytes(file, item.Value);
                    var blob = GitRepository.Run(repo, "hash-object -w --path " + ProcessArgs.Quote(item.Key) + " -- " + ProcessArgs.Quote(file)).Trim();
                    input.Append("100644 " + blob + "\t" + item.Key).Append('\0');
                }
            }
            finally { if (File.Exists(file)) File.Delete(file); }
            if (input.Length > 0) GitRepository.RunWithInput(repo, "update-index -z --index-info", env, input.ToString());
        }

        static void Drop(string repo, IDictionary<string, string> env, IList<string> paths)
        {
            if (paths.Count > 0) GitRepository.RunWithInput(repo, "update-index -z --force-remove --stdin", env, string.Join("\0", paths) + "\0");
        }

        // The files Git's ignore rules leave to the owner (ViewIgnore), as repository paths: their
        // base stays what the last sync gave them, since the disk holds the owner's file, not the IDE's.
        // Once a rule goes, the owner's file is then a change on disk the import carries.
        static IEnumerable<string> Ignored(string repo, string view, IDictionary<string, string> env, string source)
        {
            var prefix = view == "." ? "" : view.TrimEnd('/') + "/";
            var listed = GitRepository.Run(repo, "ls-files -z -- " + ProcessArgs.Quote(view), env).Split('\0')
                .Concat(GitRepository.Run(repo, "ls-tree -r -z --name-only " + source + " -- " + ProcessArgs.Quote(view)).Split('\0'))
                .Where(path => path.Length > prefix.Length && path.StartsWith(prefix, StringComparison.Ordinal)).Select(path => path.Substring(prefix.Length));
            return ViewIgnore.Match(repo, view, listed).Select(path => prefix + path).ToList();
        }

        // The base as *sourceCommit* has the view: a colleague's update
        // records the publish commit, which the published project matches.
        internal static void RecordFromCommit(string repo, string view, string sourceCommit)
        {
            var index = Path.Combine(GitRepository.Run(repo, "rev-parse --absolute-git-dir").Trim(), "cts", "base-index");
            Directory.CreateDirectory(Path.GetDirectoryName(index));
            var env = GitRepository.PrivateIndex(index);
            var parent = OwnRef(repo, BaseRef);
            GitRepository.Run(repo, "read-tree --empty", env);
            var viewPrefix = view.TrimEnd('/') + "/";
            var paths = GitRepository.Run(repo, "ls-tree -r -z --name-only " + ProcessArgs.Quote(sourceCommit))
                .Split('\0').Where(path => path == "cds-text-sync.json" || path.StartsWith(viewPrefix, StringComparison.Ordinal)).ToList();
            RestoreBaseEntries(repo, env, sourceCommit, paths);
            CommitBase(repo, env, parent, "cts base: project update");
        }

        // The index *env* names as the next base commit; null when its tree is the base's already.
        static string CommitBase(string repo, IDictionary<string, string> env, string parent, string message)
        {
            var tree = GitRepository.Run(repo, "write-tree", env).Trim();
            if (parent != null && GitRepository.Run(repo, "rev-parse " + parent + "^{tree}").Trim() == tree) return null;
            var identity = new Dictionary<string, string> { { "GIT_AUTHOR_NAME", "cts" }, { "GIT_AUTHOR_EMAIL", "cts@localhost" }, { "GIT_COMMITTER_NAME", "cts" }, { "GIT_COMMITTER_EMAIL", "cts@localhost" } };
            var commit = GitRepository.Run(repo, "commit-tree " + tree + (parent == null ? "" : " -p " + parent) + " -m " + ProcessArgs.Quote(message), identity).Trim();
            MoveRef(repo, BaseRef, commit, parent);
            return commit.Substring(0, Math.Min(12, commit.Length));
        }

        // Keep the current view with selected IDE-side bytes substituted, without touching the user's index.
        public static string KeepOverwritten(string repo, string view, IDictionary<string, byte[]> replaced)
        {
            if (replaced == null || replaced.Count == 0) return null;
            var gitDir = GitRepository.Run(repo, "rev-parse --absolute-git-dir").Trim();
            var ctsDir = Path.Combine(gitDir, "cts"); Directory.CreateDirectory(ctsDir);
            var index = Path.Combine(ctsDir, "overwritten-index");
            var temp = Path.Combine(ctsDir, "overwritten-files-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(temp);
            var env = GitRepository.PrivateIndex(index);
            env["GIT_WORK_TREE"] = repo;
            var head = GitRun.In(repo, "rev-parse -q --verify HEAD^{commit}");
            try
            {
                GitRepository.Run(repo, head.ExitCode == 0 ? "read-tree " + head.Output.Trim() : "read-tree --empty", env);
                GitRepository.StageFolder(repo, view, env);
                foreach (var item in replaced)
                {
                    var full = Path.Combine(temp, item.Key.Replace('/', Path.DirectorySeparatorChar));
                    Directory.CreateDirectory(Path.GetDirectoryName(full)); File.WriteAllBytes(full, item.Value);
                }
                env["GIT_WORK_TREE"] = temp;
                GitRepository.Run(repo, "add -f -- " + string.Join(" ", replaced.Keys.Select(ProcessArgs.Quote)), env);
                var tree = GitRepository.Run(repo, "write-tree", env).Trim();
                var previous = OwnRef(repo, OverwrittenRef);
                var previousTree = previous == null ? null : GitRepository.Run(repo, "rev-parse " + previous + "^{tree}").Trim();
                if (tree == previousTree) return previous;
                var identity = new Dictionary<string, string> { { "GIT_AUTHOR_NAME", "cts" }, { "GIT_AUTHOR_EMAIL", "cts@localhost" }, { "GIT_COMMITTER_NAME", "cts" }, { "GIT_COMMITTER_EMAIL", "cts@localhost" } };
                var commit = GitRepository.Run(repo, "commit-tree " + tree + (previous == null ? "" : " -p " + previous) + " -m " + ProcessArgs.Quote("cts import --force: preserve IDE text"), identity).Trim();
                MoveRef(repo, OverwrittenRef, commit, previous);
                return commit.Substring(0, Math.Min(12, commit.Length));
            }
            finally
            {
                if (File.Exists(index)) File.Delete(index);
                if (Directory.Exists(temp)) Directory.Delete(temp, true);
            }
        }

        // The view files that differ from *against*'s tree (edited, deleted or
        // new), with what the disk holds (null: deleted); not those Git's ignore
        // rules leave to the owner (ViewIgnore). Compared in a private
        // index, so the user's index and what they staged play no part.
        public static Dictionary<string, byte[]> Changed(string repo, string view, string against)
        {
            var result = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);
            var index = Path.Combine(GitRepository.Run(repo, "rev-parse --absolute-git-dir").Trim(), "cts", "compare-index");
            Directory.CreateDirectory(Path.GetDirectoryName(index));
            var env = GitRepository.PrivateIndex(index);
            string changed;
            try
            {
                GitRepository.Run(repo, "read-tree " + against, env);
                GitRepository.StageFolder(repo, view, env);
                changed = GitRepository.Run(repo, "diff --cached --name-only -z --no-renames " + against + " -- " + ProcessArgs.Quote(view), env);
            }
            finally { if (File.Exists(index)) File.Delete(index); }
            foreach (var path in changed.Split('\0').Where(p => p.Length > 0))
            {
                var full = Path.Combine(repo, path.Replace('/', Path.DirectorySeparatorChar));
                if (!new[] { ".st", ".xml", ".csv" }.Contains(Path.GetExtension(full), StringComparer.OrdinalIgnoreCase)) continue;
                result[view == "." ? path : path.Substring(view.Length).TrimStart('/')] = File.Exists(full) ? File.ReadAllBytes(full) : null;
            }
            foreach (var path in ViewIgnore.Match(repo, view, result.Keys)) result.Remove(path);
            return result;
        }

        // One ls-tree of the whole parent and one update-index fed on stdin: the
        // paths never go on the command line, which Windows caps at 32K characters.
        static void RestoreBaseEntries(string repo, IDictionary<string, string> env, string parent, IList<string> paths)
        {
            var wanted = new HashSet<string>(paths, StringComparer.Ordinal);
            var entries = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var record in GitRepository.Run(repo, "ls-tree -r -z " + parent).Split('\0').Where(x => x.Length > 0))
            {
                var tab = record.IndexOf('\t');
                if (tab > 0 && wanted.Contains(record.Substring(tab + 1))) entries[record.Substring(tab + 1)] = record;
            }
            var removed = "0 " + new string('0', parent.Length) + "\t";
            var input = new StringBuilder();
            foreach (var path in paths)
            {
                input.Append(entries.TryGetValue(path, out var record) ? record : removed + path);
                input.Append('\0');
            }
            GitRepository.RunWithInput(repo, "update-index -z --index-info", env, input.ToString());
        }

        public static void KeepOverwritten(string repo, string view)
        {
            var index = Path.Combine(GitRepository.Run(repo, "rev-parse --absolute-git-dir").Trim(), "cts", "overwritten-index");
            Directory.CreateDirectory(Path.GetDirectoryName(index));
            var env = GitRepository.PrivateIndex(index);
            var previous = OwnRef(repo, OverwrittenRef);
            if (previous != null) GitRepository.Run(repo, "read-tree " + previous, env);
            else
            {
                var baseIndex = Path.Combine(Path.GetDirectoryName(index), "base-index");
                if (File.Exists(baseIndex)) File.Copy(baseIndex, index, true);
                else GitRepository.Run(repo, "read-tree --empty", env);
            }
            GitRepository.StageFolder(repo, view, env);
            var tree = GitRepository.Run(repo, "write-tree", env).Trim();
            var baseTree = GitRun.In(repo, "rev-parse -q --verify " + BaseRef + "^{tree}");
            if (baseTree.ExitCode == 0 && baseTree.Output.Trim() == tree) return;
            var identity = new Dictionary<string, string> { { "GIT_AUTHOR_NAME", "cts" }, { "GIT_AUTHOR_EMAIL", "cts@localhost" }, { "GIT_COMMITTER_NAME", "cts" }, { "GIT_COMMITTER_EMAIL", "cts@localhost" } };
            var commit = GitRepository.Run(repo, "commit-tree " + tree + (previous == null ? "" : " -p " + previous) + " -m " + ProcessArgs.Quote("cts export --force: what the disk held"), identity).Trim();
            MoveRef(repo, OverwrittenRef, commit, previous);
        }

        // The project file whose IDE the base describes: an export writes it,
        // so a sync folder opened from another copy of the project (an older
        // version, a colleague's file) is not taken for this project's edits.
        public static void SaveProject(string repo, string project)
        {
            if (string.IsNullOrWhiteSpace(project)) return;
            File.WriteAllText(ProjectPath(repo), project, new UTF8Encoding(false));
        }

        // The base's project file when it is not *project*; null when it is
        // or when no export recorded one yet.
        public static string OtherProject(string repo, string project)
        {
            var path = ProjectPath(repo);
            if (string.IsNullOrWhiteSpace(project) || !File.Exists(path)) return null;
            var saved = File.ReadAllText(path).Trim();
            return saved.Length == 0 || string.Equals(saved, project.Trim(), StringComparison.OrdinalIgnoreCase) ? null : saved;
        }

        static string ProjectPath(string repo)
        {
            var cts = Path.Combine(GitRepository.Run(repo, "rev-parse --absolute-git-dir").Trim(), "cts");
            Directory.CreateDirectory(cts);
            return Path.Combine(cts, "base-project");
        }

        // Refuses a base something other than cts moved, before an export writes.
        public static void CheckBase(string repo) => OwnRef(repo, BaseRef);

        internal static void CheckBase(string repo, GitRepository.Facts facts) => OwnRef(repo, BaseRef, facts.BaseCommit, facts.GitDir);

        // The commit *name* holds, or null. cts builds only on the commit it
        // left there itself (<git dir>/cts/<ref>.own): a ref moved by anything
        // else is refused.
        static string OwnRef(string repo, string name)
        {
            var run = GitRun.In(repo, "rev-parse -q --verify " + name + "^{commit}");
            var found = run.ExitCode == 0 ? run.Output.Trim() : null;
            return OwnRef(repo, name, found, null);
        }

        static string OwnRef(string repo, string name, string found, string gitDir)
        {
            var own = gitDir == null ? OwnPath(repo, name) : OwnPathFromGitDir(gitDir, name);
            if (!File.Exists(own))
            {
                if (found != null) File.WriteAllText(own, found, Encoding.ASCII);
                return found;
            }
            var left = File.ReadAllText(own, Encoding.ASCII).Trim();
            if (found != null && left.Length > 0 && found != left)
                throw new InvalidOperationException(string.Format(
                    "{0} was moved outside cts (it names {1}, cts left {2}): git update-ref {0} {2} puts cts's back; "
                    + "git update-ref -d {0} drops it and the next cts export starts a new one", name, found.Substring(0, 12), left));
            return found;
        }

        static void MoveRef(string repo, string name, string commit, string parent)
        {
            GitRepository.Run(repo, "update-ref " + name + " " + commit + (parent == null ? "" : " " + parent));
            File.WriteAllText(OwnPath(repo, name), commit, Encoding.ASCII);
        }

        static string OwnPath(string repo, string name)
        {
            return OwnPathFromGitDir(GitRepository.Run(repo, "rev-parse --absolute-git-dir").Trim(), name);
        }

        static string OwnPathFromGitDir(string gitDir, string name)
        {
            var cts = Path.Combine(gitDir, "cts");
            Directory.CreateDirectory(cts);
            return Path.Combine(cts, name.Substring(name.LastIndexOf('/') + 1) + ".own");
        }

        // The pairs hold for the project they were found in: another project
        // file with the same object and TimeStamp can export it differently
        // (a visualization renders the library versions that project resolves).
        // A new NativesFormat drops the pairs a cts that wrote files otherwise kept.
        const string NativesFormat = "3.5.0";

        public static void SaveNatives(string repo, string project, IList<NativeExport> items, string view)
        {
            var cts = Path.Combine(GitRepository.Run(repo, "rev-parse --absolute-git-dir").Trim(), "cts");
            Directory.CreateDirectory(cts);
            var objects = new Dictionary<string, object>();
            foreach (var item in items)
            {
                var nativeFile = Path.Combine(view, item.Path.Replace('/', Path.DirectorySeparatorChar));
                if (File.Exists(nativeFile)) objects[item.Guid.Trim('{', '}').ToLowerInvariant()] = new object[] { item.Timestamp, ViewExport.BlobId(File.ReadAllBytes(nativeFile)) };
            }
            var path = Path.Combine(cts, "same-natives.json");
            var part = path + ".part";
            try
            {
                File.WriteAllText(part, Json.Pretty(new Dictionary<string, object> { { "cts", NativesFormat }, { "project", project }, { "objects", objects } }) + "\n", new UTF8Encoding(false));
                SafeFile.Replace(part, path);
            }
            catch (IOException) { if (File.Exists(part)) File.Delete(part); }
            catch (UnauthorizedAccessException) { if (File.Exists(part)) File.Delete(part); }
        }

        public static IDictionary<string, object> LoadNatives(string repo, string project)
        {
            var path = Path.Combine(GitRepository.Run(repo, "rev-parse --absolute-git-dir").Trim(), "cts", "same-natives.json");
            try
            {
                var data = Json.Parse(File.ReadAllText(path)) as IDictionary<string, object>;
                return data != null && Equals(data.ContainsKey("cts") ? data["cts"] : null, NativesFormat)
                    && string.Equals(Convert.ToString(data.ContainsKey("project") ? data["project"] : null), project, StringComparison.OrdinalIgnoreCase)
                    ? data["objects"] as IDictionary<string, object> ?? new Dictionary<string, object>()
                    : new Dictionary<string, object>();
            }
            catch (IOException) { return new Dictionary<string, object>(); }
            catch (ArgumentException) { return new Dictionary<string, object>(); }
            catch (JsonException) { return new Dictionary<string, object>(); }
        }
    }
}
