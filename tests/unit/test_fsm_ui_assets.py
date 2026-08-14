"""Static guards on the FSM window's bundled assets.

The page itself needs a browser to exercise, but three properties are worth
pinning without one: the assets ship with the package, the page loads only
package-local files, and the untrusted-text rule holds - exactly one
``innerHTML`` site, the one that inserts the SVG the Python renderer already
escaped.
"""

import re
from pathlib import Path

import cds_text_sync.fsm.ui as fsm_ui


# fsm.ui resolves the page with ``shell.package_page(__file__, ...)``, so
# anchoring on that module points at the same directory the window loads --
# unlike the root ``cds_text_sync`` shim, whose __file__ is the shim itself.
ASSETS = Path(fsm_ui.__file__).parent.parent / "fsm_ui_assets"


def _read(name):
    return (ASSETS / name).read_text(encoding="utf-8")


def test_assets_are_present_and_packaged():
    for name in ("__init__.py", "index.html", "styles.css", "app.js"):
        assert (ASSETS / name).is_file(), name


def test_page_loads_only_package_local_files():
    html = _read("index.html")
    sources = re.findall(r'(?:src|href)="([^"]+)"', html)
    assert sources == ["styles.css", "app.js"]
    # No CDN, no remote font, no inline script.
    assert "//" not in "".join(sources)
    assert "<script>" not in html


def test_app_js_has_exactly_one_innerhtml_and_it_is_the_svg_host():
    lines = _read("app.js").splitlines()
    # Comments say the word too; only assignments count.
    hits = [line.strip() for line in lines if re.search(r"\.innerHTML\s*=", line)]
    assert hits == ['$("svg-host").innerHTML = markup;']


def test_app_js_uses_no_dynamic_code_execution():
    app = _read("app.js")
    assert "eval(" not in app
    assert "new Function" not in app


def test_app_js_calls_every_bridge_method_the_api_exposes():
    from cds_text_sync.fsm.api import FsmApi

    app = _read("app.js")
    exposed = [
        name for name in dir(FsmApi)
        if not name.startswith("_")
        and callable(getattr(FsmApi, name, None))
        # close() is lifecycle and progress() is polled by the shell, not the
        # page; every other bridge method must have a caller in the window.
        and name not in ("close", "progress")
    ]
    missing = [name for name in exposed if '"' + name + '"' not in app]
    assert missing == []
