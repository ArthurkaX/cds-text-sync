using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Xml;

namespace Cts.Sync
{
    // A three-way merge of one object's view XML by element, not by line: a
    // task's settings value by value, its program calls and a Library
    // Manager's libraries as lists of named items.  Two sides that add a
    // program to the same task, or a library each, both keep theirs.
    //
    // The view writes each element on lines of its own, so an element is a
    // run of lines: its start tag, its children, its end tag.  The merge
    // keeps the lines as the sides wrote them and only chooses and orders
    // them, so the result is in the view's own form.
    internal static class XmlMerge
    {
        // Merged text, or null with *conflict* saying why: the element both
        // sides changed differently.
        internal static string Merge(string baseline, string ours, string theirs, out string conflict)
        {
            conflict = null;
            if (ours == theirs || baseline == theirs) return ours;
            if (baseline == ours) return theirs;
            var b = Parse(baseline);
            var o = Parse(ours);
            var t = Parse(theirs);
            if (b == null || o == null || t == null)
            {
                conflict = "a side is not XML in the view's form";
                return null;
            }
            var lines = new List<string>();
            var failure = Node(b, o, t, "", lines);
            if (failure != null)
            {
                conflict = "both sides changed " + failure + " differently";
                return null;
            }
            return string.Join("\n", lines);
        }

        // The same for files: UTF-8, with or without a byte order mark,
        // CRLF or LF; the merge comes back in *ours*' form.  Null with
        // *conflict* when it cannot be merged.
        internal static byte[] Merge(byte[] baseline, byte[] ours, byte[] theirs, out string conflict)
        {
            var strict = new UTF8Encoding(false, true);
            string Text(byte[] bytes) => strict.GetString(bytes).TrimStart('\uFEFF').Replace("\r\n", "\n");
            string merged;
            try { merged = Merge(Text(baseline), Text(ours), Text(theirs), out conflict); }
            catch (DecoderFallbackException)
            {
                conflict = "a side is not UTF-8 text";
                return null;
            }
            if (merged == null) return null;
            var oursText = strict.GetString(ours);
            if (oursText.Contains("\r\n")) merged = merged.Replace("\n", "\r\n");
            if (oursText.StartsWith("\uFEFF", StringComparison.Ordinal)) merged = "\uFEFF" + merged;
            return strict.GetBytes(merged);
        }

        sealed class Block
        {
            internal string Tag;
            internal string Name;
            internal string Value;
            internal string Key;
            internal int Start;
            internal int End;
            internal string[] Head;
            internal string[] Tail;
            // Null for an element merged whole: a leaf, or one whose
            // children cannot be told apart or do not each own their lines.
            internal List<Block> Children;
            internal string Text;
        }

        static string Join(IEnumerable<string> lines) => string.Join("\n", lines);

        // The whole text as a block with the root element its child: the
        // lines before it (the declaration) its head, the ones after its tail.
        static Block Parse(string text)
        {
            var lines = text.Split('\n');
            var frames = new Stack<Frame>();
            var document = new Frame { Start = 0 };
            frames.Push(document);
            try
            {
                var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null };
                using (var reader = XmlReader.Create(new StringReader(text.TrimStart('\uFEFF')), settings))
                {
                    var info = (IXmlLineInfo)reader;
                    while (reader.Read())
                    {
                        if (reader.NodeType == XmlNodeType.Element)
                        {
                            var frame = new Frame { Tag = reader.Name, Name = reader.GetAttribute("Name"), Start = info.LineNumber - 1 };
                            if (reader.IsEmptyElement) frames.Peek().Children.Add(frame.Close(lines, frame.Start));
                            else frames.Push(frame);
                        }
                        else if (reader.NodeType == XmlNodeType.EndElement)
                        {
                            var frame = frames.Pop();
                            frames.Peek().Children.Add(frame.Close(lines, info.LineNumber - 1));
                        }
                        else if (reader.NodeType == XmlNodeType.Text || reader.NodeType == XmlNodeType.CDATA)
                        {
                            frames.Peek().Value = (frames.Peek().Value ?? "") + reader.Value;
                        }
                    }
                }
            }
            catch (XmlException)
            {
                return null;
            }
            return frames.Count == 1 ? document.Close(lines, lines.Length - 1, true) : null;
        }

        sealed class Frame
        {
            internal string Tag;
            internal string Name;
            internal string Value;
            internal int Start;
            internal readonly List<Block> Children = new List<Block>();

            internal Block Close(string[] lines, int end, bool document = false)
            {
                var block = new Block { Tag = Tag, Name = Name, Value = Value, Start = Start, End = end, Text = Join(lines.Skip(Start).Take(end - Start + 1)) };
                if (Children.Count == 0)
                {
                    block.Head = lines.Skip(Start).Take(end - Start + 1).ToArray();
                    block.Tail = new string[0];
                    return block;
                }
                // Each child owns whole lines, one after another, between the
                // start tag's lines and the end tag's (the document: the lines
                // before and after the root).
                var first = Children[0].Start;
                var last = Children[Children.Count - 1].End;
                var contiguous = (document ? first >= Start : first > Start) && (document ? last <= end : last < end);
                for (var i = 1; i < Children.Count && contiguous; i++) contiguous = Children[i].Start == Children[i - 1].End + 1;
                if (contiguous)
                {
                    block.Head = lines.Skip(Start).Take(first - Start).ToArray();
                    block.Tail = lines.Skip(last + 1).Take(end - last).ToArray();
                    block.Children = Children;
                    foreach (var child in Children) child.Key = KeyOf(child);
                    if (Children.Select(child => child.Key).Distinct(StringComparer.Ordinal).Count() != Children.Count) block.Children = null;
                }
                if (block.Children == null)
                {
                    block.Head = lines.Skip(Start).Take(end - Start + 1).ToArray();
                    block.Tail = new string[0];
                }
                return block;
            }
        }

        // A child's identity among its siblings: its Name attribute; a
        // dictionary entry's key; a list item's naming field (a library's
        // placeholder or namespace, a program call's name); else its tag,
        // which leaves a parent of two such children merged whole: by
        // position or by text, an edit would read as a removal and an addition.
        static readonly string[] Naming = { "PlaceholderName", "Namespace", "Name", "Guid" };

        static string KeyOf(Block block)
        {
            if (block.Name != null) return block.Tag + "@" + block.Name;
            if (block.Children == null) return block.Tag;
            if (block.Tag == "Entry")
            {
                var key = block.Children.FirstOrDefault(child => child.Tag == "Key");
                if (key != null) return "Entry:" + key.Text.Trim();
            }
            foreach (var field in Naming)
            {
                var named = block.Children.FirstOrDefault(child => child.Name == field && child.Children == null && child.Value != null);
                if (named != null) return block.Tag + ":" + field + "=" + named.Value;
            }
            return block.Tag;
        }

        // Appends the merge of one element to *lines*; the place both sides
        // changed differently, or null.
        static string Node(Block b, Block o, Block t, string at, List<string> lines)
        {
            if (o.Text == t.Text || b != null && b.Text == t.Text)
            {
                lines.Add(o.Text);
                return null;
            }
            if (b != null && b.Text == o.Text)
            {
                lines.Add(t.Text);
                return null;
            }
            // The document and its root element name no place.
            var here = o.Key == null ? "" : at.Length == 0 ? "/" : at + Label(o) + "/";
            if (b == null || b.Children == null || o.Children == null || t.Children == null) return Place(here);
            var head = Pick(b.Head, o.Head, t.Head);
            var tail = Pick(b.Tail, o.Tail, t.Tail);
            if (head == null || tail == null) return Place(here);
            var children = new List<string>();
            var failure = Children(b, o, t, here, children);
            if (failure != null) return failure;
            lines.AddRange(head);
            lines.AddRange(children);
            lines.AddRange(tail);
            return null;
        }

        static string Place(string here) => here.Trim('/').Length == 0 ? "the whole file" : here.Trim('/');

        static string[] Pick(string[] b, string[] o, string[] t) => o.SequenceEqual(t) || b.SequenceEqual(t) ? o : b.SequenceEqual(o) ? t : null;

        static string Children(Block b, Block o, Block t, string here, List<string> lines)
        {
            var bk = b.Children.ToDictionary(child => child.Key, StringComparer.Ordinal);
            var ok = o.Children.ToDictionary(child => child.Key, StringComparer.Ordinal);
            var tk = t.Children.ToDictionary(child => child.Key, StringComparer.Ordinal);
            foreach (var key in bk.Keys)
            {
                var inO = ok.ContainsKey(key);
                var inT = tk.ContainsKey(key);
                if (!inO && inT && tk[key].Text != bk[key].Text) return Place(here + Label(bk[key]));
                if (inO && !inT && ok[key].Text != bk[key].Text) return Place(here + Label(bk[key]));
            }
            var kept = new HashSet<string>(bk.Keys.Where(key => ok.ContainsKey(key) && tk.ContainsKey(key)), StringComparer.Ordinal);
            var baseOrder = b.Children.Select(child => child.Key).Where(kept.Contains).ToList();
            var oursOrder = o.Children.Select(child => child.Key).Where(kept.Contains).ToList();
            var theirsOrder = t.Children.Select(child => child.Key).Where(kept.Contains).ToList();
            Block primary, secondary;
            if (oursOrder.SequenceEqual(baseOrder) && !theirsOrder.SequenceEqual(baseOrder)) { primary = t; secondary = o; }
            else if (theirsOrder.SequenceEqual(baseOrder) || oursOrder.SequenceEqual(theirsOrder)) { primary = o; secondary = t; }
            else return Place(here + "order");
            var order = primary.Children.Select(child => child.Key).Where(key => !bk.ContainsKey(key) || kept.Contains(key)).ToList();
            var secondaryKeys = new HashSet<string>(secondary.Children.Select(child => child.Key), StringComparer.Ordinal);
            var previous = -1;
            foreach (var key in secondary.Children.Select(child => child.Key))
            {
                var placed = order.IndexOf(key);
                if (placed >= 0)
                {
                    previous = placed;
                    continue;
                }
                if (bk.ContainsKey(key)) continue;
                // After its predecessor and after what the other side added there.
                var at = previous + 1;
                while (at < order.Count && !bk.ContainsKey(order[at]) && !secondaryKeys.Contains(order[at])) at++;
                order.Insert(at, key);
                previous = at;
            }
            foreach (var key in order)
            {
                bk.TryGetValue(key, out var baseChild);
                var hasO = ok.TryGetValue(key, out var oursChild);
                var hasT = tk.TryGetValue(key, out var theirsChild);
                if (hasO && hasT)
                {
                    var failure = Node(baseChild, oursChild, theirsChild, here, lines);
                    if (failure != null) return failure;
                }
                else lines.Add((hasO ? oursChild : theirsChild).Text);
            }
            return null;
        }

        static string Label(Block block) => block.Name ?? (block.Key.Contains("=") ? block.Key.Substring(block.Key.IndexOf('=') + 1).Trim() : block.Tag);
    }
}
