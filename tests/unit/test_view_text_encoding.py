# -*- coding: utf-8 -*-
"""
test_view_text_encoding.py - How the view reader treats editor-chosen encodings.

The writer emits UTF-8 with no BOM, but view files are hand-edited and a
Windows editor saving non-ASCII text picks its own encoding. Both cases below
are invisible while a file is pure ASCII, which is why they only ever surface
on projects with Cyrillic content:

* UTF-8 *with* a BOM must read back as the same text, or every Notepad round
  trip shows up as a phantom modification;
* ANSI/cp1251 cannot be read at all, and must be named rather than crashing or,
  worse, being silently overwritten by the next export.
"""

import json
import os

import pytest

# Flat imports, as the engine imports itself: reaching _view_text through the
# package path would bind a second copy of ViewEncodingError, and the class the
# reader raises would not be the class pytest.raises is watching for.
from _dirty_scan import dirty_view_paths, scan_dirty
from _view_text import ViewEncodingError, read_view_text
from folder_reader import FolderReader
from xml_helpers import sha1_hex

CYRILLIC_ST = u"FUNCTION_BLOCK FB_Клапан\n" \
              u"(* Открытие *)\n"


def _write_bytes(path, data):
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(path, "wb") as handle:
        handle.write(data)
    return path


class TestReadViewText:
    def test_plain_utf8_round_trips(self, tmp_path):
        path = _write_bytes(str(tmp_path / "a.st"), CYRILLIC_ST.encode("utf-8"))
        assert read_view_text(path) == CYRILLIC_ST

    def test_bom_is_dropped_so_the_hash_is_unchanged(self, tmp_path):
        plain = _write_bytes(str(tmp_path / "plain.st"), CYRILLIC_ST.encode("utf-8"))
        with_bom = _write_bytes(
            str(tmp_path / "bom.st"), b"\xef\xbb\xbf" + CYRILLIC_ST.encode("utf-8")
        )
        assert read_view_text(with_bom) == read_view_text(plain)
        assert sha1_hex(read_view_text(with_bom)) == sha1_hex(read_view_text(plain))

    def test_crlf_is_preserved(self, tmp_path):
        crlf = CYRILLIC_ST.replace(u"\n", u"\r\n")
        path = _write_bytes(str(tmp_path / "crlf.st"), crlf.encode("utf-8"))
        assert read_view_text(path) == crlf

    def test_cp1251_is_reported_with_the_file_name(self, tmp_path):
        path = _write_bytes(str(tmp_path / "ansi.st"), CYRILLIC_ST.encode("cp1251"))
        with pytest.raises(ViewEncodingError) as caught:
            read_view_text(path)
        message = str(caught.value)
        assert "ansi.st" in message
        assert "UTF-8" in message


def _manifest_for(view_path, content):
    return {
        "view_root": ".",
        "ns": "",
        "entries": [
            {
                "guid": "g1",
                "xml_path": view_path,
                "hash": sha1_hex(content),
            }
        ],
    }


class TestDirtyScanEncoding:
    def test_bom_alone_is_not_a_modification(self, tmp_path):
        views = str(tmp_path)
        _write_bytes(
            os.path.join(views, "A.xml"), b"\xef\xbb\xbf" + CYRILLIC_ST.encode("utf-8")
        )
        manifest = _manifest_for("A.xml", CYRILLIC_ST)
        assert scan_dirty(manifest, views)["dirty"] == []
        assert dirty_view_paths(manifest, views) == set()

    def test_cp1251_counts_as_dirty_so_export_cannot_overwrite_it(self, tmp_path):
        views = str(tmp_path)
        _write_bytes(os.path.join(views, "A.xml"), CYRILLIC_ST.encode("cp1251"))
        manifest = _manifest_for("A.xml", CYRILLIC_ST)

        dirty = scan_dirty(manifest, views)["dirty"]
        assert len(dirty) == 1
        assert dirty[0]["path"] == "A.xml"
        assert dirty[0]["current_hash"] is None
        assert dirty[0]["unreadable"] == "not valid UTF-8"
        assert dirty_view_paths(manifest, views) == {"A.xml"}


class TestFolderReaderEncoding:
    def test_cp1251_entry_xml_names_the_file(self, tmp_path):
        views = str(tmp_path / "views")
        dump = str(tmp_path / "dump")
        os.makedirs(dump)
        _write_bytes(os.path.join(views, "A.xml"), CYRILLIC_ST.encode("cp1251"))
        manifest = _manifest_for("A.xml", CYRILLIC_ST)
        manifest["view_root"] = views
        with open(os.path.join(dump, "manifest.json"), "w") as handle:
            json.dump(manifest, handle)

        with pytest.raises(ViewEncodingError) as caught:
            FolderReader(views, dump).read()
        assert "A.xml" in str(caught.value)
