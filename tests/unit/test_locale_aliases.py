# -*- coding: utf-8 -*-
"""
test_locale_aliases.py -- Canonicalization of localized CODESYS container names.

Guards the invariant that English input is a strict no-op while known localized
standard-container labels fold to their canonical English form.
"""

from _locale_aliases import canonical_display, canonical_key


def test_english_standard_names_are_unchanged():
    # English standard containers must pass through verbatim (no on-disk churn).
    for name in ["Device", "Plc Logic", "Application", "Task Configuration", "POUs"]:
        assert canonical_display(name) == name


def test_user_names_are_unchanged():
    for name in ["FB_Motor", "My Folder", "GVL_Global", u"Ordner_Ä"]:
        assert canonical_display(name) == name


def test_localized_zh_labels_fold_to_english():
    assert canonical_display(u"PLC逻辑") == "Plc Logic"
    assert canonical_display(u"任务配置") == "Task Configuration"


def test_canonical_key_is_symmetric_across_locales():
    # A localized path segment and the English live-IDE name collapse to one key.
    assert canonical_key(u"PLC逻辑") == canonical_key("Plc Logic")
    assert canonical_key(u"PLC逻辑") == "plc logic"
    # Case-insensitive for English too.
    assert canonical_key("PLC LOGIC") == canonical_key("plc logic")


def test_none_and_empty_are_safe():
    assert canonical_display(None) is None
    assert canonical_key(None) == u""
    assert canonical_key("") == u""
