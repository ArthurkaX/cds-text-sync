# -*- coding: utf-8 -*-
"""Listing, looking up and timestamping files on the PLC file system.

Three handlers each walked ``online_dev.get_file_list_of_directory`` with
their own copy of the same attribute-probing loop, and each rendered the
device's .NET ``DateTime`` with ``str()`` -- "9/23/2026 7:04:22 AM", a format
that is neither stable nor carries a timezone.  Everything that lists or looks
up a PLC file goes through here now, so:

* a timestamp is always ISO-8601 UTC with a trailing ``Z``;
* a file that is not in its directory is reported the same way everywhere,
  with the entries that *are* there, instead of a raw device message;
* "is this entry a directory" is answered once, so a directory is never
  listed as if it were a log.

The device API is only ever probed; nothing here raises for a missing
attribute.  IronPython 2.7.
"""

from __future__ import print_function

from ide_path_guards import as_text, plc_root_path

#: .NET custom date format: ``yyyy``/``MM``/``dd``/``HH``/``mm``/``ss`` are
#: specifiers, the trailing ``Z`` is a literal -- the value was already
#: converted to UTC by ``ToUniversalTime``.
ISO_UTC_FORMAT = "yyyy-MM-ddTHH:mm:ssZ"

#: (output key, attribute names to try).  The device API is not consistent
#: across runtimes: some expose ``Name``/``CreationTime``, older ones
#: snake_case.  First name that answers wins.
_ATTRS = (
    ("name", ("name", "Name")),
    ("size", ("length", "Length", "size", "Size")),
    ("is_directory", ("is_directory", "IsDirectory")),
    ("creation_time", ("creation_time", "CreationTime")),
    ("last_write_time", ("last_write_time", "LastWriteTime")),
)

#: Text types: IronPython 2.7 has ``unicode``, CPython 3 (the test runner)
#: does not, so ask rather than assume.
try:
    _TEXT_TYPES = (str, unicode)  # noqa: F821 - IronPython
except NameError:
    _TEXT_TYPES = (str,)

#: Where the runtime log is *not* on this PLC: the online device only exposes
#: the application's file system (``PlcLogic/`` and what is mounted under
#: it).  Appended to every not-found message so the next reader does not go
#: looking for a bug in the path handling.
OUTSIDE_FS_HINT = (
    "The runtime log may live outside the file system the online device "
    "exposes (on a Linux runtime, for example, "
    "/var/volatile/log/codesyscontrol.log); which files are visible depends "
    "on the runtime and its CmpLog configuration."
)


def _attribute(obj, names):
    """The first attribute in *names* that answers, or ``None``."""
    for name in names:
        if hasattr(obj, name):
            try:
                value = getattr(obj, name)
                if callable(value):
                    value = value()
            except Exception:
                continue
            if value is not None:
                return value
    return None


def _as_bool(value):
    """A device flag as a real bool.

    A .NET ``bool`` coerces directly; a string (some runtimes) must not --
    ``bool("False")`` is True.
    """
    if isinstance(value, _TEXT_TYPES):
        return as_text(value).strip().lower() in ("true", "1", "yes")
    return bool(value)


def iso_utc(value):
    """A PLC timestamp as ``YYYY-MM-DDTHH:MM:SSZ``, or "" when absent.

    The online device hands back a .NET ``DateTime``: ``ToUniversalTime``
    converts it before the format appends the literal ``Z``.  A plain string
    (a runtime that already formatted it) is returned unchanged -- better the
    device's own text than a guess at its format.
    """
    if value is None:
        return ""
    if hasattr(value, "ToUniversalTime"):
        try:
            return value.ToUniversalTime().ToString(ISO_UTC_FORMAT)
        except Exception:
            pass
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass
    return as_text(value)


def describe_entry(entry):
    """One directory entry as a stable, JSON-safe dict."""
    name = as_text(_attribute(entry, _ATTRS[0][1]))
    if not name:
        # No usable Name attribute: keep the old diagnostic value rather than
        # dropping the entry silently.
        name = as_text(entry)[:200]

    info = {"name": name, "is_directory": _as_bool(_attribute(entry, _ATTRS[2][1]))}

    size = _attribute(entry, _ATTRS[1][1])
    if size is not None:
        try:
            info["size"] = int(size)
        except (TypeError, ValueError):
            info["size"] = as_text(size)

    created = iso_utc(_attribute(entry, _ATTRS[3][1]))
    if created:
        info["creation_time"] = created
    modified = iso_utc(_attribute(entry, _ATTRS[4][1]))
    if modified:
        info["last_write_time"] = modified
    return info


def list_directory(online_dev, path=""):
    """List a PLC directory.  Return ``(entries, error)``.

    ``entries`` is a list (possibly empty) of :func:`describe_entry` dicts, or
    ``None`` when the listing itself failed; ``error`` is the device's own
    message in that case, else ``None``.  The ``None``/empty split matters:
    an empty directory is an answer, a failed listing is not.
    """
    target = plc_root_path(path)
    try:
        raw = online_dev.get_file_list_of_directory(target)
    except Exception as exc:
        return None, as_text(exc)
    if raw is None:
        return [], None

    entries = []
    for item in raw:
        try:
            entries.append(describe_entry(item))
        except Exception:
            continue
    return entries, None


def plc_parent(path):
    """The PLC directory that holds *path* ("" for the device root)."""
    text = as_text(path).replace("\\", "/")
    cut = text.rfind("/")
    if cut < 0:
        return ""
    return text[:cut]


def plc_name(path):
    """The last component of a PLC path."""
    text = as_text(path).replace("\\", "/")
    cut = text.rfind("/")
    return text[cut + 1:] if cut >= 0 else text


def find_entry(entries, name):
    """The entry called *name* (exact match first, then case-insensitive)."""
    if not entries:
        return None
    for entry in entries:
        if entry.get("name") == name:
            return entry
    lowered = name.lower()
    for entry in entries:
        if as_text(entry.get("name")).lower() == lowered:
            return entry
    return None


def missing_file_error(plc_path, entries, parent=""):
    """The error dict for a PLC file that is not in its directory.

    Names the entries that *are* there, so "the path was mangled" and "the
    file is not on this device" cannot be confused again.
    """
    names = [
        as_text(entry.get("name"))
        for entry in (entries or [])
        if not entry.get("is_directory")
    ]
    names = [name for name in names if name]
    listing = ", ".join(names) if names else "no files"
    where = "the PLC root" if not parent else parent
    return {
        "ok": False,
        "error": "{0} not found on the PLC file system; files in {1}: {2}. {3}".format(
            plc_path, where, listing, OUTSIDE_FS_HINT
        ),
    }


def lookup(online_dev, plc_path):
    """Resolve a PLC file.  Return ``(present, entries, parent, error)``.

    ``present`` is ``True``/``False``, or ``None`` when the directory could
    not be listed at all -- then ``error`` carries the device's message and
    the caller should attempt the read and surface the device's own failure
    instead of inventing "not found".
    """
    parent = plc_parent(plc_path)
    entries, error = list_directory(online_dev, parent)
    if entries is None:
        return None, None, parent, error
    return find_entry(entries, plc_name(plc_path)) is not None, entries, parent, None


__all__ = [
    "ISO_UTC_FORMAT",
    "OUTSIDE_FS_HINT",
    "describe_entry",
    "find_entry",
    "iso_utc",
    "list_directory",
    "lookup",
    "missing_file_error",
    "plc_name",
    "plc_parent",
]
