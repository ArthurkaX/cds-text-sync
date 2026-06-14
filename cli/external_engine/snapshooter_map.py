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


def _is_excluded_from_build(node, model, _seen=None):
    """Return True if node or any ancestor is marked ExcludeFromBuild.

    Walks parent_guid links, guarding against cycles / missing parents.
    """
    if _seen is None:
        _seen = set()
    if node is None or node.guid in _seen:
        return False
    _seen.add(node.guid)
    exclude = node.metadata.get("exclude_from_build")
    if exclude is True:
        return True
    if node.parent_guid:
        parent = model.get_node(node.parent_guid)
        if parent is not None:
            return _is_excluded_from_build(parent, model, _seen)
    return False


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
    stats = {"owners": 0, "members": 0, "leaves": 0, "readable": 0, "excluded": 0}
    owner_scopes = {
        "gvl": ("VAR_GLOBAL",),
        "program": ("VAR", "VAR_GLOBAL"),
    }

    for owner, kind, decl, node in owners:
        if kind not in ("gvl", "program"):
            continue
        owner_excluded = _is_excluded_from_build(node, model)
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
                    row = {
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
                    }
                    if owner_excluded:
                        row["excluded_from_build"] = True
                        if lf["leaf"]:
                            stats["excluded"] += 1
                    rows.append(row)

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
