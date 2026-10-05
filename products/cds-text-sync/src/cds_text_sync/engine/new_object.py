# -*- coding: utf-8 -*-
"""Create a project-view object (GVL / POU / DUT) without the IDE.

Writing the object by hand means knowing three things that are nowhere in the
help: the type GUID, the exact ST shape CODESYS accepts, and -- the trap --
that a ``.st`` with a sibling ``.xml`` is discovered by *neither* of the
reader's pending-object passes, so the pair silently needs a hand-written
manifest entry. This module encodes the first two and avoids the third by
writing the one file the reader actually looks for.

The whole flow is offline. Writing ``<view>/<parent>/<Name>.st`` is enough for
the next ``cts compare`` to report ``added=1`` and for ``cts import`` to hand
the object to ``CreateTextObjects``; no manifest entry is written, because
``FolderReader`` discovers an unmanaged ``.st`` by its own declaration keyword
(``VAR_GLOBAL``, ``PROGRAM``, ``TYPE``, ...) and gives it a synthetic
``create:<sha1>`` guid. Nothing here talks to the daemon.

IronPython 2.7 compatible (no f-strings, no annotations, no pathlib): the
module lives in the engine package, whose neighbours the CODESYS host imports.
"""

from __future__ import print_function

import os
import re

from ._manifest_bookkeeper import entries as manifest_entries
from ._manifest_bookkeeper import load as load_manifest
from ._project_layout import resolve_layout
from ._project_settings import read_project_settings


class NewObjectError(Exception):
    """A refused creation. ``exit_code`` is what the CLI should return."""

    def __init__(self, message, exit_code=1):
        Exception.__init__(self, message)
        self.message = message
        self.exit_code = exit_code


#: Object kinds this command can create, and the declaration keyword the
#: reader's pending-object pass looks for to recognise each one. A file whose
#: first meaningful word is not one of these needs a TypeGuid pragma instead.
KIND_KEYWORDS = {"gvl": "VAR_GLOBAL", "pou": "PROGRAM", "dut": "TYPE"}

#: Type GUIDs as ``profiles/default.json`` records them. They are informational
#: here (the reader detects the kind from the text); the CLI reports them so an
#: author who does need the pragma form has the right value.
KIND_TYPE_GUIDS = {
    "gvl": "ffbfa93a-b94d-45fc-a329-229860183b1d",
    "pou": "6f9dac99-8de1-4efc-8465-68ac443b7d08",
    "dut": "2db5746d-d284-4425-9f7f-2663a34b0ebc",
}

POU_KINDS = ("program", "function", "function-block")
DUT_KINDS = ("struct", "enum", "union", "alias")

#: Refused as object names. Not the full IEC keyword list -- only the words
#: that would change how the reader classifies the file or make CODESYS reject
#: the declaration outright.
RESERVED_WORDS = frozenset([
    "PROGRAM", "FUNCTION", "FUNCTION_BLOCK", "TYPE", "VAR", "VAR_GLOBAL",
    "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_TEMP", "VAR_STAT",
    "END_VAR", "END_PROGRAM", "END_FUNCTION", "END_FUNCTION_BLOCK",
    "END_TYPE", "STRUCT", "END_STRUCT", "UNION", "END_UNION", "ENUM",
    "METHOD", "END_METHOD", "ACTION", "END_ACTION", "PROPERTY", "END_PROPERTY",
    "IF", "THEN", "ELSE", "ELSIF", "END_IF", "CASE", "END_CASE", "FOR",
    "END_FOR", "WHILE", "END_WHILE", "REPEAT", "END_REPEAT", "RETURN",
    "TRUE", "FALSE", "NULL",
])

#: ``// --- implementation ---``: where the reader splits a new object's
#: declaration from its body, and where CODESYS' create path expects the cut.
IMPLEMENTATION_MARKER = "// --- implementation ---"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VAR_GLOBAL_RE = re.compile(r"^\s*VAR_GLOBAL\b", re.IGNORECASE | re.MULTILINE)


def validate_name(name):
    """Return the trimmed *name*, or raise for one CODESYS cannot accept."""
    text = (name or "").strip()
    if not text:
        raise NewObjectError("An object name is required.")
    if not _IDENTIFIER_RE.match(text):
        raise NewObjectError(
            "Invalid object name {0!r}: an IEC identifier must start with a "
            "letter or underscore and contain only letters, digits and "
            "underscores.".format(text)
        )
    if text.upper() in RESERVED_WORDS:
        raise NewObjectError(
            "{0!r} is a reserved IEC keyword and cannot be an object "
            "name.".format(text)
        )
    return text


def _normalize_parent(parent):
    """``--parent`` as a relative folder path, without separators or dots."""
    text = str(parent or "").replace("\\", "/").strip()
    parts = [part for part in text.split("/") if part and part != "."]
    if any(part == os.pardir or part == ".." for part in parts):
        raise NewObjectError(
            "Parent path may not leave the sync folder: {0!r}".format(parent)
        )
    return "/".join(parts)


def _application_prefix(path):
    """The part of a view path through its ``Application`` segment, or ``""``."""
    parts = str(path or "").replace("\\", "/").strip("/").split("/")
    for index, part in enumerate(parts):
        if part.lower() == "application":
            return "/".join(parts[: index + 1])
    return ""


def default_parent(manifest):
    """The Application folder recorded in the manifest, or ``""``.

    The view tree mirrors the CODESYS tree (``Runtime/PLC Logic/Application``),
    so the Application's own folder is the one an entry's path reaches through
    a segment named ``Application``. Several may match (one per device); the
    shortest is the most likely application, and ties break on the path text,
    so the answer is deterministic rather than dependent on manifest order.
    """
    candidates = set()
    for entry in manifest_entries(manifest):
        paths = [entry.get("xml_path"), entry.get("view_path")]
        paths.extend(entry.get("projection_paths") or [])
        for raw in paths:
            found = _application_prefix(raw)
            if found:
                candidates.add(found)
    if not candidates:
        return ""
    return sorted(candidates, key=lambda item: (item.count("/"), item.lower()))[0]


def sibling_names(directory, manifest, parent):
    """Names already taken in *directory*, compared case-insensitively.

    Both sources matter: a file on disk is what the reader will discover, while
    a manifest entry is the only record of an object whose files were moved or
    whose xml lives in ``.dump``. Checking just one lets a create collide with
    an object the other one knows about, and CODESYS answers that with a modal
    dialog the daemon cannot dismiss.
    """
    names = set()
    if os.path.isdir(directory):
        for entry in os.listdir(directory):
            stem = os.path.splitext(entry)[0]
            if stem.endswith(".cds-object"):
                continue
            names.add(stem.lower())
    prefix = (parent + "/") if parent else ""
    for record in manifest_entries(manifest):
        paths = [record.get("xml_path"), record.get("view_path")]
        paths.extend(record.get("projection_paths") or [])
        for raw in paths:
            path = str(raw or "").replace("\\", "/").strip("/")
            if not path.startswith(prefix):
                continue
            rest = path[len(prefix):]
            if "/" in rest or not rest:
                continue
            names.add(os.path.splitext(rest)[0].split(".cds-object")[0].lower())
    return names


def build_gvl(name, body):
    """A GVL's declaration. *body* is the inside of the VAR_GLOBAL block.

    A body that is already a whole ``VAR_GLOBAL ... END_VAR`` block is passed
    through: pasting a GVL's own text back in is the obvious thing to try, and
    wrapping it again would nest the block and fail to compile.
    """
    text = (body or "").strip("\n")
    if _VAR_GLOBAL_RE.match(text):
        return text.rstrip("\n") + "\n"
    if not text.strip():
        return "VAR_GLOBAL\nEND_VAR\n"
    lines = ["    " + line.strip() for line in text.splitlines() if line.strip()]
    return "VAR_GLOBAL\n{0}\nEND_VAR\n".format("\n".join(lines))


def build_pou(name, kind, body, return_type=""):
    """A POU's declaration and body, with the reader's split marker.

    The marker is always written, even for an empty body: it is where the
    reader splits declaration from implementation, and having it there from the
    start means the author types below the line instead of discovering the
    convention later.
    """
    header = "PROGRAM {0}".format(name)
    if kind == "function":
        header = "FUNCTION {0} : {1}".format(name, return_type or "BOOL")
    elif kind == "function-block":
        header = "FUNCTION_BLOCK {0}".format(name)
    lines = [header, "VAR", "END_VAR", IMPLEMENTATION_MARKER]
    text = (body or "").strip("\n")
    if text.strip():
        lines.append(text)
    return "\n".join(lines).rstrip("\n") + "\n"


def build_dut(name, kind, body, base_type=""):
    """A DUT's declaration, in the shape CODESYS types each kind."""
    text = (body or "").strip("\n")
    if kind == "alias":
        target = (base_type or "").strip()
        if not target:
            raise NewObjectError(
                "An ALIAS needs its target type: pass --base-type <TYPE> (or "
                "give the whole declaration with --text/--text-file)."
            )
        return "TYPE {0} : {1};\nEND_TYPE\n".format(name, target)
    if kind == "struct":
        return _wrapped_type(name, "STRUCT", "END_STRUCT", text)
    if kind == "union":
        return _wrapped_type(name, "UNION", "END_UNION", text)
    # ENUM: an empty member list is not valid IEC, so seed one member.
    if text.strip():
        return _wrapped_type(name, "(", ");", text)
    return "TYPE {0} :\n(\n    Member1 := 0\n);\nEND_TYPE\n".format(name)


def _wrapped_type(name, opener, closer, text):
    """``TYPE <name> : <opener> ... <closer> END_TYPE`` around a body."""
    lines = ["TYPE {0} :".format(name), opener]
    if text.strip():
        lines.append(text)
    lines.append(closer)
    lines.append("END_TYPE")
    return "\n".join(lines).rstrip("\n") + "\n"


def build_body(kind, name, text="", pou_kind="", dut_kind="", return_type="", base_type=""):
    """The ``.st`` file's text for one new object."""
    if kind == "gvl":
        return build_gvl(name, text)
    if kind == "pou":
        return build_pou(name, pou_kind, text, return_type=return_type)
    return build_dut(name, dut_kind, text, base_type=base_type)


def _read_body_file(path):
    if not os.path.isfile(path):
        raise NewObjectError("Text file not found: {0}".format(path))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except (IOError, OSError, UnicodeDecodeError) as error:
        raise NewObjectError("Could not read {0}: {1}".format(path, error))


def resolve_roots(sync_folder, view_root=None):
    """``(sync_root, view_root)``, from the project's own settings.

    Settings are read with warnings off: the CLI prints a JSON report, and a
    warning about a broken settings file would land inside it.
    """
    root = os.path.abspath(str(sync_folder))
    try:
        settings = read_project_settings(root, warn=False)[0]
    except Exception:
        settings = {}
    layout = resolve_layout(
        root,
        view_root=view_root or settings.get("view_root"),
        layout_mode=settings.get("layout"),
    )
    return root, layout.view_root


def _validate_request(kind, name, pou_kind, dut_kind, language):
    """Every refusal that can be decided before touching the filesystem."""
    if kind not in KIND_KEYWORDS:
        raise NewObjectError(
            "Unknown object kind {0!r}. Expected one of: {1}.".format(
                kind, ", ".join(sorted(KIND_KEYWORDS))
            )
        )
    if str(language or "st").strip().lower() != "st":
        raise NewObjectError(
            "Only Structured Text is supported (--language st): the import path "
            "creates textual objects, so a graphical POU cannot be authored here."
        )
    name = validate_name(name)
    _validate_subkind(kind, pou_kind, dut_kind)
    return name


def _target_folder(views, parent_path):
    """The absolute folder to write into, or raise if it is not there."""
    directory = os.path.join(views, *parent_path.split("/")) if parent_path else views
    if not os.path.isdir(directory):
        raise NewObjectError(
            "Parent folder does not exist in the view: {0}. Pass --parent with "
            "an existing project-tree path.".format(parent_path or "<view root>")
        )
    return directory


def _refuse_if_taken(directory, manifest, parent_path, name):
    if name.lower() in sibling_names(directory, manifest, parent_path):
        raise NewObjectError(
            "An object named {0!r} already exists in {1}. Creating it again "
            "would overwrite or collide with it; edit that object "
            "instead.".format(name, parent_path or "<view root>")
        )


def _write_new_file(full_path, body):
    """Write the ``.st``. Only the ``.st`` -- see :func:`create_object`."""
    try:
        with open(full_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
    except (IOError, OSError) as error:
        raise NewObjectError("Could not write {0}: {1}".format(full_path, error))


def _next_steps(kind):
    """The ordered next steps. A new object must be referenced to reach the PLC.

    CODESYS loads only objects reachable from a task's call tree, so a new
    object that nothing uses is compiled out: a full download alone is not
    enough. A GVL or POU is reached by a call; a DUT is reached only through a
    variable that uses the type, in code the task calls. A full download is
    still needed *after* it is referenced, or the PLC's symbol table stays
    stale.
    """
    steps = ["cts compare", "cts import"]
    if kind in ("gvl", "pou"):
        steps.append(
            "Reference it from a POU the task calls, or the PLC never gets it: "
            "CODESYS loads only objects reachable from a task's call tree "
            "(for a GVL, add e.g. `GVL.x;` to MAIN)."
        )
    elif kind == "dut":
        steps.append(
            "Reference it from a variable in code the task calls, or the PLC "
            "never gets it: CODESYS loads a type only through a variable that "
            "uses it, in code reachable from a task's call tree."
        )
    steps.append(
        "cts download  # full download, after the object is referenced, before "
        "its symbols are readable"
    )
    return steps


def _new_object_report(kind, name, parent_path, views, relative, full_path, body):
    """The JSON the CLI prints: what was written and what to run next."""
    result = {
        "kind": kind,
        "name": name,
        "parent": parent_path,
        "view_root": views,
        "path": relative,
        "files": [full_path],
        "type_guid": KIND_TYPE_GUIDS.get(kind, ""),
        "bytes": len(body.encode("utf-8")),
        "discovery": "pending-create (no manifest entry needed)",
        "next": _next_steps(kind),
    }
    note = _placeholder_note(kind, body)
    if note:
        result["note"] = note
    return result


def _prepare_target(sync_folder, name, parent, view_root=None):
    """``(views, manifest, parent_path)``, with every refusal short of writing.

    Split out of :func:`create_object` so the checks read as one list: the view
    root must exist, the parent folder must exist in it, and the name must be
    free -- against both the files on disk and the manifest.
    """
    root, views = resolve_roots(sync_folder, view_root=view_root)
    if not os.path.isdir(views):
        raise NewObjectError(
            "No view root at {0}. Export the project once (cts export) before "
            "creating objects in it.".format(views)
        )
    manifest = load_manifest(os.path.join(root, ".dump", "manifest.json"))
    parent_path = _resolve_parent(parent, manifest, views)
    directory = _target_folder(views, parent_path)
    _refuse_if_taken(directory, manifest, parent_path, name)
    return views, manifest, parent_path


def _describe_subkind(kind, pou_kind, dut_kind, return_type, base_type):
    """The sub-kind fields a caller set, for the report."""
    pairs = (
        ("pou_kind", pou_kind),
        ("dut_kind", dut_kind),
        ("return_type", return_type if kind == "pou" else ""),
        ("base_type", base_type if kind == "dut" else ""),
    )
    return dict((key, value) for key, value in pairs if value)


def create_object(
    sync_folder,
    kind,
    name,
    parent="",
    text="",
    text_file="",
    pou_kind="",
    dut_kind="",
    return_type="",
    base_type="",
    view_root=None,
    language="st",
):
    """Write one new object into the view and return the report dict.

    Raises :class:`NewObjectError` for every refusal (bad name, missing parent,
    an occupied name, an unsupported kind). Nothing is written until every
    check has passed, so a refused call leaves no half-created object behind.

    Only the ``.st`` is written, never a sibling ``.xml``: the reader's ST pass
    skips any file that has one (it reads that as an externalized-text
    projection) and its XML pass skips the same pair from the other side, so a
    ``Name.st`` + ``Name.xml`` pair is discovered by nothing at all.
    """
    name = _validate_request(kind, name, pou_kind, dut_kind, language)
    views, _manifest, parent_path = _prepare_target(
        sync_folder, name, parent, view_root=view_root
    )
    if text_file:
        text = _read_body_file(text_file)
    body = build_body(
        kind,
        name,
        text=text,
        pou_kind=pou_kind,
        dut_kind=dut_kind,
        return_type=return_type,
        base_type=base_type,
    )
    relative = "/".join([parent_path, name + ".st"]) if parent_path else name + ".st"
    full_path = os.path.join(views, *relative.split("/"))
    _write_new_file(full_path, body)
    report = _new_object_report(
        kind, name, parent_path, views, relative, full_path, body
    )
    report.update(_describe_subkind(kind, pou_kind, dut_kind, return_type, base_type))
    return report


def _validate_subkind(kind, pou_kind, dut_kind):
    """Refuse a missing or unknown ``--kind`` for POU/DUT before any I/O."""
    if kind == "pou":
        if pou_kind not in POU_KINDS:
            raise NewObjectError(
                "A POU needs --kind {0} (got {1!r}).".format(
                    "|".join(POU_KINDS), pou_kind or ""
                )
            )
    elif kind == "dut":
        if dut_kind not in DUT_KINDS:
            raise NewObjectError(
                "A DUT needs --kind {0} (got {1!r}).".format(
                    "|".join(DUT_KINDS), dut_kind or ""
                )
            )
    return kind


def _resolve_parent(parent, manifest, views):
    """The folder path to write into: ``--parent``, else the Application."""
    if parent:
        return _normalize_parent(parent)
    discovered = default_parent(manifest)
    if not discovered:
        raise NewObjectError(
            "Could not tell which folder is the active application: the "
            "manifest records no object under a folder named 'Application'. "
            "Pass --parent <path>, e.g. --parent 'Runtime/PLC Logic/Application'."
        )
    return discovered


def _placeholder_note(kind, body):
    """Say when the template itself is not yet valid IEC and needs an edit."""
    text = body or ""
    if "Member1 := 0" in text:
        return (
            "The empty enum was seeded with one member (Member1 := 0) because "
            "an enum with no members is not valid IEC; rename or replace it."
        )
    if kind == "pou" and text.rstrip().endswith(IMPLEMENTATION_MARKER):
        return (
            "The POU was created with an empty body; add statements below the "
            "'{0}' marker, or edit the file before importing.".format(
                IMPLEMENTATION_MARKER
            )
        )
    return ""


__all__ = [
    "DUT_KINDS",
    "KIND_TYPE_GUIDS",
    "NewObjectError",
    "POU_KINDS",
    "build_body",
    "create_object",
    "default_parent",
    "resolve_roots",
    "sibling_names",
    "validate_name",
]
