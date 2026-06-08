# -*- coding: utf-8 -*-
"""
snapshot_engine.py - Snapshot and restore orchestration logic.

Pure, transport-agnostic, no CODESYS / no pipe / no file IO. Written to run on
both IronPython 2.7 and CPython 3. Avoid f-strings and annotations.

Injected function contracts:
  read_fn(expressions) -> {expr: {name, value, read_ok, read_error}}
  write_fn(items) -> {name: {name, prepared, written, write_error}}
    items = [{"name": expr, "value": val}, ...]
"""

SNAPSHOT_COLUMNS = ["value", "read_ok", "read_error"]
RESTORE_REPORT_COLUMNS = ["path", "value", "read_ok", "restore_status"]


def run_snapshot(rows, read_fn):
    """Read online values for all leaf rows.

    read_fn is called once with all leaf paths. Every row is annotated with
    value / read_ok / read_error in place.

    Returns (rows, {"read_ok": n, "read_failed": n}).
    """
    readable = [r for r in rows if r.get("leaf")]
    read_map = read_fn([r["path"] for r in readable])

    ok = 0
    fail = 0
    for r in rows:
        if r.get("leaf"):
            rr = read_map.get(r["path"])
            if rr is not None and rr.get("read_ok"):
                r["value"] = rr.get("value", "")
                r["read_ok"] = "true"
                r["read_error"] = ""
                ok += 1
            else:
                r["value"] = ""
                r["read_ok"] = "false"
                r["read_error"] = (rr or {}).get("read_error", "no result")
                fail += 1
        else:
            r["value"] = ""
            r["read_ok"] = "false"
            note = r.get("note") or ""
            r["read_error"] = "not a readable leaf: " + note if note else "not a readable leaf"
            fail += 1

    return rows, {"read_ok": ok, "read_failed": fail}


def _coerce_enum_value(value, enum_registry):
    """If the value is a qualified enumerator 'TYPE.member', try to
    return a numeric literal that set_prepared_value accepts. If the type
    or member is unknown, return value unchanged.
    """
    if value is None or not hasattr(value, "strip"):
        return value
    s = value.strip()
    if "." not in s or " " in s or "#" in s:
        return s
    parts = s.split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return s
    type_name, mem = parts
    # Look up by exact name or case-insensitive
    enum = enum_registry.get(type_name) if enum_registry else None
    if enum is None and enum_registry:
        for k, v in enum_registry.items():
            if k.upper() == type_name.upper():
                enum = v
                break
    if enum is None or mem not in enum:
        return s
    return str(enum[mem])


def plan_restore(snap_rows, force=False, enum_registry=None):
    """Categorise snapshot rows into eligible-to-write and skipped.

    Gating: no path -> skip; read_ok!=true or empty value -> skip (unless force).
    Qualified enumerator values are coerced to numeric.

    Returns (eligible, skipped), where each element is a row with
    restore_status set (skipped rows) and value possibly coerced.
    """
    eligible = []
    skipped = []
    for r in snap_rows:
        path = (r.get("path") or "").strip()
        value = r.get("value", "")
        read_ok_val = (r.get("read_ok") or "").strip().lower() == "true"
        if not path:
            r["restore_status"] = "skipped: no path"
            skipped.append(r)
            continue
        if not force and (not read_ok_val or value == ""):
            r["restore_status"] = "skipped: read_ok!=true or empty value"
            skipped.append(r)
            continue
        # Translate qualified enumerators to numeric so CODESYS accepts them.
        original_value = value
        coerced = _coerce_enum_value(value, enum_registry)
        if coerced != original_value:
            r["_coerced_value"] = coerced
        r["value"] = coerced
        eligible.append(r)

    return eligible, skipped


def apply_restore(eligible, write_fn):
    """Write eligible rows via write_fn and annotate results.

    Each eligible row gets restore_status: "written" on success,
    "failed: <reason>" otherwise.

    Returns (eligible, {"written": n, "failed": n}).
    """
    if not eligible:
        return eligible, {"written": 0, "failed": 0}

    items = [{"name": r["path"], "value": r["value"]} for r in eligible]
    wmap = write_fn(items)

    written = 0
    failed = 0
    for r in eligible:
        wr = wmap.get(r["path"])
        if wr is not None and wr.get("written"):
            r["restore_status"] = "written"
            written += 1
        else:
            r["restore_status"] = "failed: " + ((wr or {}).get("write_error") or "no result")
            failed += 1

    return eligible, {"written": written, "failed": failed}


def mark_dry_run(eligible):
    """Mark eligible rows as dry-run (no write performed)."""
    for r in eligible:
        r["restore_status"] = "dry-run: would write"
