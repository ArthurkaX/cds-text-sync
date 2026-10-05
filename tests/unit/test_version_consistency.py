"""The tool ships as one package: every release version must agree."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_ASSIGNMENT = r'^{name}\s*=\s*"([^"]+)"'


def _find(path, name):
    text = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(_ASSIGNMENT.format(name=name), text, re.MULTILINE)
    assert match, f"{name} not found in {path}"
    return match.group(1)


def test_release_versions_agree():
    versions = {
        "cds_text_sync/__init__.py": _find("cds_text_sync/__init__.py", "__version__"),
        "cds-text-sync": _find("products/cds-text-sync/src/cds_text_sync/__init__.py", "__version__"),
        "cds-cli": _find("products/cds-cli/src/cds_cli/__init__.py", "__version__"),
        "cds-cli pyproject": _find("products/cds-cli/pyproject.toml", "version"),
        "visu-lint pyproject": _find("products/visu-lint/pyproject.toml", "version"),
        "daemon": _find("products/codesys-host/src/ide_bridge/ide_daemon_state.py", "VERSION"),
    }
    assert len(set(versions.values())) == 1, versions


def test_cli_pins_match_release_version():
    release = _find("cds_text_sync/__init__.py", "__version__")
    pyproject = (ROOT / "products/cds-cli/pyproject.toml").read_text(encoding="utf-8")
    assert f'"cds-text-sync=={release}"' in pyproject
    assert f'"visu-lint=={release}"' in pyproject


def test_cli_static_analyzer_pin_matches_the_analyzer_version():
    """The analyzer is versioned independently, so pin its actual version."""
    analyzer = _find(
        "products/cds-static-analyzer/src/cds_static_analyzer/__init__.py",
        "__version__",
    )
    assert _find("products/cds-static-analyzer/pyproject.toml", "version") == analyzer
    pyproject = (ROOT / "products/cds-cli/pyproject.toml").read_text(encoding="utf-8")
    assert f'"cds-static-analyzer=={analyzer}"' in pyproject


def test_product_console_scripts_match_the_root_wheel():
    """The root compatibility wheel and the split manifests ship the same commands."""
    import tomllib

    def _scripts(path):
        data = tomllib.loads((ROOT / path).read_text(encoding="utf-8"))
        return data.get("project", {}).get("scripts", {})

    root_scripts = _scripts("pyproject.toml")
    assert root_scripts["cts"] == "cds_cli.main:main"
    for manifest in (
        "products/cds-cli/pyproject.toml",
        "products/cds-static-analyzer/pyproject.toml",
        "products/visu-lint/pyproject.toml",
    ):
        for name, target in _scripts(manifest).items():
            assert root_scripts.get(name) == target, f"{name} differs in {manifest}"


def test_changelog_top_release_is_current_version():
    release = _find("cds_text_sync/__init__.py", "__version__")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^### Version (\S+)", changelog, re.MULTILINE)
    assert first and first.group(1) == release


def test_shipped_texts_do_not_name_the_maintainers_ssh_wrapper():
    """`tools/cts-win` was how the maintainer reached a Windows VM, not a product.

    Users run `cts` locally on Windows, so a changelog or a shipped guide that
    tells them to call the wrapper describes a setup they cannot have -- and
    the script is no longer in the repository at all. The daemon's own
    ``ssh_dacl_hint`` is a different thing: it is a runtime hint for a user who
    happens to be on an SSH session, not an instruction to install a wrapper.
    """
    shipped = [path for path in ("CHANGELOG.md", "readMe.md") if (ROOT / path).is_file()]
    shipped += [
        str(path.relative_to(ROOT))
        for folder in ("docs", "products/cds-cli/src/cds_cli/guides")
        for path in sorted((ROOT / folder).rglob("*.md"))
    ]
    for relative in shipped:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "cts-win" not in text, relative
