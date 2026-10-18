// The <ExportFile> that `project.export` writes, in the shape export_native
// writes it, so the engine reads it unchanged:
//
//   <ExportFile>
//     <StructuredView Guid="{sv}">
//   <Single xml:space="preserve" Type="{3daac5e4-...}" Method="IArchivable">
//     <Null Name="Profile" />
//     <List2 Name="EntryList">
//       <Single Type="{6198ad31-...}" Method="IArchivable">   one entry
//         IsRoot, MetaObject, Object, ParentSVNodeGuid, Path, Index
//     </List2>
//     <Null Name="ProfileName" />
//   </Single>  </StructuredView>
//   </ExportFile>
//
// MetaObject and Object are the two documents IObjectManager2.ExportObject
// writes for one object; each is its own document there, so its root element
// is renamed into the entry here.  Written as a stream: a large project's
// snapshot is ~100 MB and the IDE is a 32-bit process.
using System;
using System.IO;
using System.Security;
using System.Text;

namespace Cts.Agent
{
    public sealed class SnapshotEntry
    {
        public bool IsRoot { get; set; }
        public string Meta { get; set; }
        public string Object { get; set; }
        public Guid ParentSvNode { get; set; }
        public string[] Path { get; set; }
        public int Index { get; set; }
    }

    public static class SnapshotFile
    {
        const string ViewType = "{3daac5e4-660e-42e4-9cea-3711b98bfb63}";
        const string EntryType = "{6198ad31-4b98-445c-927f-3258a0e82fe3}";

        public static void Begin(TextWriter w)
        {
            w.Write("<ExportFile>\n");
        }

        public static void BeginView(TextWriter w, Guid view)
        {
            w.Write("  <StructuredView Guid=\"{" + view.ToString("D") + "}\">\n");
            w.Write("<Single xml:space=\"preserve\" Type=\"" + ViewType + "\" Method=\"IArchivable\">\n");
            w.Write("  <Null Name=\"Profile\" />\n  <List2 Name=\"EntryList\">\n");
        }

        public static void Entry(TextWriter w, SnapshotEntry e)
        {
            w.Write("    <Single Type=\"" + EntryType + "\" Method=\"IArchivable\">\n");
            w.Write("      <Single Name=\"IsRoot\" Type=\"bool\">" + (e.IsRoot ? "True" : "False") + "</Single>\n");
            w.Write(AsMember(e.Meta, "MetaObject"));
            w.Write("\n");
            w.Write(AsMember(e.Object, "Object"));
            w.Write("\n");
            w.Write("      <Single Name=\"ParentSVNodeGuid\" Type=\"System.Guid\">" + e.ParentSvNode.ToString("D") + "</Single>\n");
            var path = e.Path ?? new string[0];
            if (path.Length == 0)
                w.Write("      <Array Name=\"Path\" Type=\"string\" />\n");
            else
            {
                w.Write("      <Array Name=\"Path\" Type=\"string\">\n");
                foreach (var step in path)
                    w.Write("        <Single Type=\"string\">" + SecurityElement.Escape(step ?? "") + "</Single>\n");
                w.Write("      </Array>\n");
            }
            w.Write("      <Single Name=\"Index\" Type=\"int\">" + e.Index + "</Single>\n");
            w.Write("    </Single>\n");
        }

        public static void EndView(TextWriter w)
        {
            w.Write("  </List2>\n  <Null Name=\"ProfileName\" />\n</Single>  </StructuredView>\n");
        }

        public static void End(TextWriter w)
        {
            w.Write("</ExportFile>\n");
        }

        // One ExportObject document as a named member of an entry: its XML
        // declaration (and BOM) dropped and its root element -- which carries
        // xml:space="preserve" as a document of its own -- given the member's
        // Name instead; the view's Single above already preserves whitespace.
        public static string AsMember(string document, string name)
        {
            if (document == null) throw new ProtocolException(ErrorCodes.Internal, "ExportObject wrote no " + name + " document");
            var text = document.TrimStart('﻿');
            var start = 0;
            if (text.StartsWith("<?xml", StringComparison.Ordinal))
            {
                var end = text.IndexOf("?>", StringComparison.Ordinal);
                if (end < 0) throw new ProtocolException(ErrorCodes.Internal, name + " document has an unclosed declaration");
                start = end + 2;
            }
            var open = text.IndexOf('<', start);
            var close = open < 0 ? -1 : text.IndexOf('>', open);
            if (open < 0 || close < 0) throw new ProtocolException(ErrorCodes.Internal, name + " document has no root element");
            var tag = text.Substring(open, close - open);
            var space = tag.IndexOf(" xml:space=\"preserve\"", StringComparison.Ordinal);
            var named = space >= 0
                ? tag.Substring(0, space) + " Name=\"" + name + "\"" + tag.Substring(space + " xml:space=\"preserve\"".Length)
                : InsertName(tag, name);
            return MemberIndent + Indent(named + text.Substring(close).TrimEnd(), MemberIndent);
        }

        // An entry's members sit three levels deep in the file.
        const string MemberIndent = "      ";

        // The document's own formatting moved to the member's depth, the way
        // export_native indents it: a newline right after a tag's '>' and
        // followed by spaces and a '<' gets the pad.  A newline inside a text
        // value (a device description, say) is part of the value and is left
        // alone -- XmlWriter writes '>' in text as &gt;, so a '>' before a
        // newline always ends a tag -- and so is <X>\n  </X>, an element whose
        // whole value is that whitespace.
        public static string Indent(string document, string pad)
        {
            var result = new StringBuilder(document.Length + document.Length / 4);
            var tagStart = -1;
            var lastTagOpens = false;
            for (var i = 0; i < document.Length; i++)
            {
                var c = document[i];
                result.Append(c);
                if (c == '<') tagStart = i;
                else if (c == '>' && tagStart >= 0)
                {
                    var kind = document[tagStart + 1];
                    lastTagOpens = kind != '/' && kind != '?' && kind != '!' && document[i - 1] != '/';
                }
                else if (c == '\n' && EndsTag(document, i))
                {
                    var next = i + 1;
                    while (next < document.Length && document[next] == ' ') next++;
                    if (next < document.Length && document[next] == '<'
                        && !(lastTagOpens && next + 1 < document.Length && document[next + 1] == '/'))
                        result.Append(pad);
                }
            }
            return result.ToString();
        }

        static bool EndsTag(string document, int newline)
        {
            var before = newline - 1;
            if (before >= 0 && document[before] == '\r') before--;
            return before >= 0 && document[before] == '>';
        }

        static string InsertName(string tag, string name)
        {
            var space = tag.IndexOf(' ');
            return space < 0 ? tag + " Name=\"" + name + "\"" : tag.Substring(0, space) + " Name=\"" + name + "\"" + tag.Substring(space);
        }

        // A document ExportObject wrote into a stream, as text.
        public static string Text(byte[] bytes)
        {
            return bytes == null ? null : new UTF8Encoding(false).GetString(bytes);
        }
    }
}
