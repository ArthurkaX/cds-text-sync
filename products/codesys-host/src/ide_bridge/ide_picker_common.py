# -*- coding: utf-8 -*-
"""Picker-list helpers shared by the FMT and FSM object pickers.

Pure Python, stdlib only, with no feature or UI dependency: these functions
operate on the plain ``items`` dicts that both pickers hand to their list
boxes, so they live outside any WinForms module.
"""
from __future__ import print_function


def pending_indexes(items, indexes):
    """Indexes in *indexes* whose item has not been analyzed yet."""
    return [index for index in indexes if items[index].get("analysis") is None]


def sort_item_indexes(items, indexes, sort_key=None, descending=False):
    """Return *indexes* in the requested picker order.

    Counts are meaningful only after an item has been analyzed.  Leave pending
    and unreadable items below every measured result in either direction;
    reversing a normal tuple sort would otherwise put them at the top.
    """
    indexes = list(indexes)
    if sort_key == "name":
        return sorted(
            indexes, key=lambda index: items[index]["label"].lower(),
            reverse=descending,
        )
    if sort_key == "changes":
        known = [
            index for index in indexes
            if items[index].get("analysis") == "done"
        ]
        unknown = [index for index in indexes if index not in known]
        return sorted(
            known, key=lambda index: items[index].get("changed_lines", 0),
            reverse=descending,
        ) + unknown
    return indexes
