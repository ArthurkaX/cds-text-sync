"""Explicit legacy XML/task/visualization project-view compatibility API."""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

from cds_static_analyzer import project
from cds_static_analyzer.model import Diagnostic, Location
from cds_static_analyzer.st import kinds as K

_VISU_ROOT_TYPE = "{6198ad31-4b98-445c-927f-3258a0e82fe3}"
_TEXTLIST_FILENAME = "GlobalTextList.xml"
_ROOT_TAG_RE = re.compile(r"<([A-Za-z_][\w.:-]*)((?:\s[^<>]*?)?)>")


def _local_tag(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _infer_broken_xml_kind(relpath, text):
    if relpath.endswith(_TEXTLIST_FILENAME):
        return K.TEXTLIST
    match = _ROOT_TAG_RE.search(text or "")
    if match is None:
        return "xml"
    local = _local_tag(match.group(1))
    if local == "Visualization":
        return K.VISUALIZATION
    if local == "Single" and _VISU_ROOT_TYPE.lower() in (match.group(2) or "").lower():
        return K.VISUALIZATION
    if local == "TaskConfiguration":
        return K.TASK_CONFIG
    if local == "TextList":
        return K.TEXTLIST
    return "xml"


def _classify_xml(relpath, text):
    if relpath.endswith(_TEXTLIST_FILENAME):
        return K.TEXTLIST
    root = ET.fromstring(text)
    local = _local_tag(root.tag)
    if local == "TaskConfiguration":
        return K.TASK_CONFIG
    if local == "Single":
        names = {
            element.attrib.get("Name")
            for element in root.iter()
            if element.attrib.get("Name")
        }
        if {"PouList", "TaskConfigurationList"} & names:
            return K.TASK_CONFIG
    if local == "Visualization":
        return K.VISUALIZATION
    if local == "Single" and root.attrib.get("Type", "").lower() == _VISU_ROOT_TYPE.lower():
        return K.VISUALIZATION
    if local == "TextList":
        return K.TEXTLIST
    return None


def _xml_parse_error(rel, text, exc):
    line, column = getattr(exc, "position", (None, None)) or (None, None)
    return project.SourceError(
        rel,
        _infer_broken_xml_kind(rel, text),
        f"cannot parse {rel}: {exc}",
        line=line,
        column=column,
    )


def _build_xml_unit(rel, text):
    kind = _classify_xml(rel, text)
    if kind is None:
        return None
    stem = os.path.splitext(os.path.basename(rel))[0]
    return project.Unit(
        id=project.unit_id(rel, stem),
        kind=kind,
        qualified_name=stem,
        source_path=rel,
        text=text,
        source_spans=[project.SourceSpan(0, len(text), text, "whole")],
    )


def build_compat_snapshot(project_view):
    """Build the legacy snapshot including XML compatibility sources."""
    root = os.path.abspath(project_view)
    units, diagnostics, source_errors, file_directives = [], [], [], {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in sorted(filenames):
            full_path = os.path.join(dirpath, filename)
            rel = project._relpath(root, full_path)
            lower = filename.lower()
            if not lower.endswith((".st", ".xml")):
                continue
            try:
                text = project._read_text(full_path)
            except OSError as exc:
                family = "st" if lower.endswith(".st") else "xml"
                source_errors.append(project.SourceError(rel, family, f"cannot read {rel}: {exc}"))
                diagnostics.append(Diagnostic("project-read", f"cannot read {rel}: {exc}", location=Location(rel)))
                continue
            if lower.endswith(".st"):
                rules, issues = project.directive_info(text)
                file_directives[rel] = project.FileDirectives(rules, issues)
                unit = project._build_st_unit(rel, text)
            else:
                try:
                    unit = _build_xml_unit(rel, text)
                except ET.ParseError as exc:
                    source_errors.append(_xml_parse_error(rel, text, exc))
                    continue
            if unit is not None:
                units.append(unit)
    by_qual = {u.qualified_name.lower(): u for u in units}
    for unit in units:
        if unit.owner_name and unit.owner_name.lower() in by_qual:
            unit.owner_id = by_qual[unit.owner_name.lower()].id
    units.sort(key=lambda u: u.id)
    return project.ProjectSnapshot(root, units, diagnostics, source_errors, file_directives)
