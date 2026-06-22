# -*- coding: utf-8 -*-
"""
commands.py - cts visu command implementations (offline).

These functions are thin: they resolve the target screen file, call the
builder/catalog engine, write the result into project-view, and print a result.
They never touch the daemon or import.
"""

from __future__ import print_function

import os
import sys

from . import builder
from . import catalog as _catalog


def _err(msg):
    print("[ERROR] {0}".format(msg), file=sys.stderr)


def _ok(msg):
    print("[OK] {0}".format(msg), file=sys.stderr)


def _folder_to_dir(project_view_dir, folder):
    """Map a CODESYS folder path (e.g. 'Runtime/PLC Logic/...') to a real dir."""
    folder = (folder or "").replace("\\", "/").strip("/")
    if not folder:
        return project_view_dir
    return os.path.join(project_view_dir, *folder.split("/"))


def _resolve_screen_path(project_view_dir, screen, folder):
    """Resolve --screen (name or path) to an absolute .xml path.

    If ``screen`` is an existing path, use it. Otherwise treat it as a name
    under ``folder`` (relative to project-view). When ``folder`` is omitted or
    the name is not found there, fall back to a recursive search of
    project-view for ``<name>.xml`` (so callers need not repeat --folder).
    """
    if os.path.isabs(screen) and os.path.isfile(screen):
        return screen
    if os.path.isfile(screen):
        return os.path.abspath(screen)
    name = screen if screen.endswith(".xml") else screen + ".xml"
    target_dir = _folder_to_dir(project_view_dir, folder)
    candidate = os.path.join(target_dir, name)
    if os.path.isfile(candidate):
        return candidate
    # Recursive fallback: find <name>.xml anywhere under project-view.
    matches = []
    for dirpath, _dirs, files in os.walk(project_view_dir):
        if name in files:
            matches.append(os.path.join(dirpath, name))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        _err(
            "Screen name '{0}' is ambiguous ({1} matches); pass --folder to "
            "disambiguate:\n  {2}".format(
                screen, len(matches), "\n  ".join(matches)
            )
        )
        sys.exit(1)
    return candidate


# ---------------------------------------------------------------------------
# create-screen
# ---------------------------------------------------------------------------


def create_screen(project_view_dir, name, folder, width, height, start_visu):
    target_dir = _folder_to_dir(project_view_dir, folder)
    if not os.path.isdir(target_dir):
        _err(
            "Target folder does not exist: {0}\n"
            "Point --folder at an existing project-view folder.".format(target_dir)
        )
        sys.exit(1)

    sibling = builder.find_sibling_object(target_dir)
    if sibling is None:
        _err(
            "Folder '{0}' contains no existing object to copy placement from.\n"
            "Placement (ParentGuid/ParentSVNodeGuid) is derived from a sibling "
            "object. Choose a folder that already contains at least one object.".format(
                folder
            )
        )
        sys.exit(1)

    placement = builder.read_placement_from_sibling(sibling)
    out_path = os.path.join(target_dir, name + ".xml")
    if os.path.exists(out_path):
        _err("Screen already exists: {0}".format(out_path))
        sys.exit(1)

    xml_text = builder.build_screen(
        name=name,
        size_x=width,
        size_y=height,
        parent_guid=placement["parent_guid"],
        parent_svnode_guid=placement["parent_svnode_guid"],
        path_segments=placement["path"],
        is_start_visu=start_visu,
    )
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(xml_text)
    _ok("Created screen {0} ({1}x{2}) at {3}".format(name, width, height, out_path))
    print(out_path)


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


def add_element(project_view_dir, screen, folder, type_name, params):
    path = _resolve_screen_path(project_view_dir, screen, folder)
    if not os.path.isfile(path):
        _err("Screen file not found: {0}".format(path))
        sys.exit(1)
    try:
        catalog = _catalog.load_catalog(type_name)
    except _catalog.CatalogError as exc:
        _err(str(exc))
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as handle:
        xml_text = handle.read()
    try:
        new_xml, geometry, info = builder.append_element(xml_text, catalog, params)
    except builder.BuilderError as exc:
        _err(str(exc))
        sys.exit(1)

    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(new_xml)
    _ok(
        "Added {0} '{1}' at X={2} Y={3} W={4} H={5} (Center {6},{7})".format(
            info["type"],
            info["identifier"],
            geometry["x"],
            geometry["y"],
            geometry["width"],
            geometry["height"],
            geometry["center_x"],
            geometry["center_y"],
        )
    )


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def list_screen(project_view_dir, screen, folder):
    path = _resolve_screen_path(project_view_dir, screen, folder)
    if not os.path.isfile(path):
        _err("Screen file not found: {0}".format(path))
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as handle:
        xml_text = handle.read()
    elements = builder.list_elements(xml_text)
    if not elements:
        print("(no elements)")
        return
    print(
        "{0:<3} {1:<16} {2:<16} {3:>6} {4:>6} {5:>6} {6:>6}".format(
            "Idx", "Type", "Identifier", "X", "Y", "W", "H"
        )
    )
    for el in elements:
        print(
            "{0:<3} {1:<16} {2:<16} {3:>6} {4:>6} {5:>6} {6:>6}".format(
                el["index"],
                el["type"],
                el["identifier"],
                el.get("x") or "-",
                el.get("y") or "-",
                el.get("width") or "-",
                el.get("height") or "-",
            )
        )


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def check_screen(project_view_dir, screen, folder):
    path = _resolve_screen_path(project_view_dir, screen, folder)
    if not os.path.isfile(path):
        _err("Screen file not found: {0}".format(path))
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as handle:
        xml_text = handle.read()

    size_x, size_y = builder.read_screen_size(xml_text)
    elements = builder.list_elements(xml_text)
    problems = []
    boxes = []

    for el in elements:
        members = el.get("members", {})
        try:
            x = int(el.get("x") or 0)
            y = int(el.get("y") or 0)
            w = int(el.get("width") or 0)
            h = int(el.get("height") or 0)
        except ValueError:
            problems.append("{0}: non-numeric geometry".format(el["identifier"]))
            continue

        for e in builder.validate_bounds(
            {"x": x, "y": y, "width": w, "height": h}, size_x, size_y
        ):
            problems.append("{0}: {1}".format(el["identifier"], e))

        cx = members.get(550940142, {}).get("value")
        cy = members.get(1473355128, {}).get("value")
        if cx is not None and str(cx).strip() != str(x + w // 2):
            problems.append(
                "{0}: CenterX {1} != X+W/2 ({2})".format(el["identifier"], cx, x + w // 2)
            )
        if cy is not None and str(cy).strip() != str(y + h // 2):
            problems.append(
                "{0}: CenterY {1} != Y+H/2 ({2})".format(el["identifier"], cy, y + h // 2)
            )

        # Color CanonicalName non-empty.
        for mid, m in members.items():
            if m.get("kind") == "color" and not (m.get("canonical_name") or "").strip():
                problems.append(
                    "{0}: color member {1} has empty CanonicalName".format(
                        el["identifier"], mid
                    )
                )

        # Text / Text-ID invariant.
        text_m = members.get(390574330, {})
        if (text_m.get("value") or "").strip():
            if not (members.get(823443203, {}).get("value") or "").strip():
                problems.append(
                    "{0}: has non-empty text but no Text ID (823443203); "
                    "CODESYS will reject the import".format(el["identifier"])
                )

        boxes.append((el["identifier"], x, y, w, h))

    # Basic overlap detection.
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if _overlap(a[1:], b[1:]):
                problems.append("overlap: {0} overlaps {1}".format(a[0], b[0]))

    if problems:
        for p in problems:
            print("[FAIL] {0}".format(p))
        _err("{0} problem(s) found".format(len(problems)))
        sys.exit(1)
    _ok("Screen OK: {0} element(s), no problems".format(len(elements)))


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


# ---------------------------------------------------------------------------
# types
# ---------------------------------------------------------------------------


def list_types():
    types = _catalog.list_types()
    if not types:
        print("(no catalog types)")
        return
    for t in types:
        try:
            cat = _catalog.load_catalog(t)
            desc = cat.get("description", "")
        except _catalog.CatalogError:
            desc = ""
        print("{0:<14} {1}".format(t, desc))


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------


def describe(project_view_dir, type_name, screen=None, folder="", elem=None):
    try:
        catalog = _catalog.load_catalog(type_name)
    except _catalog.CatalogError as exc:
        _err(str(exc))
        sys.exit(1)

    print("Type: {0}  (VisualElementTypeName={1})".format(
        catalog["type"], catalog["visualElementTypeName"]))
    if catalog.get("description"):
        print(catalog["description"])
    print("")

    variants = catalog.get("shape_variants")
    if variants:
        print("Shape variants:")
        for k, v in sorted(variants.items()):
            print("  {0:<12} -> {1}".format(k, v))
        print("")

    print("Settable properties:")
    for pname, spec in sorted(catalog.get("params", {}).items()):
        default = _default_for_param(catalog, spec)
        flags = []
        if spec.get("geometry"):
            flags.append("geometry")
        if spec.get("requires"):
            flags.append("requires={0}".format(spec["requires"]))
        flag_s = " [{0}]".format(", ".join(flags)) if flags else ""
        print(
            "  {0:<14} kind={1:<8} default={2!r:<20} {3}{4}".format(
                pname,
                spec.get("kind", ""),
                default,
                spec.get("doc", ""),
                flag_s,
            )
        )
    print("")

    bindings = catalog.get("optional_bindings")
    if bindings:
        print("Optional bindings (variable references):")
        for bname, spec in sorted(bindings.items()):
            print("  {0:<14} member={1:<12} {2}".format(
                bname, spec.get("member_id"), spec.get("doc", "")))
        print("")

    invariants = catalog.get("invariants")
    if invariants:
        print("Invariants:")
        for inv in invariants:
            print("  [{0}] {1}".format(inv.get("severity", "?"), inv.get("rule", "")))
        print("")

    if screen:
        path = _resolve_screen_path(project_view_dir, screen, folder)
        if not os.path.isfile(path):
            _err("Screen file not found: {0}".format(path))
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as handle:
            xml_text = handle.read()
        elements = builder.list_elements(xml_text)
        if elem is None:
            return
        if elem < 0 or elem >= len(elements):
            _err("Element index {0} out of range (0..{1})".format(elem, len(elements) - 1))
            sys.exit(1)
        target = elements[elem]
        print("Element #{0}: {1} ({2})".format(elem, target["identifier"], target["type"]))
        for mid, m in sorted(target.get("members", {}).items()):
            if m.get("kind") == "color":
                print("  {0:<12} color={1} canonical={2}".format(
                    mid, m.get("color"), m.get("canonical_name")))
            else:
                print("  {0:<12} {1!r}".format(mid, m.get("value")))


def _default_for_param(catalog, spec):
    mid = spec.get("member_id")
    for m in catalog.get("base_members", []):
        if m.get("id") == mid:
            if m.get("form") == "color":
                return m.get("color")
            return m.get("value")
    return None
