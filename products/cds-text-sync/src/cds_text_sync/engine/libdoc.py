# -*- coding: utf-8 -*-
"""
libdoc.py - Structured symbol records from CODESYS's installed library docs.

Every installed library keeps a Sphinx-generated HTML documentation tree under
``<LibDoc root>/<vendor>/<library>/<version>/<locale>``, indexed by a
``manifest.json`` whose ``std:doc`` inventory names pages like ``"Swap (FUN)"``.
This module locates that tree for one library, picks the best installed
version and locale, and parses each POU page into a compact record: symbol
name, kind, declaration signature, description and the interface table.

The interface table is ordinary HTML with one wrinkle: CODESYS groups
consecutive rows sharing a scope and emits the scope cell once with a
``rowspan`` covering the whole group, so spanning cells must be carried
forward or every later cell in the row shifts left.
"""

from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path

#: A real POU page's manifest name ends with a parenthesised kind suffix such
#: as ``"Swap (FUN)"``; navigation pages (``fld-*``, ``index``, ``info``,
#: ``libraries``) carry no suffix. A positive allowlist, not a filename
#: blacklist.
POU_KIND_RE = re.compile(r"\s\(([A-Z_]+)\)$")

#: Locale subdirectories to prefer, in order.
LOCALE_PREFERENCE = ("en", "Default")

MANIFEST_NAME = "manifest.json"


def _clean(parts):
    """Join text fragments, unescape entities and collapse whitespace."""
    return " ".join(html.unescape("".join(parts)).split())


def _child_dir(parent, wanted_lower):
    """Return the child directory whose name matches case-insensitively."""
    for child in sorted(parent.iterdir()):
        if child.is_dir() and child.name.lower() == wanted_lower:
            return child
    return None


def _version_sort_key(version_name):
    """Compare dotted versions numerically per segment.

    ``3.5.15.0`` must beat ``3.5.9.0``, which plain string comparison would
    get wrong; non-numeric segments fall back to string compare per segment.
    """
    key = []
    for segment in str(version_name).split("."):
        if segment.isdigit():
            key.append((0, int(segment), ""))
        else:
            key.append((1, 0, segment))
    return tuple(key)


def _pick_version_dir(library_dir, version):
    """Resolve ``version`` to a concrete version directory.

    ``"*"`` - or a version whose folder is not installed - selects the
    highest installed version; an unknown version scheme means no directory
    is found.
    """
    try:
        candidates = [child for child in library_dir.iterdir() if child.is_dir()]
    except OSError:
        return None
    if not candidates:
        return None
    wanted = str(version or "").strip()
    if wanted not in ("", "*"):
        for child in candidates:
            if child.name == wanted:
                return child
    return max(candidates, key=lambda child: _version_sort_key(child.name))


def _pick_locale_dir(version_dir):
    """Pick the locale directory by preference, else any with a manifest."""
    try:
        candidates = [child for child in version_dir.iterdir() if child.is_dir()]
    except OSError:
        return None
    by_name = dict((child.name, child) for child in candidates)
    for locale in LOCALE_PREFERENCE:
        if locale in by_name:
            return by_name[locale]
    for child in candidates:
        if (child / MANIFEST_NAME).is_file():
            return child
    return None


def _read_manifest(locale_dir):
    """Read and parse ``manifest.json`` from a locale directory, or ``None``."""
    try:
        return json.loads(
            (locale_dir / MANIFEST_NAME).read_text(encoding="utf-8-sig")
        )
    except (OSError, ValueError):
        return None


def find_libdoc(library_root, name, vendor, version):
    """Locate the LibDoc tree of one installed library. Never raises.

    ``library_root`` may be the LibDoc root itself or a parent containing a
    ``LibDoc`` child. ``vendor`` and ``name`` are matched case-insensitively
    against the actual directory names; an empty ``vendor`` searches every
    vendor directory. ``version`` is ``"*"`` or a concrete dotted version; a
    missing exact version folder falls back to the highest installed one,
    compared numerically per segment. Returns ``{"path", "version", "vendor",
    "manifest"}`` or ``None`` when anything is missing or unreadable.
    """
    try:
        root = Path(library_root)
        if (root / "LibDoc").is_dir():
            root = root / "LibDoc"
        if not root.is_dir():
            return None
        wanted_name = (name or "").strip().lower()
        if not wanted_name:
            return None
        wanted_vendor = (vendor or "").strip().lower()
        for vendor_dir in sorted(root.iterdir()):
            if not vendor_dir.is_dir():
                continue
            if wanted_vendor and vendor_dir.name.lower() != wanted_vendor:
                continue
            library_dir = _child_dir(vendor_dir, wanted_name)
            if library_dir is None:
                continue
            version_dir = _pick_version_dir(library_dir, version)
            if version_dir is None:
                continue
            locale_dir = _pick_locale_dir(version_dir)
            if locale_dir is None:
                continue
            manifest = _read_manifest(locale_dir)
            if manifest is None:
                continue
            return {
                "path": locale_dir,
                "version": version_dir.name,
                "vendor": vendor_dir.name,
                "manifest": manifest,
            }
        return None
    except Exception:
        return None


def pou_pages(manifest):
    """List ``{"name", "kind", "location"}`` for every POU page in a manifest.

    Names ending in a parenthesised kind suffix identify real POU pages; the
    suffix is stripped and the kind upper-cased. Sorted case-insensitively by
    name for deterministic output; a missing or malformed inventory yields
    an empty list.
    """
    if not isinstance(manifest, dict):
        return []
    inventory = manifest.get("inventory")
    pages = inventory.get("std:doc") if isinstance(inventory, dict) else None
    if not isinstance(pages, dict):
        return []
    found = []
    for entry in pages.values():
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("name") or "")
        match = POU_KIND_RE.search(raw)
        if match is None:
            continue
        found.append({
            "name": raw[: match.start()].rstrip(),
            "kind": match.group(1).upper(),
            "location": str(entry.get("location") or ""),
        })
    found.sort(key=lambda page: (page["name"].lower(), page["location"]))
    return found


class _PouPageParser(HTMLParser):
    """Collects the structured pieces of one POU documentation page.

    Page shape after the ``<h1>`` (POU name and kind): the first ``<p>`` is
    the declaration signature, following ``<p>``/``<ul>`` blocks form the
    description, and the ``InOut:`` definition list holds the interface table
    whose ``<thead>`` fixes the real column order.
    """

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self._stack = []
        self._in_h1 = False
        self._h1_done = False
        self._h1_parts = []
        self._signature = ""
        self._signature_done = False
        self._collect_desc = False
        self._blocks = []
        self._p_open = False
        self._p_parts = []
        self._ul_open = False
        self._ul_items = []
        self._li_parts = None
        self._dl_interface = False
        self._dt_parts = None
        self._in_table = False
        self._in_thead = False
        self._headers = []
        self._rows = []
        self._pending = None
        self._carry = {}
        self._cell_parts = []
        self._cell_span = 1

    def results(self):
        """Assemble the record; called once after ``feed`` and ``close``."""
        headline = " ".join(
            "".join(self._h1_parts).replace("¶", " ").split()
        )
        match = POU_KIND_RE.search(headline)
        if match is None:
            name, kind = headline, ""
        else:
            name = headline[: match.start()].rstrip()
            kind = match.group(1).upper()
        interface = [
            row for row in self._rows if str(row.get("name") or "").strip()
        ]
        return {
            "name": name,
            "kind": kind,
            "signature": self._signature,
            "description": "\n\n".join(self._blocks),
            "interface": interface,
        }

    def handle_starttag(self, tag, attrs):
        self._stack.append(tag)
        if not self._h1_done:
            if tag == "h1":
                self._in_h1 = True
                self._h1_parts = []
            return
        if tag == "dl":
            self._dl_interface = False
            self._dt_parts = None
            self._collect_desc = False
        elif tag == "dt":
            self._dt_parts = []
        elif tag == "table" and self._dl_interface:
            self._in_table = True
            self._headers = []
            self._rows = []
            self._carry = {}
            self._pending = None
        elif self._in_table:
            if tag == "thead":
                self._in_thead = True
            elif tag == "tbody":
                self._in_thead = False
            elif tag == "tr" and not self._in_thead:
                self._pending = []
            elif tag in ("td", "th"):
                self._cell_parts = []
                self._cell_span = self._rowspan(attrs)
        elif self._desc_context():
            if tag == "p":
                self._p_open = True
                self._p_parts = []
            elif tag == "ul":
                self._ul_open = True
                self._ul_items = []
            elif tag == "li" and self._ul_open:
                self._li_parts = []

    def handle_endtag(self, tag):
        stack = self._stack
        if tag not in stack:
            return
        while stack:
            if stack.pop() == tag:
                break
        if not self._h1_done:
            if tag == "h1":
                self._in_h1 = False
                self._h1_done = True
                self._collect_desc = True
            return
        if tag == "h1":
            return
        if tag == "p" and self._p_open:
            self._p_open = False
            text = _clean(self._p_parts)
            if not self._signature_done:
                self._signature = text
                self._signature_done = True
            elif text:
                self._blocks.append(text)
        elif tag == "li" and self._li_parts is not None:
            item = _clean(self._li_parts)
            self._li_parts = None
            if item:
                self._ul_items.append(item)
        elif tag == "ul" and self._ul_open:
            self._ul_open = False
            if self._ul_items:
                self._blocks.append(
                    "\n".join("- " + item for item in self._ul_items)
                )
            self._ul_items = []
        elif tag == "dt" and self._dt_parts is not None:
            label = _clean(self._dt_parts).lower()
            self._dt_parts = None
            if label.startswith("inout"):
                self._dl_interface = True
        elif tag == "dl":
            self._dl_interface = False
        elif tag == "thead":
            self._in_thead = False
        elif tag in ("td", "th"):
            text = _clean(self._cell_parts)
            if tag == "th" and self._in_thead:
                self._headers.append(text.lower())
            elif self._pending is not None:
                self._pending.append((text, self._cell_span))
        elif tag == "tr" and self._pending is not None:
            self._emit_row()
            self._pending = None
        elif tag == "table" and self._in_table:
            self._in_table = False

    def handle_data(self, data):
        stack = self._stack
        if "td" in stack or "th" in stack:
            self._cell_parts.append(data)
        elif self._in_h1:
            self._h1_parts.append(data)
        elif "dt" in stack and self._dt_parts is not None:
            self._dt_parts.append(data)
        elif "li" in stack and self._li_parts is not None:
            self._li_parts.append(data)
        elif "p" in stack:
            self._p_parts.append(data)

    def _emit_row(self):
        """Split one body row across the header columns, honouring rowspan."""
        headers = self._headers
        if not headers:
            return
        row = {}
        col = 0
        index = 0
        cells = self._pending or []
        while col < len(headers):
            carried = self._carry.get(col)
            if carried is not None:
                value, remaining = carried
                if remaining > 1:
                    self._carry[col] = (value, remaining - 1)
                else:
                    del self._carry[col]
                row[headers[col]] = value
                col += 1
                continue
            if index >= len(cells):
                break
            text, span = cells[index]
            index += 1
            row[headers[col]] = text
            if span > 1:
                self._carry[col] = (text, span - 1)
            col += 1
        self._rows.append(row)

    @staticmethod
    def _rowspan(attrs):
        for key, value in attrs:
            if key == "rowspan":
                try:
                    return max(1, int(value))
                except (TypeError, ValueError):
                    break
        return 1

    def _desc_context(self):
        return self._collect_desc and not self._in_table


def parse_pou_html(text):
    """Parse one POU page into ``{name, kind, signature, description,
    interface}``. Never raises on malformed HTML; returns the empty-ish
    structure instead."""
    parser = _PouPageParser()
    try:
        parser.feed(str(text))
        parser.close()
    except Exception:
        pass
    return parser.results()


def library_symbols(libdoc):
    """Parse every POU page of a located LibDoc tree into symbol records.

    Each record from :func:`parse_pou_html` gains its manifest ``location``;
    pages that fail to read or carry no recognizable heading are skipped.
    """
    if not isinstance(libdoc, dict):
        return []
    base = libdoc.get("path")
    if not base:
        return []
    records = []
    for page in pou_pages(libdoc.get("manifest")):
        location = page.get("location") or ""
        if not location:
            continue
        try:
            text = (Path(base) / location).read_text(
                encoding="utf-8-sig", errors="replace"
            )
        except OSError:
            continue
        record = parse_pou_html(text)
        if not record.get("name"):
            continue
        record["location"] = location
        records.append(record)
    return records


__all__ = [
    "LOCALE_PREFERENCE",
    "POU_KIND_RE",
    "find_libdoc",
    "library_symbols",
    "parse_pou_html",
    "pou_pages",
]