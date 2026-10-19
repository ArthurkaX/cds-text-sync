using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Diagnostics;

namespace Cts.Sync
{
    internal interface IViewFiles
    {
        IEnumerable<string> Paths { get; }
        byte[] Read(string path);
        IDictionary<string, byte[]> ReadMany(IEnumerable<string> paths);
        string BlobId(string path);
    }

    internal sealed class OverlayViewFiles : IViewFiles, IDisposable
    {
        readonly IViewFiles baseline;
        readonly IViewFiles written;
        readonly HashSet<string> writtenPaths;
        readonly HashSet<string> removed;

        internal OverlayViewFiles(IViewFiles baseline, IViewFiles written, IEnumerable<string> removedPaths)
        {
            this.baseline = baseline;
            this.written = written;
            writtenPaths = new HashSet<string>(written.Paths, StringComparer.OrdinalIgnoreCase);
            removed = new HashSet<string>(removedPaths, StringComparer.OrdinalIgnoreCase);
        }

        public IEnumerable<string> Paths => baseline.Paths.Where(path => !removed.Contains(path) && !writtenPaths.Contains(path)).Concat(writtenPaths).ToList();
        public byte[] Read(string path) => writtenPaths.Contains(path) ? written.Read(path) : baseline.Read(path);
        public string BlobId(string path) => writtenPaths.Contains(path) ? written.BlobId(path) : removed.Contains(path) ? null : baseline.BlobId(path);

        public IDictionary<string, byte[]> ReadMany(IEnumerable<string> paths)
        {
            var wanted = paths.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
            var result = new Dictionary<string, byte[]>(baseline.ReadMany(wanted.Where(path => !writtenPaths.Contains(path))), StringComparer.OrdinalIgnoreCase);
            foreach (var path in wanted.Where(writtenPaths.Contains)) result[path] = written.Read(path);
            return result;
        }

        public void Dispose() => (baseline as IDisposable)?.Dispose();
    }

    internal interface IViewRenderTarget
    {
        void Write(string path, byte[] bytes);
        void Keep(string path);
        bool HasBlob(string path, string blobId);
        IList<string> KeptOrphans();
    }

    // The rendered IDE view, in memory. It renders every object: a native's timestamp alone does not prove the IDE
    // left it as the base holds it.
    internal sealed class MemoryViewFiles : IViewFiles, IViewRenderTarget
    {
        readonly Dictionary<string, byte[]> files = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<string, string> blobIds = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

        public IEnumerable<string> Paths
        {
            get { return files.Keys.ToList(); }
        }

        public byte[] Read(string path)
        {
            return files.TryGetValue(path, out var bytes) ? bytes : null;
        }

        public string BlobId(string path)
        {
            if (!files.TryGetValue(path, out var bytes))
            {
                return null;
            }
            if (!blobIds.TryGetValue(path, out var blobId))
            {
                blobId = ViewExport.BlobId(bytes);
                blobIds[path] = blobId;
            }
            return blobId;
        }

        public IDictionary<string, byte[]> ReadMany(IEnumerable<string> paths)
        {
            return paths.Distinct(StringComparer.OrdinalIgnoreCase).ToDictionary(path => path, Read, StringComparer.OrdinalIgnoreCase);
        }

        public void Write(string path, byte[] bytes)
        {
            files[path] = bytes;
            blobIds.Remove(path);
        }

        internal void Remove(string path)
        {
            files.Remove(path);
            blobIds.Remove(path);
        }

        public void Keep(string path)
        {
        }

        public bool HasBlob(string path, string blobId)
        {
            return false;
        }

        public IList<string> KeptOrphans()
        {
            return new List<string>();
        }
    }

    // The view folder of a repository. What the render writes is held until
    // the render is done: a file Git's ignore rules match (ViewIgnore) is then
    // neither written nor an orphan, and a rule that would leave a hole
    // refuses before anything is written.
    internal sealed class FolderViewRenderTarget : IViewRenderTarget
    {
        readonly string root;
        readonly string repository;
        readonly Dictionary<string, byte[]> written = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);
        readonly HashSet<string> kept = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        readonly ViewStamps stamps;

        public FolderViewRenderTarget(string root, string repository, ViewStamps stamps)
        {
            this.root = Path.GetFullPath(root);
            this.repository = repository;
            this.stamps = stamps;
            Directory.CreateDirectory(this.root);
        }

        // The view's files the rules matched, known once the render is done.
        internal ISet<string> Ignored { get; private set; } = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        public void Write(string path, byte[] bytes)
        {
            if (PathSafety.SafePath(root, path) == null) return;
            written[path] = bytes;
        }

        public void Keep(string path)
        {
            if (PathSafety.SafePath(root, path) == null) return;
            kept.Add(path);
        }
        public bool HasBlob(string path, string blobId)
        {
            var full = PathSafety.SafePath(root, path);
            if (full == null || !File.Exists(full))
            {
                return false;
            }
            try
            {
                return string.Equals(ViewExport.BlobId(File.ReadAllBytes(full)), blobId, StringComparison.Ordinal);
            }
            catch (IOException)
            {
                return false;
            }
            catch (UnauthorizedAccessException)
            {
                return false;
            }
        }
        public IList<string> KeptOrphans()
        {
            var onDisk = Directory.GetFiles(root, "*", SearchOption.AllDirectories)
                .Where(file => new[] { ".st", ".csv", ".xml" }.Contains(Path.GetExtension(file), StringComparer.OrdinalIgnoreCase))
                .Select(file => file.Substring(root.TrimEnd(Path.DirectorySeparatorChar).Length + 1).Replace(Path.DirectorySeparatorChar, '/'))
                .Where(relative => !relative.Split('/')[0].StartsWith(".")).ToList();
            var all = written.Keys.Concat(kept).Concat(onDisk).ToList();
            Ignored = ViewIgnore.Match(repository, Relative(), all);
            ViewIgnore.Refuse(Ignored, all, path => written.TryGetValue(path, out var bytes) ? bytes : ReadDisk(path));
            foreach (var item in written.Where(item => !Ignored.Contains(item.Key)))
            {
                // A file whose objects are the IDE's but for blank edges stays as it is: compare
                // calls it unchanged, and rewriting it would only show in git.
                if (item.Key.EndsWith(".st", StringComparison.OrdinalIgnoreCase) && ReadDisk(item.Key) is byte[] disk
                    && StViewReader.SameObjects(item.Key, disk, item.Value)) continue;
                stamps.Write(PathSafety.SafePath(root, item.Key), item.Value);
            }
            var emitted = new HashSet<string>(written.Keys.Concat(kept), StringComparer.OrdinalIgnoreCase);
            return onDisk.Where(path => !emitted.Contains(path) && !Ignored.Contains(path)).ToList();
        }

        byte[] ReadDisk(string path)
        {
            var full = PathSafety.SafePath(root, path);
            return full != null && File.Exists(full) ? File.ReadAllBytes(full) : null;
        }

        string Relative()
        {
            var top = Path.GetFullPath(repository).TrimEnd(Path.DirectorySeparatorChar);
            if (root.TrimEnd(Path.DirectorySeparatorChar).Equals(top, StringComparison.OrdinalIgnoreCase)) return ".";
            return root.StartsWith(top + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                ? root.Substring(top.Length + 1).TrimEnd(Path.DirectorySeparatorChar).Replace(Path.DirectorySeparatorChar, '/') : ".";
        }
    }

    internal sealed class DirectoryViewFiles : IViewFiles
    {
        readonly string root;

        public DirectoryViewFiles(string root)
        {
            this.root = Path.GetFullPath(root);
        }

        public IEnumerable<string> Paths
        {
            get
            {
                if (!Directory.Exists(root)) return Enumerable.Empty<string>();
                var pending = new Stack<string>();
                var paths = new List<string>();
                pending.Push(root);
                while (pending.Count > 0)
                {
                    var current = pending.Pop();
                    try
                    {
                        foreach (var file in Directory.GetFiles(current))
                        {
                            var extension = Path.GetExtension(file);
                            if (new[] { ".st", ".xml", ".csv" }.Contains(extension, StringComparer.OrdinalIgnoreCase))
                            {
                                paths.Add(file.Substring(root.TrimEnd(Path.DirectorySeparatorChar).Length + 1).Replace(Path.DirectorySeparatorChar, '/'));
                            }
                        }
                        foreach (var child in Directory.GetDirectories(current))
                        {
                            if (!Path.GetFileName(child).StartsWith("."))
                            {
                                pending.Push(child);
                            }
                        }
                    }
                    catch (IOException)
                    {
                    }
                    catch (UnauthorizedAccessException)
                    {
                    }
                }
                return paths;
            }
        }

        public byte[] Read(string path)
        {
            var full = Path.Combine(root, path.Replace('/', Path.DirectorySeparatorChar));
            return File.Exists(full) ? File.ReadAllBytes(full) : null;
        }

        public string BlobId(string path) => null;

        public IDictionary<string, byte[]> ReadMany(IEnumerable<string> paths)
        {
            return paths.Distinct(StringComparer.OrdinalIgnoreCase).ToDictionary(path => path, Read, StringComparer.OrdinalIgnoreCase);
        }
    }

    internal sealed class TimedViewFiles : IViewFiles
    {
        readonly IViewFiles inner;
        readonly Stopwatch elapsed = new Stopwatch();

        public TimedViewFiles(IViewFiles inner)
        {
            this.inner = inner;
        }

        public double ElapsedSeconds => elapsed.Elapsed.TotalSeconds;

        public IEnumerable<string> Paths
        {
            get
            {
                elapsed.Start();
                try
                {
                    return inner.Paths.ToList();
                }
                finally
                {
                    elapsed.Stop();
                }
            }
        }

        public string BlobId(string path) => inner.BlobId(path);

        public byte[] Read(string path)
        {
            elapsed.Start();
            try
            {
                return inner.Read(path);
            }
            finally
            {
                elapsed.Stop();
            }
        }

        public IDictionary<string, byte[]> ReadMany(IEnumerable<string> paths)
        {
            elapsed.Start();
            try
            {
                return inner.ReadMany(paths);
            }
            finally
            {
                elapsed.Stop();
            }
        }
    }

}
