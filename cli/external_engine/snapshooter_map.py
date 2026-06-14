# -*- coding: utf-8 -*-
"""
snapshooter_map.py - Build Snapshooter variable tree from native IDE.xml.

This module runs in CPython via engine_cli.py. CODESYS/IronPython only exports
the native snapshot; parsing and type expansion stay in the external engine.
"""

from __future__ import print_function

import json
import os

import variable_map
from snapshot_reader import SnapshotReader


def _node_decl(node):
    decl, _impl = variable_map.split_decl_impl(node.code or "")
    return decl


def _node_owner_name(node, decl):
    return variable_map.pou_name(decl, node.name) or node.name


def build_snapshooter_map(snapshot_path, project_name=""):
    model = SnapshotReader(snapshot_path, project_name=project_name).read()
    registry = variable_map.TypeRegistry()
    owners = []

    for node in model.nodes.values():
        if not node.code:
            continue
        decl = _node_decl(node)
        kind = variable_map.detect_owner_kind(decl)
        owner = _node_owner_name(node, decl)
        if kind == "dut":
            registry.add_dut(decl)
        elif kind == "function_block":
            registry.add_fb(owner, decl)
        registry.add_constants_from_gvl(owner, decl)
        owners.append((owner, kind, decl, node))

    rows = []
    stats = {"owners": 0, "members": 0, "leaves": 0, "readable": 0}
    owner_scopes = {
        "gvl": ("VAR_GLOBAL",),
        "program": ("VAR", "VAR_GLOBAL"),
    }

    for owner, kind, decl, node in owners:
        if kind not in ("gvl", "program"):
            continue
        stats["owners"] += 1
        for block in variable_map.parse_var_blocks(decl):
            if block["scope"] not in owner_scopes.get(kind, ()):
                continue
            for mem in block["members"]:
                stats["members"] += 1
                root_path = owner + "." + mem["name"]
                leaves = variable_map.expand_leaves(root_path, mem["type"], registry)
                for lf in leaves:
                    stats["leaves"] += 1
                    if lf["leaf"]:
                        stats["readable"] += 1
                    leaf_name = lf["path"].rsplit(".", 1)[-1]
                    is_root = lf["path"] == root_path
                    rows.append({
                        "path": lf["path"],
                        "name": leaf_name,
                        "type": lf["type"],
                        "scope": block["scope"],
                        "owner": owner,
                        "file": node.get_view_path(model, extension=".st"),
                        "line": mem["line"],
                        "initial": mem["initial"] if is_root else "",
                        "leaf": lf["leaf"],
                        "note": lf["note"],
                    })

    rows.sort(key=lambda r: r.get("path", "").lower())
    return {
        "source": os.path.abspath(snapshot_path),
        "stats": stats,
        "rows": rows,
    }


def write_snapshooter_map(snapshot_path, output_path, project_name=""):
    data = build_snapshooter_map(snapshot_path, project_name=project_name)
    directory = os.path.dirname(os.path.abspath(output_path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return data
