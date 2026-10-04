# -*- coding: utf-8 -*-
"""Handler for the local ``cts guide`` command.

The guides are package data (``cds_cli/guides``), so this reads them from the
installed package and never talks to the daemon -- it works with no IDE
running, like ``cts where``.
"""

from __future__ import annotations

import json

from cds_cli._cli_io import _print_error
from cds_cli.guides_data import GuideError, list_topics, read_file, read_topic


def _emit(data, output_fmt, text):
    """JSON object for scripts; the verbatim text for someone reading."""
    if output_fmt == "text":
        print(text)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def _cmd_guide(args, output_fmt):
    topic = (getattr(args, "topic", "") or "").strip()
    file_name = (getattr(args, "file", "") or "").strip()

    try:
        if file_name and not topic:
            raise GuideError(
                "--file needs a topic, e.g. "
                "`cts guide visu-svg --file examples/pid-schematic.svg`"
            )
        if file_name:
            data = read_file(topic, file_name)
            _emit(data, output_fmt, data["text"])
            return
        if topic:
            data = read_topic(topic)
            _emit(data, output_fmt, data["text"])
            return

        index = list_topics()
        if output_fmt != "text":
            _emit(index, output_fmt, "")
            return
        print("Topics:")
        for entry in index["topics"]:
            print("  {0:<10} {1}".format(entry["topic"], entry["summary"]))
        print()
        print("Guide directory: {0}".format(index["guide_dir"]))
    except GuideError as error:
        _print_error(str(error))
        raise SystemExit(2)


def dispatch_guide(args, output_fmt="json"):
    """Handle `cts guide`. Return True if handled, else False."""
    if getattr(args, "command", None) != "guide":
        return False
    _cmd_guide(args, output_fmt)
    return True


__all__ = ["dispatch_guide"]
