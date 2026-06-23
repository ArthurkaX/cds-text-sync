# -*- coding: utf-8 -*-
"""
textlist.py - Text-ID allocation and GlobalTextList handling.

This module handles allocating Text-IDs and writing entries to the
GlobalTextList XML file for CODESYS visualization text management.

XML is written manually (string manipulation) to preserve the exact
format and member order that CODESYS expects, consistent with the
approach used in builder.py. ElementTree is used for read-only
parsing only.
"""

from __future__ import print_function

import csv
import os
import re
import sys
import xml.etree.ElementTree as ET

# TextList entry element type GUID.
_TEXTLIST_ENTRY_TYPE = "{53da1be7-ad25-47c3-b0e8-e26286dad2e0}"


# ---------------------------------------------------------------------------
# XML escaping
# ---------------------------------------------------------------------------


def _esc(value):
    """XML-escape a string value (copied pattern from builder.py)."""
    if value is None:
        value = ""
    value = str(value)
    value = value.replace("&", "&amp;")
    value = value.replace("<", "&lt;")
    value = value.replace(">", "&gt;")
    return value


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _find_global_textlist(project_view_dir):
    """Find the GlobalTextList.xml path.

    Returns the absolute path to ``POUs/GlobalTextList.xml`` under
    *project_view_dir*, or ``None`` if the file does not exist.
    """
    path = os.path.join(project_view_dir, "POUs", "GlobalTextList.xml")
    if os.path.isfile(path):
        return os.path.abspath(path)
    return None


def _global_textlist_csv_path(project_view_dir):
    """Return the absolute path to ``POUs/GlobalTextList.csv``."""
    return os.path.abspath(os.path.join(project_view_dir, "POUs", "GlobalTextList.csv"))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _read_textlist_entries(xml_path):
    """Parse a TextList XML file and return a list of entry dicts.

    Each entry dict has keys ``text_id`` and ``text_default`` (both
    strings, or ``None`` if absent). Returns an empty list when the
    file cannot be parsed or the TextList is empty.

    Uses ElementTree for read-only inspection only.
    """
    if not os.path.isfile(xml_path):
        return []
    try:
        tree = ET.parse(xml_path)
    except (ET.ParseError, IOError):
        return []
    root = tree.getroot()

    # Locate <List Name="TextList"> by recursive search.
    text_list = _named_descendant_list(root, "TextList")
    if text_list is None:
        return []

    entries = []
    for child in list(text_list):
        tag = child.tag
        if not (tag == "Single" or tag.endswith("}Single")):
            continue
        text_id = _named_child_text(child, "TextID")
        text_default = _named_child_text(child, "TextDefault")
        entries.append(
            {
                "text_id": text_id,
                "text_default": text_default,
            }
        )
    return entries


def _named_child_text(element, name):
    """Return the text content of a named ``<Single Name=name>`` child,
    or empty string if missing."""
    for child in list(element):
        child_tag = child.tag
        if not (child_tag == "Single" or child_tag.endswith("}Single")):
            continue
        if child.attrib.get("Name") == name:
            return (child.text or "").strip()
    return ""


def _named_descendant_list(element, name):
    """Recursively find a ``<List Name=name>`` descendant."""
    for child in element.iter():
        tag = child.tag
        if (tag == "List" or tag.endswith("}List")) and child.attrib.get(
            "Name"
        ) == name:
            return child
    return None


def _max_numeric_text_id(entries):
    """Compute the maximum numeric Text-ID from a list of entries.

    Returns 0 if no entries have numeric IDs.
    """
    max_id = 0
    for entry in entries:
        tid = entry.get("text_id") or ""
        try:
            max_id = max(max_id, int(tid))
        except (ValueError, TypeError):
            pass
    return max_id


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_textlist_entry(text_id, text):
    """Render a single TextList entry as an XML text fragment.

    Returns a string with the full ``<Single Type="{53da1be7-...}">``
    element block. Indentation matches the typical project-view format
    (12 spaces for the entry, 14 spaces for children).
    """
    return (
        '            <Single Type="'
        + _TEXTLIST_ENTRY_TYPE
        + '" Method="IArchivable">\n'
        '              <Single Name="TextID" Type="string">'
        + _esc(text_id)
        + "</Single>\n"
        '              <Single Name="TextDefault" Type="string">'
        + _esc(text)
        + "</Single>\n"
        '              <List Name="LanguageTexts" Type="System.Collections.ArrayList" />\n'
        "            </Single>\n"  # noqa: E131
    )


# ---------------------------------------------------------------------------
# XML insertion  (string-based, preserves formatting)
# ---------------------------------------------------------------------------


def _find_list_open(content, name):
    """Find a ``<List Name=name>`` opening tag.

    Returns the position of the ``'<'`` character, or ``None``.
    """
    pattern = r'<List\s+Name="' + re.escape(name) + r'"[^>]*>'
    match = re.search(pattern, content)
    if match is None:
        return None
    return match.start()


def _find_matching_list_close(content, open_start):
    """Find the matching ``</List>`` for a ``<List>`` at *open_start*.

    Returns the position of the ``<`` in ``</List>``, or ``None`` if
    the tag is self-closing or no match is found.
    """
    # Locate the end of the opening tag.
    gt_pos = content.index(">", open_start)
    if content[gt_pos - 1] == "/":
        return None  # Self-closing <List ... />

    depth = 1
    pos = gt_pos + 1

    while pos < len(content) and depth > 0:
        next_open = content.find("<List", pos)
        next_close = content.find("</List>", pos)

        if next_close == -1:
            return None

        if next_open != -1 and next_open < next_close:
            # Opening <List — check if self-closing.
            end = content.index(">", next_open)
            if content[end - 1] == "/":
                # Self-closing — do not increase depth.
                pos = end + 1
            else:
                depth += 1
                pos = end + 1
        else:
            depth -= 1
            if depth == 0:
                return next_close
            pos = next_close + len("</List>")

    return None


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _write_textlist_entry(xml_path, text_id, text):
    """Append a new TextList entry to the XML file *and* its CSV projection.

    The XML entry is inserted as a text fragment before the closing
    ``</List>`` of the ``<List Name="TextList">`` element. The CSV is
    appended as a new row with TextID and TextDefault columns.

    If the XML file does not exist a warning is printed to stderr and
    no write is performed.
    """
    if not os.path.isfile(xml_path):
        print(
            "[WARN] GlobalTextList.xml not found at {0}; cannot register text entry".format(
                xml_path
            ),
            file=sys.stderr,
        )
        return

    entry_xml = _render_textlist_entry(text_id, text)

    # Read existing content.
    with open(xml_path, "r", encoding="utf-8") as handle:
        content = handle.read()

    # Find the TextList section and insert before its closing </List>.
    open_pos = _find_list_open(content, "TextList")
    if open_pos is not None:
        close_pos = _find_matching_list_close(content, open_pos)
        if close_pos is not None:
            new_content = content[:close_pos] + entry_xml + content[close_pos:]
            with open(xml_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(new_content)
        else:
            # Should not happen for a well-formed file.
            print(
                "[WARN] Could not locate closing </List> for TextList in {0}".format(
                    xml_path
                ),
                file=sys.stderr,
            )
    else:
        print(
            '[WARN] No <List Name="TextList"> found in {0}'.format(xml_path),
            file=sys.stderr,
        )

    # CSV projection.
    _write_csv_entry(xml_path, text_id, text)


def _write_csv_entry(xml_path, text_id, text):
    """Append a row to the GlobalTextList CSV projection.

    If the CSV file does not yet exist it is bootstrapped from the
    current XML entries (all existing entries plus the new one).
    If it already exists, the new row is appended while preserving
    existing rows and the column layout (including language columns).

    For a new entry without translations, only TextID and
    TextDefault are populated; language columns are left blank.
    """
    csv_path = xml_path.replace(".xml", ".csv")

    existing_header = []
    existing_rows = []
    if os.path.isfile(csv_path):
        try:
            with open(csv_path, "r", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                rows = list(reader)
            if rows:
                existing_header = rows[0]
                existing_rows = rows[1:]
        except (IOError, csv.Error):
            existing_header = []
            existing_rows = []

    # Determine columns.
    if existing_header:
        columns = existing_header
        # Check for duplicate TextID (defensive).
        new_text_id = str(text_id)
        for row in existing_rows:
            if row and row[0] == new_text_id:
                # Already exists in CSV (should not happen if caller
                # deduplicates, but guard against it).
                return
    else:
        columns = ["TextID", "TextDefault"]
        # Bootstrap from XML entries.
        xml_entries = _read_textlist_entries(xml_path)
        existing_rows = []
        for entry in xml_entries:
            tid = entry.get("text_id") or ""
            tdef = entry.get("text_default") or ""
            # Skip the entry we are about to add (defensive).
            if str(tid) == str(text_id):
                continue
            existing_rows.append([tid, tdef])

    # Build the new row, matching the column count.
    new_row = [""] * len(columns)
    for col_idx, col_name in enumerate(columns):
        col_name_lower = col_name.strip().lower()
        if col_name_lower == "textid":
            new_row[col_idx] = str(text_id)
        elif col_name_lower == "textdefault":
            new_row[col_idx] = text

    # Write back.
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for row in existing_rows:
            writer.writerow(row)
        writer.writerow(new_row)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_text_id(project_view_dir, text):
    """Look up an existing Text-ID for the given text.

    Scans ``POUs/GlobalTextList.xml`` for an entry whose TextDefault
    matches *text* (case-sensitive exact match).

    Returns the Text-ID string if found, or ``None``.
    """
    if not text:
        return None

    xml_path = _find_global_textlist(project_view_dir)
    if xml_path is None:
        return None

    entries = _read_textlist_entries(xml_path)
    for entry in entries:
        if entry.get("text_default") == text:
            return entry.get("text_id")

    return None


def register_text_entry(project_view_dir, text_id, text):
    """Write a new entry to the GlobalTextList.

    Appends an entry (TextID=*text_id*, TextDefault=*text*) to both
    the XML file and its CSV projection.

    *text_id* should be the string representation of a numeric ID
    (e.g. ``"875"``). This function does **not** check for duplicates;
    callers should use ``allocate_text_id`` or ``find_text_id`` first.
    """
    xml_path = _find_global_textlist(project_view_dir)
    if xml_path is None:
        print(
            "[WARN] POUs/GlobalTextList.xml not found under {0}".format(
                project_view_dir
            ),
            file=sys.stderr,
        )
        return

    _write_textlist_entry(xml_path, text_id, text)


def allocate_text_id(project_view_dir, text):
    """Find or allocate a Text-ID for the given text.

    This is the primary entry point for the forward algorithm
    (plan_4 item 4):

    1. Scan ``POUs/GlobalTextList.xml`` for existing entries.
    2. If *text* already exists as a ``TextDefault``, reuse its ID.
    3. Otherwise, allocate ``max(existing numeric TextID) + 1``.
    4. Write the new entry to ``GlobalTextList.xml`` **and** its CSV
       projection.

    Returns the Text-ID string (e.g. ``"875"``).
    """
    if not text:
        text = ""

    xml_path = _find_global_textlist(project_view_dir)

    if xml_path is not None:
        entries = _read_textlist_entries(xml_path)
        # Check for existing entry (case-sensitive exact match).
        for entry in entries:
            if entry.get("text_default") == text:
                return entry.get("text_id")

        # Allocate new ID.
        max_id = _max_numeric_text_id(entries)
        text_id = str(max_id + 1)
    else:
        # No GlobalTextList.xml exists — start from 1.
        text_id = "1"

    register_text_entry(project_view_dir, text_id, text)
    return text_id
