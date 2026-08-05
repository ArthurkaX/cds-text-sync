"""Static analyzer product-boundary contracts."""

import ast
import os

import cds_static_analyzer as analyzer


def test_package_root_exposes_only_the_st_snapshot_builder():
    assert hasattr(analyzer, "build_st_snapshot")
    assert not hasattr(analyzer, "build_snapshot")


def test_analyzer_package_does_not_ship_xml_compat_module():
    source_root = os.path.dirname(os.path.dirname(__file__))
    compat_path = os.path.join(
        source_root, "src", "cds_static_analyzer", "project_compat.py"
    )
    assert not os.path.exists(compat_path)


def test_analyzer_source_has_no_sync_or_codesys_host_imports():
    source_root = os.path.dirname(os.path.dirname(__file__))
    offenders = []
    for dirpath, _dirnames, filenames in os.walk(
        os.path.join(source_root, "src", "cds_static_analyzer")
    ):
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                offenders.extend(
                    (path, name)
                    for name in names
                    if name == "cds_text_sync"
                    or name.startswith("cds_text_sync.")
                    or name == "ide_bridge"
                    or name.startswith("ide_bridge.")
                )
    assert offenders == []
