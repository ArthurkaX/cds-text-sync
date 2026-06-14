# -*- coding: utf-8 -*-
"""
project_snapshooter.pyw - PLC variable preset snapshots.

Shared backend for the CODESYS Project_snapshooter.py entrypoint and the
future cts snapshooter CLI. Keep UI concerns at the edge; this module owns the
preset format, path resolution, read/compare/restore logic, and file IO.
"""

from __future__ import print_function

import io
import json
import os
import pickle
import re
import sys
import tempfile
import time

import ide_export_snapshot
import ide_online_helpers as _helpers
import ide_runtime_common


# --- Temporary diagnostic logger --------------------------------------------
# Writes to <sync-folder>/.dump/snapshooter.log AND %TEMP%/snapshooter.log
# with millisecond timestamps. Also echoes to the scripting console via print.
# Remove when the freeze is diagnosed.
_SNAPSHOOTER_LOG_PATHS = None


def _log_resolve_paths():
    global _SNAPSHOOTER_LOG_PATHS
    if _SNAPSHOOTER_LOG_PATHS is not None:
        return _SNAPSHOOTER_LOG_PATHS
    paths = []
    sync = None
    try:
        proj = None
        state = getattr(sys, "_codesys_daemon_loop", None)
        if isinstance(state, dict):
            try:
                proj = state.get("projects").primary
            except Exception:
                proj = None
        if proj is None:
            try:
                import __main__
                pmain = getattr(__main__, "projects", None)
                if pmain is not None:
                    proj = pmain.primary
            except Exception:
                proj = None
        if proj is not None:
            try:
                pi = proj.get_project_info()
            except Exception:
                pi = None
            if pi is None:
                try:
                    pi = proj.project_info
                except Exception:
                    pi = None
            if pi is not None:
                values = getattr(pi, "values", pi)
                try:
                    sync = values["cds-sync-folder"]
                except Exception:
                    try:
                        sync = values.get("cds-sync-folder", "")
                    except Exception:
                        sync = None
    except Exception:
        pass
    if sync:
        paths.append(os.path.join(sync, ".dump", "snapshooter.log"))
    try:
        paths.append(os.path.join(tempfile.gettempdir(), "snapshooter.log"))
    except Exception:
        pass
    try:
        paths.append(os.path.join(os.getcwd(), "snapshooter.log"))
    except Exception:
        pass
    _SNAPSHOOTER_LOG_PATHS = paths
    return paths


def _log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    ms = int((time.time() % 1) * 1000)
    line = "{0}.{1:03d} {2}".format(ts, ms, msg)
    try:
        print("[snapshooter] " + line)
    except Exception:
        pass
    for path in _log_resolve_paths():
        try:
            directory = os.path.dirname(path)
            if directory and not os.path.isdir(directory):
                try:
                    os.makedirs(directory)
                except Exception:
                    continue
            with io.open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
        except Exception:
            continue
# ----------------------------------------------------------------------------


FORMAT_VERSION = 1
TUI_WIDTH = 63
TUI_BODY_HEIGHT = 12
_SNAPSHOOTER_ROWS_BY_PATH = {}


class TuiNode(object):
    __slots__ = (
        "name", "path", "type", "value", "leaf", "parent", "children",
        "expanded", "source_kind", "leaf_count", "search_text",
        "excluded_from_build",
    )

    def __init__(self, name, path="", typ="", value="", leaf=False, parent=None):
        self.name = name
        self.path = path
        self.type = typ
        self.value = value
        self.leaf = leaf
        self.parent = parent
        self.children = []
        self.expanded = False
        self.source_kind = ""
        self.leaf_count = 1 if leaf else 0
        self.search_text = ""
        self.excluded_from_build = False

    def add_child(self, child):
        self.children.append(child)
        child.parent = self
        self.leaf_count += child.leaf_count
        return child

    def leaves(self):
        if self.leaf:
            return [self]
        out = []
        for child in self.children:
            out.extend(child.leaves())
        return out

    def branch_counts(self):
        gvl = 0
        prg = 0
        for child in self.children:
            owner = (child.source_kind or "").lower()
            if owner == "program":
                prg += 1
            else:
                gvl += 1
        return gvl, prg


def _ensure_engine_path():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.dirname(os.path.dirname(here))
    engine = os.path.join(repo, "cli", "external_engine")
    if os.path.isdir(engine) and engine not in sys.path:
        sys.path.insert(0, engine)


def _now_text():
    return time.strftime("%Y-%m-%dT%H:%M")


def _text(value):
    if value is None:
        return ""
    try:
        return unicode(value)  # noqa: F821 - IronPython
    except NameError:
        return str(value)


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "ok")


def _get_active_project(project=None):
    if project is not None:
        return project
    state = getattr(sys, "_codesys_daemon_loop", None)
    if isinstance(state, dict):
        projects = state.get("projects")
        if projects is not None:
            try:
                if projects.primary is not None:
                    return projects.primary
            except Exception:
                pass
    try:
        import __main__
        projects = getattr(__main__, "projects", None)
        if projects is not None and projects.primary is not None:
            return projects.primary
    except Exception:
        pass
    raise RuntimeError("No active CODESYS project is available.")


def _project_name(project):
    for attr in ("name", "title", "filename"):
        try:
            value = getattr(project, attr)
            if value:
                if attr == "filename":
                    return os.path.splitext(os.path.basename(_text(value)))[0]
                return _text(value)
        except Exception:
            pass
    return ""


def _project_info_values(project):
    proj_info = None
    try:
        if hasattr(project, "get_project_info"):
            proj_info = project.get_project_info()
    except Exception:
        pass
    if proj_info is None:
        try:
            proj_info = project.project_info
        except Exception:
            proj_info = None
    if proj_info is None:
        return {}
    return getattr(proj_info, "values", proj_info)


def _read_project_property(project, key):
    values = _project_info_values(project)
    try:
        if hasattr(values, "__contains__") and key in values:
            return _text(values[key])
    except Exception:
        pass
    try:
        if hasattr(values, "get"):
            return _text(values.get(key, ""))
    except Exception:
        pass
    try:
        return _text(values[key])
    except Exception:
        return ""


def _sync_folder(project):
    return _read_project_property(project, "cds-sync-folder")


def _safe_filename(label):
    name = (label or "preset").strip() or "preset"
    chars = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", "."):
            chars.append(ch)
        elif ch.isspace():
            chars.append("-")
    filename = "".join(chars).strip(".-") or "preset"
    if not filename.lower().endswith(".json"):
        filename += ".json"
    return filename


def _filename_stamp():
    return time.strftime("%Y-%m-%d_%H%M%S")


def _snapshot_default_label(base="preset"):
    clean = os.path.splitext(_safe_filename(base))[0]
    return "{0}_{1}".format(clean, _filename_stamp())


def _default_preset_path(project, label=""):
    filename = _safe_filename(label)
    return os.path.join(_default_snapshot_dir(project), filename)


def _default_snapshot_dir(project):
    sync_folder = _sync_folder(project)
    if not sync_folder:
        raise RuntimeError("Snapshooter requires project property cds-sync-folder.")
    return os.path.join(sync_folder, ".dump", "snapshots")


def _ensure_default_snapshot_dir(project):
    directory = _default_snapshot_dir(project)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    return directory


def _resolve_preset_path(project, path, label=""):
    if not path:
        return _default_preset_path(project, label)
    if os.path.isabs(path):
        return path
    sync_folder = _sync_folder(project)
    if sync_folder:
        return os.path.join(sync_folder, path)
    return os.path.join(_default_snapshot_dir(project), path)


def _normalize_paths(paths):
    if paths is None:
        return []
    if isinstance(paths, (list, tuple)):
        return [_text(p).strip() for p in paths if _text(p).strip()]
    text = _text(paths).strip()
    if not text:
        return []
    text = text.replace("\r\n", ",").replace("\n", ",")
    return [p.strip() for p in text.split(",") if p.strip()]


def _snapshot_tree_paths(project):
    sync_folder = _sync_folder(project)
    if not sync_folder:
        raise RuntimeError("Snapshooter requires project property cds-sync-folder.")
    dump_dir = os.path.join(sync_folder, ".dump")
    snapshot_dir = _ensure_default_snapshot_dir(project)
    if dump_dir and not os.path.isdir(dump_dir):
        os.makedirs(dump_dir)
    return (
        snapshot_dir,
        os.path.join(dump_dir, "IDE.xml"),
        os.path.join(snapshot_dir, "variable_tree.json"),
    )


_PICKLE_PROTOCOL = 2  # IronPython 2.7 + CPython compatible


def _pickle_path(json_path):
    return json_path + ".cache.pkl"


def _save_pickle(rows, stats, json_path):
    pkl = _pickle_path(json_path)
    tmp = pkl + ".tmp"
    try:
        with open(tmp, "wb") as handle:
            pickle.dump((rows, stats), handle, protocol=_PICKLE_PROTOCOL)
        if os.path.exists(pkl):
            try:
                os.remove(pkl)
            except Exception:
                pass
        os.rename(tmp, pkl)
    except Exception as e:
        _log("pickle save failed: {0}".format(e))


def _load_snapshooter_tree(path):
    """Load variable tree rows/stats from JSON, with pickle cache fallback.

    On large projects the JSON is tens of MB and json.load() is the slow
    part in IronPython. The pickle cache makes subsequent loads ~50x faster.
    """
    pkl = _pickle_path(path)
    if os.path.exists(pkl) and os.path.exists(path):
        try:
            pkl_mtime = os.path.getmtime(pkl)
            json_mtime = os.path.getmtime(path)
            if pkl_mtime >= json_mtime:
                _log("loading tree from pickle cache: {0}".format(pkl))
                t0 = time.time()
                with open(pkl, "rb") as handle:
                    rows, stats = pickle.load(handle)
                _log("pickle load returned {0} rows in {1:.2f}s".format(len(rows), time.time() - t0))
                return rows, stats
        except Exception as e:
            _log("pickle load failed ({0}), falling back to JSON".format(e))

    _log("loading tree from JSON: {0}".format(path))
    t0 = time.time()
    with io.open(path, "r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    _log("json.load done in {0:.2f}s".format(time.time() - t0))
    raw_rows = data.get("rows", [])
    stats = data.get("stats", {})
    # Compact rows for faster pickle load in IronPython.
    keep_keys = ("path", "name", "type", "scope", "owner", "leaf", "note",
                 "excluded_from_build")
    rows = []
    for r in raw_rows:
        slim = {}
        for k in keep_keys:
            v = r.get(k)
            if v is not None and v != "":
                slim[k] = v
        rows.append(slim)
    _save_pickle(rows, stats, path)
    _log("loaded {0} rows (slim) total".format(len(rows)))
    return rows, stats


_SNAPSHOOTER_DECL_RE = re.compile(
    r"^\s*(TYPE|VAR_GLOBAL|PROGRAM|FUNCTION_BLOCK)\b",
    re.IGNORECASE,
)

_SNAPSHOOTER_TEXT_TYPE_GUIDS = set([
    "2db5746d-d284-4425-9f7f-2663a34b0ebc",  # DUT
    "6f9dac99-8de1-4efc-8465-68ac443b7d08",  # POU
    "ffbfa93a-b94d-45fc-a329-229860183b1d",  # GVL
])


def _textual_declaration_text(obj):
    try:
        decl = getattr(obj, "textual_declaration", None)
        if decl is None:
            return ""
        text = getattr(decl, "text", None)
        if callable(text):
            text = text()
        return _text(text)
    except Exception:
        return ""


def _object_type_guid(obj):
    try:
        value = getattr(obj, "type", "")
    except Exception:
        value = ""
    return _text(value).strip().strip("{}").lower()


def _is_snapshooter_declaration(obj):
    if _object_type_guid(obj) in _SNAPSHOOTER_TEXT_TYPE_GUIDS:
        return True
    text = _textual_declaration_text(obj)
    return bool(text and _SNAPSHOOTER_DECL_RE.search(text))


def _snapshooter_export_objects(project):
    _log("get_children(recursive=True)...")
    t0 = time.time()
    try:
        children = list(project.get_children(True))
    except Exception:
        try:
            children = list(project.get_children(recursive=True))
        except Exception:
            children = []
    _log("get_children returned {0} children in {1:.2f}s".format(len(children), time.time() - t0))
    t0 = time.time()
    filtered = [obj for obj in children if _is_snapshooter_declaration(obj)]
    _log("filtered to {0} textual objects in {1:.2f}s".format(len(filtered), time.time() - t0))
    return filtered


def _build_available_rows(project):
    global _SNAPSHOOTER_ROWS_BY_PATH
    sync_folder = _sync_folder(project)
    if not sync_folder:
        raise RuntimeError("Snapshooter requires project property cds-sync-folder.")

    snapshot_dir, ide_xml_path, tree_json_path = _snapshot_tree_paths(project)
    _log("snapshot_dir={0}".format(snapshot_dir))
    _log("ide_xml_path={0}".format(ide_xml_path))
    _log("tree_json_path={0}".format(tree_json_path))

    pkl_path = _pickle_path(tree_json_path)
    cache_valid = (
        os.path.exists(pkl_path)
        and os.path.exists(tree_json_path)
        and os.path.exists(ide_xml_path)
        and os.path.getmtime(pkl_path) >= os.path.getmtime(tree_json_path)
        and os.path.getmtime(pkl_path) >= os.path.getmtime(ide_xml_path)
    )
    if cache_valid:
        _log("tree + IDE.xml + pickle all present, skipping export and engine")
        t0 = time.time()
        rows, stats = _load_snapshooter_tree(tree_json_path)
        _log("cache hit: tree ready in {0:.2f}s".format(time.time() - t0))
        _SNAPSHOOTER_ROWS_BY_PATH = dict((r.get("path"), r) for r in rows if r.get("path"))
        if not rows:
            raise RuntimeError("Snapshooter variable tree is empty: {0}".format(tree_json_path))
        return rows, stats

    _log("cache miss, calling _snapshooter_export_objects...")
    t0 = time.time()
    objects = _snapshooter_export_objects(project)
    _log("_snapshooter_export_objects done in {0:.2f}s, {1} objects".format(time.time() - t0, len(objects)))
    if not objects:
        raise RuntimeError("No textual declaration objects found for Snapshooter export.")
    _log("calling export_selected_snapshot with {0} objects to {1}...".format(len(objects), ide_xml_path))
    t0 = time.time()
    ok = ide_export_snapshot.export_selected_snapshot(project, objects, ide_xml_path)
    _log("export_selected_snapshot returned {0} in {1:.2f}s".format(ok, time.time() - t0))

    args = [
        "snapshooter-map",
        "--project-root", sync_folder,
        "--snapshot", ide_xml_path,
        "--output", tree_json_path,
    ]
    _log("calling run_external_engine snapshooter-map...")
    t0 = time.time()
    engine_ok = ide_runtime_common.run_external_engine(args, project_root=sync_folder, dump_root=snapshot_dir)
    _log("run_external_engine returned {0} in {1:.2f}s".format(engine_ok, time.time() - t0))
    if not engine_ok:
        raise RuntimeError("Failed to build Snapshooter variable tree JSON: {0}".format(tree_json_path))

    _log("loading tree JSON: {0}".format(tree_json_path))
    t0 = time.time()
    rows, stats = _load_snapshooter_tree(tree_json_path)
    _log("_load_snapshooter_tree done in {0:.2f}s".format(time.time() - t0))
    _SNAPSHOOTER_ROWS_BY_PATH = dict((r.get("path"), r) for r in rows if r.get("path"))
    if not rows:
        raise RuntimeError("Snapshooter variable tree is empty: {0}".format(tree_json_path))
    return rows, stats


def _rows_for_paths(project, paths):
    explicit = _normalize_paths(paths)
    rows_by_path = dict(_SNAPSHOOTER_ROWS_BY_PATH)
    if not rows_by_path or not explicit:
        rows, _stats = _build_available_rows(project)
        rows_by_path = dict((r.get("path"), r) for r in rows if r.get("path"))

    if explicit:
        selected = []
        for path in explicit:
            mapped = rows_by_path.get(path)
            if mapped is not None:
                selected.append(dict(mapped))
            else:
                selected.append({"path": path, "type": "", "leaf": True, "owner": path.split(".", 1)[0]})
        return selected

    if not rows_by_path:
        raise RuntimeError("Snapshooter variable tree is empty.")
    return [r for r in rows_by_path.values() if r.get("leaf")]


def build_tree(app="Application", project=None):
    """Return variable-map rows. UI layers can group these into a tree."""
    project = _get_active_project(project)
    return _rows_for_paths(project, [])


def _read_rows(project, rows):
    names = [r["path"] for r in rows if r.get("path")]
    if not names:
        return {}
    _log("_read_rows: calling read_variables_impl with {0} names...".format(len(names)))
    t0 = time.time()
    result = _helpers.read_variables_impl(project, names)
    _log("_read_rows: read_variables_impl returned in {0:.2f}s, {1} results".format(
        time.time() - t0, len(result.get("results", []))))
    by_name = {}
    for item in result.get("results", []):
        by_name[item.get("name")] = item
    return by_name


def _vars_key(data):
    if isinstance(data, dict) and "variables" in data:
        return "variables"
    return "vars"


def _vars_from_data(data):
    if isinstance(data, dict):
        return list(data.get("variables", data.get("vars", [])))
    return list(data or [])


def _make_document(variables, app="Application", label="", description="", project=None):
    return {
        "meta": {
            "format_version": FORMAT_VERSION,
            "created": _now_text(),
            "project": _project_name(project) if project is not None else "",
            "app": _text(app),
            "label": _text(label),
            "description": _text(description),
        },
        "variables": variables,
    }


def take(paths=None, app="Application", label="", description="", project=None):
    """Read current PLC values and return a preset document."""
    project = _get_active_project(project)
    _log("take: paths={0} (None=all)".format(paths))
    t0 = time.time()
    rows = _rows_for_paths(project, paths)
    _log("take: _rows_for_paths returned {0} rows in {1:.2f}s".format(len(rows), time.time() - t0))
    live_rows = [r for r in rows if not r.get("excluded_from_build")]
    reads = _read_rows(project, live_rows)

    variables = []
    for row in rows:
        path = row.get("path", "")
        if row.get("excluded_from_build"):
            item = {
                "path": path,
                "type": row.get("type", ""),
                "value": "",
                "read_ok": False,
                "read_error": "excluded from build",
            }
            variables.append(item)
            continue
        rr = reads.get(path, {})
        item = {
            "path": path,
            "type": row.get("type", ""),
            "value": _text(rr.get("value", "")),
            "read_ok": _as_bool(rr.get("read_ok", False)),
        }
        if rr.get("read_error"):
            item["read_error"] = _text(rr.get("read_error"))
        variables.append(item)
    return _make_document(variables, app=app, label=label, description=description, project=project)


def read_values(leaves, project=None):
    """Read live values for leaf rows or path strings."""
    project = _get_active_project(project)
    rows = []
    for item in leaves:
        if isinstance(item, dict):
            rows.append(item)
        else:
            rows.append({"path": _text(item), "type": "", "leaf": True})
    _log("read_values: {0} paths to query".format(len(rows)))
    reads = _read_rows(project, rows)
    out = []
    for row in rows:
        path = row.get("path", "")
        rr = reads.get(path, {})
        copied = dict(row)
        copied["value"] = _text(rr.get("value", ""))
        copied["read_ok"] = _as_bool(rr.get("read_ok", False))
        if rr.get("read_error"):
            copied["read_error"] = _text(rr.get("read_error"))
        out.append(copied)
    return out


def compare(data, current=None):
    """Compare a saved preset against a current preset."""
    expected = _vars_from_data(data)
    if current is None:
        current = take([v.get("path", "") for v in expected])
    actual = _vars_from_data(current)
    actual_by_path = dict((v.get("path"), v) for v in actual if v.get("path"))

    missing = []
    type_changed = []
    value_changed = []
    same = []

    for saved in expected:
        path = saved.get("path", "")
        now = actual_by_path.get(path)
        if now is None or not _as_bool(now.get("read_ok", False)):
            missing.append(path)
            continue
        saved_type = _text(saved.get("type", ""))
        now_type = _text(now.get("type", ""))
        changed = False
        if saved_type and now_type and saved_type != now_type:
            type_changed.append({"path": path, "was": saved_type, "now": now_type})
            changed = True
        if _as_bool(saved.get("read_ok", True)) and _text(saved.get("value", "")) != _text(now.get("value", "")):
            value_changed.append({
                "path": path,
                "was": _text(saved.get("value", "")),
                "now": _text(now.get("value", "")),
            })
            changed = True
        if not changed:
            same.append(path)

    return {
        "identical": not missing and not type_changed and not value_changed,
        "same": same,
        "missing": missing,
        "type_changed": type_changed,
        "value_changed": value_changed,
    }


def compare_preset(preset_data, live_data):
    return compare(preset_data, current=live_data)


def restore(data, apply=False, on_type_mismatch="warn",
            on_path_missing="skip", project=None):
    """Validate and optionally write a preset back to the PLC."""
    if on_type_mismatch not in ("warn", "skip", "force"):
        raise ValueError("on_type_mismatch must be warn, skip, or force")
    if on_path_missing not in ("skip", "warn"):
        raise ValueError("on_path_missing must be skip or warn")

    project = _get_active_project(project)
    saved = _vars_from_data(data)
    current = take([v.get("path", "") for v in saved], project=project)
    current_by_path = dict((v.get("path"), v) for v in _vars_from_data(current))

    warnings = []
    skipped = []
    eligible = []

    for item in saved:
        path = item.get("path", "")
        if not path:
            skipped.append({"path": path, "reason": "empty path"})
            continue
        if not _as_bool(item.get("read_ok", True)):
            skipped.append({"path": path, "reason": "source read_ok=false"})
            continue
        now = current_by_path.get(path)
        if now is None or not _as_bool(now.get("read_ok", False)):
            reason = "path missing or not readable"
            if on_path_missing == "warn":
                warnings.append({"path": path, "warning": reason})
            skipped.append({"path": path, "reason": reason})
            continue
        old_type = _text(item.get("type", ""))
        now_type = _text(now.get("type", ""))
        if old_type and now_type and old_type != now_type:
            warning = "type mismatch: {0} -> {1}".format(old_type, now_type)
            if on_type_mismatch == "skip":
                skipped.append({"path": path, "reason": warning})
                continue
            if on_type_mismatch == "warn":
                warnings.append({"path": path, "warning": warning})
        eligible.append({"name": path, "value": item.get("value", "")})

    written = 0
    if apply and eligible:
        result = _helpers.write_variables_impl(project, eligible)
        by_name = dict((r.get("name"), r) for r in result.get("results", []))
        failed = []
        for item in eligible:
            wr = by_name.get(item["name"])
            if wr is not None and wr.get("written"):
                written += 1
            else:
                failed.append({
                    "path": item["name"],
                    "reason": (wr or {}).get("write_error", "no result"),
                })
        skipped.extend(failed)

    return {
        "written": written,
        "skipped": len(skipped),
        "warnings": warnings,
        "would_write": 0 if apply else len(eligible),
        "details": {
            "eligible": len(eligible),
            "skipped": skipped,
            "apply": bool(apply),
        },
    }


def restore_preset(preset_data, apply=False, on_diff="warn", project=None):
    mode = "warn" if on_diff in ("warn", "ask") else on_diff
    return restore(preset_data, apply=apply, on_type_mismatch=mode, project=project)


def save(data, path):
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2, ensure_ascii=False))
        handle.write("\n")
    return path


def save_preset(leaves, path, label="", app="Application", description="", project=None):
    variables = _vars_from_data(leaves)
    data = _make_document(variables, app=app, label=label, description=description, project=project)
    return save(data, path)


def load(path):
    with io.open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_preset(path):
    return load(path)


def _summary_text(data):
    vars_out = _vars_from_data(data)
    read_ok = sum(1 for v in vars_out if v.get("read_ok"))
    return "Read variables: {0}\nRead OK: {1}".format(len(vars_out), read_ok)


def _split_path(path):
    return [p for p in _text(path).split(".") if p]


def _sort_nodes(nodes):
    return sorted(nodes, key=lambda n: (n.leaf, n.name.lower()))


def build_tui_tree(rows, app="Application"):
    """Build a UI tree from variable-map/read rows."""
    _log("build_tui_tree: {0} input rows".format(len(rows)))
    t0 = time.time()
    root = TuiNode(app, app, leaf=False)
    root.expanded = False
    by_path = {app: root}
    for row in rows:
        path = row.get("path", "")
        if not path:
            continue
        parts = _split_path(path)
        parent = root
        current = ""
        for idx, part in enumerate(parts):
            current = part if not current else current + "." + part
            is_leaf = idx == len(parts) - 1
            node = by_path.get(current)
            if node is None:
                node = TuiNode(
                    part,
                    current,
                    row.get("type", "") if is_leaf else "",
                    row.get("value", "") if is_leaf else "",
                    leaf=is_leaf,
                )
                node.excluded_from_build = bool(row.get("excluded_from_build")) if is_leaf else False
                if idx == 0:
                    scope = _text(row.get("scope", "")).upper()
                    node.source_kind = row.get("kind") or row.get("owner_kind") or (
                        "gvl" if scope == "VAR_GLOBAL" else "program"
                    )
                parent.add_child(node)
                by_path[current] = node
            if is_leaf:
                node.leaf = True
                node.type = row.get("type", "")
                node.value = row.get("value", "")
                node.leaf_count = 1
                node.excluded_from_build = bool(row.get("excluded_from_build"))
            parent = node
    _sort_children_recursive(root)
    _compute_search_text_recursive(root)
    _log("build_tui_tree done: {0} nodes, {1} root children in {2:.2f}s".format(
        len(by_path), len(root.children), time.time() - t0))
    return root


def _sort_children_recursive(node):
    if not node.children:
        return
    node.children = _sort_nodes(node.children)
    for child in node.children:
        _sort_children_recursive(child)


def _compute_search_text_recursive(node):
    if node.leaf:
        node.search_text = "{0} {1}".format(node.path, node.name).lower()
    else:
        node.search_text = node.name.lower()
        for child in node.children:
            _compute_search_text_recursive(child)


def _visible_nodes(root):
    out = [(root, 0)]

    def walk(node, depth):
        if not node.expanded:
            return
        for child in node.children:
            out.append((child, depth + 1))
            walk(child, depth + 1)

    walk(root, 0)
    return out


def _node_leaf_paths(node):
    return [leaf.path for leaf in node.leaves()]


def _checkbox(node, selected):
    if node.leaf:
        return "[x]" if node.path in selected else "[ ]"
    if node.leaf_count == 0:
        return "[ ]"
    # Count how many of this branch's descendant leaves are selected.
    count = sum(1 for p in _node_leaf_paths(node) if p in selected)
    if count == 0:
        return "[ ]"
    if count == node.leaf_count:
        return "[x]"
    return "[-]"


def _toggle_node(node, selected):
    leaves = _node_leaf_paths(node)
    if not leaves:
        return
    count = sum(1 for p in leaves if p in selected)
    if count == len(leaves):
        for path in leaves:
            selected.discard(path)
    else:
        for path in leaves:
            selected.add(path)


def _clip(text, width):
    text = _text(text)
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[:width - 1] + u"…"


def _pad(text, width):
    text = _clip(text, width)
    return text + (" " * max(0, width - len(text)))


def _branch_summary(node):
    if node.parent is None:
        owners = node.children
        gvl = 0
        prg = 0
        for child in owners:
            kind = getattr(child, "source_kind", "")
            if _text(kind).lower() == "program":
                prg += 1
            else:
                gvl += 1
        parts = []
        if gvl:
            parts.append("{0} GVL".format(gvl))
        if prg:
            parts.append("{0} PRG".format(prg))
        return ", ".join(parts)
    return "{0} leaves".format(len(node.leaves()))


def _format_node_line(node, depth, selected, cursor=False, match=False):
    marker = ">" if cursor else " "
    box = _checkbox(node, selected)
    arrow = " " if node.leaf else (u"▼" if node.expanded else u"▶")
    indent = "  " * depth
    name = indent + arrow + " " + node.name
    if node.leaf:
        typ = node.type or ""
        value = node.value or ""
        main = "{0} {1} {2}".format(box, _pad(name, 27), _pad(typ, 12))
        text = "{0}{1} {2}".format(marker, main, value)
    else:
        summary = _branch_summary(node)
        main = "{0} {1}".format(box, _pad(name, 35))
        text = "{0}{1} {2}".format(marker, main, summary)
    if match:
        text = text + " ◄"
    return _pad(text, TUI_WIDTH - 4)


def render_tui(root, selected, cursor_index=0, scroll=0, project_name="", app="Application",
               message="", matches=None):
    """Render the snapshooter text UI frame."""
    matches = matches or set()
    visible = _visible_nodes(root)
    total = len(root.leaves())
    selected_count = len([p for p in selected if p])
    body = visible[scroll:scroll + TUI_BODY_HEIGHT]
    title = "Snapshooter :: {0} :: {1}".format(project_name or "project", app)
    lines = []
    lines.append(u"┌" + (u"─" * (TUI_WIDTH - 2)) + u"┐")
    lines.append(u"│ " + _pad(title, TUI_WIDTH - 4) + u" │")
    lines.append(u"├" + (u"─" * (TUI_WIDTH - 2)) + u"┤")
    for offset in range(TUI_BODY_HEIGHT):
        if offset < len(body):
            node, depth = body[offset]
            idx = scroll + offset
            line = _format_node_line(
                node, depth, selected,
                cursor=(idx == cursor_index),
                match=(node.path in matches),
            )
        else:
            line = " " * (TUI_WIDTH - 4)
        lines.append(u"│ " + line + u" │")
    lines.append(u"├" + (u"─" * (TUI_WIDTH - 2)) + u"┤")
    status = "Selected: {0}/{1} leaves".format(selected_count, total)
    if message:
        status = status + " | " + _text(message)
    lines.append(u"│ " + _pad(status, TUI_WIDTH - 4) + u" │")
    keys = u"↑↓ · Space · →← · [s]ave [l]oad [d]iff [/]search [q]uit"
    lines.append(u"│ " + _pad(keys, TUI_WIDTH - 4) + u" │")
    lines.append(u"└" + (u"─" * (TUI_WIDTH - 2)) + u"┘")
    return "\n".join(lines)


def _get_key():
    try:
        import msvcrt
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            ch2 = msvcrt.getch()
            return {
                b"H": "up",
                b"P": "down",
                b"K": "left",
                b"M": "right",
                b"<": "f3prev",
                b"=": "f3",
            }.get(ch2, "")
        try:
            return ch.decode("utf-8").lower()
        except Exception:
            return str(ch).lower()
    except Exception:
        try:
            prompt = raw_input  # noqa: F821 - IronPython
        except NameError:
            prompt = input
        return prompt("key: ").strip().lower()[:1]


def _clear_screen():
    # CODESYS scripting console does not reliably support ANSI clear.
    print("\n" * 4)


def _prompt(text, default=""):
    try:
        prompt = raw_input  # noqa: F821 - IronPython
    except NameError:
        prompt = input
    suffix = " [{0}]".format(default) if default else ""
    value = prompt("{0}{1}: ".format(text, suffix)).strip()
    return value if value else default


def _show_diff_table(report):
    print(u"┌─ Diff: preset vs live PLC " + (u"─" * 31) + u"┐")
    same = report.get("same", [])
    for path in same[:8]:
        print(u"│ OK  {0} same │".format(_pad(path, 45)))
    for item in report.get("type_changed", [])[:8]:
        text = "{0} {1} -> {2} type chg".format(item.get("path"), item.get("was"), item.get("now"))
        print(u"│ WARN {0} │".format(_pad(text, 45)))
    for item in report.get("value_changed", [])[:8]:
        text = "{0} {1} -> {2}".format(item.get("path"), item.get("was"), item.get("now"))
        print(u"│ DIFF {0} │".format(_pad(text, 45)))
    for path in report.get("missing", [])[:8]:
        print(u"│ MISS {0} path missing in PLC │".format(_pad(path, 25)))
    print(u"└" + (u"─" * 59) + u"┘")


def _run_winforms_interactive(app="Application", save_to=""):
    import clr

    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")

    from System.Windows.Forms import (
        Form, TreeView, Button, Label, TextBox, Panel, DockStyle,
        FormStartPosition, AnchorStyles, MessageBox, MessageBoxButtons,
        MessageBoxIcon, DialogResult, SaveFileDialog, OpenFileDialog,
        Application, Padding, TreeNode, Keys,
    )
    from System.Drawing import Point, Size, Font, FontStyle, Color

    project = _get_active_project()
    _log("=== _run_winforms_interactive START app={0} ===".format(app))
    _ensure_default_snapshot_dir(project)
    project_name = _project_name(project) or "project"
    _log("project_name={0}".format(project_name))
    try:
        _log("calling build_tree (structure only, no PLC read)...")
        t0 = time.time()
        tree = build_tree(app=app, project=project)
        _log("build_tree returned {0} rows in {1:.2f}s".format(len(tree), time.time() - t0))
        rows = tree
    except RuntimeError as e:
        MessageBox.Show(
            "Cannot build Snapshooter variable tree.\n\n{0}\n\n"
            "Snapshooter exports .dump\\IDE.xml and builds "
            ".dump\\snapshots\\variable_tree.json via CPython. Check cds-sync-folder "
            "and the external Python engine."
            .format(e),
            "Project_snapshooter",
            MessageBoxButtons.OK,
            MessageBoxIcon.Warning,
        )
        return None
    root_model = build_tui_tree(rows, app=app)
    leaf_rows = dict((r.get("path"), r) for r in rows if r.get("path") and r.get("leaf"))

    class SnapshooterForm(Form):
        def __init__(self):
            Form.__init__(self)
            self.Text = "Project_snapshooter"
            self.Width = 760
            self.Height = 560
            self.MinimumSize = Size(640, 420)
            self.StartPosition = FormStartPosition.CenterScreen
            self._checking = False
            self._last_data = None
            self._closed = False
            self._last_search_query = ""
            self._last_search_index = -1
            self._leaf_count = 0
            self._selected_count = 0
            self._all_leaf_nodes = []
            self._node_models = {}
            self.FormClosed += self._on_closed
            self._build_ui()
            self._populate_tree()
            self._update_status()

        def _build_ui(self):
            title = Label()
            title.Text = "Snapshooter :: {0} :: {1}".format(project_name, app)
            title.Dock = DockStyle.Top
            title.Height = 34
            title.Font = Font("Segoe UI", 11, FontStyle.Bold)
            title.BackColor = Color.FromArgb(245, 245, 245)
            title.Padding = Padding(10, 8, 0, 0)
            self.Controls.Add(title)

            content = Panel()
            content.Location = Point(0, 34)
            content.Size = Size(self.ClientSize.Width, self.ClientSize.Height - 116)
            content.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right

            self.tree = TreeView()
            self.tree.CheckBoxes = True
            self.tree.Dock = DockStyle.Fill
            self.tree.Font = Font("Consolas", 9.5, FontStyle.Regular)
            self.tree.FullRowSelect = True
            self.tree.HideSelection = False
            self.tree.ShowLines = True
            self.tree.ShowPlusMinus = True
            self.tree.ShowRootLines = True
            self.tree.AfterCheck += self._on_after_check
            content.Controls.Add(self.tree)

            bottom = Panel()
            bottom.Location = Point(0, self.ClientSize.Height - 82)
            bottom.Size = Size(self.ClientSize.Width, 82)
            bottom.Anchor = AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right
            bottom.Height = 82

            self.status = Label()
            self.status.Text = "Selected: 0/0 leaves"
            self.status.Location = Point(10, 8)
            self.status.Size = Size(260, 22)
            bottom.Controls.Add(self.status)

            self.search_box = TextBox()
            self.search_box.Location = Point(280, 6)
            self.search_box.Size = Size(210, 22)
            self.search_box.Anchor = AnchorStyles.Top | AnchorStyles.Right
            self.search_box.KeyDown += self._on_search_key
            bottom.Controls.Add(self.search_box)

            prev_btn = Button()
            prev_btn.Text = "Prev"
            prev_btn.Location = Point(500, 5)
            prev_btn.Size = Size(62, 25)
            prev_btn.Anchor = AnchorStyles.Top | AnchorStyles.Right
            prev_btn.Click += self._on_search_prev
            bottom.Controls.Add(prev_btn)

            next_btn = Button()
            next_btn.Text = "Next"
            next_btn.Location = Point(568, 5)
            next_btn.Size = Size(62, 25)
            next_btn.Anchor = AnchorStyles.Top | AnchorStyles.Right
            next_btn.Click += self._on_search_next
            bottom.Controls.Add(next_btn)

            self.save_btn = Button()
            self.save_btn.Text = "Save"
            self.save_btn.Location = Point(10, 42)
            self.save_btn.Size = Size(82, 28)
            self.save_btn.Click += self._on_save
            bottom.Controls.Add(self.save_btn)

            self.load_btn = Button()
            self.load_btn.Text = "Load"
            self.load_btn.Location = Point(100, 42)
            self.load_btn.Size = Size(82, 28)
            self.load_btn.Click += self._on_load
            bottom.Controls.Add(self.load_btn)

            self.diff_btn = Button()
            self.diff_btn.Text = "Diff"
            self.diff_btn.Location = Point(190, 42)
            self.diff_btn.Size = Size(82, 28)
            self.diff_btn.Click += self._on_diff
            bottom.Controls.Add(self.diff_btn)

            self.restore_btn = Button()
            self.restore_btn.Text = "Restore..."
            self.restore_btn.Location = Point(280, 42)
            self.restore_btn.Size = Size(92, 28)
            self.restore_btn.Click += self._on_restore
            bottom.Controls.Add(self.restore_btn)

            close_btn = Button()
            close_btn.Text = "Close"
            close_btn.Location = Point(650, 42)
            close_btn.Size = Size(82, 28)
            close_btn.Anchor = AnchorStyles.Top | AnchorStyles.Right
            close_btn.Click += self._on_close
            bottom.Controls.Add(close_btn)

            self.Controls.Add(bottom)
            self.Controls.Add(content)

        def _node_text(self, node):
            if node.leaf:
                name = _text(node.name).ljust(34)
                typ = _text(node.type or "").ljust(12)
                text = "{0} {1} {2}".format(name, typ, node.value or "")
                if node.excluded_from_build:
                    text = text + " [excluded from build]"
                return text
            return "{0}    {1}".format(node.name, _branch_summary(node))

        def _add_node(self, parent_ui, model):
            ui = TreeNode(self._node_text(model))
            ui.Name = model.path
            self._node_models[ui] = model
            if model.leaf:
                ui.Tag = 1
                self._all_leaf_nodes.append(ui)
            else:
                ui.Tag = 0
            for child in model.children:
                self._add_node(ui, child)
            parent_ui.Nodes.Add(ui)
            return ui

        def _populate_tree(self):
            self._leaf_count = 0
            self._all_leaf_nodes = []
            self._node_models = {}
            self.tree.BeginUpdate()
            try:
                self.tree.Nodes.Clear()
                root_ui = TreeNode(self._node_text(root_model))
                root_ui.Name = root_model.path
                root_ui.Tag = 0
                self._node_models[root_ui] = root_model
                for child in root_model.children:
                    self._add_node(root_ui, child)
                self.tree.Nodes.Add(root_ui)
                self._leaf_count = len(self._all_leaf_nodes)
                root_ui.Expand()
                self.tree.SelectedNode = root_ui
                root_ui.EnsureVisible()
            finally:
                self.tree.EndUpdate()

        def _walk_nodes(self, nodes):
            for i in range(nodes.Count):
                node = nodes[i]
                yield node
                for child in self._walk_nodes(node.Nodes):
                    yield child

        def _leaf_nodes(self):
            return [n for n in self._walk_nodes(self.tree.Nodes) if n.Tag == 1]

        def _selected_paths(self):
            return [str(n.Name) for n in self._leaf_nodes() if n.Checked]

        def _first_checked_label(self):
            for node in self._walk_nodes(self.tree.Nodes):
                if node.Checked:
                    return str(node.Name or node.Text or "preset")
            return "preset"

        def _set_children_checked(self, node, checked):
            delta = 0
            for i in range(node.Nodes.Count):
                child = node.Nodes[i]
                if child.Tag == 1:
                    if child.Checked != checked:
                        delta += 1 if checked else -1
                child.Checked = checked
                delta += self._set_children_checked(child, checked)
            return delta

        def _update_parent_state(self, start_node):
            parent = start_node.Parent
            while parent is not None:
                checked_count = 0
                for i in range(parent.Nodes.Count):
                    if parent.Nodes[i].Checked:
                        checked_count += 1
                model = self._node_models.get(parent)
                total = model.leaf_count if model else len(self._leaf_nodes())
                if checked_count == 0:
                    parent.Checked = False
                elif checked_count == total:
                    parent.Checked = True
                else:
                    parent.Checked = False
                parent = parent.Parent

        def _on_after_check(self, sender, args):
            if self._checking:
                return
            self._checking = True
            try:
                delta = self._set_children_checked(args.Node, args.Node.Checked)
                self._selected_count += delta
                self._update_parent_state(args.Node)
            finally:
                self._checking = False
            self._update_status()

        def _update_status(self):
            self.status.Text = "Selected: {0}/{1} leaves".format(
                self._selected_count, self._leaf_count)

        def _search_matches(self, query):
            matches = []
            for ui_node in self._all_leaf_nodes:
                model = self._node_models.get(ui_node)
                text = model.search_text if model else "{0} {1}".format(ui_node.Name, ui_node.Text).lower()
                if query in text:
                    matches.append(ui_node)
            return matches

        def _current_match_index(self, matches):
            current = self.tree.SelectedNode
            if current is None:
                return -1
            for i in range(len(matches)):
                if matches[i] is current:
                    return i
            return -1

        def _select_search_match(self, direction):
            query = self.search_box.Text.strip().lower()
            if not query:
                return
            matches = self._search_matches(query)
            if not matches:
                self._last_search_query = query
                self._last_search_index = -1
                MessageBox.Show("No matching variable path.", "Search",
                                MessageBoxButtons.OK, MessageBoxIcon.Information)
                return
            if query != self._last_search_query:
                index = 0 if direction >= 0 else len(matches) - 1
            else:
                current_index = self._current_match_index(matches)
                if current_index < 0:
                    current_index = self._last_search_index
                index = (current_index + direction) % len(matches)
            node = matches[index]
            self._last_search_query = query
            self._last_search_index = index
            self.tree.SelectedNode = node
            node.EnsureVisible()

        def _on_search_prev(self, sender, args):
            self._select_search_match(-1)

        def _on_search_next(self, sender, args):
            self._select_search_match(1)

        def _on_search_key(self, sender, args):
            if args.KeyCode == Keys.Enter:
                self._select_search_match(1)
                args.Handled = True
                args.SuppressKeyPress = True
            elif args.KeyCode == Keys.F3:
                if args.Shift:
                    self._select_search_match(-1)
                else:
                    self._select_search_match(1)
                args.Handled = True
                args.SuppressKeyPress = True

        def _default_path(self, label):
            return _default_preset_path(project, label or "preset")

        def _on_save(self, sender, args):
            paths = self._selected_paths()
            if not paths:
                MessageBox.Show("Select at least one leaf variable.", "Save",
                                MessageBoxButtons.OK, MessageBoxIcon.Warning)
                return
            default_label = _snapshot_default_label(self._first_checked_label())
            default_path = self._default_path(default_label)
            dialog = SaveFileDialog()
            dialog.Filter = "JSON presets (*.json)|*.json|All files (*.*)|*.*"
            dialog.FileName = os.path.basename(default_path)
            directory = os.path.dirname(default_path)
            if os.path.isdir(directory):
                dialog.InitialDirectory = directory
            if dialog.ShowDialog(self) != DialogResult.OK:
                return
            label = os.path.splitext(os.path.basename(dialog.FileName))[0]
            data = take(paths=paths, app=app, label=label, project=project)
            save(data, dialog.FileName)
            self._last_data = data
            MessageBox.Show("Saved {0} variables.".format(len(_vars_from_data(data))),
                            "Save", MessageBoxButtons.OK, MessageBoxIcon.Information)

        def _load_dialog(self):
            dialog = OpenFileDialog()
            dialog.Filter = "JSON presets (*.json)|*.json|All files (*.*)|*.*"
            directory = os.path.dirname(_default_preset_path(project, "preset"))
            if os.path.isdir(directory):
                dialog.InitialDirectory = directory
            if dialog.ShowDialog(self) != DialogResult.OK:
                return None
            return load(dialog.FileName)

        def _format_diff(self, report):
            return (
                "same: {0}\nmissing: {1}\ntype changed: {2}\nvalue changed: {3}"
                .format(
                    len(report.get("same", [])),
                    len(report.get("missing", [])),
                    len(report.get("type_changed", [])),
                    len(report.get("value_changed", [])),
                )
            )

        def _on_load(self, sender, args):
            data = self._load_dialog()
            if data is None:
                return
            self._last_data = data
            paths = set(v.get("path", "") for v in _vars_from_data(data))
            self._checking = True
            self.tree.BeginUpdate()
            try:
                selected = 0
                for node in self._all_leaf_nodes:
                    checked = str(node.Name) in paths
                    node.Checked = checked
                    if checked:
                        selected += 1
                self._selected_count = selected
                self._recompute_parent_states()
            finally:
                self.tree.EndUpdate()
                self._checking = False
            self._update_status()
            MessageBox.Show("Loaded {0} variables.".format(len(paths)), "Load",
                            MessageBoxButtons.OK, MessageBoxIcon.Information)

        def _recompute_parent_states(self):
            seen = set()
            for leaf in self._all_leaf_nodes:
                parent = leaf.Parent
                while parent is not None and id(parent) not in seen:
                    seen.add(id(parent))
                    parent = parent.Parent
            # Process deepest first by sorting on path depth (Name dots).
            parents = list(seen)
            parents.sort(key=lambda n: str(n.Name).count("."), reverse=True)
            for parent in parents:
                model = self._node_models.get(parent)
                total = model.leaf_count if model else 0
                if total == 0:
                    parent.Checked = False
                    continue
                checked_count = 0
                for i in range(parent.Nodes.Count):
                    if parent.Nodes[i].Checked:
                        checked_count += 1
                # For a branch, checked_count is the number of *direct* children
                # whose Checked box is on. With full parent tri-state that only
                # happens when every descendant leaf is selected.
                parent.Checked = checked_count == parent.Nodes.Count

        def _on_diff(self, sender, args):
            data = self._last_data or self._load_dialog()
            if data is None:
                return
            current = take([v.get("path", "") for v in _vars_from_data(data)], project=project)
            report = compare(data, current=current)
            MessageBox.Show(self._format_diff(report), "Diff",
                            MessageBoxButtons.OK,
                            MessageBoxIcon.Information if report.get("identical") else MessageBoxIcon.Warning)
            self._last_data = data

        def _on_restore(self, sender, args):
            data = self._last_data or self._load_dialog()
            if data is None:
                return
            current = take([v.get("path", "") for v in _vars_from_data(data)], project=project)
            report = compare(data, current=current)
            answer = MessageBox.Show(
                self._format_diff(report) + "\n\nWrite matching variables to PLC?",
                "Restore",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Warning,
            )
            if answer != DialogResult.Yes:
                return
            result = restore(data, apply=True, project=project)
            MessageBox.Show(
                "Written: {0}\nSkipped: {1}".format(result.get("written"), result.get("skipped")),
                "Restore",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information,
            )
            self._last_data = data

        def _on_close(self, sender, args):
            self.Close()

        def _on_closed(self, sender, args):
            self._closed = True

    form = SnapshooterForm()
    form.Show()
    while not form._closed:
        Application.DoEvents()
        time.sleep(0.05)
    return form._last_data


def interactive(app="Application", save_to=""):
    """Open the Snapshooter window."""
    try:
        return _run_winforms_interactive(app=app, save_to=save_to)
    except Exception as e:
        print("Project_snapshooter failed: {0}".format(e))
        return None


snapshooter = sys.modules.get(__name__)
