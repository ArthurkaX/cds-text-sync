"""Pure comparison of two snapshot variable collections."""

from cts_shared.coerce import as_bool as _as_bool  # noqa: F401 - re-exported


def _text(value):
    return "" if value is None else str(value)


def compare_documents(expected, current):
    """Compare two snapshot documents without project or IDE dependencies."""
    expected = expected or []
    current = current or []
    actual_by_path = dict((v.get("path"), v) for v in current if v.get("path"))
    missing, type_changed, value_changed, same = [], [], [], []

    for saved in expected:
        path = saved.get("path", "")
        now = actual_by_path.get(path)
        if now is None or not _as_bool(now.get("read_ok", False)):
            missing.append(path)
            continue
        changed = False
        saved_type = _text(saved.get("type", ""))
        now_type = _text(now.get("type", ""))
        if saved_type and now_type and saved_type != now_type:
            type_changed.append({"path": path, "was": saved_type, "now": now_type})
            changed = True
        if _as_bool(saved.get("read_ok", True)) and _text(saved.get("value", "")) != _text(now.get("value", "")):
            value_changed.append({"path": path, "was": _text(saved.get("value", "")), "now": _text(now.get("value", ""))})
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
