// Paths on the PLC (`cts plc`): they name files on the device, not on this
// PC, and the device API takes its root as "".  Git Bash rewrites an argument
// that starts with '/' into a Windows path before `cts` sees it, so a drive
// letter or a UNC share here is that rewrite, refused rather than sent.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;

namespace Cts.Agent
{
    public static class PlcPaths
    {
        static readonly string[] RootTokens = { ".", "", "/", "\\", "/.", ".\\" };

        public static string Normal(string name, string value)
        {
            var text = value ?? "";
            var rewritten = (text.Length >= 2 && text[1] == ':' && char.IsLetter(text[0]))
                || text.StartsWith("\\\\", StringComparison.Ordinal) || text.StartsWith("//", StringComparison.Ordinal);
            if (rewritten)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "PLC path in '" + name + "' looks like a path on this PC, not on the device: " + text
                    + ". Git Bash rewrites an argument that starts with '/' into a Windows path before 'cts' sees it. "
                    + "For the PLC root pass '.', or run with MSYS_NO_PATHCONV=1 to keep a leading '/' as typed.");
            return RootTokens.Contains(text) ? "" : text;
        }

        // A file on this PC the agent reads or writes: absolute, since the
        // IDE's working directory has nothing to do with the caller's.
        public static string HostFile(string name, string value)
        {
            if (string.IsNullOrEmpty(value))
                throw new ProtocolException(ErrorCodes.BadParams, "missing parameter '" + name + "'");
            var rooted = (value.Length >= 3 && value[1] == ':' && char.IsLetter(value[0]) && (value[2] == '\\' || value[2] == '/'))
                || value.StartsWith("\\\\", StringComparison.Ordinal);
            if (!rooted)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "'" + name + "' must be an absolute path on this PC, got '" + value + "'.");
            return value;
        }

        // One directory entry; the device's times are UTC already.  Flag bit 1
        // marks a directory.  "." and ".." are left out by the caller.
        public static Dictionary<string, object> Entry(string name, uint flag, long size, DateTime created, DateTime modified)
        {
            return new Dictionary<string, object>
            {
                { "name", name },
                { "is_directory", (flag & 2) != 0 },
                { "size", size },
                { "creation_time", Utc(created) },
                { "last_write_time", Utc(modified) },
            };
        }

        // The directory holding a PLC file, "." for the root.
        public static string Parent(string file)
        {
            var slash = file.LastIndexOfAny(new[] { '/', '\\' });
            return slash <= 0 ? "." : file.Substring(0, slash);
        }

        public static bool IsSelfOrParent(string name)
        {
            return name == "." || name == "..";
        }

        // A directory lists "." and ".."; a path that is not one answers no
        // entries at all instead of an error, so its listing lacks ".".
        public static void RequireDirectory(string path, IEnumerable<string> names)
        {
            if (!names.Contains("."))
                throw new ProtocolException(ErrorCodes.BadParams, "No directory '" + path + "' on the PLC.");
        }

        // The CRC32 (zlib's) of a file on this PC, the checksum the PLC gives
        // for its own files.
        public static uint Crc32(string file)
        {
            using (var stream = File.OpenRead(file)) return Crc32(stream);
        }

        public static uint Crc32(Stream stream)
        {
            var crc = 0xFFFFFFFFu;
            var buffer = new byte[65536];
            int read;
            while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
                for (var i = 0; i < read; i++)
                    crc = CrcTable[(crc ^ buffer[i]) & 0xFF] ^ (crc >> 8);
            return ~crc;
        }

        public static string Hex(uint crc)
        {
            return crc.ToString("x8", CultureInfo.InvariantCulture);
        }

        static readonly uint[] CrcTable = Enumerable.Range(0, 256).Select(n =>
        {
            var c = (uint)n;
            for (var k = 0; k < 8; k++) c = (c & 1) != 0 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
            return c;
        }).ToArray();

        static string Utc(DateTime time)
        {
            return time.ToString("yyyy-MM-ddTHH:mm:ss", CultureInfo.InvariantCulture) + "Z";
        }
    }
}
