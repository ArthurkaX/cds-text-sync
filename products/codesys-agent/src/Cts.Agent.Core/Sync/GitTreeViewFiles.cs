using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Diagnostics;
using System.Text;
using Cts.Agent;

namespace Cts.Sync
{
    internal sealed class GitTreeViewFiles : IViewFiles, IDisposable
    {
        double elapsedSeconds;
        readonly string commit;
        readonly Dictionary<string, string> blobs = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        readonly Dictionary<string, byte[]> cache = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);
        readonly Process reader;
        readonly object gate = new object();

        public GitTreeViewFiles(string root, string commit, string view)
        {
            this.commit = commit;
            var tree = view == "." ? commit + "^{tree}" : commit + ":" + ProcessArgs.Quote(view);
            var listing = Stopwatch.StartNew();
            var result = GitRun.In(root, "ls-tree -r -z " + tree);
            listing.Stop();
            elapsedSeconds += listing.Elapsed.TotalSeconds;
            if (result.ExitCode != 0)
            {
                throw new InvalidOperationException(result.Message);
            }
            foreach (var record in result.Output.Split('\0').Where(value => value.Length > 0))
            {
                var separator = record.IndexOf('\t');
                if (separator < 0)
                {
                    continue;
                }
                var fields = record.Substring(0, separator).Split(' ');
                var path = record.Substring(separator + 1);
                if (fields.Length != 3 || fields[1] != "blob")
                {
                    continue;
                }
                if (!new[] { ".st", ".xml", ".csv" }.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase))
                {
                    continue;
                }
                var segments = path.Split('/');
                if (segments.Take(segments.Length - 1).Any(part => part.StartsWith(".")))
                {
                    continue;
                }
                blobs[path] = fields[2];
            }
            reader = GitRun.Start(root, "cat-file --batch", null, true, true, false);
        }

        public IEnumerable<string> Paths => blobs.Keys.ToList();
        public double ElapsedSeconds => elapsedSeconds;
        public string Commit => commit;

        public byte[] Read(string path)
        {
            var files = ReadMany(new[] { path });
            return files[path];
        }

        public string BlobId(string path)
        {
            return blobs.TryGetValue(path, out var blob) ? blob : null;
        }

        public IDictionary<string, byte[]> ReadMany(IEnumerable<string> paths)
        {
            lock (gate)
            {
                var requested = paths.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
                var pending = requested.Where(path => !cache.ContainsKey(path) && blobs.ContainsKey(path)).ToList();
                var readTimer = Stopwatch.StartNew();
                var writer = System.Threading.Tasks.Task.Run(() =>
                {
                    foreach (var path in pending) WriteObjectName(blobs[path]);
                });
                foreach (var path in pending)
                {
                    var header = ReadHeader(reader.StandardOutput.BaseStream);
                    var fields = header?.Split(' ');
                    if (fields != null && fields.Length == 2 && fields[1] == "missing")
                    {
                        cache[path] = null;
                        continue;
                    }
                    cache[path] = ReadBlob(reader.StandardOutput.BaseStream, fields);
                }
                writer.GetAwaiter().GetResult();
                readTimer.Stop();
                elapsedSeconds += readTimer.Elapsed.TotalSeconds;
                return requested.ToDictionary(path => path, path => cache.TryGetValue(path, out var bytes) ? bytes : null, StringComparer.OrdinalIgnoreCase);
            }
        }

        void WriteObjectName(string name)
        {
            WriteObjectName(name, Encoding.ASCII);
        }

        void WriteObjectName(string name, Encoding encoding)
        {
            var bytes = encoding.GetBytes(name + "\n");
            reader.StandardInput.BaseStream.Write(bytes, 0, bytes.Length);
            reader.StandardInput.BaseStream.Flush();
        }

        static byte[] ReadBlob(Stream stream, string[] fields)
        {
            if (fields == null || fields.Length != 3 || fields[1] != "blob")
            {
                throw new IOException("git cat-file returned an invalid blob header");
            }
            var length = int.Parse(fields[2], System.Globalization.CultureInfo.InvariantCulture);
            var bytes = new byte[length];
            var offset = 0;
            while (offset < length)
            {
                var count = stream.Read(bytes, offset, length - offset);
                if (count == 0)
                {
                    throw new EndOfStreamException("git cat-file ended before the blob was read");
                }
                offset += count;
            }
            stream.ReadByte();
            return bytes;
        }

        static string ReadHeader(Stream stream)
        {
            var bytes = new List<byte>();
            int current;
            while ((current = stream.ReadByte()) >= 0 && current != '\n')
            {
                bytes.Add((byte)current);
            }
            if (current < 0)
            {
                return null;
            }
            return Encoding.UTF8.GetString(bytes.ToArray()).TrimEnd('\r');
        }

        public void Dispose()
        {
            reader.StandardInput.Close();
            if (!reader.WaitForExit(1000))
            {
                reader.Kill();
            }
            reader.Dispose();
        }
    }
}
