using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Sync;

namespace Cts.Cli
{
    // Content keys: whether two files of the view hold the same content, cached by blob.
    internal static partial class ComparePlanner
    {
        internal sealed class ContentKeyCache
        {
            readonly string path;
            readonly Dictionary<string, string> keys = new Dictionary<string, string>(StringComparer.Ordinal);
            readonly HashSet<string> used = new HashSet<string>(StringComparer.Ordinal);
            bool dirty;

            internal ContentKeyCache(string path)
            {
                this.path = path;
                try
                {
                    foreach (var line in File.ReadAllLines(path))
                    {
                        var fields = line.Split(' ');
                        if (fields.Length != 3 || fields.Any(string.IsNullOrEmpty)) throw new FormatException();
                        keys[fields[0] + " " + fields[1]] = fields[2];
                    }
                }
                catch { keys.Clear(); dirty = true; }
            }

            internal string Get(string blob, string kind)
            {
                used.Add(blob);
                return blob != null && keys.TryGetValue(blob + " " + kind, out var key) ? key : null;
            }

            internal void Put(string blob, string kind, string key)
            {
                if (blob == null || key == null) return;
                used.Add(blob);
                var slot = blob + " " + kind;
                if (!keys.ContainsKey(slot)) dirty = true;
                keys[slot] = key;
            }

            internal void Touch(string blob)
            {
                if (blob != null) used.Add(blob);
            }

            internal void Save()
            {
                if (!dirty && keys.Count <= 20000) return;
                var entries = keys.Where(entry => used.Contains(entry.Key.Substring(0, entry.Key.IndexOf(' ')))).ToList();
                if (entries.Count > 20000) entries = entries.Skip(entries.Count - 20000).ToList();
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                File.WriteAllLines(path, entries.Select(entry => entry.Key + " " + entry.Value));
            }
        }

        internal static bool SameViewContent(string path, IViewFiles left, IViewFiles right, ContentKeyCache contentKeys)
        {
            var leftBlob = left?.BlobId(path);
            var rightBlob = right?.BlobId(path);
            if (leftBlob != null && rightBlob != null && string.Equals(leftBlob, rightBlob, StringComparison.Ordinal))
            {
                contentKeys.Touch(leftBlob);
                return true;
            }
            var kind = ContentKeyKind(path);
            var leftKey = ViewContentKey(path, left, leftBlob, kind, contentKeys);
            var rightKey = ViewContentKey(path, right, rightBlob, kind, contentKeys);
            return string.Equals(leftKey, rightKey, StringComparison.Ordinal);
        }

        static string ViewContentKey(string path, IViewFiles files, string blob, string kind, ContentKeyCache cache)
        {
            if (blob != null && cache.Get(blob, kind) is string stored) return stored;
            var bytes = files?.Read(path);
            if (bytes == null) return ExportCommand.ContentKey(path, null);
            var actualBlob = ViewExport.BlobId(bytes);
            var key = cache.Get(actualBlob, kind) ?? ExportCommand.ContentKey(path, bytes);
            cache.Put(actualBlob, kind, key);
            return key;
        }

        static string ContentKeyKind(string path)
        {
            var extension = Path.GetExtension(path).ToLowerInvariant();
            if (extension == ".xml") return "xml2";   // a new normalization rule takes a new kind, so keys cached by the old one go unused
            if (extension == ".st" || extension == ".csv") return "text";
            return "bytes";
        }
    }
}
