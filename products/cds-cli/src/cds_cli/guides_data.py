# -*- coding: utf-8 -*-
"""Read the operating guides that ship inside this package.

The guides live under ``cds_cli/guides`` as package data, so a pip/irm install
has them and they are version-matched with the CLI that serves them through
``cts guide``. The guides used to sit in ``skills/`` at the repository root,
which is not package data: an installed wheel had none of them.

Each topic is one markdown file named by :data:`TOPICS`; a topic may also own a
folder (``guides/<topic>/``) with extra files such as ``examples/*.svg``,
reachable through ``cts guide <topic> --file <name>``.
"""

from __future__ import annotations

import re
from importlib.resources import files
from importlib.resources.abc import Traversable

GUIDE_DIR = "guides"

# One entry per topic: the summary is what `cts guide` lists, the file is the
# markdown `cts guide <topic>` prints.
TOPICS = (
    {
        "topic": "workflow",
        "file": "workflow.md",
        "summary": "How to operate cts safely across folder, IDE, and PLC.",
    },
    {
        "topic": "commands",
        "file": "commands.md",
        "summary": "Routing table: which cts command for which job.",
    },
    {
        "topic": "visu-svg",
        "file": "visu-svg.md",
        "summary": "Author SVG sketches that compile into CODESYS HMI screens.",
    },
)

# A --file name must stay inside its topic folder: no absolute paths, drive
# letters, or parent traversal.
_UNSAFE_NAME = re.compile(r"(^/)|(^[A-Za-z]:)|(\.\.)")


class GuideError(Exception):
    """A guide topic or file that is not shipped with this package."""


def guide_root() -> Traversable:
    """The package data directory holding the guides."""
    return files("cds_cli") / GUIDE_DIR


def topic_names() -> list[str]:
    return [entry["topic"] for entry in TOPICS]


def _entry(topic: str) -> dict:
    for entry in TOPICS:
        if entry["topic"] == topic:
            return entry
    raise GuideError(
        "unknown guide topic {0!r}; valid topics: {1}".format(
            topic, ", ".join(topic_names())
        )
    )


def _list_files(directory: Traversable, prefix: str = "") -> list[str]:
    """Every file under ``directory``, as topic-relative names."""
    found: list[str] = []
    for child in sorted(directory.iterdir(), key=lambda item: item.name):
        name = prefix + child.name
        if child.is_dir():
            found.extend(_list_files(child, name + "/"))
        else:
            found.append(name)
    return found


def list_topics() -> dict:
    """The topic index: one summary and path per topic, plus the guide dir."""
    root = guide_root()
    return {
        "guide_dir": str(root),
        "topics": [
            {
                "topic": entry["topic"],
                "summary": entry["summary"],
                "path": str(root / entry["file"]),
            }
            for entry in TOPICS
        ],
    }


def read_topic(topic: str) -> dict:
    """The guide text for ``topic``, plus any extra files it ships."""
    entry = _entry(topic)
    root = guide_root()
    path = root / entry["file"]
    if not path.is_file():
        raise GuideError(
            "guide topic {0!r} is missing its file {1!r}".format(topic, entry["file"])
        )
    topic_dir = root / topic
    return {
        "topic": topic,
        "path": str(path),
        "text": path.read_text(encoding="utf-8"),
        "files": _list_files(topic_dir) if topic_dir.is_dir() else [],
    }


def read_file(topic: str, name: str) -> dict:
    """One extra file shipped with ``topic``, e.g. an example SVG."""
    _entry(topic)
    if not name or _UNSAFE_NAME.search(name):
        raise GuideError("invalid guide file name {0!r}".format(name))
    topic_dir = guide_root() / topic
    path = topic_dir
    for part in name.split("/"):
        path = path / part
    if not path.is_file():
        available = _list_files(topic_dir) if topic_dir.is_dir() else []
        raise GuideError(
            "guide topic {0!r} has no file {1!r}; available files: {2}".format(
                topic, name, ", ".join(available) or "(none)"
            )
        )
    return {
        "topic": topic,
        "file": name,
        "path": str(path),
        "text": path.read_text(encoding="utf-8"),
    }


__all__ = [
    "GUIDE_DIR",
    "TOPICS",
    "GuideError",
    "guide_root",
    "list_topics",
    "read_file",
    "read_topic",
    "topic_names",
]
