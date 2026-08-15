"""Static guards on the FSM window's bundled assets.

The page itself needs a browser to exercise, but three properties are worth
pinning without one: the assets ship with the package, the page loads only
package-local files, and the untrusted-text rule holds - exactly one
``innerHTML`` site, the one that inserts the SVG the Python renderer already
escaped.
"""

import re

import cds_text_sync.fsm.ui as fsm_ui


ASSETS = fsm_ui.page_path().parent


def _read(name):
    return (ASSETS / name).read_text(encoding="utf-8")


def test_the_page_the_window_loads_exists():
    # A page path that does not resolve is invisible to every other test here:
    # the window simply opens on ERR_FILE_NOT_FOUND.
    page = fsm_ui.page_path()
    assert page.is_file(), page


def test_the_analyzer_page_the_window_loads_exists():
    import cds_text_sync.ui as analyzer_ui

    from cds_text_sync.webui import shell

    page = shell.package_page(analyzer_ui.__file__, "ui_assets")
    assert page.is_file(), page


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


def test_app_js_wires_ctrl_wheel_zoom_on_the_canvas():
    app = _read("app.js")
    # A passive wheel listener silently loses preventDefault and the WebView
    # zooms the whole page instead of the diagram.
    assert 'canvas.addEventListener("wheel"' in app
    assert "{ passive: false }" in app
    assert "event.preventDefault()" in app
    assert "event.ctrlKey" in app


def test_the_copy_buttons_are_wired_in_the_page_and_the_script():
    html = _read("index.html")
    app = _read("app.js")
    # The bridge returns both encodings, so a copy button the script never
    # wires would leave the second one unreachable from the window.
    assert 'id="copy-plantuml"' in html
    assert '$("copy-mermaid").addEventListener("click",' in app
    assert '$("copy-plantuml").addEventListener("click",' in app
