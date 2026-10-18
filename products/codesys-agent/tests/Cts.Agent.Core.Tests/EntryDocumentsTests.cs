using System;
using System.IO;
using System.Text;
using System.Xml.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    // objects.replace reads a disk .xml (one export entry) back into the two
    // documents ImportObject takes: the reverse of SnapshotFile.AsMember.
    public class EntryDocumentsTests
    {
        const string Meta = "<Single xml:space=\"preserve\" Type=\"{81297157-7ec9-45ce-845e-84cab2b88ade}\" Method=\"IArchivable\">\r\n"
            + "  <Single Name=\"Guid\" Type=\"System.Guid\">1b54da9c-93e4-48f0-b396-491e9d6c9567</Single>\r\n"
            + "  <Single Name=\"Name\" Type=\"string\">Visualization</Single>\r\n"
            + "</Single>";

        const string Obj = "<Single xml:space=\"preserve\" Type=\"{f18bec89-9fef-401d-9953-2f11739a6808}\" Method=\"IArchivable\">\r\n"
            + "  <Single Name=\"Text\" Type=\"string\">  first&#xD;\n  second\r\n third  </Single>\r\n"
            + "</Single>";

        static string Entry()
        {
            var writer = new StringWriter();
            SnapshotFile.Entry(writer, new SnapshotEntry
            {
                Meta = Meta, Object = Obj, ParentSvNode = Guid.NewGuid(), Path = new[] { "PLC" }, Index = 3,
            });
            return "<?xml version='1.0' encoding='utf-8'?>\n" + writer;
        }

        static XElement Root(byte[] document)
        {
            return XDocument.Parse(Encoding.UTF8.GetString(document), LoadOptions.PreserveWhitespace).Root;
        }

        [Fact]
        public void EachMemberBecomesADocumentRootAgainWithItsSpaceAttributeAndWithoutItsName()
        {
            var documents = EntryDocuments.Parse(Entry());

            var meta = Root(documents.Meta);
            Assert.Null(meta.Attribute("Name"));
            Assert.Equal("preserve", meta.Attribute(XNamespace.Xml + "space").Value);
            Assert.Equal("{81297157-7ec9-45ce-845e-84cab2b88ade}", meta.Attribute("Type").Value);
            Assert.Equal(new Guid("1b54da9c-93e4-48f0-b396-491e9d6c9567"), documents.Guid);

            var obj = Root(documents.Object);
            Assert.Null(obj.Attribute("Name"));
            Assert.Equal("{f18bec89-9fef-401d-9953-2f11739a6808}", obj.Attribute("Type").Value);
        }

        [Fact]
        public void AValueKeepsItsEscapedCarriageReturnAndALineBreakIsALineFeed()
        {
            var obj = Root(EntryDocuments.Parse(Entry()).Object);
            Assert.Equal("  first\r\n  second\n third  ", (string)obj.Element("Single"));
        }

        [Fact]
        public void ADocumentHasNoByteOrderMark()
        {
            var documents = EntryDocuments.Parse("﻿" + Entry());
            Assert.NotEqual(0xEF, documents.Meta[0]);
            Assert.NotEqual(0xEF, documents.Object[0]);
        }

        [Fact]
        public void AnEntryWithoutBothMembersOrAGuidIsRefused()
        {
            Assert.Throws<ProtocolException>(() => EntryDocuments.Parse(""));
            Assert.Throws<ProtocolException>(() => EntryDocuments.Parse("not xml"));
            Assert.Throws<ProtocolException>(() => EntryDocuments.Parse(Entry().Replace("Name=\"Object\"", "Name=\"Other\"")));
            Assert.Throws<ProtocolException>(() => EntryDocuments.Parse(
                Entry().Replace("1b54da9c-93e4-48f0-b396-491e9d6c9567", "00000000-0000-0000-0000-000000000000")));
        }
    }
}
