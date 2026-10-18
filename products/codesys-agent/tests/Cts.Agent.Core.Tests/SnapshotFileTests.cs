using System;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    // project.export's file must be the shape export_native writes, since the
    // engine's snapshot reader parses it unchanged.
    public class SnapshotFileTests
    {
        const string Meta = "﻿<?xml version=\"1.0\" encoding=\"utf-8\"?>\r\n"
            + "<Single xml:space=\"preserve\" Type=\"{81297157-7ec9-45ce-845e-84cab2b88ade}\" Method=\"IArchivable\">\r\n"
            + "  <Single Name=\"Guid\" Type=\"System.Guid\">32d92914-bcb4-4227-b529-32fd90910eca</Single>\r\n"
            + "  <Single Name=\"Name\" Type=\"string\">MAIN</Single>\r\n"
            + "</Single>\r\n";

        const string Obj = "<Single xml:space=\"preserve\" Type=\"{6f9dac99-8de1-4efc-8465-68ac443b7d08}\" Method=\"IArchivable\">"
            + "<Single Name=\"Text\" Type=\"string\">  x := 1;  </Single></Single>";

        [Fact]
        public void AMemberTakesTheNameInsteadOfItsOwnSpaceAttributeAndLosesItsDeclaration()
        {
            var member = SnapshotFile.AsMember(Meta, "MetaObject");
            Assert.StartsWith("      <Single Name=\"MetaObject\" Type=\"{81297157", member);
            Assert.DoesNotContain("<?xml", member);
            Assert.DoesNotContain("xml:space", member);
            Assert.EndsWith("</Single>", member);
        }

        [Fact]
        public void TheMembersFormattingMovesToTheEntryDepthButItsTextDoesNot()
        {
            var document = "<Single xml:space=\"preserve\" Type=\"t\">\r\n"
                + "  <Single Name=\"Description\" Type=\"string\">first\r\n  second</Single>\r\n"
                + "  <Single Name=\"Blank\" Type=\"string\">\r\n  </Single>\r\n"
                + "  <Array Name=\"A\">\r\n    <Single Type=\"string\">x</Single>\r\n  </Array>\r\n"
                + "</Single>";

            var member = SnapshotFile.AsMember(document, "Object");

            Assert.Equal("      <Single Name=\"Object\" Type=\"t\">\r\n"
                + "        <Single Name=\"Description\" Type=\"string\">first\r\n  second</Single>\r\n"
                + "        <Single Name=\"Blank\" Type=\"string\">\r\n  </Single>\r\n"
                + "        <Array Name=\"A\">\r\n          <Single Type=\"string\">x</Single>\r\n        </Array>\r\n"
                + "      </Single>", member);
        }

        [Fact]
        public void ARootWithoutASpaceAttributeStillGetsTheName()
        {
            Assert.Equal("      <Single Name=\"Object\" Type=\"t\"/>", SnapshotFile.AsMember("<Single Type=\"t\"/>", "Object"));
            Assert.Throws<ProtocolException>(() => SnapshotFile.AsMember("no xml", "Object"));
            Assert.Throws<ProtocolException>(() => SnapshotFile.AsMember(null, "Object"));
        }

        [Fact]
        public void AFileIsViewsOfEntriesWithTheirPlacement()
        {
            var w = new StringWriter();
            SnapshotFile.Begin(w);
            SnapshotFile.BeginView(w, new Guid("d9b2b2cc-ea99-4c3b-aa42-1e5c49e65b84"));
            SnapshotFile.Entry(w, new SnapshotEntry
            {
                IsRoot = false, Meta = Meta, Object = Obj,
                ParentSvNode = new Guid("1e5b3f5c-0000-0000-0000-000000000000"),
                Path = new[] { "PLC_Stabur", "PLC Logic", "A & B" }, Index = -1,
            });
            SnapshotFile.EndView(w);
            SnapshotFile.End(w);

            var root = XDocument.Parse(w.ToString(), LoadOptions.PreserveWhitespace).Root;
            var view = root.Element("StructuredView");
            Assert.Equal("{d9b2b2cc-ea99-4c3b-aa42-1e5c49e65b84}", view.Attribute("Guid").Value);
            var entry = view.Element("Single").Element("List2").Element("Single");
            var names = entry.Elements().Select(e => (string)e.Attribute("Name")).ToArray();
            Assert.Equal(new[] { "IsRoot", "MetaObject", "Object", "ParentSVNodeGuid", "Path", "Index" }, names);
            Assert.Equal(new[] { "PLC_Stabur", "PLC Logic", "A & B" },
                entry.Elements().First(e => (string)e.Attribute("Name") == "Path").Elements().Select(e => e.Value).ToArray());
            // The text inside an object keeps its own whitespace.
            Assert.Contains("  x := 1;  ", entry.Elements().First(e => (string)e.Attribute("Name") == "Object").Value);
        }

        [Fact]
        public void ARootEntryHasAnEmptyPath()
        {
            var w = new StringWriter();
            SnapshotFile.Entry(w, new SnapshotEntry { IsRoot = true, Meta = Meta, Object = Obj, Index = -1 });
            Assert.Contains("<Single Name=\"IsRoot\" Type=\"bool\">True</Single>", w.ToString());
            Assert.Contains("<Array Name=\"Path\" Type=\"string\" />", w.ToString());
            Assert.Contains("00000000-0000-0000-0000-000000000000", w.ToString());
        }
    }
}
