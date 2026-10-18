using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    internal static class CompareTool
    {
        internal static IDictionary<string, object> Open(string folder, string view, IViewFiles ideView, string against, GitRepository.Facts facts)
        {
            var target = Resolve(folder, against);
            var commit = Store(folder, view, ideView, facts, ideView as GitTreeViewFiles, true);
            var gitDir = facts.GitDir;
            return SnapshotResult(folder, view, against, target, commit, gitDir);
        }

        internal static string Store(string folder, string view, IViewFiles files, GitRepository.Facts facts, GitTreeViewFiles previousView) => Store(folder, view, files, facts, previousView, false);

        static string Store(string folder, string view, IViewFiles files, GitRepository.Facts facts, GitTreeViewFiles previousView, bool preserveDisk = false)
        {
            var format = facts.ObjectFormat;
            var gitDir = facts.GitDir;
            Directory.CreateDirectory(Path.Combine(gitDir, "cts"));
            var previousRun = GitRun.In(folder, "rev-parse -q --verify refs/cts/ide^{commit}");
            var previous = previousRun.ExitCode == 0 ? previousRun.Output.Trim() : null;
            var oldBlobs = previous == null ? new Dictionary<string, string>(StringComparer.Ordinal) : ReadViewTree(folder, previous, previousView, view);
            var current = new Dictionary<string, ViewBlob>(StringComparer.Ordinal);
            var diskRoot = view == "." ? folder : Path.Combine(folder, view.Replace('/', Path.DirectorySeparatorChar));
            var prefix = view == "." ? "" : view.TrimEnd('/') + "/";
            foreach (var path in files.Paths)
            {
                var blobId = preserveDisk ? null : files.BlobId(path);
                var pathInTree = prefix + path;
                if (blobId != null && oldBlobs.TryGetValue(pathInTree, out var oldBlobId) && oldBlobId == blobId)
                {
                    current[pathInTree] = new ViewBlob(null, blobId);
                    continue;
                }
                var bytes = files.Read(path);
                if (preserveDisk)
                {
                    var disk = Path.Combine(diskRoot, path.Replace('/', Path.DirectorySeparatorChar));
                    var kept = File.Exists(disk) ? File.ReadAllBytes(disk) : null;
                    if (kept != null && ExportCommand.SameContent(path, kept, bytes)) bytes = kept;
                }
                current[pathInTree] = new ViewBlob(bytes, ViewExport.BlobId(bytes, format));
            }
            var oldViewBlobs = oldBlobs.Where(item => item.Key.StartsWith(prefix, StringComparison.Ordinal)).ToDictionary(item => item.Key, item => item.Value, StringComparer.Ordinal);
            if (previous != null && current.Count == oldViewBlobs.Count && current.All(item => oldViewBlobs.TryGetValue(item.Key, out var id) && id == item.Value.Id)) return previous;
            foreach (var item in oldBlobs.Where(item => !item.Key.StartsWith(prefix, StringComparison.Ordinal))) current[item.Key] = new ViewBlob(null, item.Value);
            return CommitView(folder, previous, current, oldBlobs);
        }

        sealed class ViewBlob
        {
            public ViewBlob(byte[] bytes, string id) { Bytes = bytes; Id = id; }
            public byte[] Bytes { get; }
            public string Id { get; }
        }

        static Dictionary<string, string> ReadViewTree(string folder, string previous, GitTreeViewFiles previousView, string view)
        {
            var result = GitRun.In(folder, "ls-tree -r -z " + previous);
            if (result.ExitCode != 0) throw new InvalidOperationException(result.Message);
            var blobs = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var record in result.Output.Split('\0').Where(value => value.Length > 0))
            {
                var separator = record.IndexOf('\t');
                if (separator < 0) continue;
                var metadata = record.Substring(0, separator).Split(' ');
                var path = record.Substring(separator + 1);
                if (metadata.Length == 3 && metadata[1] == "blob") blobs[path] = metadata[2];
            }
            if (previousView != null && previousView.Commit == previous)
            {
                var prefix = view == "." ? "" : view.TrimEnd('/') + "/";
                foreach (var path in previousView.Paths) blobs[prefix + path] = previousView.BlobId(path);
            }
            return blobs;
        }

        static string CommitView(string folder, string previous, IDictionary<string, ViewBlob> files, IDictionary<string, string> oldBlobs)
        {
            var process = GitRun.Start(folder, "fast-import --quiet --done", null, true, true, true);
            var errorTask = process.StandardError.ReadToEndAsync();
            string commit;
            try
            {
                using (var stream = process.StandardInput.BaseStream)
                {
                    var message = Encoding.UTF8.GetBytes("cts compare: IDE snapshot");
                    var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString(System.Globalization.CultureInfo.InvariantCulture);
                    WriteText(stream, "commit refs/cts/ide\nmark :1\nauthor cts <cts@localhost> " + now + " +0000\ncommitter cts <cts@localhost> " + now + " +0000\ndata " + message.Length.ToString(System.Globalization.CultureInfo.InvariantCulture) + "\n");
                    stream.Write(message, 0, message.Length);
                    WriteText(stream, "\n");
                    if (previous != null) WriteText(stream, "from " + previous + "\n");
                    WriteText(stream, "deleteall\n");
                    foreach (var item in files)
                    {
                        var path = QuoteFastImportPath(item.Key);
                        if (oldBlobs.TryGetValue(item.Key, out var oldId) && oldId == item.Value.Id) WriteText(stream, "M 100644 " + oldId + " " + path + "\n");
                        else if (item.Value.Bytes != null)
                        {
                            WriteText(stream, "M 100644 inline " + path + "\ndata " + item.Value.Bytes.Length.ToString(System.Globalization.CultureInfo.InvariantCulture) + "\n");
                            stream.Write(item.Value.Bytes, 0, item.Value.Bytes.Length);
                            WriteText(stream, "\n");
                        }
                    }
                    WriteText(stream, "get-mark :1\ndone\n");
                }
                commit = process.StandardOutput.ReadToEnd().Trim();
                process.WaitForExit();
                var error = errorTask.GetAwaiter().GetResult();
                if (process.ExitCode != 0) throw new InvalidOperationException(error.Trim());
            }
            finally { process.Dispose(); }
            return commit;
        }

        static string QuoteFastImportPath(string path)
        {
            if (path.Length == 0 || path[0] == '"' || path.IndexOfAny(new[] { '"', '\n', '\r', '\t', '\\' }) >= 0) return "\"" + path.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "\\r").Replace("\t", "\\t") + "\"";
            return path;
        }

        static void WriteText(Stream stream, string value)
        {
            var bytes = Encoding.UTF8.GetBytes(value);
            stream.Write(bytes, 0, bytes.Length);
        }

        static IDictionary<string, object> SnapshotResult(string folder, string view, string against, string target, string commit, string gitDir)
        {
                var compareIndex = Path.Combine(gitDir, "cts", "compare-index");
                var compareEnv = GitRepository.PrivateIndex(compareIndex);
                var head = GitRun.In(folder, "rev-parse -q --verify HEAD^{commit}");
                GitRepository.Run(folder, "read-tree " + (head.ExitCode == 0 ? "HEAD" : "--empty"), compareEnv);
                GitRepository.StageFolder(folder, view, compareEnv);
                var diff = GitRun.In(folder, "diff --name-only " + commit + (target == null ? "" : " " + target) + " -- " + ProcessArgs.Quote(view), compareEnv);
                if (diff.ExitCode != 0) throw new InvalidOperationException(diff.Message);
                var paths = diff.Output.Split(new[] { '\n' }, StringSplitOptions.RemoveEmptyEntries);
                var tool = CompareUses(folder);
                if (tool == "desktop")
                {
                    var desktop = DesktopExecutable();
                    if (desktop == null) throw new InvalidOperationException("GitHub Desktop is not installed (it is looked for in %LOCALAPPDATA%\\GitHubDesktop)");
                    var copy = DesktopCopy(folder, view, commit, target, against);
                    if (paths.Length > 0) OpenDesktop(desktop, copy);
                    return new Dictionary<string, object> { { "tool", "github-desktop" }, { "files", paths.Length }, { "ide", commit.Substring(0, 12) }, { "against", against }, { "paths", paths.Take(50).ToList() }, { "desktop_repository", copy } };
                }
                if (tool == null) throw new InvalidOperationException("no diff tool: configure git diff.tool or install WinMerge");
                if (paths.Length > 0) Start(folder, view, commit, target, tool, compareIndex, ToolPath(folder, tool));
                return new Dictionary<string, object> { { "tool", tool }, { "files", paths.Length }, { "ide", commit.Substring(0, 12) }, { "against", against }, { "paths", paths.Take(50).ToList() } };
        }

        internal static void ValidateAgainst(string folder, string against) { Resolve(folder, against); }

        static string Resolve(string folder, string against)
        {
            if (string.IsNullOrWhiteSpace(against)) return null;
            var result = GitRun.In(folder, "rev-parse --verify " + ProcessArgs.Quote(against) + "^{commit}");
            if (result.ExitCode != 0) throw new InvalidOperationException(against + " names no branch, tag or commit here");
            return result.Output.Trim();
        }

        internal static readonly string[] MergeTools = { "kdiff3", "winmerge", "vscode" };
        internal const string OpenKey = "cts.openTool";
        internal static readonly string[] OpenTools = { "desktop", "vscode", "zed", "explorer" };

        // git's value of *key* as read in *folder*, or null.
        internal static string Configured(string folder, string key)
        {
            var value = GitRun.In(folder, "config --get " + ProcessArgs.Quote(key));
            return value.ExitCode == 0 && value.Output.Trim().Length > 0 ? value.Output.Trim() : null;
        }

        // What `cts compare --tool` opens from *folder*: git's diff.tool, else
        // desktop, else WinMerge, or null.
        internal static string CompareUses(string folder) =>
            Configured(folder, "diff.tool") ?? (DesktopExecutable() != null ? "desktop" : null)
            ?? (WinMergeExecutable() != null ? "winmerge" : null);

        // git's merge.tool when cts can show overlapping edits side by side in it, else the first installed one; null when none.
        internal static string MergeUses(string folder) =>
            MergeTools.Contains(Configured(folder, "merge.tool"), StringComparer.OrdinalIgnoreCase)
                ? Configured(folder, "merge.tool")
                : MergeTools.FirstOrDefault(name => InstalledExecutable(name) != null);

        // What `cts open` opens the sync folder in: the user's choice (one of
        // OpenTools or a program's full path), else the first of GitHub
        // Desktop, VS Code and Zed installed, else Explorer.
        internal static string OpenUses(string folder) =>
            Configured(folder, OpenKey) ?? OpenTools.First(name => OpenExecutable(name) != null);

        // The program behind *name*, one of OpenTools or a program's full
        // path; null when it is not installed.  VS Code and Zed start as their
        // window program, not the console one on the PATH.
        internal static string OpenExecutable(string name)
        {
            switch (name)
            {
                case "desktop": return DesktopExecutable();
                case "explorer": return "explorer.exe";
                case "vscode": return Window(InstalledExecutable(name), "Code.exe");
                case "zed": return Window(InstalledExecutable(name), "Zed.exe");
                default: return Path.IsPathRooted(name) && File.Exists(name) ? name : null;
            }
        }

        // *window* in the folder above the bin folder *found* is in, else *found*.
        static string Window(string found, string window)
        {
            var bin = found == null ? null : Path.GetDirectoryName(found);
            var root = bin == null ? null : Path.GetDirectoryName(bin);
            var beside = root == null ? null : Path.Combine(root, window);
            return beside != null && File.Exists(beside) ? beside : found;
        }

        internal static string DesktopExecutable()
        {
            var local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
            var exe = string.IsNullOrEmpty(local) ? null : Path.Combine(local, "GitHubDesktop", "GitHubDesktop.exe");
            return exe != null && File.Exists(exe) ? exe : null;
        }

        static string WinMergeExecutable()
        {
            var programFiles = Environment.GetEnvironmentVariable("ProgramFiles");
            var programFilesX86 = Environment.GetEnvironmentVariable("ProgramFiles(x86)");
            foreach (var root in new[] { programFiles, programFilesX86 }.Where(value => !string.IsNullOrEmpty(value)))
            {
                var path = Path.Combine(root, "WinMerge", "WinMergeU.exe");
                if (File.Exists(path)) return path;
            }
            return null;
        }

        // The program git difftool runs for *tool* when git would not find it itself: a known tool installed off the
        // PATH (KDiff3 in Program Files), unless the user's git names its
        // path. Null leaves it to git.
        internal static string ToolPath(string folder, string tool)
        {
            var named = GitRun.In(folder, "config --get " + ProcessArgs.Quote("difftool." + tool + ".path"));
            if (named.ExitCode == 0 && named.Output.Trim().Length > 0) return null;
            return InstalledExecutable(tool);
        }

        internal static string InstalledExecutable(string name)
        {
            if (name == "winmerge") return WinMergeExecutable();
            var command = name == "kdiff3" ? "kdiff3" : name == "vscode" ? "code" : name == "zed" ? "zed" : null;
            if (command == null) return null;
            foreach (var directory in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
            {
                foreach (var extension in Path.DirectorySeparatorChar == '\\' ? new[] { ".exe", ".cmd", ".bat", "" } : new[] { "" })
                {
                    var path = Path.Combine(directory, command + extension);
                    if (File.Exists(path)) return path;
                }
            }
            var roots = new List<string> { Environment.GetEnvironmentVariable("ProgramFiles"), Environment.GetEnvironmentVariable("ProgramFiles(x86)") }
                .Where(root => !string.IsNullOrEmpty(root)).ToList();
            var local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
            if (!string.IsNullOrEmpty(local)) roots.Add(Path.Combine(local, "Programs"));
            foreach (var root in roots)
                foreach (var relative in name == "kdiff3" ? new[] { "KDiff3/bin/kdiff3.exe", "KDiff3/kdiff3.exe" }
                    : name == "zed" ? new[] { "Zed/Zed.exe" }
                    : new[] { "Microsoft VS Code/bin/code.cmd", "Microsoft VS Code/Code.exe" })
                {
                    var path = Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
                    if (File.Exists(path)) return path;
                }
            return null;
        }

        internal static string DesktopCopy(string folder, string view, string ideCommit, string target, string against)
        {
            var gitDir = GitRepository.Run(folder, "rev-parse --absolute-git-dir").Trim();
            var label = string.IsNullOrWhiteSpace(against) ? "disk" : string.Concat(against.Select(ch => Path.GetInvalidFileNameChars().Contains(ch) ? '-' : ch));
            var copy = Path.Combine(gitDir, "cts", "desktop", Path.GetFileName(folder) + " (IDE vs " + label + ")");
            Directory.CreateDirectory(copy);
            // The copy sits inside the project's .git, where rev-parse finds the project's own repository:
            // init is safe to repeat and keeps every later command in the copy.
            GitRepository.Run(copy, "init -q");
            var common = GitRepository.Run(folder, "rev-parse --git-common-dir").Trim();
            if (!Path.IsPathRooted(common)) common = Path.GetFullPath(Path.Combine(folder, common));
            var info = Path.Combine(copy, ".git", "objects", "info");
            Directory.CreateDirectory(info);
            File.WriteAllText(Path.Combine(info, "alternates"), Path.Combine(common, "objects") + "\n", new UTF8Encoding(false));
            foreach (var key in new[] { "core.autocrlf", "core.eol" })
            {
                var setting = GitRun.In(folder, "config --get " + key);
                if (setting.ExitCode == 0) GitRepository.Run(copy, "config " + key + " " + ProcessArgs.Quote(setting.Output.Trim()));
            }
            var attributes = Path.Combine(folder, ".gitattributes");
            if (File.Exists(attributes))
            {
                // git init writes .git/info only from its templates, and a git without them leaves it out.
                Directory.CreateDirectory(Path.Combine(copy, ".git", "info"));
                File.Copy(attributes, Path.Combine(copy, ".git", "info", "attributes"), true);
            }
            GitRepository.Run(copy, "update-ref refs/heads/ide " + ideCommit);
            GitRepository.Run(copy, "symbolic-ref HEAD refs/heads/ide");
            GitRepository.Run(copy, "read-tree HEAD");
            ClearDesktopWorktree(copy);
            if (target == null)
            {
                var diskRoot = view == "." ? folder : Path.Combine(folder, view.Replace('/', Path.DirectorySeparatorChar));
                foreach (var relative in new DirectoryViewFiles(diskRoot).Paths)
                    CopyDesktopFile(copy, view == "." ? relative : view.TrimEnd('/') + "/" + relative, File.ReadAllBytes(Path.Combine(diskRoot, relative.Replace('/', Path.DirectorySeparatorChar))));
            }
            else if (view == "." || GitRun.In(copy, "cat-file -e " + ProcessArgs.Quote(target + ":" + view.TrimEnd('/'))).ExitCode == 0)
            {
                GitRepository.Run(copy, "checkout -q " + target + " -- " + ProcessArgs.Quote(view));
            }
            return copy;
        }

        static void ClearDesktopWorktree(string root)
        {
            foreach (var file in Directory.GetFiles(root, "*", SearchOption.AllDirectories).Where(path => !path.Split(Path.DirectorySeparatorChar).Contains(".git"))) File.Delete(file);
            foreach (var directory in Directory.GetDirectories(root, "*", SearchOption.AllDirectories).OrderByDescending(path => path.Length).Where(path => !path.Split(Path.DirectorySeparatorChar).Contains(".git")))
                if (Directory.Exists(directory) && !Directory.EnumerateFileSystemEntries(directory).Any()) Directory.Delete(directory);
        }

        static void CopyDesktopFile(string root, string relative, byte[] bytes)
        {
            var full = Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(full));
            File.WriteAllBytes(full, bytes);
        }

        internal static void OpenDesktop(string exe, string repository)
        {
            var info = new ProcessStartInfo(exe, "--cli-open=\"" + repository.Replace("\"", "\\\"") + "\"") { UseShellExecute = true, CreateNoWindow = true };
            try { Process.Start(info); }
            catch (System.ComponentModel.Win32Exception error) { throw new InvalidOperationException("GitHub Desktop could not start: " + error.Message); }
        }

        static void Start(string folder, string view, string commit, string target, string tool, string compareIndex, string toolPath)
        {
            var args = (toolPath == null ? "" : "-c difftool." + tool + ".path=" + ProcessArgs.Quote(toolPath) + " ")
                + "difftool --dir-diff --no-prompt --tool=" + ProcessArgs.Quote(tool)
                + " " + commit + (target == null ? "" : " " + target) + " -- " + ProcessArgs.Quote(view);
            var said = new StringBuilder();
            using (var process = GitRun.Start(folder, args, new Dictionary<string, string> { { "GIT_INDEX_FILE", compareIndex } }, false, false, true))
            {
                process.ErrorDataReceived += (sender, line) => { if (line.Data != null) lock (said) said.AppendLine(line.Data); };
                process.BeginErrorReadLine();
                // A tool that fails fails at once; one that opened stays open after cts ends.
                if (process.WaitForExit(2000) && process.ExitCode != 0)
                {
                    process.WaitForExit();
                    string reason;
                    lock (said) reason = said.ToString().Trim().Replace("\r", "").Replace("\n", "; ");
                    throw new InvalidOperationException("git difftool exited " + process.ExitCode + (reason.Length > 0 ? ": " + reason : ""));
                }
            }
        }
    }
}
