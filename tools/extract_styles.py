# -*- coding: utf-8 -*-
"""
extract_styles.py - Dev tool: snapshot installed CODESYS visualization styles.

Walks the installed ``styledef.xml`` files, resolves each preset style's full
colour/font palette through its ``baseStyle`` chain, and writes
``cds_text_sync/visu/styles_snapshot.json``. The snapshot lets the tool resolve theme
palettes on machines without CODESYS installed (CI). It is committed.

Run from the repo root:

    python tools/extract_styles.py            # write the snapshot
    python tools/extract_styles.py --check     # verify snapshot is up to date
    python tools/extract_styles.py --print      # dump resolved palettes

This tool is NOT part of the runtime package; it only regenerates the snapshot.
"""

from __future__ import print_function

import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cds_text_sync.visu import styledef  # noqa: E402

_SNAPSHOT_PATH = os.path.join(_ROOT, "cds_text_sync", "visu", "styles_snapshot.json")


def build_snapshot():
    """Resolve every preset style from the install into a snapshot dict."""
    index = styledef.build_index()
    if not index:
        raise SystemExit(
            "No styledef.xml found. Install CODESYS or set CDS_VISU_STYLE_ROOTS."
        )
    snapshot = {}
    missing = []
    for preset, (name, version, company) in sorted(styledef.PRESET_STYLES.items()):
        node = styledef._lookup(index, name, version, company)
        if node is None:
            missing.append(preset)
            continue
        profile = styledef.resolve_chain(name, version, company, index=index)
        snapshot[styledef._snapshot_key(name, version, company)] = profile
    if missing:
        print("WARNING: presets not found in install: {0}".format(", ".join(missing)),
              file=sys.stderr)
    return snapshot


def _dump(snapshot):
    return json.dumps(snapshot, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="verify the committed snapshot matches the install")
    parser.add_argument("--print", dest="do_print", action="store_true",
                        help="print resolved palettes and exit")
    args = parser.parse_args(argv)

    snapshot = build_snapshot()

    if args.do_print:
        for key in sorted(snapshot):
            prof = snapshot[key]
            print("\n=== {0}  (chain: {1}) ===".format(key, " -> ".join(prof["base_chain"])))
            for cn in sorted(prof["colors"]):
                print("  {0:36s} {1}".format(cn, prof["colors"][cn]))
        return 0

    new_text = _dump(snapshot)
    if args.check:
        if not os.path.isfile(_SNAPSHOT_PATH):
            print("snapshot missing: {0}".format(_SNAPSHOT_PATH), file=sys.stderr)
            return 1
        with open(_SNAPSHOT_PATH, "r", encoding="utf-8") as handle:
            old_text = handle.read()
        if old_text != new_text:
            print("snapshot OUT OF DATE; run: python tools/extract_styles.py",
                  file=sys.stderr)
            return 1
        print("snapshot up to date ({0} styles).".format(len(snapshot)))
        return 0

    with open(_SNAPSHOT_PATH, "w", encoding="utf-8") as handle:
        handle.write(new_text)
    print("wrote {0} styles -> {1}".format(len(snapshot), _SNAPSHOT_PATH))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
