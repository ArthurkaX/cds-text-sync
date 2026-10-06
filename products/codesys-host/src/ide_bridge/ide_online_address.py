# -*- coding: utf-8 -*-
"""ide_online_address.py -- resolve a PLC's router address from its IP.

``cts connect --ip`` used to hand the IP straight to
``set_gateway_and_address(gateway, ip)`` -- into the slot that wants a CODESYS
*router address*, not an IP.  Live, with the PLC reachable by ping and ssh,
that produced::

    Safe PLC login (OnlineChangeOption.Keep) failed ... No connection to the
    device. Please rescan your network.

and only a manual Online -> Login worked.  A broadcast scan cannot see an IDE
behind NAT, but a *targeted* lookup can:
``gateway.find_address_by_ip(IPAddress, 11740)`` asks the gateway for one
address directly and returns the router address to set on the device.

This is the same call the headless CRC probe already makes (see
products/codesys-host/headless/plc_crc.py, ``_scan_target``).  It is a separate
module only because headless is deployed and run on its own path contract; the
API and the fallbacks below are deliberately identical.

Every ScriptEngine call is hasattr-guarded and returns ``None`` on any failure,
so a build without the targeted lookup degrades to the old plain-string form
instead of raising out of the connect path.

IronPython 2.7: no f-strings, no annotations, no pathlib.
"""

from __future__ import print_function

#: The CODESYS gateway's default device port for a targeted address lookup.
GATEWAY_PORT = 11740


def _parse_ip(ip_address):
    """A System.Net.IPAddress for ``ip_address``, or the string as a fallback.

    Under CODESYS IronPython ``System.Net`` is always present.  Off the IDE
    (unit tests, a plain-CPython dry run) it is not, and passing the string is
    the closest faithful stand-in: the real lookup either accepts it or raises,
    and either way the caller falls back to the plain-string form.
    """
    text = str(ip_address)
    try:
        from System.Net import IPAddress

        return IPAddress.Parse(text)
    except Exception:
        return text or None


def find_gateway(script_online, gateway_name):
    """The single gateway named ``gateway_name``, else ``None``.

    ``None`` covers both "no such gateway" and "the name is ambiguous": either
    way there is no one gateway to ask, and the caller falls back.
    """
    try:
        matches = [
            item for item in script_online.gateways if str(item.name) == str(gateway_name)
        ]
    except Exception:
        return None
    if len(matches) != 1:
        return None
    return matches[0]


def resolve_router_address(gateway, ip_address, port=GATEWAY_PORT):
    """The router address for ``ip_address``, else ``None``.

    ``None`` means the targeted lookup is unavailable or found nothing; the
    caller must not treat it as "the PLC is unreachable" -- it is "could not
    resolve by address", and the plain-string form is still worth a try.
    """
    if gateway is None or not hasattr(gateway, "find_address_by_ip"):
        return None
    address = _parse_ip(ip_address)
    if address is None:
        return None
    try:
        resolved = gateway.find_address_by_ip(address, port)
    except Exception:
        return None
    return resolved


def unreachable_error(message):
    """Whether ``message`` is the device saying it could not be reached.

    CODESYS words this a few ways ("No connection to the device", "Please
    rescan your network", "rescan").  Matching all of them is what lets the
    caller retry once after re-resolving the address instead of giving up on
    the first wording.
    """
    text = str(message).lower()
    return (
        "no connection to the device" in text
        or "rescan" in text
        or "not found" in text and "address" in text
    )


def login_refused_error(message):
    """Whether the PLC was reached but refused the login (credentials/dialog)."""
    text = str(message).lower()
    return (
        "access denied" in text
        or "password" in text
        or "credential" in text
        or "not authorized" in text
        or "user management" in text
    )


__all__ = [
    "GATEWAY_PORT",
    "find_gateway",
    "resolve_router_address",
    "unreachable_error",
    "login_refused_error",
]
