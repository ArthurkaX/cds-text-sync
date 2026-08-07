# -*- coding: utf-8 -*-
"""
project_snapshooter.py - PLC variable preset snapshots.

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


class SnapshotOnlineError(RuntimeError):
    """Raised when a snapshot write is attempted during an online session."""


def ensure_snapshot_import_allowed():
    """Reject snapshot import workflows while the IDE is online."""
    if _helpers.is_online_session_active():
        raise SnapshotOnlineError(
            "Snapshot import is disabled while CODESYS is online. "
            "Disconnect from the PLC/runtime and retry."
        )
import snapshot_store as _snapshot_store
import snapshot_compare as _snapshot_compare
import snapshot_model as _snapshot_model
import snapshot_adapter as _snapshot_adapter


# --- Diagnostic logger ------------------------------------------------------
# Gated by the project option "Save detailed engine logs in .dump"
# (verbose_logging). When enabled, writes millisecond-stamped lines to
# <sync-folder>/.dump/snapshooter.log and echoes to the scripting console.
# When disabled, _log() is a cheap no-op.
_SNAPSHOOTER_LOG_PATHS = None
_SNAPSHOOTER_SYNC = None
_SNAPSHOOTER_VERBOSE = None


def _resolve_log_sync_folder():
    """Best-effort cds-sync-folder lookup from the active CODESYS project.

    Cached because it is consulted on every _log() call and on the verbose
    check. Returns "" when no project/sync folder is available.
    """
    global _SNAPSHOOTER_SYNC
    if _SNAPSHOOTER_SYNC:
        return _SNAPSHOOTER_SYNC
    sync = ""
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
                        sync = ""
    except Exception:
        sync = ""
    _SNAPSHOOTER_SYNC = sync or ""
    return _SNAPSHOOTER_SYNC


def _snapshooter_verbose():
    """True when the project option verbose_logging is enabled.

    Only the resolved result is cached; while the project/sync folder is not
    yet available we keep returning False without memoizing, so logging can
    still switch on once the project becomes reachable.
    """
    global _SNAPSHOOTER_VERBOSE
    if _SNAPSHOOTER_VERBOSE is not None:
        return _SNAPSHOOTER_VERBOSE
    sync = _resolve_log_sync_folder()
    if not sync:
        return False
    verbose = False
    try:
        verbose, _log_path = ide_runtime_common.project_logging_config(sync)
        verbose = bool(verbose)
    except Exception:
        verbose = False
    _SNAPSHOOTER_VERBOSE = verbose
    return verbose


def _log_resolve_paths():
    global _SNAPSHOOTER_LOG_PATHS
    if _SNAPSHOOTER_LOG_PATHS is not None:
        return _SNAPSHOOTER_LOG_PATHS
    paths = []
    sync = _resolve_log_sync_folder()
    if sync:
        paths.append(os.path.join(sync, ".dump", "snapshooter.log"))
    else:
        # No sync folder resolved: fall back so verbose logs are not lost.
        try:
            paths.append(os.path.join(tempfile.gettempdir(), "snapshooter.log"))
        except Exception:
            pass
    _SNAPSHOOTER_LOG_PATHS = paths
    return paths


def _log(msg):
    if not _snapshooter_verbose():
        return
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
    engine = os.path.join(
        repo, "products", "cds-text-sync", "src", "cds_text_sync", "engine"
    )
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
    adapter = _snapshot_adapter.SnapshotProjectAdapter(
        project, ide_export_snapshot, _helpers, ide_runtime_common
    )
    children = adapter.children()
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
    adapter = _snapshot_adapter.SnapshotProjectAdapter(
        project, ide_export_snapshot, _helpers, ide_runtime_common
    )
    ok = adapter.export_selected_snapshot(objects, ide_xml_path)
    _log("export_selected_snapshot returned {0} in {1:.2f}s".format(ok, time.time() - t0))

    args = [
        "snapshooter-map",
        "--project-root", sync_folder,
        "--snapshot", ide_xml_path,
        "--output", tree_json_path,
    ]
    _log("calling run_external_engine snapshooter-map...")
    t0 = time.time()
    engine_ok = adapter.run_external_engine(
        args, project_root=sync_folder, dump_root=snapshot_dir
    )
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
    adapter = _snapshot_adapter.SnapshotProjectAdapter(
        project, ide_export_snapshot, _helpers, ide_runtime_common
    )
    result = adapter.read_variables(names)
    _log("_read_rows: read_variables_impl returned in {0:.2f}s, {1} results".format(
        time.time() - t0, len(result.get("results", []))))
    by_name = {}
    for item in result.get("results", []):
        by_name[item.get("name")] = item
    return by_name


def _vars_key(data):
    return _snapshot_model.vars_key(data)


def _vars_from_data(data):
    return _snapshot_model.vars_from_data(data)


def _make_document(variables, app="Application", label="", description="", project=None):
    project_name = _project_name(project) if project is not None else ""
    return _snapshot_model.make_document(
        variables,
        format_version=FORMAT_VERSION,
        created=_now_text(),
        project_name=project_name,
        app=app,
        label=label,
        description=description,
    )


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
    return _snapshot_compare.compare_documents(expected, _vars_from_data(current))


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
    if apply:
        ensure_snapshot_import_allowed()
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
    return _snapshot_store.save(data, path)


def save_preset(leaves, path, label="", app="Application", description="", project=None):
    variables = _vars_from_data(leaves)
    data = _make_document(variables, app=app, label=label, description=description, project=project)
    return save(data, path)


def load(path):
    return _snapshot_store.load(path)


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
    """Launch the optional WinForms frontend without importing it at module load."""
    import project_snapshooter_ui

    return project_snapshooter_ui.run(
        backend=globals(), app=app, save_to=save_to
    )


def interactive(app="Application", save_to=""):
    """Open the Snapshooter window."""
    try:
        return _run_winforms_interactive(app=app, save_to=save_to)
    except Exception as e:
        print("Project_snapshooter failed: {0}".format(e))
        return None


snapshooter = sys.modules.get(__name__)
