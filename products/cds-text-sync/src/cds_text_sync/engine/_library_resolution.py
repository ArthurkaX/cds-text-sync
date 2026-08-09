# -*- coding: utf-8 -*-
"""
_library_resolution.py - Which library versions a project model was built from.

CODESYS resolves library placeholders against what is installed on the machine
that opens the project. Re-resolving one library rewrites the IDE-generated
subtrees of every visualization object at once, so a project exported under one
resolution and compared after a compile under another shows dozens of visu
objects as modified even though nobody touched them.

The effective resolution is readable straight from the serialized project: each
generated block carries a ``LibraryId`` string. Note that the *declared*
placeholder default in Library Manager (``DefaultResolution``) does not move
when the effective resolution does, so it must not be used as the signal.
"""

import re

LIBRARY_ID_RE = re.compile(
    r"""<Single[^>]*\sName=["']LibraryId["'][^>]*>([^<]*)</Single>"""
)
_LIBRARY_ENTRY_RE = re.compile(r"^\s*([^,]+),\s*([0-9][0-9.]*)")


def resolution_from_model(model):
    """Return ``{library_name: (version, ...)}`` for a project model.

    Names are lower-cased and versions sorted, so two models can be compared
    directly. Nodes without xml text (``st_only`` entries) carry no library
    reference and are skipped.
    """
    found = {}
    for node in (getattr(model, "nodes", None) or {}).values():
        xml_text = getattr(node, "xml_text", None)
        if not xml_text:
            continue
        for value in LIBRARY_ID_RE.findall(xml_text):
            match = _LIBRARY_ENTRY_RE.match(value)
            if match is None:
                continue
            name = match.group(1).strip().lower()
            found.setdefault(name, set()).add(match.group(2))
    return dict((name, tuple(sorted(versions))) for name, versions in found.items())


def resolution_drift(disk_resolution, ide_resolution):
    """Return the libraries whose resolved versions differ between two models.

    Empty list means the two sides agree, which is the common case.
    """
    drift = []
    for name in sorted(set(disk_resolution) | set(ide_resolution)):
        disk_versions = list(disk_resolution.get(name, ()))
        ide_versions = list(ide_resolution.get(name, ()))
        if disk_versions != ide_versions:
            drift.append(
                {"library": name, "disk": disk_versions, "ide": ide_versions}
            )
    return drift


def describe_drift(drift):
    """Render drift rows as one human-readable line each."""
    return [
        "{0}: disk {1} -> IDE {2}".format(
            row.get("library"),
            ", ".join(row.get("disk") or []) or "(absent)",
            ", ".join(row.get("ide") or []) or "(absent)",
        )
        for row in drift or []
    ]
