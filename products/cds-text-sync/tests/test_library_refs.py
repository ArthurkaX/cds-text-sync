# -*- coding: utf-8 -*-
"""Reading library references out of an exported Library Manager.

A Library Manager export carries two kinds of library entry, and both are real
project references:

* placeholder items (type ``4723ebe7-...``): the project names a library and a
  default version and CODESYS resolves it against the machine;
* concrete items (type ``51a11660...``): the project pins a library directly,
  carrying ``Name``/``Resolution`` instead of ``PlaceholderName``/
  ``DefaultResolution``.

Both are real references; reading only the placeholder ones leaves a pinned
library out of the report.

On top of the items sits the ``PlaceholderRedirectionTable``, which points a
placeholder at the version actually used. ``Standard`` is reached only that
way - it has no ``Items`` entry at all - so ignoring the table reports a
referenced library as "not referenced".
"""

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENGINE = _PROJECT_ROOT / "products" / "cds-text-sync" / "src"
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

from cds_text_sync.engine import library_refs  # noqa: E402

LIBRARY_MANAGER_GUID = library_refs.LIBRARY_MANAGER_TYPE_GUID
PLACEHOLDER_GUID = library_refs.PLACEHOLDER_ITEM_TYPE_GUID
CONCRETE_GUID = library_refs.CONCRETE_ITEM_TYPE_GUID_PREFIX + "-2362-4f77-9ad0-7f11f8a5b001"


def _single(name, value):
    return '          <Single Name="{0}" Type="string">{1}</Single>'.format(name, value)


def _placeholder_item(name, version, vendor, namespace, system="False"):
    resolution = "{0}, {1} ({2})".format(name, version, vendor)
    return "\n".join(
        [
            '        <Single Type="{%s}" Method="IArchivable">' % PLACEHOLDER_GUID,
            _single("DefaultResolution", resolution),
            _single("PlaceholderName", name),
            _single("Namespace", namespace),
            _single("SystemLibrary", system),
            "        </Single>",
        ]
    )


def _concrete_item(name, version, vendor, namespace, system="False"):
    return "\n".join(
        [
            '        <Single Type="{%s}" Method="IArchivable">' % CONCRETE_GUID,
            _single("Name", name),
            _single("Resolution", "{0}, {1} ({2})".format(name, version, vendor)),
            _single("Namespace", namespace),
            _single("SystemLibrary", system),
            "        </Single>",
        ]
    )


def _redirection_table(entries):
    rows = "\n".join(
        '          <Single Name="{0}" Type="string">{1}</Single>'.format(key, value)
        for key, value in entries
    )
    return (
        '      <Dictionary Name="PlaceholderRedirectionTable"'
        ' Type="System.Collections.Hashtable">\n'
        + rows
        + "\n      </Dictionary>"
    )


def _library_manager_xml(items, redirections=()):
    body = "\n".join(items)
    if redirections:
        body += "\n" + _redirection_table(redirections)
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<Single Type="{6198ad31-4b98-445c-927f-3258a0e82fe3}" Method="IArchivable">\n'
        '  <Single Name="Object" Type="{%s}" Method="IArchivable">\n' % LIBRARY_MANAGER_GUID
        + '    <List Name="Items" Type="System.Collections.ArrayList">\n'
        + body
        + "\n    </List>\n  </Single>\n</Single>\n"
    )


@pytest.fixture
def project_view(tmp_path):
    """A project view with one Library Manager carrying both entry kinds."""

    def _write(items, redirections=()):
        view = tmp_path / "project-view"
        view.mkdir(exist_ok=True)
        (view / "Library Manager.xml").write_text(
            _library_manager_xml(items, redirections), encoding="utf-8"
        )
        return view

    return _write


def _by_name(references):
    return {ref["name"]: ref for ref in references}


def test_concrete_references_are_read_alongside_placeholders(project_view):
    view = project_view(
        [
            _placeholder_item("IoStandard", "*", "CODESYS", "IoStandard"),
            _concrete_item("PSVRetain", "*", "PSV Electro", "PSVRetain", system="True"),
        ]
    )

    references, gap = library_refs.explicit_library_references(view)

    assert gap is None
    by_name = _by_name(references)
    assert set(by_name) == {"IoStandard", "PSVRetain"}
    assert by_name["IoStandard"]["kind"] == "placeholder"
    concrete = by_name["PSVRetain"]
    assert concrete["kind"] == "concrete"
    # ``*`` is the declared version; the resolved one comes from the installed
    # LibDoc tree, which docgen fills in.
    assert concrete["version"] == "*"
    assert concrete["vendor"] == "PSV Electro"
    assert concrete["namespace"] == "PSVRetain"
    assert concrete["system"] is True


def test_a_placeholder_keeps_its_declared_default_resolution(project_view):
    view = project_view(
        [_placeholder_item("CAA Device Diagnosis", "3.5.22.0", "CODESYS", "CDD")]
    )

    references, _gap = library_refs.explicit_library_references(view)

    ref = references[0]
    assert ref["kind"] == "placeholder"
    assert ref["placeholder"] == "CAA Device Diagnosis"
    assert (ref["version"], ref["vendor"]) == ("3.5.22.0", "CODESYS")


def test_a_library_without_a_resolution_keeps_its_version_wildcard(project_view):
    item = '        <Single Type="{%s}">' % CONCRETE_GUID
    item += '\n' + _single("Name", "BareLib") + "\n        </Single>"
    view = project_view([item])

    references, _gap = library_refs.explicit_library_references(view)

    assert [ref["name"] for ref in references] == ["BareLib"]
    assert references[0]["version"] == "*"


def test_the_redirection_table_adds_an_implicit_reference(project_view):
    """Standard reaches a project through the table, not through an item."""
    view = project_view(
        [_placeholder_item("IoStandard", "*", "CODESYS", "IoStandard")],
        redirections=[("Standard", "Standard, 3.5.22.0 (System)")],
    )

    references, _gap = library_refs.explicit_library_references(view)

    standard = _by_name(references)["Standard"]
    assert standard["kind"] == "redirected"
    assert (standard["version"], standard["vendor"]) == ("3.5.22.0", "System")
    assert standard["placeholder"] == "Standard"
    assert standard["system"] is True


def test_the_table_fixes_the_version_of_a_placeholder_in_items(project_view):
    view = project_view(
        [_placeholder_item("Standard", "3.5.18.0", "System", "Standard")],
        redirections=[("Standard", "Standard, 3.5.22.0 (System)")],
    )

    references, _gap = library_refs.explicit_library_references(view)

    # One entry, not two: the table's version is the one actually used.
    assert [ref["name"] for ref in references] == ["Standard"]
    assert references[0]["version"] == "3.5.22.0"
    assert references[0]["kind"] == "redirected"


def test_a_redirect_to_an_already_referenced_version_adds_nothing(project_view):
    view = project_view(
        [_placeholder_item("Standard", "3.5.22.0", "System", "Standard")],
        redirections=[("Standard", "Standard, 3.5.22.0 (System)")],
    )

    references, _gap = library_refs.explicit_library_references(view)

    assert len(references) == 1
