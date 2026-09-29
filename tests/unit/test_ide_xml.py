# -*- coding: utf-8 -*-
"""test_ide_xml.py — parse_xml_file keeps non-Latin-1 text intact."""

import os
import sys
import xml.etree.ElementTree as ET

_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

from ide_xml import parse_xml_file  # noqa: E402


def test_cyrillic_comment_round_trips(tmp_path):
    text = "PROGRAM PLC_PRG\n// Комментарий: ёж\nVAR\nEND_VAR\n"
    root = ET.Element("Root")
    ET.SubElement(root, "Single", {"Name": "Имя"}).text = text
    path = tmp_path / "IMPORT.xml"
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)

    parsed = parse_xml_file(str(path)).getroot()

    assert parsed.find("Single").text == text
    assert parsed.find("Single").get("Name") == "Имя"
