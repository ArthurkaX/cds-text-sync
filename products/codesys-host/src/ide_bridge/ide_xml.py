# -*- coding: utf-8 -*-
"""
ide_xml.py - XML parsing that works on every CODESYS IronPython.
Must be compatible with IronPython 2.7.

Some CODESYS releases (e.g. 3.5.17) ship an IronPython without pyexpat, so
ElementTree falls back to xmllib, which rejects every character outside
Latin-1 ("Syntax error at line N: illegal character in content"). Under
IronPython the file is therefore read with .NET's XmlReader and fed into an
ElementTree TreeBuilder, giving the same tree ET.parse would.
"""
from __future__ import print_function

import sys
import xml.etree.ElementTree as ET

_XMLNS_URI = "http://www.w3.org/2000/xmlns/"


def parse_xml_file(path):
    """Return an ElementTree for the XML file at path."""
    if sys.platform == "cli":
        return _parse_with_dotnet(path)
    return ET.parse(path)


def _qualified(namespace, local_name):
    if namespace:
        return "{" + namespace + "}" + local_name
    return local_name


def _parse_with_dotnet(path):
    import clr

    clr.AddReference("System.Xml")
    from System.Xml import DtdProcessing, XmlNodeType, XmlReader, XmlReaderSettings

    settings = XmlReaderSettings()
    settings.DtdProcessing = DtdProcessing.Ignore
    settings.IgnoreComments = True
    settings.IgnoreProcessingInstructions = True
    settings.IgnoreWhitespace = False
    text_types = (
        XmlNodeType.Text,
        XmlNodeType.CDATA,
        XmlNodeType.Whitespace,
        XmlNodeType.SignificantWhitespace,
    )

    builder = ET.TreeBuilder()
    reader = XmlReader.Create(path, settings)
    try:
        while reader.Read():
            node_type = reader.NodeType
            if node_type == XmlNodeType.Element:
                tag = _qualified(reader.NamespaceURI, reader.LocalName)
                is_empty = reader.IsEmptyElement
                attrs = {}
                if reader.MoveToFirstAttribute():
                    while True:
                        if reader.NamespaceURI != _XMLNS_URI:
                            name = _qualified(reader.NamespaceURI, reader.LocalName)
                            attrs[name] = reader.Value
                        if not reader.MoveToNextAttribute():
                            break
                    reader.MoveToElement()
                builder.start(tag, attrs)
                if is_empty:
                    builder.end(tag)
            elif node_type == XmlNodeType.EndElement:
                builder.end(_qualified(reader.NamespaceURI, reader.LocalName))
            elif node_type in text_types:
                builder.data(reader.Value)
    except Exception as error:
        raise ET.ParseError("{0}: {1}".format(path, error))
    finally:
        reader.Close()
    return ET.ElementTree(builder.close())
