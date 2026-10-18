using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;

namespace Cts.Cli
{
    // A CODESYS profile's toolbar file (*.opt.tbar, XML in the IDE's own
    // archive format) with one more button on the Standard toolbar: an item
    // naming the Script Command's GUID. The file is edited as text, keeping
    // its encoding, line ends and indentation.
    static class ToolbarFile
    {
        const string StandardToolbar = "{66f789cf-103c-4468-9061-8f9f2c328b4f}";
        const string ItemType = "{d7c09fff-b12f-47d8-bd4f-3d60b8672b7f}";
        static readonly Regex Single = new Regex(@"</?Single\b[^>]*>");

        // *file* with the button for *guid*, or null when it has it already or
        // cannot take it (*problem* then says why).
        internal static byte[] WithButton(byte[] file, string guid, string name, string description, out string problem)
        {
            problem = null;
            var encoding = Detect(file, out var bom);
            var text = encoding.GetString(file, bom, file.Length - bom);
            if (text.Contains(guid)) return null;
            var namePos = text.IndexOf("<Single Name=\"Name\" Type=\"string\">Standard</Single>", StringComparison.Ordinal);
            var start = namePos < 0 ? -1 : text.LastIndexOf("<Single Type=", namePos, StringComparison.Ordinal);
            var end = start < 0 ? -1 : BlockEnd(text, start);
            if (end < 0 || text.IndexOf(StandardToolbar, start, end - start, StringComparison.Ordinal) < 0)
            {
                problem = "no Standard toolbar";
                return null;
            }
            var items = text.IndexOf("<List Name=\"Items\"", start, end - start, StringComparison.Ordinal);
            var close = items < 0 ? -1 : text.IndexOf("</List>", items, end - items, StringComparison.Ordinal);
            if (close < 0)
            {
                problem = "no item list on the Standard toolbar";
                return null;
            }
            var lineStart = text.LastIndexOf('\n', close) + 1;
            var closeIndent = new string(text.Substring(lineStart, close - lineStart).TakeWhile(c => c == ' ' || c == '\t').ToArray());
            var step = closeIndent.Contains("\t") ? "\t" : "  ";
            var indent = closeIndent + step;
            var newline = text.Contains("\r\n") ? "\r\n" : "\n";
            var entry = indent + "<Single Type=\"" + ItemType + "\" Method=\"IArchivable\">" + newline
                + indent + step + "<Single Name=\"CommandGuid\" Type=\"System.Guid\">" + guid + "</Single>" + newline
                + indent + step + "<Single Name=\"InfoCache\" Type=\"string\">" + InfoCache(name, description) + "</Single>" + newline
                + indent + "</Single>" + newline;
            var preamble = new byte[bom];
            Array.Copy(file, preamble, bom);
            return preamble.Concat(encoding.GetBytes(text.Insert(lineStart, entry))).ToArray();
        }

        // The encoding of *file* by its byte order mark (none: UTF-8), and
        // the mark's length.
        static Encoding Detect(byte[] file, out int bom)
        {
            if (file.Length >= 2 && file[0] == 0xFF && file[1] == 0xFE) { bom = 2; return new UnicodeEncoding(false, false); }
            if (file.Length >= 2 && file[0] == 0xFE && file[1] == 0xFF) { bom = 2; return new UnicodeEncoding(true, false); }
            bom = file.Length >= 3 && file[0] == 0xEF && file[1] == 0xBB && file[2] == 0xBF ? 3 : 0;
            return new UTF8Encoding(false);
        }

        // The end of the <Single> element starting at *start*, or -1.
        static int BlockEnd(string text, int start)
        {
            var depth = 0;
            for (var match = Single.Match(text, start); match.Success; match = match.NextMatch())
            {
                if (match.Value.EndsWith("/>", StringComparison.Ordinal)) continue;
                depth += match.Value.StartsWith("</", StringComparison.Ordinal) ? -1 : 1;
                if (depth == 0) return match.Index + match.Length;
            }
            return -1;
        }

        // What CODESYS caches for a command button: its name and tooltip as
        // BinaryWriter strings between a fixed header and four zero bytes.
        internal static string InfoCache(string name, string description)
        {
            using (var stream = new MemoryStream())
            {
                using (var writer = new BinaryWriter(stream, new UTF8Encoding(false), true))
                {
                    writer.Write(new byte[] { 0x01, 0x00, 0x00, 0x00, 0x1d, 0x3e, 0xb7, 0x8e });
                    writer.Write(name);
                    writer.Write(description);
                    writer.Write(0);
                }
                return Convert.ToBase64String(stream.ToArray());
            }
        }
    }
}
