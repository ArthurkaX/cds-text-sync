"""The release version is said once, and the changelog names it."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# cts.exe and the agent take their version from here; `cts --version` prints it.
RELEASE_PROPS = "products/codesys-agent/Directory.Build.props"


def _release():
    text = (ROOT / RELEASE_PROPS).read_text(encoding="utf-8")
    match = re.search(r"<Version>([^<]+)</Version>", text)
    assert match, f"no <Version> in {RELEASE_PROPS}"
    return match.group(1)


def test_changelog_top_release_is_current_version():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^### Version (\S+)", changelog, re.MULTILINE)
    assert first and first.group(1) == _release()


def test_shipped_texts_do_not_name_the_maintainers_ssh_wrapper():
    """`tools/cts-win` was how the maintainer reached a Windows VM, not a product.

    Users run `cts` locally on Windows, so a changelog or a shipped guide that
    tells them to call the wrapper describes a setup they cannot have -- and
    the script is no longer in the repository at all.
    """
    shipped = [path for path in ("CHANGELOG.md", "readMe.md") if (ROOT / path).is_file()]
    shipped += [
        str(path.relative_to(ROOT))
        for folder in ("docs", "products/codesys-agent/src/Cts.Agent.Core/Guides")
        for path in sorted((ROOT / folder).rglob("*.md"))
    ]
    for relative in shipped:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "cts-win" not in text, relative
