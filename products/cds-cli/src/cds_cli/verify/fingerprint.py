"""Deterministic fingerprint for the files that form a sync workspace.

The fingerprint is deliberately local and content-based.  It is a handshake
hint between ``cts verify`` and the IDE daemon, not a replacement for the
manifest/import protocol: a daemon that predates the field may omit it.
"""

import hashlib
import os


_EXCLUDED_DIRS = frozenset((".git", ".dump"))


def workspace_fingerprint(root):
    """Return ``(digest, complete, errors)`` for regular files below *root*.

    Paths are normalised to forward-slash relative names and sorted before
    hashing.  File contents are streamed so a large project does not occupy
    the agent's memory.  Read failures are reported rather than silently
    producing a fingerprint that could be mistaken for complete evidence.
    """
    root = os.path.abspath(root)
    digest = hashlib.sha256()
    errors = []
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if name not in _EXCLUDED_DIRS
        )
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            files.append((rel, path))

    for rel, path in files:
        try:
            encoded = rel.encode("utf-8")
            digest.update(encoded)
            digest.update(b"\0")
            with open(path, "rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            digest.update(b"\0")
        except (IOError, OSError) as exc:
            errors.append("{0}: {1}".format(rel, exc))

    return digest.hexdigest(), not errors, errors


__all__ = ["workspace_fingerprint"]
