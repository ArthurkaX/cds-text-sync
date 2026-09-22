# -*- coding: utf-8 -*-
"""
_view_text.py - The single way engine code reads a text file out of the view.

The writer emits UTF-8 with no BOM, but view files exist to be hand-edited, and
a Windows editor asked to save non-ASCII text picks its own encoding: UTF-8
with a BOM, or ANSI (cp1251 on a Russian system). Both are invisible while a
file stays pure ASCII, which is why this only ever bites projects with Cyrillic
(or any other non-ASCII) content.

Reading through ``utf-8-sig`` drops a BOM instead of carrying ``\\ufeff`` into
the text, so a round trip through Notepad no longer changes the hash and shows
up as a phantom modification. An ANSI save is genuine data loss in waiting and
is reported as ``ViewEncodingError`` naming the file, not as a bare
``UnicodeDecodeError`` traceback.

Every view read goes through here so the hash stays byte-identical across
``folder_reader``, ``_dirty_scan`` and ``_projection_changes``: a file counts as
changed in one exactly when it does in the others.
"""

VIEW_ENCODING = "utf-8-sig"


class ViewEncodingError(ValueError):
    """A view file is not UTF-8 - nearly always an ANSI/cp1251 re-save."""

    def __init__(self, path, error):
        self.path = path
        self.error = error
        ValueError.__init__(
            self,
            "{0}: not valid UTF-8 ({1}). cds-text-sync writes the view as UTF-8; "
            "an editor most likely re-saved this file as ANSI/cp1251. Reopen it, "
            "save it as UTF-8, and retry.".format(path, error),
        )


def read_view_text(path):
    """Read one view file as UTF-8, dropping a leading BOM if present.

    Reads bytes and decodes in one step rather than streaming, so the offset in
    a decode failure points into the file itself instead of into a chunk.
    """
    with open(path, "rb") as handle:
        data = handle.read()
    try:
        return data.decode(VIEW_ENCODING)
    except UnicodeDecodeError as error:
        raise ViewEncodingError(path, error)
