# -*- coding: utf-8 -*-
"""
test_connect_by_ip.py — connect by IP must resolve a router address first.

Live, with the PLC reachable by ping and ssh, ``cts connect --ip 192.168.1.10``
answered::

    Safe PLC login (OnlineChangeOption.Keep) failed ... No connection to the
    device. Please rescan your network.

because the IP was handed to ``set_gateway_and_address(gateway, address)`` --
into the slot that wants a CODESYS router address.  A broadcast scan cannot
cross NAT, but ``gateway.find_address_by_ip(IPAddress, 11740)`` is targeted and
is what the headless CRC probe already uses.  ``ide_online_address`` is the
daemon-side twin of that logic; ``connect_to_device_impl`` resolves first and
only falls back to the plain string form.
"""

from __future__ import print_function

import importlib
import os
import sys
from types import SimpleNamespace

import pytest

_BRIDGE = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__), "..", "..", "products", "codesys-host",
        "src", "ide_bridge",
    )
)
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

STATE_KEY = "_codesys_daemon_loop"


@pytest.fixture(autouse=True)
def _clean_state():
    saved = getattr(sys, STATE_KEY, None)
    if hasattr(sys, STATE_KEY):
        delattr(sys, STATE_KEY)
    yield
    if saved is None:
        if hasattr(sys, STATE_KEY):
            delattr(sys, STATE_KEY)
    else:
        setattr(sys, STATE_KEY, saved)


@pytest.fixture
def address():
    return importlib.import_module("ide_online_address")


@pytest.fixture
def helpers():
    return importlib.import_module("ide_online_helpers")


# ── the resolver ───────────────────────────────────────────────────────────


class _Gateway(object):
    def __init__(self, name="Gateway-1", router="ROUTER-1", raise_on_lookup=None):
        self.name = name
        self._router = router
        self._raise = raise_on_lookup
        self.calls = []

    def find_address_by_ip(self, ip, port):
        self.calls.append((str(ip), port))
        if self._raise:
            raise self._raise
        return self._router


def test_resolve_returns_the_router_address(address):
    gateway = _Gateway(router="ROUTER-9")
    assert address.resolve_router_address(gateway, "192.168.1.10") == "ROUTER-9"
    assert gateway.calls == [("192.168.1.10", 11740)]


def test_resolve_is_none_when_the_gateway_lacks_the_lookup(address):
    assert address.resolve_router_address(object(), "192.168.1.10") is None


def test_resolve_is_none_when_the_lookup_raises(address):
    gateway = _Gateway(raise_on_lookup=RuntimeError("no route"))
    assert address.resolve_router_address(gateway, "192.168.1.10") is None


def test_find_gateway_matches_by_name(address):
    gw = _Gateway(name="Gateway-1")
    online = SimpleNamespace(gateways=[_Gateway(name="Other"), gw])
    assert address.find_gateway(online, "Gateway-1") is gw


def test_find_gateway_is_none_when_absent_or_ambiguous(address):
    assert address.find_gateway(SimpleNamespace(gateways=[]), "Gateway-1") is None
    online = SimpleNamespace(gateways=[_Gateway(), _Gateway()])
    assert address.find_gateway(online, "Gateway-1") is None


# ── error classification ───────────────────────────────────────────────────


def test_the_rescan_wording_is_unreachable(address):
    assert address.unreachable_error(
        "No connection to the device. Please rescan your network."
    )
    assert not address.login_refused_error(
        "No connection to the device. Please rescan your network."
    )


def test_credentials_are_a_refused_login(address):
    assert address.login_refused_error("Access denied: wrong password")
    assert not address.unreachable_error("Access denied: wrong password")


# ── connect_to_device_impl wires the resolver in ───────────────────────────


class _Device(object):
    def __init__(self):
        self.calls = []

    def get_name(self):
        return "Device"

    def set_gateway_and_address(self, first, second):
        self.calls.append((first, second))


def _project(device):
    def get_children(recursive=False):
        return [device]

    return SimpleNamespace(get_children=get_children)


def _install(monkeypatch, helpers, device, router="ROUTER-1", login_error=None):
    gateway = _Gateway(router=router)

    class _OnlineApp(object):
        # No liveness flags: the daemon sees no cached session and logs in,
        # which is the path under test.
        def __init__(self):
            self.login_calls = 0

        def login(self, option, delete_foreign):
            self.login_calls += 1
            if login_error:
                raise login_error

    online_app = _OnlineApp()
    fake_se = SimpleNamespace(
        online=SimpleNamespace(gateways=[gateway]),
        OnlineChangeOption=SimpleNamespace(Keep="KEEP"),
    )
    monkeypatch.setitem(sys.modules, "scriptengine", fake_se)
    monkeypatch.setattr(
        helpers, "ensure_online_connection", lambda project: (online_app, device)
    )
    monkeypatch.setattr(helpers, "_find_main_device", lambda project: device)
    sys._codesys_daemon_loop = {}
    return online_app, gateway


def test_connect_sets_the_router_address_not_the_raw_ip(monkeypatch, helpers):
    device = _Device()
    online_app, gateway = _install(monkeypatch, helpers, device, router="ROUTER-7")

    result = helpers.connect_to_device_impl(_project(device), "192.168.1.10")

    assert result["state"] == "connected"
    # First attempt used the resolved router address, gateway object included.
    assert device.calls[0] == (gateway, "ROUTER-7")
    assert online_app.login_calls == 1


def test_connect_falls_back_to_the_string_form_without_a_lookup(monkeypatch, helpers):
    device = _Device()
    gateway = SimpleNamespace(name="Gateway-1")  # no find_address_by_ip

    class _OnlineApp(object):
        def login(self, option, delete_foreign):
            return None

    monkeypatch.setitem(
        sys.modules,
        "scriptengine",
        SimpleNamespace(
            online=SimpleNamespace(gateways=[gateway]),
            OnlineChangeOption=SimpleNamespace(Keep="KEEP"),
        ),
    )
    monkeypatch.setattr(
        helpers, "ensure_online_connection",
        lambda project: (_OnlineApp(), device),
    )
    monkeypatch.setattr(helpers, "_find_main_device", lambda project: device)
    sys._codesys_daemon_loop = {}

    helpers.connect_to_device_impl(_project(device), "192.168.1.10")

    assert device.calls[0] == ("Gateway-1", "192.168.1.10")


def test_a_remembered_ip_is_reused_when_ip_is_omitted(monkeypatch, helpers):
    device = _Device()
    _install(monkeypatch, helpers, device, router="ROUTER-3")
    sys._codesys_daemon_loop["last_connect_ip"] = "10.0.0.5"

    helpers.connect_to_device_impl(_project(device))

    assert device.calls[0][0].find_address_by_ip
    assert sys._codesys_daemon_loop["last_connect_ip"] == "10.0.0.5"


def test_connect_stores_the_ip_in_daemon_state_not_the_project(monkeypatch, helpers):
    device = _Device()
    _install(monkeypatch, helpers, device)

    helpers.connect_to_device_impl(_project(device), "192.168.1.10")

    assert sys._codesys_daemon_loop["last_connect_ip"] == "192.168.1.10"
    # The project object is untouched: no attribute was written on it.
    assert not hasattr(_project(device), "last_connect_ip")


# ── the error must say which failure it was ────────────────────────────────


def test_unreachable_login_names_the_manual_fix(monkeypatch, helpers):
    device = _Device()
    _install(
        monkeypatch, helpers, device,
        login_error=RuntimeError("No connection to the device. Please rescan your network."),
    )

    with pytest.raises(RuntimeError) as excinfo:
        helpers.connect_to_device_impl(_project(device), "192.168.1.10")

    message = str(excinfo.value)
    assert "PLC unreachable" in message
    assert "Online -> Login" in message
    assert "rescan" not in message.lower()


def test_refused_login_is_not_reported_as_unreachable(monkeypatch, helpers):
    device = _Device()
    _install(monkeypatch, helpers, device, login_error=RuntimeError("Access denied"))

    with pytest.raises(RuntimeError) as excinfo:
        helpers.connect_to_device_impl(_project(device), "192.168.1.10")

    message = str(excinfo.value)
    assert "login was refused" in message
    assert "PLC unreachable" not in message
