"""Build the documentation site (cds-text-sync.pages.dev) from the repository's Markdown.

The pages are the files GitHub shows, not copies: the README is the home page,
then docs/, the installer guide, the changelog and the guides cts.exe serves
with `cts guide`. They are staged into .site-src/ with their links rewritten
(a link to another page goes to that page on the site, a link to code goes to
GitHub, GitHub's `> [!NOTE]` boxes become admonitions), and Zensical builds
site/ from there with mkdocs.yml (Material for MkDocs' successor, which
reads the same file).

Usage::

    pip install -r requirements-site.txt
    python3 tools/site.py            # build into site/
    python3 tools/site.py --serve    # preview on http://127.0.0.1:8000
"""

import argparse
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGE = REPO / ".site-src"
GITHUB = "https://github.com/ArthurkaX/cds-text-sync/blob/main/"
GUIDES = "products/codesys-agent/src/Cts.Agent.Core/Guides/"

# Repository path -> page on the site.
PAGES = {
    "readMe.md": "index.md",
    "docs/README.md": "documentation.md",
    "irm/setup.md": "setup.md",
    "CHANGELOG.md": "changelog.md",
}
ASSETS = ("img/",)

LINK = re.compile(r"(\]\()([^)\s]+)(\))|((?:src|srcset|href)=\")([^\"]+)(\")")
ALERT = re.compile(r"^> \[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$")
ALERT_KIND = {"NOTE": "note", "TIP": "tip", "IMPORTANT": "info", "WARNING": "warning", "CAUTION": "danger"}


def pages():
    """Every page: the fixed ones, each docs/*.md and each guide."""
    found = dict(PAGES)
    for path in sorted((REPO / "docs").glob("*.md")):
        rel = path.relative_to(REPO).as_posix()
        found.setdefault(rel, path.name)
    for path in sorted((REPO / GUIDES).rglob("*.md")):
        rel = path.relative_to(REPO).as_posix()
        found.setdefault(rel, "guides/" + path.relative_to(REPO / GUIDES).as_posix())
    return found


def rewrite(target, source, page, found):
    """The link *target* written in *source* (repository path) as it reads on *page*."""
    if re.match(r"^[a-z]+:|^#|^//", target):
        return target
    path, _, anchor = target.partition("#")
    if not path:
        return target
    repo_path = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
    if repo_path in found:
        site_path = found[repo_path]
    elif repo_path.startswith(ASSETS):
        site_path = repo_path
    else:
        kind = "tree/main/" if (REPO / repo_path).is_dir() else "blob/main/"
        return GITHUB.replace("blob/main/", kind) + repo_path + ("#" + anchor if anchor else "")
    relative = posixpath.relpath(site_path, posixpath.dirname(page) or ".")
    return relative + ("#" + anchor if anchor else "")


def alerts(text):
    """GitHub's `> [!NOTE]` blocks as mkdocs admonitions."""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        match = ALERT.match(lines[i])
        if not match:
            out.append(lines[i])
            i += 1
            continue
        out.append("!!! " + ALERT_KIND[match.group(1)])
        i += 1
        while i < len(lines) and lines[i].startswith(">"):
            body = lines[i][1:]
            out.append("    " + body[1:] if body.startswith(" ") else "    " + body)
            i += 1
    return "\n".join(out)


def stage():
    if STAGE.exists():
        shutil.rmtree(STAGE)
    found = pages()
    for source, page in found.items():
        text = (REPO / source).read_text(encoding="utf-8")

        def link(match):
            if match.group(1):
                return match.group(1) + rewrite(match.group(2), source, page, found) + match.group(3)
            return match.group(4) + rewrite(match.group(5), source, page, found) + match.group(6)

        out = STAGE / page
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(alerts(LINK.sub(link, text)), encoding="utf-8")
    for asset in ASSETS:
        shutil.copytree(REPO / asset, STAGE / asset)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve", action="store_true", help="preview instead of building")
    serve = parser.parse_args().serve
    stage()
    command = ["serve"] if serve else ["build", "--clean"]
    sys.exit(subprocess.run([sys.executable, "-m", "zensical"] + command, cwd=REPO).returncode)


if __name__ == "__main__":
    main()
