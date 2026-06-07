# -*- coding: utf-8 -*-
"""
ide_online_helpers.py — Online connection helpers for CODESYS IronPython daemon.
Provides connect, disconnect, read/write variable, simulation, and credentials.
Reusable by ide_daemon.pyw.
"""

from __future__ import print_function
import traceback
import os
import re
import sys


# ── Atomic file write using .NET System.IO.File.Replace ────────────────────

def atomic_write(file_path, content):
    """Atomically replace a file using .NET System.IO.File.Replace (NTFS).
    
    Guarantees readers see either the old file or the new file, never partial.
    Works inside CODESYS IronPython environment (which has full .NET access).
    
    Args:
        file_path: Target file path (str)
        content: File content (bytes or unicode str)
    """
    import os
    import time
    
    tmp_path = file_path + ".tmp"
    
    # Accept either bytes or unicode
    if isinstance(content, str):
        content = content.encode('utf-8')
    
    # Write to temp file with fsync for durability
    with open(tmp_path, 'wb') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    
    # Atomic replace via .NET (preferred path in CODESYS IronPython)
    try:
        from System.IO import File as NetFile
        if os.path.exists(file_path):
            # Replace = atomic delete+rename on NTFS
            # 3rd param (None) = no backup copy needed
            NetFile.Replace(tmp_path, file_path, None)
        else:
            NetFile.Move(tmp_path, file_path)
    except Exception:
        # Fallback: retry-based remove + rename
        # Antivirus / Defender scanning .tmp can hold transient lock
        for attempt in range(5):
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                os.rename(tmp_path, file_path)
                return
            except OSError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))


# ── Output capture for script execution ────────────────────────────────────

class OutputCapture:
    """Capture stdout/stderr for CODESYS script execution."""
    def __init__(self):
        self._buffer = []
    
    def write(self, s):
        self._buffer.append(str(s))
    
    def writelines(self, lines):
        self._buffer.extend([str(l) for l in lines])
    
    def flush(self):
        pass
    
    def getvalue(self):
        return ''.join(self._buffer)


# ── Online connection helpers ──────────────────────────────────────────────

# Shared state key — must match ide_reverse_pipe_loop.py
DAEMON_STATE_KEY = "_codesys_daemon_loop"


def _get_daemon_state():
    """Get the daemon shared state dict."""
    state = getattr(sys, DAEMON_STATE_KEY, None)
    if not isinstance(state, dict):
        return None
    return state


def _get_cached_online_app():
    """Get cached online_app from shared state, with validation."""
    state = _get_daemon_state()
    if state is None:
        return None, None
    online_app = state.get("online_app")
    target_app = state.get("online_target_app")
    if online_app is None or target_app is None:
        return None, None
    # Validate — check if still alive
    try:
        _ = online_app.is_connected  # fast property access
        return online_app, target_app
    except Exception:
        state["online_app"] = None
        state["online_target_app"] = None
        return None, None

def find_device_with_capability(project, attr_name):
    """Find the first child of project that supports a given capability.
    
    Args:
        project: CODESYS project object
        attr_name: Attribute name to check (e.g. 'set_gateway_and_address')
    
    Returns:
        Device object or None
    """
    for child in project.get_children(True):
        if hasattr(child, attr_name):
            return child
    return None


def get_active_application(project):
    """Get the active application from a project.
    
    Args:
        project: CODESYS project object
    
    Returns:
        Application object or None
    """
    target_app = None
    try:
        target_app = project.active_application
    except Exception:
        pass
    
    if not target_app:
        for child in project.get_children(True):
            if hasattr(child, 'is_application'):
                try:
                    if child.is_application:
                        target_app = child
                        break
                except Exception:
                    pass
    
    return target_app


def ensure_online_connection(project, prefer_device=False):
    """Create an online application connection for the given project.
    
    Creates the online application object that allows reading/writing
    PLC variables and checking device state.
    
    Args:
        project: CODESYS project object
        prefer_device: If True, try create_online_device first. Disabled by
                       default because create_online_device can corrupt the
                       online stack in CODESYS SP21+/SP22.
    
    Returns:
        (online_application, target_application) tuple
    
    Raises:
        RuntimeError with actionable message on failure
    """
    import scriptengine as se
    
    online_app, target_app = _get_cached_online_app()
    if online_app is not None and target_app is not None:
        return online_app, target_app
    
    # Try device-based approach first if preferred
    if prefer_device:
        try:
            device = _find_main_device(project)
            if device is not None:
                online_dev = se.online.create_online_device(device)
                if online_dev is not None:
                    # Try to get application from online device
                    if hasattr(online_dev, 'application'):
                        online_app = online_dev.application
                        if online_app is not None:
                            return online_app, device
                    # Or try to get application recursively
                    for child in device.get_children(True):
                        if hasattr(child, 'is_application'):
                            try:
                                if child.is_application:
                                    online_app = se.online.create_online_application(child)
                                    if online_app is not None:
                                        return online_app, child
                            except Exception:
                                pass
        except Exception:
            pass
    
    # Fallback to direct application approach
    target_app = get_active_application(project)
    if not target_app:
        raise RuntimeError(
            "No active application found. "
            "Open the project in the IDE and right-click the Application node "
            "-> Set Active Application."
        )
    
    app_name = getattr(target_app, 'get_name', lambda: '?')()
    
    try:
        online_app = se.online.create_online_application(target_app)
        if online_app is not None:
            # Auto-login on fresh connection (gateway/ip already set by connect_to_device)
            try:
                _ensure_logged_in(online_app)
            except Exception:
                pass  # Login might fail if gateway not set — read/write will give clear error
            return online_app, target_app
    except Exception as e:
        msg = (
            "create_online_application failed for '%s': %s. "
            "For simulation, call set_simulation_mode(enable=True) first; "
            "for a real PLC, ensure the gateway/address is set on the device. "
            "If simulation is engaged but this still raises 'Stack empty', "
            "click Online -> Login once in the IDE for this session."
        ) % (app_name, e)
        raise RuntimeError(msg)
    
    raise RuntimeError(
        "create_online_application returned None for '%s'." % app_name
    )


def _find_main_device(project):
    """Find the first device object that looks like a main controller."""
    for child in project.get_children(True):
        name = getattr(child, 'get_name', lambda: '?')()
        child_type = str(type(child).__name__)
        # Look for common controller names
        if name in ('HSC', 'LCC', 'Device') or 'Controller' in child_type or 'Device' in child_type:
            if hasattr(child, 'set_simulation_mode'):
                return child
    # Fallback: first device with set_simulation_mode
    for child in project.get_children(True):
        if hasattr(child, 'set_simulation_mode'):
            return child
    return None


def connect_to_device_impl(project, ip_address="", gateway_name="Gateway-1"):
    """Connect to a real PLC device.
    
    Sets gateway and IP address on the device, then creates online connection
    and logs in.
    
    Args:
        project: CODESYS project object
        ip_address: IP address of the PLC (empty = use existing config)
        gateway_name: Gateway name (default: "Gateway-1")
    
    Returns:
        dict with state info
    """
    if ip_address:
        candidates = []
        main_device = _find_main_device(project)
        if main_device is not None:
            candidates.append(main_device)
        for child in project.get_children(True):
            if hasattr(child, 'set_gateway_and_address'):
                candidates.append(child)
        seen = set()
        device = None
        device_errors = []
        for cand in candidates:
            key = str(getattr(cand, 'Guid', id(cand)))
            if key in seen:
                continue
            seen.add(key)
            try:
                dev_name = getattr(cand, 'get_name', lambda: '?')()
                cand.set_gateway_and_address(gateway_name, ip_address)
                device = cand
                break
            except Exception as e:
                device_errors.append(str(e))
        if device is None:
            raise RuntimeError(
                "No writable device in the project supports set_gateway_and_address. "
                "Errors: " + "; ".join(device_errors[-5:])
            )
    
    online_app, target_app = ensure_online_connection(project)
    app_name = getattr(target_app, 'get_name', lambda: "Unknown")()
    
    # CODESYS SP22 login() takes (OnlineChangeOption, password), but enum
    # member names differ between versions. Pick a safe online-change option.
    import scriptengine as se
    if not hasattr(online_app, 'login'):
        raise TypeError("Online application does not support login().")

    login_errors = []
    option_candidates = []
    if hasattr(se, 'OnlineChangeOption'):
        enum_type = se.OnlineChangeOption
        for name in (
            'TryOnlineChange', 'Try', 'PerformOnlineChange',
            'OnlineChange', 'Always', 'Never', 'NoOnlineChange'
        ):
            try:
                if hasattr(enum_type, name):
                    option_candidates.append(getattr(enum_type, name))
            except Exception:
                pass
        try:
            from System import Enum
            values = list(Enum.GetValues(enum_type))
            preferred = []
            fallback = []
            for value in values:
                name = str(Enum.GetName(enum_type, value))
                if 'try' in name.lower() or 'change' in name.lower():
                    preferred.append(value)
                else:
                    fallback.append(value)
            option_candidates.extend(preferred + fallback)
        except Exception:
            pass

    seen = set()
    for option in option_candidates:
        key = str(option)
        if key in seen:
            continue
        seen.add(key)
        try:
            online_app.login(option, "")
            break
        except Exception as e:
            login_errors.append(str(e))
    else:
        for args in ((0, ""), (None, ""), tuple()):
            try:
                online_app.login(*args)
                break
            except Exception as e:
                login_errors.append(str(e))
        else:
            raise RuntimeError("login() failed: " + "; ".join(login_errors[-5:]))
    
    state = "connected"
    if hasattr(online_app, 'application_state'):
        try:
            state = str(online_app.application_state)
        except Exception:
            pass
    
    try:
        daemon_state = _get_daemon_state()
        if daemon_state is not None:
            daemon_state['online_app'] = online_app
            daemon_state['online_target_app'] = target_app
    except Exception:
        pass

    return {
        "state": state,
        "application": app_name,
        "device": str(ip_address) if ip_address else "existing config",
    }


def disconnect_from_device_impl(project):
    """Disconnect from a PLC device.
    
    Logs out and clears cached online_app.
    Next read/write will create a fresh connection with auto-login.
    Safe to call when not connected — returns success with note.
    
    Returns:
        dict with state info
    """
    import scriptengine as se
    try:
        # Use cached online_app if available
        online_app, _ = _get_cached_online_app()
        if online_app is None:
            target_app = get_active_application(project)
            if target_app is not None:
                online_app = se.online.create_online_application(target_app)
        if online_app is not None:
            try:
                online_app.logout()
            except Exception:
                pass
        # Clear cache so next call creates fresh connection
        try:
            daemon_state = _get_daemon_state()
            if daemon_state is not None:
                daemon_state['online_app'] = None
                daemon_state['online_target_app'] = None
        except Exception:
            pass
        return {"state": "disconnected"}
    except Exception as e:
        return {"state": "disconnected", "note": str(e)}


def download_impl(project, start=True):
    """Force a FULL download of the active application to the PLC.

    connect_to_device logs in with an online-change option and force_download
    disabled, so newly-added objects (new GVL/DUT/POU and their symbols) never
    reach the controller. This logs out, then logs in with the second login
    argument (bForceDownload) set to True and a "no online change" option, which
    stops the running app and downloads the freshly built code. Optionally
    starts the app again afterwards (a full download leaves it stopped).

    Returns a dict describing the result.
    """
    import scriptengine as se

    online_app, target_app = ensure_online_connection(project)
    if online_app is None:
        raise RuntimeError("Not connected. Call connect_to_device first.")
    if not hasattr(online_app, 'login'):
        raise TypeError("Online application does not support login().")

    # Log out of the (old) running app first so login performs a fresh download.
    try:
        online_app.logout()
    except Exception:
        pass

    # Prefer options that do NOT online-change, so login does a real download.
    options = []
    if hasattr(se, 'OnlineChangeOption'):
        et = se.OnlineChangeOption
        for nm in ('Never', 'NoOnlineChange', 'ForceDownload', 'Force',
                   'Try', 'TryOnlineChange'):
            if hasattr(et, nm):
                options.append((nm, getattr(et, nm)))

    errors = []
    used = None
    for nm, opt in options:
        try:
            # Second arg = bForceDownload -> True forces a full download.
            online_app.login(opt, True)
            used = nm
            break
        except Exception as e:
            errors.append("{0}: {1}".format(nm, str(e)[:160]))
    if used is None:
        # Last resort: raw positional force-download attempts.
        for args in ((0, True), (None, True)):
            try:
                online_app.login(*args)
                used = "raw{0}".format(args)
                break
            except Exception as e:
                errors.append("raw{0}: {1}".format(args, str(e)[:160]))
    if used is None:
        raise RuntimeError("Force download failed: " + "; ".join(errors[-4:]))

    started = False
    if start:
        try:
            _call_online_app(online_app, ('start',))
            started = True
        except Exception as e:
            errors.append("start: {0}".format(str(e)[:160]))

    state = "unknown"
    if hasattr(online_app, 'application_state'):
        try:
            state = str(online_app.application_state)
        except Exception:
            pass

    # Refresh the cached online_app so later reads/writes reuse this session.
    try:
        daemon_state = _get_daemon_state()
        if daemon_state is not None:
            daemon_state['online_app'] = online_app
            daemon_state['online_target_app'] = target_app
    except Exception:
        pass

    app_name = getattr(target_app, 'get_name', lambda: "Unknown")()
    return {"downloaded": True, "option": used, "started": started,
            "state": state, "application": app_name}


def _call_online_app(io_obj, names, *args):
    last_error = None
    for name in names:
        if hasattr(io_obj, name):
            try:
                method = getattr(io_obj, name)
                if callable(method):
                    return method(*args)
            except Exception as e:
                last_error = e
    if last_error is not None:
        raise last_error
    raise AttributeError("None of these methods exist: {0}".format(", ".join(names)))


def _ensure_logged_in(online_app):
    """Ensure the online application is logged in. Auto-login if needed."""
    # Check if already logged in via is_logged_in
    logged_in = False
    if hasattr(online_app, 'is_logged_in'):
        try:
            val = online_app.is_logged_in
            if callable(val):
                val = val()
            logged_in = bool(val)
        except Exception:
            pass
    else:
        # Fallback: try application_state (some SP22 versions lack is_logged_in)
        try:
            online_app.application_state
            logged_in = True
        except Exception:
            pass
    
    if logged_in:
        return
    # Auto-login with best-effort OnlineChangeOption
    if hasattr(online_app, 'login'):
        import scriptengine as se
        login_errors = []
        option_candidates = []
        if hasattr(se, 'OnlineChangeOption'):
            enum_type = se.OnlineChangeOption
            for name in (
                'TryOnlineChange', 'Try', 'PerformOnlineChange',
                'OnlineChange', 'Always', 'Never', 'NoOnlineChange'
            ):
                try:
                    if hasattr(enum_type, name):
                        option_candidates.append(getattr(enum_type, name))
                except Exception:
                    pass
            try:
                from System import Enum
                values = list(Enum.GetValues(enum_type))
                preferred = []
                fallback = []
                for value in values:
                    name = str(Enum.GetName(enum_type, value))
                    if 'try' in name.lower() or 'change' in name.lower():
                        preferred.append(value)
                    else:
                        fallback.append(value)
                option_candidates.extend(preferred + fallback)
            except Exception:
                pass

        seen = set()
        for option in option_candidates:
            key = str(option)
            if key in seen:
                continue
            seen.add(key)
            try:
                online_app.login(option, "")
                return
            except Exception as e:
                login_errors.append(str(e))
        # Last resort: try raw args
        for args in ((0, ""), (None, ""), tuple()):
            try:
                online_app.login(*args)
                return
            except Exception as e:
                login_errors.append(str(e))
        raise RuntimeError("Auto-login failed: " + "; ".join(login_errors[-5:]))


def read_variable_impl(project, variable_name):
    """Read a variable value from an online PLC connection.
    
    Auto-connects if online_app is cached but not logged in.
    """
    if not variable_name:
        raise ValueError("Variable name is required")
    
    online_app, _ = ensure_online_connection(project)
    if online_app is None:
        raise RuntimeError("Not connected. Call connect_to_device first.")
    
    # Auto-login if needed
    _ensure_logged_in(online_app)
    
    candidates = [variable_name]
    if not variable_name.startswith("Application."):
        candidates.append("Application." + variable_name)
    last_error = None
    for candidate in candidates:
        try:
            val = _call_online_app(
                online_app,
                ('read_value', 'read_values'),
                candidate,
            )
            str_val = str(val)
            if "Invalid expression" in str_val or "invalid expression" in str_val.lower():
                raise RuntimeError(
                    "Invalid expression: '{0}' is not exported to the online application. "
                    "It may be a struct/array, not declared as a symbol, or not compiled into the PLC."
                    .format(candidate))
            return {"name": candidate, "value": str_val}
        except Exception as e:
            # Check if the exception itself is about invalid expression
            e_msg = str(e)
            if "Invalid expression" in e_msg or "invalid expression" in e_msg.lower():
                if "not exported" not in e_msg:
                    last_error = RuntimeError(
                        "Invalid expression: '{0}' is not exported to the online application. "
                        "It may be a struct/array, not declared as a symbol, or not compiled into the PLC."
                        .format(candidate))
                else:
                    last_error = e
            else:
                last_error = e
    raise last_error if last_error is not None else RuntimeError("Read failed")


def write_variable_impl(project, variable_name, value):
    """Write a value to a PLC variable via online connection.
    
    Auto-connects if online_app is cached but not logged in.
    """
    if not variable_name:
        raise ValueError("Variable name is required")
    if value is None:
        raise ValueError("Value is required")
    
    online_app, _ = ensure_online_connection(project)
    if online_app is None:
        raise RuntimeError("Not connected. Call connect_to_device first.")
    
    # Auto-login if needed
    _ensure_logged_in(online_app)
    
    value = normalize_write_value(value)
    candidates = [variable_name]
    if not variable_name.startswith("Application."):
        candidates.append("Application." + variable_name)
    last_error = None
    for candidate in candidates:
        try:
            _call_online_app(online_app, ('set_prepared_value',), candidate, value)
            _call_online_app(online_app, ('write_prepared_values',),)
            return {"name": candidate, "written": True, "value": str(value)}
        except Exception as e:
            last_error = e
    raise last_error if last_error is not None else RuntimeError("Write failed")


# Qualified enumerator as returned by read_value, e.g. "COLOR.green".
# Both sides must be identifiers (so a REAL like "13.0" is excluded: "13" is
# not an identifier).
_ENUM_QUALIFIED = re.compile(r"^[A-Za-z_]\w*\.[A-Za-z_]\w*$")


def normalize_write_value(value):
    """Make a snapshot value safe for set_prepared_value.

    Enums read back as a qualified enumerator 'TYPE.member' (no '#'), but
    set_prepared_value auto-prefixes the enum type for unprefixed values,
    producing the invalid literal 'TYPE#TYPE.member'. Rewrite 'TYPE.member' to
    the typed-literal form 'TYPE#member' (consistent with how 'INT#5' round-
    trips). Values that already contain '#' (INT#5, COLOR#green) and non-enum
    values (REAL '13.0', strings, bare members) are returned unchanged.
    """
    if value is None:
        return value
    s = str(value)
    stripped = s.strip()
    if "#" not in stripped and _ENUM_QUALIFIED.match(stripped):
        return stripped.replace(".", "#", 1)
    return s


def _mk_read_result(name, val):
    """Classify a raw read result string into a snapshot row."""
    low = val.lower()
    if "invalid expression" in low:
        return {"name": name, "value": "", "read_ok": False,
                "read_error": "Invalid expression (not readable online)"}
    return {"name": name, "value": val, "read_ok": True, "read_error": ""}


def read_variables_impl(project, names):
    """Batch-read a list of fully-qualified leaf expressions.

    Tries OnlineApplication.read_values() once; falls back to per-item
    read_value() if the batch call raises, so a single bad expression never
    aborts the whole snapshot. Each result carries read_ok / read_error.
    """
    names = [str(n) for n in (names or [])]
    if not names:
        return {"results": [], "count": 0}

    online_app, _ = ensure_online_connection(project)
    if online_app is None:
        raise RuntimeError("Not connected. Call connect_to_device first.")
    _ensure_logged_in(online_app)

    results = []
    values = None
    try:
        raw = _call_online_app(online_app, ('read_values',), list(names))
        values = [str(v) for v in raw]
    except Exception:
        values = None

    if values is not None and len(values) == len(names):
        for i in range(len(names)):
            results.append(_mk_read_result(names[i], values[i]))
    else:
        for nm in names:
            try:
                val = _call_online_app(online_app, ('read_value',), nm)
                results.append(_mk_read_result(nm, str(val)))
            except Exception as e:
                results.append({"name": nm, "value": "", "read_ok": False,
                                "read_error": str(e)[:200]})
    return {"results": results, "count": len(results)}


def write_variables_impl(project, items):
    """Batch-write a list of {name, value} pairs.

    Prepares each value with set_prepared_value (per-item failures recorded),
    then commits once with write_prepared_values. A single bad value never
    aborts the whole restore.
    """
    items = items or []
    if not items:
        return {"results": [], "written": 0}

    online_app, _ = ensure_online_connection(project)
    if online_app is None:
        raise RuntimeError("Not connected. Call connect_to_device first.")
    _ensure_logged_in(online_app)

    results = []
    prepared = 0
    for it in items:
        nm = it.get("name")
        val = normalize_write_value(it.get("value"))
        try:
            _call_online_app(online_app, ('set_prepared_value',),
                             nm, str(val))
            results.append({"name": nm, "prepared": True, "write_error": ""})
            prepared += 1
        except Exception as e:
            results.append({"name": nm, "prepared": False,
                            "write_error": str(e)[:200]})

    write_ok = True
    write_err = ""
    if prepared > 0:
        try:
            _call_online_app(online_app, ('write_prepared_values',))
        except Exception as e:
            write_ok = False
            write_err = str(e)[:200]

    for r in results:
        if r["prepared"]:
            r["written"] = write_ok
            if not write_ok and not r["write_error"]:
                r["write_error"] = write_err
        else:
            r["written"] = False
    return {"results": results, "written": (prepared if write_ok else 0)}


def set_simulation_mode_impl(project, enable=True):
    """Enable or disable PLC simulation mode.
    
    Searches for Device object with set_simulation_mode capability.
    Falls back to project.find('Device', True) if needed.
    
    Args:
        project: CODESYS project object
        enable: True to enable, False to disable
    
    Returns:
        dict with simulation state
    """
    enable = bool(enable)
    
    # Find device with set_simulation_mode
    candidates = []
    for child in project.get_children(True):
        if hasattr(child, 'set_simulation_mode'):
            name = getattr(child, 'get_name', lambda: '?')()
            is_sim = None
            if hasattr(child, 'is_simulation_mode'):
                try:
                    is_sim = child.is_simulation_mode
                except Exception:
                    pass
            candidates.append({'obj': child, 'name': name, 'before': is_sim})
    
    # Prefer object literally named "Device"
    target = None
    for c in candidates:
        if c['name'] == 'Device':
            target = c
            break
    if target is None and candidates:
        target = candidates[0]
    if target is None:
        # Last-ditch: try project.find
        try:
            found = project.find('Device', True)
            for f in found:
                if hasattr(f, 'set_simulation_mode'):
                    target = {
                        'obj': f,
                        'name': getattr(f, 'get_name', lambda: '?')(),
                        'before': None
                    }
                    break
        except Exception:
            pass
    
    if target is None:
        raise RuntimeError(
            "No object with set_simulation_mode found. "
            "Project has no Device descriptor or none exposes simulation_mode."
        )
    
    device = target['obj']
    before = target['before']
    
    device.set_simulation_mode(enable)
    
    # Save so simulation state persists
    try:
        project.save()
    except Exception:
        pass
    
    # Read back
    after = None
    if hasattr(device, 'is_simulation_mode'):
        try:
            after = device.is_simulation_mode
        except Exception:
            pass
    
    return {
        "device": target['name'],
        "simulation": enable,
        "before": str(before) if before is not None else "unknown",
        "after": str(after) if after is not None else "set (readback not available)",
    }


def set_credentials_impl(username, password=""):
    """Set PLC login credentials via CODESYS DeviceUserManagement.
    
    Args:
        username: Username for PLC authentication
        password: Password (optional, empty string = no password)
    
    Returns:
        dict with confirmation
    """
    if not username:
        raise ValueError("Username is required")
    
    import scriptengine as se
    se.system.commands['DeviceUserManagement'].execute(
        'SetCredentials', username, password
    )
    return {"username": username, "credentials_set": True}


def get_application_state_impl(project):
    """Get the application state (connected, running, stopped, etc.).
    
    Returns information about the online application state without
    establishing a new connection.
    
    Args:
        project: CODESYS project object
    
    Returns:
        dict with application state info
    """
    import scriptengine as se
    try:
        online_app = None
        target_app = None
        
        # Try device-based approach first
        try:
            device = _find_main_device(project)
            if device is not None:
                online_dev = se.online.create_online_device(device)
                if online_dev is not None:
                    if hasattr(online_dev, 'application'):
                        online_app = online_dev.application
                    if online_app is None:
                        for child in device.get_children(True):
                            if hasattr(child, 'is_application'):
                                try:
                                    if child.is_application:
                                        target_app = child
                                        online_app = se.online.create_online_application(child)
                                        break
                                except Exception:
                                    pass
        except Exception:
            pass
        
        # Fallback: direct application
        if online_app is None:
            if target_app is None:
                target_app = get_active_application(project)
            if target_app is None:
                return {"state": "unknown", "note": "No active application"}
            
            online_app = se.online.create_online_application(target_app)
            if online_app is None:
                return {"state": "disconnected"}
        
        if target_app is None:
            target_app = device if device else project
        
        info = {
            "application": getattr(target_app, 'get_name', lambda: "Unknown")(),
        }
        
        for attr in [
            'application_state', 'is_connected', 'is_running',
            'is_online', 'login_state', 'connection_state'
        ]:
            if hasattr(online_app, attr):
                try:
                    val = getattr(online_app, attr)
                    if callable(val):
                        info[attr] = str(val())
                    else:
                        info[attr] = str(val)
                except Exception:
                    pass
        
        return info
    except Exception as e:
        return {"state": "error", "error": str(e)}
