# -*- coding: utf-8 -*-
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "cds_text_sync", "engine"))

from cds_text_sync.engine.xml_helpers import split_st_projection_values, st_projection_content

ACCESSOR = """<Single Name="Object"><Single Name="Implementation"><Single Name="TextDocument"><Single Name="TextBlobForSerialisation" Type="string">{impl}</Single></Single></Single><Single Name="Interface"><Single Name="TextDocument"><Single Name="TextBlobForSerialisation" Type="string">{decl}</Single></Single></Single></Single>"""


def _entry(impl="", decl=""):
    return ET.fromstring(ACCESSOR.format(impl=impl, decl=decl))


def test_accessor_projection_is_declaration_first():
    content = st_projection_content(_entry(impl="Prop := fValue;"))
    assert content == "\n\n// === SECTION ===\n\nProp := fValue;\n"


def test_accessor_import_puts_code_into_implementation():
    entry = _entry()
    values = split_st_projection_values("\n\n// === SECTION ===\n\nProp := fValue;\n", entry)
    assert values == ["Prop := fValue;\n", ""]


def test_split_st_text_understands_section_marker():
    bridge = os.path.join(os.path.dirname(__file__), "..", "..", "products", "codesys-host", "src", "ide_bridge")
    sys.path.insert(0, bridge)
    from ide_st_text import split_st_text

    assert split_st_text("\n\n// === SECTION ===\n\nProp := fValue;\n") == ("", "Prop := fValue;")
    assert split_st_text("VAR x : INT; END_VAR\n\n// === SECTION ===\n\nx := 1;\n") == ("VAR x : INT; END_VAR", "x := 1;")


def test_new_property_reads_accessor_sidecars(tmp_path):
    bridge = os.path.join(os.path.dirname(__file__), "..", "..", "products", "codesys-host", "src", "ide_bridge")
    sys.path.insert(0, bridge)
    import ide_handlers_sync

    (tmp_path / "Fb.Prop2.st").write_text("PROPERTY Prop2 : INT", encoding="utf-8")
    (tmp_path / "Fb.Prop2.Get.st").write_text(
        "\n\n// === SECTION ===\n\nProp2 := 42;\n", encoding="utf-8"
    )
    result = ide_handlers_sync._read_accessor_sidecars(str(tmp_path / "Fb.Prop2.st"))
    assert result == {"Get": {"declaration": "", "implementation": "Prop2 := 42;"}}
