"""The sync product package.

The source-checkout ``sys.path`` bootstrapping lives in the root
``cds_text_sync`` shim, and the installed wheel ships every product package
side by side, so nothing here needs to touch ``sys.path``.
"""

__version__ = "3.4.0"
