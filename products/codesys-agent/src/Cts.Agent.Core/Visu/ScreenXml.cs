using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Xml;
using System.Xml.Linq;

namespace Cts.Visu
{
    // One member of a visu element: a scalar value, a colour with the style
    // name it follows, or a list (neither).
    internal sealed class ScreenMember
    {
        internal string Kind;
        internal string Value;
        internal string Color;
        internal string CanonicalName;
    }

    internal sealed class ScreenElement
    {
        internal int Index;
        internal string Type;
        internal string Identifier;
        internal XElement Source;
        internal SortedDictionary<long, ScreenMember> Members;

        // A geometry member's value, or null when the element has none.
        internal string Value(long id)
        {
            return Members.TryGetValue(id, out var member) ? member.Value : null;
        }
    }

    // A visualization screen as CODESYS exports it: its size and the
    // elements of its VisualElementList.
    internal static class ScreenXml
    {
        internal const long X = 1649127785;
        internal const long Y = 357335551;
        internal const long Width = 2422045748;
        internal const long Height = 2134141914;
        internal const long CenterX = 550940142;
        internal const long CenterY = 1473355128;
        internal const long Text = 390574330;
        internal const long TextId = 823443203;

        internal static XElement Parse(string text)
        {
            try
            {
                return XElement.Parse(text, LoadOptions.PreserveWhitespace | LoadOptions.SetLineInfo);
            }
            catch (XmlException error)
            {
                throw new VisuException("Could not parse screen XML: " + error.Message);
            }
        }

        internal static (int Width, int Height) Size(XElement root)
        {
            var width = Anywhere(root, "SizeX");
            var height = Anywhere(root, "SizeY");
            if (width == null || height == null) throw new VisuException("Screen file has no SizeX/SizeY");
            return (Number(width), Number(height));
        }

        // The elements in list order; the index counts every entry of the
        // list, as CODESYS numbers them.
        internal static List<ScreenElement> Elements(XElement root)
        {
            var elements = new List<ScreenElement>();
            var list = root.DescendantsAndSelf("List").FirstOrDefault(node => (string)node.Attribute("Name") == "VisualElementList");
            if (list == null) return elements;
            var index = 0;
            foreach (var entry in list.Elements())
            {
                if (entry.Name.LocalName == "Single")
                {
                    elements.Add(new ScreenElement
                    {
                        Index = index,
                        Type = NamedText(entry, "VisualElementTypeName"),
                        Identifier = NamedText(entry, "VisualElementIdentifier"),
                        Source = entry,
                        Members = Members(entry),
                    });
                }
                index++;
            }
            return elements;
        }

        internal static SortedDictionary<long, ScreenMember> Members(XElement element)
        {
            var members = new SortedDictionary<long, ScreenMember>();
            foreach (var member in MemberEntries(element))
            {
                var id = long.Parse(Named(member, "Single", "Id").Value.Trim(), CultureInfo.InvariantCulture);
                var scalar = Named(member, "Single", "Value");
                if (scalar != null)
                {
                    members[id] = new ScreenMember { Kind = "scalar", Value = scalar.Value };
                    continue;
                }
                var list = Named(member, "List", "Value");
                if (list == null) continue;
                var first = list.Elements().FirstOrDefault();
                var color = first == null ? null : Named(first, "Single", "Color");
                members[id] = color == null
                    ? new ScreenMember { Kind = "list" }
                    : new ScreenMember { Kind = "color", Color = color.Value.Trim(), CanonicalName = Named(first, "Single", "CanonicalName")?.Value ?? "" };
            }
            return members;
        }

        // The entries of the element's own member list that carry an id.
        internal static IEnumerable<XElement> MemberEntries(XElement element)
        {
            var list = MemberList(element);
            if (list == null) return Enumerable.Empty<XElement>();
            return list.Elements("Single").Where(member => !string.IsNullOrEmpty(Named(member, "Single", "Id")?.Value));
        }

        // <Single Name="VisualElemMemberList"><List Name="VisualElemMemberList">.
        internal static XElement MemberList(XElement element)
        {
            var holder = Named(element, "Single", "VisualElemMemberList");
            return holder == null ? null : Named(holder, "List", "VisualElemMemberList");
        }

        // The first direct child <tag Name="name">.
        internal static XElement Named(XElement parent, string tag, string name)
        {
            return parent.Elements(tag).FirstOrDefault(child => (string)child.Attribute("Name") == name);
        }

        internal static string NamedText(XElement parent, string name)
        {
            return Named(parent, "Single", name)?.Value.Trim() ?? "";
        }

        static XElement Anywhere(XElement root, string name)
        {
            return root.DescendantsAndSelf("Single").FirstOrDefault(node => (string)node.Attribute("Name") == name);
        }

        static int Number(XElement node)
        {
            if (!int.TryParse(node.Value.Trim(), out var value)) throw new VisuException("Screen file has no SizeX/SizeY");
            return value;
        }
    }
}
