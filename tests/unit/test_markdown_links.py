import re
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)")


def test_readme_and_docs_relative_links_exist():
    # The archived changelog is historical source material and deliberately
    # excluded from this current-document link check.
    markdown = [
        ROOT / "readMe.md",
        *sorted(path for path in (ROOT / "docs").glob("*.md") if path.name != "changelog-archive.md"),
    ]
    missing = []

    for document in markdown:
        for target in LINK.findall(document.read_text(encoding="utf-8")):
            parsed = urlsplit(target.strip("<>"))
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            if not (document.parent / parsed.path).exists():
                missing.append(f"{document.relative_to(ROOT)}: {target}")

    assert not missing, "Broken relative Markdown links:\n" + "\n".join(missing)
