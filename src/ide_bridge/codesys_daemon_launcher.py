# -*- coding: utf-8 -*-
"""
codesys_daemon_launcher.py - Starts the reverse-pipe daemon loop.

Loaded by cds_bootstrap.launch() for the Project_daemon entry point.

The loop module is *executed*, not imported: it expects to run as __main__ with
the CODESYS-injected globals of the calling script, and it must keep the script
context alive for as long as the daemon runs. That is also why this does not go
through codesys_runtime.run_operation -- that path clears the loaded modules and
is built for short operations, whereas the daemon holds the context for hours.
"""
import os
import sys
import time

_BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))


def _host(caller_globals, name):
 if caller_globals and caller_globals.get(name) is not None:
  return caller_globals.get(name)
 return globals().get(name)


def _notify(caller_globals, msg, is_error=False):
 """Show a message to the user in CODESYS, falling back to stdout."""
 host = _host(caller_globals, "system")
 try:
  if is_error:
   host.ui.error(msg)
  else:
   host.ui.info(msg)
 except Exception:
  print(msg)


def _loop_path():
 candidates = [
  os.path.join(_BRIDGE_DIR, "ide_reverse_pipe_loop.py"),
  # Legacy flat layout: everything sat next to the root scripts.
  os.path.join(
   os.path.dirname(os.path.dirname(_BRIDGE_DIR)),
   "ide_reverse_pipe_loop.py",
  ),
 ]
 for path in candidates:
  if os.path.exists(path):
   return path
 return None


def run(params=None, caller_globals=None):
 loop_path = _loop_path()
 if not loop_path:
  _notify(
   caller_globals,
   "ide_reverse_pipe_loop.py not found next to:\n" + _BRIDGE_DIR,
   is_error=True,
  )
  return

 try:
  handle = open(loop_path, "r")
  try:
   code = handle.read()
  finally:
   handle.close()
 except Exception as error:
  _notify(caller_globals, "Cannot read the daemon loop:\n" + str(error), is_error=True)
  return

 # The loop reads system/projects out of its own globals, so hand it the
 # namespace CODESYS injected into the entry script.
 ns = dict(caller_globals) if caller_globals else {}
 for name in ("system", "projects"):
  if ns.get(name) is None:
   value = globals().get(name)
   if value is not None:
    ns[name] = value
 ns["__file__"] = loop_path
 ns["__name__"] = "__main__"

 try:
  exec(code, ns)
 except Exception as error:
  _notify(caller_globals, "Reverse pipe daemon error:\n" + str(error), is_error=True)
  return

 loop_info = getattr(sys, "_codesys_daemon_loop", None)
 if not loop_info or not loop_info.get("started"):
  _notify(caller_globals, "Reverse pipe daemon failed to start.", is_error=True)
  return

 # Keep the script context alive while the daemon runs. When the user clicks
 # Stop, running=False and this exits naturally.
 try:
  while sys._codesys_daemon_loop.get("running", False):
   time.sleep(0.5)
 except KeyboardInterrupt:
  pass
