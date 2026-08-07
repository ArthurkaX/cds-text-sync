# -*- coding: utf-8 -*-
"""Projection encode/decode boundary shared by folder orchestration."""

from xml_helpers import (
    apply_alarm_items_csv,
    apply_textlist_csv,
    csv_projection_content,
    split_st_projection_values,
    st_projection_content,
)


def encode(node, projection):
    """Return projection text for a model node and projection descriptor."""
    if projection.get("format") == "st":
        content = st_projection_content(node.entry_element)
        if content is not None:
            return content
    if projection.get("format") == "csv":
        return csv_projection_content(
            node.entry_element, projection.get("extractor") or projection.get("id")
        )
    return node.code


def decode_st(content, entry_element):
    """Apply a structured-text projection to an XML entry element."""
    return split_st_projection_values(content, entry_element)


def decode_csv(content, entry_element, extractor):
    """Apply a CSV projection using the registered extractor."""
    if extractor == "textlist_csv":
        return apply_textlist_csv(entry_element, content)
    if extractor == "alarm_items_csv":
        return apply_alarm_items_csv(entry_element, content)
    return False
