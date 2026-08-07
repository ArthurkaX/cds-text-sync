"""Pure JSON persistence for PLC snapshot documents.

This module deliberately has no CODESYS, CLR, or bridge imports so the file
format can be tested under CPython independently of the interactive UI.
"""

import io
import json
import os


def save(data, path):
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    with io.open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, indent=2, ensure_ascii=False))
        handle.write("\n")
    return path


def load(path):
    with io.open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)
