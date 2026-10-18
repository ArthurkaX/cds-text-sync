// The disk `.xml` of a non-text object is one export entry -- IsRoot,
// MetaObject, Object, ParentSVNodeGuid, Path, Index -- and `objects.replace`
// (or `objects.import`, for a new object) reads it through IObjectManager2.ImportObject, which reads the
// MetaObject and the Object as two documents of their own: the reverse of
// SnapshotFile.AsMember.  Each member becomes a document root again (its Name
// dropped, xml:space="preserve" back on it); the whitespace between elements is
// left as it is, the archive reader skips it the same way it does in the
// IDE's own export.  A line break in the file is a "\n" once parsed, as XML
// has it; a carriage return inside a value is only kept when the file
// escapes it (&#xD;), and it is written back escaped, never as a bare CR.
//
//   objects.replace {"guid", "xml": "<the entry file's text>"}
//   objects.import  {"parent_guid", "xml"}  ->  {"guid", "type_guid", "parent_guid", "path"}
//   objects.export  {"guids": [...]}  ->  {"objects": [{"guid", "meta", "object"}]}
using System;
using System.IO;
using System.Text;
using System.Xml;

namespace Cts.Agent
{
    public sealed class EntryDocuments
    {
        public byte[] Meta { get; private set; }
        public byte[] Object { get; private set; }
        public Guid Guid { get; private set; }

        public static EntryDocuments Parse(string entry)
        {
            if (string.IsNullOrEmpty(entry)) throw new ProtocolException(ErrorCodes.BadParams, "xml is required");
            var document = new XmlDocument { PreserveWhitespace = true, XmlResolver = null };
            var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null };
            try
            {
                using (var reader = XmlReader.Create(new StringReader(entry.TrimStart('﻿')), settings))
                    document.Load(reader);
            }
            catch (XmlException e) { throw new ProtocolException(ErrorCodes.BadParams, "xml does not parse: " + e.Message); }
            var root = document.DocumentElement;
            var meta = Member(root, "MetaObject");
            var guidText = MemberText(meta, "Guid");
            Guid guid;
            if (!Guid.TryParse(guidText ?? "", out guid) || guid == Guid.Empty)
                throw new ProtocolException(ErrorCodes.BadParams, "the entry's MetaObject has no Guid");
            return new EntryDocuments
            {
                Meta = AsDocument(meta),
                Object = AsDocument(Member(root, "Object")),
                Guid = guid,
            };
        }

        static XmlElement Member(XmlElement root, string name)
        {
            if (root != null)
                foreach (XmlNode child in root.ChildNodes)
                {
                    var element = child as XmlElement;
                    if (element != null && element.GetAttribute("Name") == name) return element;
                }
            throw new ProtocolException(ErrorCodes.BadParams, "the entry has no " + name);
        }

        static string MemberText(XmlElement parent, string name)
        {
            foreach (XmlNode child in parent.ChildNodes)
            {
                var element = child as XmlElement;
                if (element != null && element.GetAttribute("Name") == name) return element.InnerText.Trim();
            }
            return null;
        }

        static byte[] AsDocument(XmlElement member)
        {
            var document = new XmlDocument { PreserveWhitespace = true };
            var root = (XmlElement)document.ImportNode(member, true);
            root.RemoveAttribute("Name");
            var space = document.CreateAttribute("xml", "space", "http://www.w3.org/XML/1998/namespace");
            space.Value = "preserve";
            root.Attributes.Prepend(space);
            document.AppendChild(root);
            var settings = new XmlWriterSettings { Encoding = new UTF8Encoding(false), Indent = false, NewLineHandling = NewLineHandling.Entitize };
            using (var stream = new MemoryStream())
            {
                using (var writer = XmlWriter.Create(stream, settings)) document.Save(writer);
                return stream.ToArray();
            }
        }
    }
}
