using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace Cts.Sync
{
    // The view's files as an import or export found them before it read them
    // (size and write time), and as it wrote them since. A file someone changed
    // on disk while cts ran is not overwritten, and its sync base does not take
    // that change (SyncBase.Record): the next compare finds it.
    // The folder lock keeps other cts commands out; this is for everyone else.
    internal sealed class ViewStamps
    {
        readonly string _view;
        readonly Dictionary<string, Stamp> _seen = new Dictionary<string, Stamp>(StringComparer.OrdinalIgnoreCase);
        readonly SortedSet<string> _changed = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<string, byte[]> _wrote = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);

        struct Stamp
        {
            internal long Length, Written;
        }

        ViewStamps(string view) { _view = view; }

        internal static ViewStamps Take(string view)
        {
            var stamps = new ViewStamps(view);
            foreach (var full in Files(view))
                if (Of(new FileInfo(full)) is Stamp stamp) stamps._seen[stamps.Relative(full)] = stamp;
            return stamps;
        }

        // The view files Moved found changed on disk while cts ran.
        internal IReadOnlyCollection<string> Changed => _changed;

        // Every view file that is not as cts last saw it, one someone made
        // meanwhile too: Changed once the whole view is looked at again.
        internal IReadOnlyCollection<string> Recheck()
        {
            foreach (var path in _seen.Keys.Concat(Files(_view).Select(Relative)).ToList()) Moved(path);
            return _changed;
        }

        // What cts last wrote to the view file *path* (null: deleted it).
        internal bool Wrote(string path, out byte[] bytes) => _wrote.TryGetValue(Relative(path), out bytes);

        // Whether the view file *path* (relative or full) is not as cts last
        // saw it; such a file is named in Changed from then on.
        internal bool Moved(string path)
        {
            var relative = Relative(path);
            if (_changed.Contains(relative)) return true;
            _seen.TryGetValue(relative, out var before);
            var now = Of(new FileInfo(Full(relative)));
            var moved = _seen.ContainsKey(relative) ? !now.HasValue || now.Value.Length != before.Length || now.Value.Written != before.Written : now.HasValue;
            if (moved) _changed.Add(relative);
            return moved;
        }

        // Writes *bytes* to *path* unless it Moved; false when it did. The
        // bytes go to a file beside it that then takes its place: a write cut
        // short leaves the old file whole, never half of the new one (and at
        // worst that file beside it, which the sync folder's .gitignore names).
        internal bool Write(string path, byte[] bytes)
        {
            if (Moved(path)) return false;
            var full = Full(Relative(path));
            Directory.CreateDirectory(Path.GetDirectoryName(full));
            var next = Path.Combine(Path.GetDirectoryName(full), "~cts-" + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                File.WriteAllBytes(next, bytes);
                if (File.Exists(full)) File.Replace(next, full, null);
                else File.Move(next, full);
            }
            finally { if (File.Exists(next)) File.Delete(next); }
            Saw(path, bytes);
            return true;
        }

        // Deletes *path* unless it Moved; false when it did.
        internal bool Delete(string path)
        {
            if (Moved(path)) return false;
            File.Delete(Full(Relative(path)));
            Saw(path, null);
            return true;
        }

        void Saw(string path, byte[] bytes)
        {
            var relative = Relative(path);
            _wrote[relative] = bytes;
            var now = Of(new FileInfo(Full(relative)));
            if (now.HasValue) _seen[relative] = now.Value;
            else _seen.Remove(relative);
        }

        static IEnumerable<string> Files(string view) =>
            Directory.Exists(view) ? Directory.EnumerateFiles(view, "*", SearchOption.AllDirectories) : Enumerable.Empty<string>();

        static Stamp? Of(FileInfo file)
        {
            file.Refresh();
            return file.Exists ? new Stamp { Length = file.Length, Written = file.LastWriteTimeUtc.Ticks } : (Stamp?)null;
        }

        string Relative(string path)
        {
            var full = Path.IsPathRooted(path) ? Path.GetFullPath(path) : Path.GetFullPath(Path.Combine(_view, path.Replace('/', Path.DirectorySeparatorChar)));
            var root = Path.GetFullPath(_view).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            return full.StartsWith(root, StringComparison.OrdinalIgnoreCase) ? full.Substring(root.Length).Replace(Path.DirectorySeparatorChar, '/') : full;
        }

        string Full(string relative) => Path.Combine(_view, relative.Replace('/', Path.DirectorySeparatorChar));
    }
}
