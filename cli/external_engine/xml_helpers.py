# -*- coding: utf-8 -*-
"""
xml_helpers.py - Shared XML and hashing helpers for the external engine.
"""

import copy
import csv
import hashlib
import io
import os
import re
import xml.etree.ElementTree as ET

TEXT_PROJECTION_SEPARATOR = "\n\n// === SECTION ===\n\n"
ST_IMPLEMENTATION_MARKER = "// --- implementation ---"
IMPORT_SAFE_CSV_EXTRACTORS = set(["textlist_csv", "alarm_items_csv"])
ACTION_HEADER_RE = re.compile(
    r"^\s*ACTION\s+([A-Za-z_][A-Za-z0-9_]*)\s*$",
    re.IGNORECASE,
)

POU_END_KEYWORDS = {
    "PROGRAM": "END_PROGRAM",
    "FUNCTION_BLOCK": "END_FUNCTION_BLOCK",
    "FUNCTION": "END_FUNCTION",
    "METHOD": "END_METHOD",
    "PROPERTY": "END_PROPERTY",
}

CDS_TEXT_SYNC_PRAGMA_RE = re.compile(
    r"\(\*\s*cds-text-sync\s*:\s*TypeGuid\s*=\s*\"\{?([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\}?\"\s*\*\)",
    re.IGNORECASE,
)

CDS_TEXT_SYNC_ANY_PRAGMA_RE = re.compile(
    r"\(\*\s*cds-text-sync\s*:.*?\*\)",
    re.IGNORECASE,
)


def extract_cds_text_sync_type_guid(content):
    """Extract TypeGuid from a cds-text-sync block-comment pragma if present.

    Returns the normalized lowercase GUID string (without braces), or None.
    """
    match = CDS_TEXT_SYNC_PRAGMA_RE.search(content or "")
    if match:
        return match.group(1).strip().lower()
    return None


def strip_cds_text_sync_pragmas(content):
    """Remove all cds-text-sync block-comment pragmas from content.

    Preserves all other user comments.
    """
    return CDS_TEXT_SYNC_ANY_PRAGMA_RE.sub("", content or "")


VOLATILE_XML_NAMES = set(
    [
        "Timestamp",
        "UniqueIdGenerator",
        "GuidInit",
        "GuidReInit",
        "GuidExitX",
    ]
)


class ProjectionValidationError(ValueError):
    pass


def normalize_guid(value):
    if value is None:
        return ""
    return str(value).strip().strip("{}").lower()


def ensure_dir(path):
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except Exception:
            if not os.path.isdir(path):
                raise


def get_namespace(tag):
    if tag and tag.startswith("{"):
        return tag.split("}")[0] + "}"
    return ""


def entry_to_xml(entry_element):
    if entry_element is None:
        return None
    data = ET.tostring(entry_element, encoding="utf-8")
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return "<?xml version='1.0' encoding='utf-8'?>\n" + data


def _is_text_blob_element(element):
    return (
        element is not None
        and element.attrib.get("Name") == "TextBlobForSerialisation"
        and (element.tag == "Single" or str(element.tag).endswith("}Single"))
    )


def _is_text_lines_element(element):
    return (
        element is not None
        and element.attrib.get("Name") == "TextLines"
        and (element.tag == "Array" or str(element.tag).endswith("}Array"))
    )


def _named_text_child(element):
    if element is None:
        return None
    for child in list(element):
        if child.attrib.get("Name") == "Text" and (
            child.tag == "Single" or str(child.tag).endswith("}Single")
        ):
            return child
    return None


def _text_lines_value(text_lines):
    lines = []
    for line in list(text_lines or []):
        text_child = _named_text_child(line)
        if text_child is not None:
            lines.append(text_child.text or "")
    return "\n".join(lines)


def _text_section_elements(entry_element):
    if entry_element is None:
        return []
    result = []
    for element in entry_element.iter():
        if _is_text_blob_element(element):
            result.append({"kind": "blob", "element": element})
        elif _is_text_lines_element(element):
            result.append({"kind": "lines", "element": element})
    return result


def text_blob_elements(entry_element):
    if entry_element is None:
        return []
    return [section["element"] for section in _text_section_elements(entry_element)]


def text_blob_values(entry_element):
    values = []
    for section in _text_section_elements(entry_element):
        if section["kind"] == "blob":
            values.append(section["element"].text or "")
        elif section["kind"] == "lines":
            values.append(_text_lines_value(section["element"]))
    return values


def _text_blob_sections(entry_element):
    sections = []

    def walk(element, names):
        if element is None:
            return
        next_names = list(names)
        element_name = element.attrib.get("Name")
        if element_name:
            next_names.append(element_name)
        if _is_text_blob_element(element) or _is_text_lines_element(element):
            lowered = [name.lower() for name in names]
            role = "section"
            if "interface" in lowered or "declaration" in lowered:
                role = "declaration"
            elif "implementation" in lowered:
                role = "implementation"
            if _is_text_lines_element(element):
                text = _text_lines_value(element)
            else:
                text = element.text or ""
            sections.append({"role": role, "text": text})
            return
        for child in list(element):
            walk(child, next_names)

    walk(entry_element, [])
    return sections


def _first_st_keyword(text):
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("FUNCTION_BLOCK"):
            return "FUNCTION_BLOCK"
        for keyword in ("PROGRAM", "FUNCTION", "METHOD", "PROPERTY"):
            if upper == keyword or upper.startswith(keyword + " "):
                return keyword
        return None
    return None


def _normalize_trailing_newline(text):
    return (text or "").rstrip() + "\n"


def _entry_object_name(entry_element):
    """Return the object name carried by the entry's own MetaObject, or None.

    Only direct children are inspected: a nested object's MetaObject must never
    be mistaken for this entry's own.
    """
    meta = _named_child_any(entry_element, "MetaObject")
    if meta is None:
        return None
    name_element = _named_child_any(meta, "Name")
    if name_element is None:
        return None
    return (name_element.text or "").strip() or None


def _action_header_name(line):
    """Return the name from an ``ACTION <name>`` header line, or None."""
    match = ACTION_HEADER_RE.match(line or "")
    return match.group(1) if match else None


def st_projection_content(entry_element):
    sections = _text_blob_sections(entry_element)
    if not sections:
        return None
    declarations = [
        section["text"] for section in sections if section["role"] == "declaration"
    ]
    implementations = [
        section["text"] for section in sections if section["role"] == "implementation"
    ]
    if len(declarations) == 1 and len(implementations) == 1:
        declaration = declarations[0]
        implementation = implementations[0]
        keyword = _first_st_keyword(declaration)
        if POU_END_KEYWORDS.get(keyword):
            content = _normalize_trailing_newline(declaration)
            if implementation.strip():
                content += (
                    "\n"
                    + ST_IMPLEMENTATION_MARKER
                    + "\n\n"
                    + _normalize_trailing_newline(implementation)
                )
            return content
        if declaration.strip() and implementation.strip():
            return (
                _normalize_trailing_newline(declaration)
                + "\n"
                + ST_IMPLEMENTATION_MARKER
                + "\n\n"
                + _normalize_trailing_newline(implementation)
            )
    # ACTIONs (and other declaration-less POU children) expose an implementation
    # section only. Without a header the projected .st is not self-describing:
    # the folder reader cannot tell what kind it is, and the import path cannot
    # tell the body apart from a GVL/DUT declaration. Synthesise the header from
    # the entry's own MetaObject name; split_st_projection_values() strips it
    # again on the way back, so the stored blob is unchanged.
    if not declarations and len(implementations) == 1:
        action_name = _entry_object_name(entry_element)
        if action_name:
            return (
                "ACTION {0}\n".format(action_name)
                + "\n"
                + ST_IMPLEMENTATION_MARKER
                + "\n\n"
                + _normalize_trailing_newline(implementations[0])
            )
    return join_text_blob_values([section["text"] for section in sections])


def join_text_blob_values(values):
    values = list(values or [])
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return TEXT_PROJECTION_SEPARATOR.join(values)


def split_text_projection(value, expected_count):
    expected_count = int(expected_count or 0)
    if expected_count <= 0:
        return []
    parts = (value or "").split(TEXT_PROJECTION_SEPARATOR)
    if len(parts) < expected_count:
        parts.extend([""] * (expected_count - len(parts)))
    if len(parts) > expected_count:
        parts = parts[: expected_count - 1] + [
            TEXT_PROJECTION_SEPARATOR.join(parts[expected_count - 1 :])
        ]
    return parts


def _split_full_pou_projection(value):
    lines = (value or "").splitlines()
    first_keyword = _first_st_keyword(value)
    end_keyword = POU_END_KEYWORDS.get(first_keyword)
    if not end_keyword:
        return None

    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip().upper() == end_keyword:
        lines.pop()

    declaration_end = None
    for index, line in enumerate(lines):
        if line.strip().upper() == "END_VAR":
            declaration_end = index
    if declaration_end is None:
        return None

    declaration_lines = lines[: declaration_end + 1]
    implementation_lines = lines[declaration_end + 1 :]
    while implementation_lines and not implementation_lines[0].strip():
        implementation_lines.pop(0)
    if (
        implementation_lines
        and implementation_lines[0].strip() == ST_IMPLEMENTATION_MARKER
    ):
        implementation_lines.pop(0)
        while implementation_lines and not implementation_lines[0].strip():
            implementation_lines.pop(0)
    return (
        "\n".join(declaration_lines).rstrip() + "\n",
        "\n".join(implementation_lines).rstrip()
        + ("\n" if implementation_lines else ""),
    )


def split_action_projection(value):
    """Return the implementation body of an ``ACTION``-headed ST projection.

    Returns None when *value* carries no ``ACTION <name>`` header, so callers
    can fall back to their normal declaration/implementation handling. The
    optional ``END_ACTION`` terminator is dropped: CODESYS stores the bare body
    and re-adds the keywords itself.
    """
    normalized = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or not _action_header_name(lines[index]):
        return None

    body = lines[index + 1 :]
    while body and not body[0].strip():
        body.pop(0)
    if body and body[0].strip() == ST_IMPLEMENTATION_MARKER:
        body.pop(0)
        while body and not body[0].strip():
            body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    if body and body[-1].strip().upper() == "END_ACTION":
        body.pop()
        while body and not body[-1].strip():
            body.pop()
    return "\n".join(body) + ("\n" if body else "")


def _split_marked_projection(value):
    marker = "\n" + ST_IMPLEMENTATION_MARKER + "\n"
    normalized = (value or "").replace("\r\n", "\n")
    if marker not in normalized:
        return None
    declaration, implementation = normalized.split(marker, 1)
    implementation = implementation.lstrip("\n")
    return (
        declaration.rstrip() + "\n",
        implementation.rstrip() + ("\n" if implementation else ""),
    )


def split_st_projection_values(value, entry_element):
    blobs = text_blob_elements(entry_element)
    sections = _text_blob_sections(entry_element)
    # Declaration-less entry (ACTION): the projection carries a synthesised
    # ``ACTION <name>`` header that must not reach the stored blob. Strip it
    # here, otherwise the header and the marker are written straight into the
    # Implementation text by replace_text_blob_values().
    if (
        len(blobs) == len(sections) == 1
        and sections[0]["role"] == "implementation"
    ):
        action_body = split_action_projection(value)
        if action_body is not None:
            return [action_body]
    marked_parts = _split_marked_projection(value) or _split_full_pou_projection(value)
    if marked_parts and len(blobs) == len(sections) == 2:
        declaration, implementation = marked_parts
        values = []
        for section in sections:
            if section["role"] == "declaration":
                values.append(declaration)
            elif section["role"] == "implementation":
                values.append(implementation)
            else:
                return split_text_projection(value, len(blobs))
        return values
    return split_text_projection(value, len(blobs))


def replace_text_blob_values(entry_element, values):
    blobs = _text_section_elements(entry_element)
    values = list(values or [])
    for index, section in enumerate(blobs):
        value = values[index] if index < len(values) else ""
        if section["kind"] == "blob":
            section["element"].text = value
        elif section["kind"] == "lines":
            _replace_text_lines_value(section["element"], value)
    return len(blobs)


def _replace_text_lines_value(text_lines, value):
    existing = list(text_lines or [])
    template = existing[0] if existing else None
    lines = (value or "").splitlines()
    if value and (value.endswith("\n") or value.endswith("\r\n")):
        lines = lines[:-1] if lines and lines[-1] == "" else lines
    if not lines:
        lines = [""]

    for child in existing:
        text_lines.remove(child)

    if template is None:
        return

    for index, line_text in enumerate(lines):
        line_element = copy.deepcopy(template)
        id_child = _named_child(line_element, "Single", "Id")
        text_child = _named_text_child(line_element)
        if id_child is not None:
            id_child.text = str(index + 1)
        if text_child is not None:
            text_child.text = line_text
        text_lines.append(line_element)


def externalized_text_xml(entry_element):
    if entry_element is None:
        return None
    cloned = copy.deepcopy(entry_element)
    if not text_blob_elements(cloned):
        return entry_to_xml(cloned)
    replace_text_blob_values(cloned, [""] * len(text_blob_elements(cloned)))
    return entry_to_xml(cloned)


def _named_child(element, tag_name, name):
    if element is None:
        return None
    for child in list(element):
        if (
            child.tag == tag_name or str(child.tag).endswith("}" + tag_name)
        ) and child.attrib.get("Name") == name:
            return child
    return None


def _named_child_any(element, name):
    if element is None:
        return None
    for child in list(element):
        if child.attrib.get("Name") == name:
            return child
    return None


def _ensure_named_child(element, tag_name, name, attrs=None):
    child = _named_child(element, tag_name, name)
    if child is not None:
        return child
    child = ET.SubElement(element, tag_name, attrs or {})
    child.set("Name", name)
    return child


def _named_descendant(element, tag_name, name):
    if element is None:
        return None
    for child in element.iter():
        if (
            child.tag == tag_name or str(child.tag).endswith("}" + tag_name)
        ) and child.attrib.get("Name") == name:
            return child
    return None


def _first_child(element, tag_name):
    if element is None:
        return None
    for child in list(element):
        if child.tag == tag_name or str(child.tag).endswith("}" + tag_name):
            return child
    return None


def _element_text(element):
    if element is None or element.text is None:
        return ""
    return element.text


def _named_child_text(element, name):
    return _element_text(_named_child(element, "Single", name))


def _sort_csv_rows(rows, key_name):
    def sort_key(row):
        value = row.get(key_name) or ""
        try:
            return (0, int(value))
        except Exception:
            return (1, value)

    return sorted(rows, key=sort_key)


def textlist_csv(entry_element):
    text_list = _named_descendant(entry_element, "List", "TextList")
    if text_list is None:
        return None
    languages_list = _named_descendant(entry_element, "List", "Languages")
    languages = []
    if languages_list is not None:
        for item in list(languages_list):
            if item.text:
                languages.append(item.text)

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["TextID", "TextDefault"] + languages)

    for item in list(text_list):
        if not (item.tag == "Single" or str(item.tag).endswith("}Single")):
            continue
        text_id = _named_child(item, "Single", "TextID")
        text_default = _named_child(item, "Single", "TextDefault")
        row = [
            text_id.text if text_id is not None and text_id.text is not None else "",
            text_default.text
            if text_default is not None and text_default.text is not None
            else "",
        ]
        language_texts = _named_child(item, "List", "LanguageTexts")
        texts = list(language_texts) if language_texts is not None else []
        for index, _language in enumerate(languages):
            if index < len(texts) and texts[index].text is not None:
                row.append(texts[index].text)
            else:
                row.append("")
        writer.writerow(row)

    return output.getvalue()


def apply_textlist_csv(entry_element, csv_content):
    text_list = _named_descendant(entry_element, "List", "TextList")
    if text_list is None:
        return False

    reader = csv.DictReader(io.StringIO(csv_content or ""))
    if not reader.fieldnames or "TextID" not in reader.fieldnames:
        return False

    languages = [
        name
        for name in reader.fieldnames
        if name not in ("TextID", "TextDefault") and name
    ]
    rows_by_id = {}
    for row in reader:
        text_id = row.get("TextID")
        if text_id is None and not any(row.values()):
            continue
        if text_id in rows_by_id:
            raise ProjectionValidationError(
                "Duplicate TextID in TextList CSV: {0}".format(text_id)
            )
        rows_by_id[text_id] = row

    existing_ids = []
    for item in list(text_list):
        if not (item.tag == "Single" or str(item.tag).endswith("}Single")):
            continue
        text_id = _named_child(item, "Single", "TextID")
        if text_id is not None:
            existing_ids.append(text_id.text or "")

    csv_ids = set(rows_by_id.keys())
    existing_id_set = set(existing_ids)
    added_ids = sorted(csv_ids - existing_id_set)
    removed_ids = sorted(existing_id_set - csv_ids)
    if added_ids or removed_ids:
        parts = []
        if added_ids:
            parts.append("inserted TextID: {0}".format(", ".join(added_ids)))
        if removed_ids:
            parts.append("removed TextID: {0}".format(", ".join(removed_ids)))
        raise ProjectionValidationError(
            "TextList CSV supports editing existing rows only; {0}".format(
                "; ".join(parts)
            )
        )

    changed = False
    for item in list(text_list):
        if not (item.tag == "Single" or str(item.tag).endswith("}Single")):
            continue
        text_id = _named_child(item, "Single", "TextID")
        text_id_value = text_id.text if text_id is not None else None
        if text_id_value not in rows_by_id:
            continue

        row = rows_by_id[text_id_value]
        text_default = _ensure_named_child(item, "Single", "TextDefault")
        new_default = row.get("TextDefault") or ""
        if (text_default.text or "") != new_default:
            text_default.text = new_default
            changed = True

        language_texts = _named_child(item, "List", "LanguageTexts")
        if languages or language_texts is not None:
            if language_texts is None:
                language_texts = _ensure_named_child(
                    item,
                    "List",
                    "LanguageTexts",
                    {"Type": "System.Collections.ArrayList"},
                )
            while len(list(language_texts)) < len(languages):
                ET.SubElement(language_texts, "Single", {"Type": "string"})
            for index, language in enumerate(languages):
                child = list(language_texts)[index]
                new_value = row.get(language) or ""
                if (child.text or "") != new_value:
                    child.text = new_value
                    changed = True

    languages_list = _named_descendant(entry_element, "List", "Languages")
    if languages or languages_list is not None:
        if languages_list is None:
            languages_list = _ensure_named_child(
                _named_descendant(entry_element, "Single", "Object") or entry_element,
                "List",
                "Languages",
                {"Type": "System.Collections.ArrayList"},
            )
        existing_languages = [
            item.text or ""
            for item in list(languages_list)
            if item.tag == "Single" or str(item.tag).endswith("}Single")
        ]
        if existing_languages != languages:
            for item in list(languages_list):
                languages_list.remove(item)
            for language in languages:
                child = ET.SubElement(languages_list, "Single", {"Type": "string"})
                child.text = language
            changed = True

    return changed


def _additional_message_ids(alarm_element):
    messages = _named_child(alarm_element, "List", "AdditionalMessageIDs")
    if messages is None:
        return ""

    values = []
    for item in list(messages):
        if item.tag == "Single" or str(item.tag).endswith("}Single"):
            text_id = _named_child_text(item, "TextID")
            text_default = _named_child_text(item, "TextDefault")
            if text_id and text_default:
                values.append("{0}:{1}".format(text_id, text_default))
            elif text_id:
                values.append(text_id)
            elif item.text:
                values.append(item.text)
    return ";".join(values)


def _set_named_single_text(element, name, value, default_type="string"):
    if element is None:
        return False
    value = value or ""
    child = _named_child_any(element, name)
    if child is None:
        if not value:
            return False
        child = ET.SubElement(element, "Single", {"Name": name, "Type": default_type})
        child.text = value
        return True

    if child.tag == "Null" or str(child.tag).endswith("}Null"):
        if not value:
            return False
        child.tag = "Single"
        child.attrib.clear()
        child.set("Name", name)
        child.set("Type", default_type)
        child.text = value
        return True

    if not (child.tag == "Single" or str(child.tag).endswith("}Single")):
        return False

    if (child.text or "") != value:
        child.text = value
        return True
    return False


def _alarm_items(entry_element):
    alarms = _named_descendant(entry_element, "Dictionary", "Alarms")
    if alarms is None:
        return []

    items = []
    for entry in list(alarms):
        if not (entry.tag == "Entry" or str(entry.tag).endswith("}Entry")):
            continue
        value = _first_child(entry, "Value")
        alarm = _first_child(value, "Single")
        if alarm is not None:
            items.append(alarm)
    return items


def apply_alarm_items_csv(entry_element, csv_content):
    reader = csv.DictReader(io.StringIO(csv_content or ""))
    if not reader.fieldnames or "AlarmID" not in reader.fieldnames:
        return False

    rows_by_id = {}
    for row in reader:
        alarm_id = row.get("AlarmID")
        if alarm_id is None and not any(row.values()):
            continue
        if alarm_id in rows_by_id:
            raise ProjectionValidationError(
                "Duplicate AlarmID in alarm CSV: {0}".format(alarm_id)
            )
        rows_by_id[alarm_id] = row

    alarms = _alarm_items(entry_element)
    existing_ids = [_named_child_text(alarm, "ID") or "" for alarm in alarms]
    csv_ids = set(rows_by_id.keys())
    existing_id_set = set(existing_ids)
    added_ids = sorted(csv_ids - existing_id_set)
    removed_ids = sorted(existing_id_set - csv_ids)
    if added_ids or removed_ids:
        parts = []
        if added_ids:
            parts.append("inserted AlarmID: {0}".format(", ".join(added_ids)))
        if removed_ids:
            parts.append("removed AlarmID: {0}".format(", ".join(removed_ids)))
        raise ProjectionValidationError(
            "Alarm CSV supports editing existing rows only; {0}".format(
                "; ".join(parts)
            )
        )

    changed = False
    for alarm in alarms:
        alarm_id = _named_child_text(alarm, "ID")
        if alarm_id not in rows_by_id:
            continue

        row = rows_by_id[alarm_id]
        additional_message_ids = row.get("AdditionalMessageIDs")
        if (
            additional_message_ids is not None
            and additional_message_ids != _additional_message_ids(alarm)
        ):
            raise ProjectionValidationError(
                "Alarm CSV field AdditionalMessageIDs is read-only until message list import is implemented "
                "for AlarmID: {0}".format(alarm_id)
            )
        observation = _named_child(alarm, "Single", "ObservationType")
        if observation is not None:
            changed = (
                _set_named_single_text(observation, "Expression", row.get("Expression"))
                or changed
            )
            changed = (
                _set_named_single_text(observation, "Comparison", row.get("Comparison"))
                or changed
            )
            changed = (
                _set_named_single_text(
                    observation,
                    "ExpressionToCompare",
                    row.get("ExpressionToCompare"),
                )
                or changed
            )

        alarm_class = row.get("AlarmClass")
        alarm_class_element = _named_child(alarm, "Single", "AlarmClass")
        if alarm_class_element is not None:
            changed = (
                _set_named_single_text(alarm_class_element, "Name", alarm_class)
                or changed
            )
        if _named_child_any(alarm, "FullAlarmClassName") is not None:
            changed = (
                _set_named_single_text(alarm, "FullAlarmClassName", alarm_class)
                or changed
            )

        for field_name in [
            "LatchVariable1",
            "LatchVariable2",
            "Deactivation",
            "MinPendingTime",
            "OffDelayTime",
            "HigherPrioAlarm",
        ]:
            changed = (
                _set_named_single_text(alarm, field_name, row.get(field_name))
                or changed
            )

    return changed


def alarm_items_csv(entry_element):
    alarms = _alarm_items(entry_element)
    if not alarms:
        return None

    headers = [
        "AlarmID",
        "Expression",
        "Comparison",
        "ExpressionToCompare",
        "AlarmClass",
        "LatchVariable1",
        "LatchVariable2",
        "Deactivation",
        "MinPendingTime",
        "OffDelayTime",
        "HigherPrioAlarm",
        "AdditionalMessageIDs",
    ]
    rows = []

    for alarm in alarms:
        observation = _named_child(alarm, "Single", "ObservationType")
        alarm_class = _named_child(alarm, "Single", "AlarmClass")
        row = {
            "AlarmID": _named_child_text(alarm, "ID"),
            "Expression": _named_child_text(observation, "Expression"),
            "Comparison": _named_child_text(observation, "Comparison"),
            "ExpressionToCompare": _named_child_text(
                observation, "ExpressionToCompare"
            ),
            "AlarmClass": _named_child_text(alarm_class, "Name")
            or _named_child_text(alarm, "FullAlarmClassName"),
            "LatchVariable1": _named_child_text(alarm, "LatchVariable1"),
            "LatchVariable2": _named_child_text(alarm, "LatchVariable2"),
            "Deactivation": _named_child_text(alarm, "Deactivation"),
            "MinPendingTime": _named_child_text(alarm, "MinPendingTime"),
            "OffDelayTime": _named_child_text(alarm, "OffDelayTime"),
            "HigherPrioAlarm": _named_child_text(alarm, "HigherPrioAlarm"),
            "AdditionalMessageIDs": _additional_message_ids(alarm),
        }
        rows.append(row)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    for row in _sort_csv_rows(rows, "AlarmID"):
        writer.writerow(row)
    return output.getvalue()


CSV_EXTRACTORS = {
    "textlist_csv": textlist_csv,
    "alarm_items_csv": alarm_items_csv,
}


def csv_projection_content(entry_element, extractor_name):
    extractor = CSV_EXTRACTORS.get(extractor_name or "textlist_csv")
    if extractor is None:
        return None
    return extractor(entry_element)


def sha1_hex(value):
    if value is None:
        return None
    data = value.encode("utf-8") if hasattr(value, "encode") else value
    return hashlib.sha1(data).hexdigest()


def extract_bool_property(entry_element, property_name, ns=""):
    if entry_element is None:
        return None
    pattern = ".//{0}Single[@Name='{1}']".format(ns, property_name)
    prop_elem = entry_element.find(pattern)
    if prop_elem is None or prop_elem.text is None:
        return None
    value = prop_elem.text.strip().lower()
    if value in ("true", "false"):
        return value == "true"
    return None


def normalize_xml_element(element):
    element.text = (element.text or "").strip()
    element.tail = None

    if _is_text_lines_element(element):
        while list(element):
            last_child = list(element)[-1]
            text_child = _named_text_child(last_child)
            if text_child is None or (text_child.text or "").strip():
                break
            element.remove(last_child)

    for child in list(element):
        if child.attrib.get("Name") == "Id" and _named_text_child(element) is not None:
            element.remove(child)
        elif child.attrib.get("Name") in VOLATILE_XML_NAMES:
            element.remove(child)
        else:
            normalize_xml_element(child)

    if element.tag == "Dictionary":
        entries = list(element)
        for entry in entries:
            element.remove(entry)
        entries.sort(key=lambda entry: ET.tostring(entry, encoding="utf-8"))
        for entry in entries:
            element.append(entry)


def normalized_xml_text(value):
    try:
        root = ET.fromstring(value)
    except Exception:
        return value
    normalize_xml_element(root)
    data = ET.tostring(root, encoding="utf-8")
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return data
