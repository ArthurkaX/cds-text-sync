# -*- coding: utf-8 -*-
"""Turn decompiled CODESYS scripting-API sources into a JSON snapshot.

The bridge calls into the CODESYS scripting API by *name* -- ``system.get_messages``,
``online.create_online_application``, ``oa.read_value`` -- and a typo or an API move
only shows up on the live stand, as a Python ``AttributeError`` deep inside a daemon
command.  ``cts read-log`` was exactly that class of bug: it called
``get_message_objects`` with a category GUID the storage does not know, and the
failure surfaced as ``Value cannot be null. Parameter name: category``.

This tool reads the *names and declarations* of the scripting API out of a
decompiled assembly tree and writes them to JSON, so ``tools/check_script_api.py``
can verify our calls without CODESYS, without IronPython and without a VM.

Only names and declarations are stored -- never method bodies.  The generated file
carries no CODESYS code; the decompiled tree it is generated from stays outside the
repository.

Usage::

    python tools/script_api_snapshot.py --src <decompiled ScriptEngine3 dir> \\
        --out products/codesys-host/api/scriptengine_api.json

``--src`` is the directory that contains
``_3S.CoDeSys.ScriptEngine.BasicFunctionality/`` (i.e. the ILSpy output of
``ScriptEngine3.dll``).  It is deliberately *not* a default: it is proprietary
CODESYS material and never lives in this repository.
"""

from __future__ import print_function

import argparse
import json
import os
import re
import sys

#: Interfaces live in these subdirectories of the decompiled tree.
_API_DIRS = ("_3S.CoDeSys.ScriptEngine.BasicFunctionality",)

_INTERFACE_RE = re.compile(r"^\s*public\s+interface\s+(\w+)\s*(?::\s*(.*?))?\s*$")
_METHOD_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*[\w<>\[\],\.\?]+\s+(\w+)\s*\(")
_PROPERTY_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)*[\w<>\[\],\.\?]+\s+(\w+)\s*\{\s*(?:get|set)")
_EVENT_RE = re.compile(r"^\s*event\s+[\w<>\[\],\.\?]+\s+(\w+)")
_FAMILY_RE = re.compile(r"^(.*?)(\d*)$")


def family_of(type_name):
    """``IScriptProject7`` -> ``IScriptProject``; a name without a version stays put."""
    match = _FAMILY_RE.match(type_name)
    return match.group(1)


def parse_interfaces(text):
    """Yield ``(type_name, bases, member_name, declaration)`` for one file's source."""
    current = None
    depth = 0
    for raw in text.splitlines():
        if current is None:
            match = _INTERFACE_RE.match(raw)
            if not match:
                continue
            current = match.group(1)
            depth = 0
            continue
        stripped = raw.strip()
        if stripped == "{":
            depth += 1
            continue
        if stripped == "}":
            depth -= 1
            if depth <= 0:
                current = None
            continue
        # Methods and events end with ";", properties with "}" (``bool ui_present { get; }``).
        if depth != 1 or not stripped.endswith((";", "}")):
            continue
        name = None
        for pattern in (_EVENT_RE, _PROPERTY_RE, _METHOD_RE):
            match = pattern.match(stripped)
            if match:
                name = match.group(1)
                break
        if name:
            yield current, name, stripped


def build_snapshot(src_dir):
    """Collect the API surface under ``src_dir`` into a JSON-ready dict."""
    found = {}
    for api_dir in _API_DIRS:
        path = os.path.join(src_dir, api_dir)
        if not os.path.isdir(path):
            continue
        for entry in sorted(os.listdir(path)):
            if not entry.endswith(".cs"):
                continue
            with open(os.path.join(path, entry), "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
            for type_name, member, declaration in parse_interfaces(text):
                types = found.setdefault(family_of(type_name), {})
                members = types.setdefault(type_name, {})
                members.setdefault(member, []).append(declaration)

    families = {}
    for family in sorted(found):
        types = found[family]
        merged = {}
        for type_name in sorted(types, key=_version_key):
            for member in sorted(types[type_name]):
                merged.setdefault(member, {})
                for declaration in sorted(set(types[type_name][member])):
                    merged[member].setdefault(
                        type_name, []
                    ).append(declaration)
        # Flatten to member -> list of declarations, keeping the per-type map out of
        # the way: the checker only needs names, a human reader wants the signatures.
        flat = {}
        for member in sorted(merged):
            declarations = []
            for type_name in sorted(merged[member], key=_version_key):
                for declaration in merged[member][type_name]:
                    if declaration not in declarations:
                        declarations.append(declaration)
            flat[member] = declarations
        families[family] = {
            "types": sorted(types, key=_version_key),
            "members": flat,
        }
    return {
        "note": (
            "Names and declarations of the CODESYS scripting API, extracted from "
            "decompiled ScriptEngine3.dll. No method bodies, no CODESYS code. "
            "Regenerate with tools/script_api_snapshot.py."
        ),
        "families": families,
    }


def _version_key(type_name):
    """Sort ``ISystem`` before ``ISystem2`` before ``ISystem10``."""
    match = _FAMILY_RE.match(type_name)
    suffix = match.group(2)
    return (match.group(1), int(suffix) if suffix else 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--src",
        required=True,
        help="decompiled ScriptEngine3 tree (contains the BasicFunctionality dir)",
    )
    parser.add_argument("--out", required=True, help="JSON file to write")
    args = parser.parse_args(argv)

    snapshot = build_snapshot(args.src)
    families = snapshot["families"]
    if not families:
        print("no interfaces found under " + args.src, file=sys.stderr)
        return 1
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=1, sort_keys=True)
        handle.write("\n")
    print(
        "{0} families, {1} members -> {2}".format(
            len(families),
            sum(len(f["members"]) for f in families.values()),
            args.out,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
