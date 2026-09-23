# -*- coding: utf-8 -*-
"""Read a CODESYS runtime Application CRC without opening a user project.

Run with CODESYS.exe --runscript=... --noUI; request and result paths are
provided through CDS_HEADLESS_CRC_INPUT/CDS_HEADLESS_CRC_OUTPUT.
The script creates a disposable project solely because ScriptOnlineDevice is
bound to a ScriptDeviceObject.  It never calls OnlineApplication.login(), so a
project mismatch cannot trigger an online change or download.
"""
from __future__ import print_function

import base64
import json
import os
import sys
import tempfile
import time
import uuid

try:
    _STRING_TYPES = (basestring,)  # noqa: F821  (IronPython 2)
except NameError:
    _STRING_TYPES = (str,)


def _argument(name, default=None):
    args = list(sys.argv[1:])
    for index, value in enumerate(args):
        if value == name and index + 1 < len(args):
            return args[index + 1]
        prefix = name + "="
        if value.startswith(prefix):
            return value[len(prefix):]
    return default


# Environment transport avoids the nested quoting differences between the
# vanilla CODESYS and Astra command-line parsers.  Explicit arguments remain
# useful for manual IDE-side diagnostics.
_OUTPUT_PATH = (
    _argument("--output")
    or os.environ.get("CDS_HEADLESS_CRC_OUTPUT")
    or os.environ.get("CDS_CRC_PROBE_OUTPUT")
)


def _emit(payload):
    text = json.dumps(payload, sort_keys=True)
    print("CRC_RESULT " + text)
    if _OUTPUT_PATH:
        with open(_OUTPUT_PATH, "w") as handle:
            handle.write(text + "\n")


def _watch_setting(name, default=None):
    return os.environ.get(name, default)


def _watch_emit(path, payload):
    """Append one complete event; JSONL permits consumers to tail safely."""
    payload["session_id"] = _watch_setting("CDS_HEADLESS_CRC_WATCH_SESSION", "")
    text = json.dumps(payload, sort_keys=True)
    with open(path, "a") as handle:
        handle.write(text + "\n")
        handle.flush()


def _watch_stop_requested(path):
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path) as handle:
            command = json.load(handle)
            if command.get("action") != "stop":
                return False
            requested_session = command.get("session_id")
            current_session = _watch_setting("CDS_HEADLESS_CRC_WATCH_SESSION", "")
            return not requested_session or requested_session == current_session
    except Exception:
        # A client may be halfway through replacing the small control file.
        return False


def _gateway(script_online, name):
    matches = [item for item in script_online.gateways if str(item.name) == name]
    if not matches:
        raise RuntimeError("Gateway not found: " + name)
    if len(matches) != 1:
        raise RuntimeError("Gateway name is ambiguous: " + name)
    return matches[0]


def _stable_error_code(error, stage):
    text = str(error).lower()
    if "gateway name is ambiguous" in text:
        return "gateway_ambiguous"
    if stage == "gateway" and "not found" in text:
        return "gateway_not_found"
    if stage == "validate":
        return "invalid_target"
    if stage == "scan":
        return "target_not_found" if "not found" in text else "scan_failed"
    if stage == "device":
        return "device_description_missing" if "device description" in text or "parameters wrong" in text else "connect_failed"
    if stage == "connect":
        return "connect_failed"
    if stage == "crc":
        return "crc_read_failed"
    return "target_failed"


def _scan_target(gateway, address):
    # find_address_by_ip is targeted (unlike a broadcast scan) and returns the
    # CODESYS router address required by the temporary project device.
    scanned_address = gateway.find_address_by_ip(address, 11740)
    cached = list(gateway.get_cached_network_scan_result())
    for item in cached:
        if str(item.address) == str(scanned_address):
            return scanned_address, item
    # Some gateway implementations do not populate the cache after a targeted
    # lookup.  A scan is still read-only and gives us the target DeviceID.
    scanned = list(gateway.perform_network_scan())
    for item in scanned:
        if str(item.address) == str(scanned_address):
            return scanned_address, item
    # A targeted TCP lookup and a broadcast scan may expose different router
    # addresses for the same PLC.  With exactly one scan target, it is still
    # unambiguous which DeviceID belongs to the address returned above.
    if len(scanned) == 1:
        return scanned_address, scanned[0]
    descriptions = []
    for item in cached + scanned:
        try:
            descriptions.append(
                "address={0}; name={1}; type={2}".format(
                    item.address, item.device_name, item.type_name
                )
            )
        except Exception:
            descriptions.append(str(item))
    raise RuntimeError(
        "Runtime address {0} was found, but no scan target matched it. "
        "Scan entries: {1}".format(scanned_address, descriptions)
    )


def _device_id_text(value):
    """Convert a scanned numeric CODESYS device ID to its repository form."""
    text = str(value)
    if not text.isdigit():
        return text
    number = int(text)
    return "{0:04x} {1:04x}".format((number >> 16) & 0xFFFF, number & 0xFFFF)


def _device_version_text(value):
    """Convert a scanned packed version to CODESYS' dotted repository form."""
    text = str(value)
    if not text.isdigit():
        return text
    number = int(text)
    return "{0}.{1}.{2}.{3}".format(
        (number >> 24) & 0xFF,
        (number >> 16) & 0xFF,
        (number >> 8) & 0xFF,
        number & 0xFF,
    )


def _read_crc(remote, local_path, application_name="Application"):
    if not isinstance(application_name, _STRING_TYPES) or not application_name:
        raise ValueError("application must be a non-empty name")
    if application_name in (".", "..") or "/" in application_name or "\\" in application_name:
        raise ValueError("application must be a single application name")
    remote_path = "PlcLogic/{0}/{0}.crc".format(application_name)
    remote.upload_file(remote_path, local_path, True)
    with open(local_path, "rb") as handle:
        data = handle.read()
    encoded = base64.b64encode(data)
    if not isinstance(encoded, str):
        encoded = encoded.decode("ascii")
    return {
        "crc_file_base64": encoded,
        "crc_file_size": len(data),
        "remote_file": remote_path,
    }


def _targets():
    input_path = _argument("--input") or os.environ.get("CDS_HEADLESS_CRC_INPUT")
    default_application = _argument("--application", "Application")
    if input_path:
        with open(input_path) as stream:
            request = json.load(stream)
        targets = request.get("targets", request) if isinstance(request, dict) else request
    else:
        ip = _argument("--ip")
        if not ip:
            raise RuntimeError("Usage: --input targets.json or --ip <PLC IPv4>")
        target = {
            "ip": ip,
            "gateway": _argument("--gateway", "Gateway-1"),
            "request_id": "1",
            "application": default_application,
        }
        # The single-target CLI path has no JSON object in which to name
        # credentials.  Honor these conventional names without ever copying
        # their values into the request or result.
        if (
            os.environ.get("CDS_CRC_PLC_USERNAME") is not None
            or os.environ.get("CDS_CRC_PLC_PASSWORD") is not None
        ):
            target["credentials"] = {
                "username_env": "CDS_CRC_PLC_USERNAME",
                "password_env": "CDS_CRC_PLC_PASSWORD",
            }
        targets = [target]
    if not isinstance(targets, list) or not targets:
        raise ValueError("targets must be a non-empty array")
    for target in targets:
        if isinstance(target, dict):
            target.setdefault("application", default_application)
    return targets


def _configure_credentials(target, device, se):
    """Configure per-target credentials without putting secrets in JSON output.

    A target may name inherited environment variables as follows::

        {"credentials": {"username_env": "PLC_USER", "password_env": "PLC_PASSWORD"}}

    The values themselves never enter the request, result, or error payload.
    """
    credentials = target.get("credentials")
    if credentials is None:
        return
    if not isinstance(credentials, dict):
        raise ValueError("credentials must be an object with username_env and password_env")
    username_env = credentials.get("username_env")
    password_env = credentials.get("password_env")
    if not isinstance(username_env, _STRING_TYPES) or not username_env:
        raise ValueError("credentials.username_env must name an environment variable")
    if not isinstance(password_env, _STRING_TYPES) or not password_env:
        raise ValueError("credentials.password_env must name an environment variable")
    username = os.environ.get(username_env)
    password = os.environ.get(password_env)
    if username is None or password is None:
        raise RuntimeError("credential environment variable is not set")
    online = getattr(se, "online", None)
    set_credentials = getattr(online, "set_specific_credentials", None)
    if not callable(set_credentials):
        raise RuntimeError("CODESYS profile does not support per-target credentials")
    # Newer profiles re-export the enum from scriptengine; Astra 1.7 exposes
    # it from scriptengine.online instead.  Both bindings describe the same
    # ScriptOnline API.
    credential_kind = getattr(se, "CredentialSourceKind", None)
    if credential_kind is None:
        credential_kind = getattr(online, "CredentialSourceKind", None)
    no_fallback = getattr(credential_kind, "none", None)
    if no_fallback is None:
        # ScriptOnline defines CredentialSourceKind.none as enum value zero.
        # Some Astra runtimes expose the property but not the enum wrapper.
        no_fallback = 0
    # Fail closed: a headless probe must never hang on an interactive password
    # dialog or silently use credentials from a different project session.
    online.auth_fallback_modes = no_fallback
    set_credentials(device, username, password)


def _check_targets(targets, se, IPAddress):

    results = []
    for index, target in enumerate(targets):
        is_mapping = isinstance(target, dict)
        ip = target.get("ip") if is_mapping else None
        gateway_name = target.get("gateway", "Gateway-1") if is_mapping else "Gateway-1"
        request_id = target.get("request_id", str(index + 1)) if is_mapping else str(index + 1)
        base = {"request_id": request_id, "target": {"ip": ip}}
        stage = "validate"
        try:
            if not is_mapping or not ip:
                raise ValueError("target must contain ip")
            IPAddress.Parse(ip)
            stage = "gateway"
            gateway = _gateway(se.online, gateway_name)
            stage = "scan"
            router_address, scanned = _scan_target(gateway, IPAddress.Parse(ip))
            target_id = scanned.device_id
            base["target"].update({
                "name": getattr(scanned, "device_name", ""),
                "device_type": getattr(target_id, "type", ""),
                "device_id": _device_id_text(target_id.id),
                "device_description_version": _device_version_text(target_id.version),
                "router_address": str(router_address),
            })
            unique = uuid.uuid4().hex
            project_path = os.path.join(tempfile.gettempdir(), "cds-crc-probe-" + unique + ".project")
            local_crc = os.path.join(tempfile.gettempdir(), "cds-crc-probe-" + unique + ".crc")
            project = None
            online_device = None
            try:
                stage = "device"
                project = projects.create(project_path, primary=True)  # noqa: F821
                device_id = DeviceID(  # noqa: F821
                    target_id.type,
                    _device_id_text(target_id.id),
                    _device_version_text(target_id.version),
                )
                project.add("CRC probe", device_id)
                devices = project.find("CRC probe")
                if not devices:
                    raise RuntimeError("CODESYS did not create the temporary CRC probe device")
                device = devices[0]
                device.set_gateway_and_address(gateway, router_address)
                _configure_credentials(target, device, se)
                stage = "connect"
                online_device = se.online.create_online_device(device)
                online_device.connect()
                stage = "crc"
                application_name = target.get("application", "Application")
                base["application"] = application_name
                base["crc_file"] = _read_crc(
                    online_device, local_crc, application_name
                )
                base["ok"] = True
            finally:
                if online_device is not None:
                    try:
                        online_device.disconnect()
                    except Exception:
                        pass
                    try:
                        online_device.Dispose()
                    except Exception:
                        pass
                if project is not None:
                    try:
                        project.close()
                    except Exception:
                        pass
                for path in (local_crc, project_path):
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                    except Exception:
                        pass
        except Exception as error:
            base.update({"ok": False, "error": {"code": _stable_error_code(error, stage), "message": str(error)}})
        results.append(base)
    return {
        "ok": all(item.get("ok") for item in results),
        "results": results,
        "summary": {
            "total": len(results),
            "succeeded": sum(1 for item in results if item.get("ok")),
            "failed": sum(1 for item in results if not item.get("ok")),
        },
    }


def _watch(targets, se, IPAddress):
    """Keep the same IDE alive, but never retain an online PLC connection."""
    output = _watch_setting("CDS_HEADLESS_CRC_WATCH_OUTPUT")
    control = _watch_setting("CDS_HEADLESS_CRC_WATCH_CONTROL")
    if not output:
        raise RuntimeError("CDS_HEADLESS_CRC_WATCH_OUTPUT is required in watch mode")
    try:
        interval = float(_watch_setting("CDS_HEADLESS_CRC_WATCH_INTERVAL", "60"))
    except ValueError:
        raise RuntimeError("CDS_HEADLESS_CRC_WATCH_INTERVAL must be numeric")
    if interval <= 0:
        raise RuntimeError("CDS_HEADLESS_CRC_WATCH_INTERVAL must be greater than zero")

    _watch_emit(output, {
        "ok": True,
        "event": "started",
        "interval_seconds": interval,
        "target_count": len(targets),
        "timestamp_unix": time.time(),
    })
    cycle = 0
    while not _watch_stop_requested(control):
        cycle += 1
        payload = _check_targets(targets, se, IPAddress)
        payload.update({
            "event": "cycle",
            "cycle": cycle,
            "interval_seconds": interval,
            "timestamp_unix": time.time(),
        })
        _watch_emit(output, payload)
        # Check once per second, so externally requested shutdown never waits a
        # complete interval.  A CRC cycle itself is deliberately not interrupted.
        remaining = interval
        while remaining > 0 and not _watch_stop_requested(control):
            sleep_for = min(1.0, remaining)
            time.sleep(sleep_for)
            remaining -= sleep_for
    _watch_emit(output, {
        "ok": True,
        "event": "stopped",
        "cycles": cycle,
        "timestamp_unix": time.time(),
    })


def main():
    import scriptengine as se
    from System.Net import IPAddress

    targets = _targets()
    if _watch_setting("CDS_HEADLESS_CRC_WATCH") == "1":
        _watch(targets, se, IPAddress)
    else:
        _emit(_check_targets(targets, se, IPAddress))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        _emit({
            "ok": False,
            "error": {"code": "invalid_request", "message": str(error)},
            "results": [],
        })
