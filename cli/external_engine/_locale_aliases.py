# -*- coding: utf-8 -*-
"""
_locale_aliases.py - Canonicalize CODESYS standard-container names across UI locales.

Background
----------
On a non-English CODESYS UI locale the native XML export writes the object
``<Array Name="Path">`` using the *localized* IDE tree labels (e.g. zh-CN
"PLC<logic>", "<task config>"), while each object's own ``Name`` stays English
("Plc Logic", "Task Configuration"). That asymmetry makes the on-disk
``project-view/`` folders localized and breaks import-time container resolution,
which matches path segments against the English IDE object names.

This module maps *known localized* standard-container labels back to their
canonical English display form. English input is never present in the table, so
``canonical_display`` / ``canonical_key`` are strict no-ops on English projects
(same folders, same matches, zero churn).

Only CODESYS *standard* containers get localized in ``Path``; user folders and
user objects keep identical names in both places, so a bounded table suffices.

Compatibility
-------------
Must stay importable under both CPython 3 (external engine) and IronPython 2.7
(IDE bridge): no f-strings, no type hints, dependency-free.
"""

# Localized standard-container label -> canonical English display name.
#
# Keys are the exact strings CODESYS emits in <Array Name="Path"> for the given
# UI locale. Extend this as new locales are reported.
#
# NEVER add an English name as a key: doing so would rewrite English projects and
# cause on-disk folder churn. English standard names must fall through unchanged.
_LOCALIZED_TO_ENGLISH = {
    # --- zh-CN (Simplified Chinese) --- reported against cds-text-sync 2.8.0 ---
    u"PLC逻辑": "Plc Logic",                    # PLC<Logic>
    u"任务配置": "Task Configuration",  # <Task><Configuration>
}


def _u(value):
    """Best-effort coercion to a unicode string across CPython 3 / IronPython 2.7."""
    if value is None:
        return u""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", "replace")
        except Exception:
            return value.decode("latin-1", "replace")
    try:
        return unicode(value)  # noqa: F821 - Py2 / IronPython builtin
    except NameError:
        return str(value)


# Case-insensitive lookup, built once at import.
_CI = {}
for _k, _v in _LOCALIZED_TO_ENGLISH.items():
    _CI[_u(_k).strip().lower()] = _v


def canonical_display(name):
    """Return the canonical English display name for a path segment.

    Localized standard-container labels map to their English form; every other
    value (English standard names, user folders, user objects) is returned
    unchanged. This is a strict no-op on English projects.
    """
    if name is None:
        return name
    return _CI.get(_u(name).strip().lower(), name)


def canonical_key(name):
    """Return a locale-independent, case-insensitive comparison key.

    ``canonical_key(u"PLC<logic>") == canonical_key("Plc Logic") == "plc logic"``.
    Used to compare a (possibly localized) path segment against a (possibly
    localized or English) live IDE object name symmetrically.
    """
    if name is None:
        return u""
    return _u(canonical_display(name)).strip().lower()
