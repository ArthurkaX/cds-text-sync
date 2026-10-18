using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;

namespace Cts.Sync
{
    internal sealed class DiskAgainstBaseViewFiles : IViewFiles
    {
        readonly GitTreeViewFiles baseline;
        readonly DirectoryViewFiles directory;
        readonly Func<string, byte[]> readDisk;
        readonly string diskRoot;
        readonly HashSet<string> changed;
        readonly HashSet<string> deleted;
        readonly List<string> paths;

        public DiskAgainstBaseViewFiles(string root, string view, GitTreeViewFiles baseline, string indexPath, Func<string, byte[]> readDisk = null)
        {
            this.baseline = baseline;
            this.readDisk = readDisk;
            diskRoot = view == "." ? root : Path.Combine(root, view.Replace('/', Path.DirectorySeparatorChar));
            directory = new DirectoryViewFiles(diskRoot);
            var gitDirectory = Path.GetDirectoryName(indexPath);
            Directory.CreateDirectory(gitDirectory);
            var environment = GitRepository.PrivateIndex(indexPath);
            var baseRecord = indexPath + ".base";
            var recordedBase = File.Exists(baseRecord) ? File.ReadAllText(baseRecord, Encoding.ASCII).Trim() : null;
            if (!File.Exists(indexPath) || recordedBase != baseline.Commit)
            {
                var readTree = GitRun.In(root, (File.Exists(indexPath) ? "read-tree -m " : "read-tree ") + baseline.Commit + "^{tree}", environment);
                if (readTree.ExitCode != 0)
                {
                    throw new InvalidOperationException(readTree.Message);
                }
                File.WriteAllText(baseRecord, baseline.Commit, Encoding.ASCII);
            }
            // Keep the private index's refreshed stat data as a cache across calls.
            environment["GIT_OPTIONAL_LOCKS"] = "1";
            var status = GitRun.In(root, "status --porcelain=v1 -z --no-renames --untracked-files=all -- " + ProcessArgs.Quote(view), environment);
            if (status.ExitCode != 0)
            {
                throw new InvalidOperationException(status.Message);
            }
            var statusPaths = ParseWorktreeStatus(status.Output, view);
            changed = new HashSet<string>(statusPaths.Where(item => item.Status[1] == 'M' || item.Status[1] == 'D').Select(item => item.Path), StringComparer.OrdinalIgnoreCase);
            deleted = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var path in changed)
            {
                if (!File.Exists(Path.Combine(diskRoot, path.Replace('/', Path.DirectorySeparatorChar))))
                {
                    deleted.Add(path);
                }
            }
            paths = baseline.Paths.Where(IsViewPath).Where(path => !deleted.Contains(path)).ToList();
            paths.AddRange(changed.Where(IsViewPath).Where(path => !deleted.Contains(path)));
            paths.AddRange(statusPaths.Where(item => item.Status == "??").Select(item => item.Path).Where(IsViewPath));
            paths = paths.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        }

        sealed class WorktreeStatus
        {
            internal string Path { get; set; }
            internal string Status { get; set; }
        }

        static IEnumerable<WorktreeStatus> ParseWorktreeStatus(string output, string view)
        {
            var prefix = view == "." ? "" : view.TrimEnd('/') + "/";
            foreach (var record in output.Split('\0'))
            {
                if (record.Length < 4) continue;
                var status = record.Substring(0, 2);
                var path = record.Substring(3);
                if (status == "??" || status[1] == 'M' || status[1] == 'D')
                    yield return new WorktreeStatus { Path = prefix.Length > 0 && path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) ? path.Substring(prefix.Length) : path, Status = status };
            }
        }

        static bool IsViewPath(string path)
        {
            return new[] { ".st", ".xml", ".csv" }.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase)
                && !path.Split('/').Take(path.Split('/').Length - 1).Any(part => part.StartsWith("."));
        }

        public IEnumerable<string> Paths => paths;
        public string BlobId(string path) => !changed.Contains(path) && !deleted.Contains(path) ? baseline.BlobId(path) : null;
        public byte[] Read(string path)
        {
            if (changed.Contains(path) || baseline.BlobId(path) == null)
            {
                return readDisk == null ? directory.Read(path) : readDisk(path);
            }
            return baseline.Read(path);
        }
        public IDictionary<string, byte[]> ReadMany(IEnumerable<string> requested) => requested.Distinct(StringComparer.OrdinalIgnoreCase).ToDictionary(path => path, Read, StringComparer.OrdinalIgnoreCase);
    }
}
