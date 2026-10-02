# -*- coding: utf-8 -*-
"""wire.py — the one description of the CLI <-> CODESYS reverse-pipe format.

Both ends of the reverse pipe used to carry their own copy of the same rules:
the framing header (a 4-byte little-endian length in front of a UTF-8 JSON
body), the size cap, the hello exchange that opens a protocol-v2 session, and
the response envelope (``ok`` / ``data`` / ``error``).  Two implementations of
one format drift: a change on one side is a silent incompatibility on the
other, and the ``ok`` field in particular was read on one side and assumed on
the other.  This module is the single source for all of it.

IronPython 2.7 compatible: no annotations, no f-strings, no dataclasses,
no pathlib.  Both CPython 3 and IronPython import it directly.

The wire format is unchanged by this module's existence: a frame is still
``struct.pack("<I", len(body)) + body`` with ``body = json.dumps(...).encode("utf-8")``,
and the protocol version stays 2.
"""

from __future__ import print_function

import json
import struct

# ── Protocol ───────────────────────────────────────────────────────────────

#: Wire protocol version. Sent in the hello and compared by the client before
#: a command is sent; a daemon that answers with anything else is refused.
PROTOCOL = 2

#: Largest single message either direction will frame. Raised to 32 MiB for
#: large application_tree / sync_export_text payloads on big projects.
MAX_MESSAGE_SIZE = 32 * 1024 * 1024

HEADER_FORMAT = "<I"
HEADER_SIZE = 4

#: Keys of the handshake and of a command/response envelope.
HELLO_METHOD = "ping"
HELLO_PARAM = "hello"
REQUEST_ID_KEY = "request_id"


class WireError(Exception):
    """A frame that cannot be decoded: short header, oversize, truncated body."""


# ── Framing ────────────────────────────────────────────────────────────────


def encode_body(data):
    """A JSON-serialisable value as UTF-8 bytes, with no header.

    Separate from :func:`encode_message` for the .NET pipe paths, which write
    the four header bytes and the body through different stream primitives and
    so cannot use a single assembled buffer.
    """
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def encode_header(length):
    """The 4-byte little-endian header for a body of *length* bytes."""
    return struct.pack(HEADER_FORMAT, length)


def encode_message(data):
    """A JSON-serialisable value as one framed message: header + body."""
    body = encode_body(data)
    return encode_header(len(body)) + body


def parse_header(raw):
    """The message length from four header bytes.

    Returns ``0`` for an empty frame (the protocol's "nothing to say" message).
    Raises :class:`WireError` for a short header or a length past the cap, so
    both ends reject the same frames for the same reason.
    """
    raw = bytes(raw)
    if len(raw) < HEADER_SIZE:
        raise WireError("short header: {0} byte(s)".format(len(raw)))
    msg_len = struct.unpack(HEADER_FORMAT, raw[:HEADER_SIZE])[0]
    if msg_len == 0:
        return 0
    if msg_len > MAX_MESSAGE_SIZE:
        raise WireError("message too large: {0} bytes".format(msg_len))
    return msg_len


def decode_body(body):
    """UTF-8 JSON bytes as the value they encode."""
    return json.loads(bytes(body).decode("utf-8"))


def decode_message(frame):
    """One framed message as its value; ``{}`` for an empty frame."""
    msg_len = parse_header(frame)
    if msg_len == 0:
        return {}
    frame = bytes(frame)
    if len(frame) < HEADER_SIZE + msg_len:
        raise WireError(
            "truncated message: header says {0} byte(s), {1} present".format(
                msg_len, len(frame) - HEADER_SIZE
            )
        )
    return decode_body(frame[HEADER_SIZE : HEADER_SIZE + msg_len])


# ── Handshake ──────────────────────────────────────────────────────────────


def hello_request():
    """The client's opening probe: a ping carrying the protocol it speaks."""
    return {"method": HELLO_METHOD, "params": {HELLO_PARAM: PROTOCOL}}


def is_hello_message(message):
    """True when *message* is the client's hello probe rather than a command."""
    if not isinstance(message, dict):
        return False
    params = message.get("params")
    return isinstance(params, dict) and HELLO_PARAM in params


def build_hello(instance_id, pid, version, poll_ms, project):
    """The daemon's H2 payload: who it is and what project it holds open."""
    return {
        "protocol": PROTOCOL,
        "id": instance_id,
        "pid": pid,
        "version": version,
        "poll_ms": poll_ms,
        "project": project,
    }


def hello_reply(hello):
    """Wrap a :func:`build_hello` payload in the response envelope."""
    return {"ok": True, "hello": hello}


def parse_hello(data):
    """A hello envelope *or* a bare hello payload as a plain field dict.

    Accepts both shapes on purpose: the H2 reply nests the payload under
    ``hello``, while older daemons put the fields at the top level.  Field
    defaults match what the client used before this module existed, so an
    older daemon is still read the same way.
    """
    if isinstance(data, dict) and isinstance(data.get("hello"), dict):
        data = data["hello"]
    if not isinstance(data, dict):
        data = {}
    pid = int(data.get("pid", 0) or 0)
    return {
        "protocol": int(data.get("protocol", PROTOCOL) or PROTOCOL),
        "id": data.get("id") or "ide-{0}".format(pid),
        "pid": pid,
        "version": str(data.get("version", "") or ""),
        "poll_ms": int(data.get("poll_ms", 200) or 200),
        "project": data.get("project"),
    }


# ── Envelope ───────────────────────────────────────────────────────────────


def ok_response(data=None, **extra):
    """A success envelope. Extra keys (``instance``, ``request_id``) merge in."""
    response = {"ok": True}
    if data is not None:
        response["data"] = data
    response.update(extra)
    return response


def error_response(error, code=None, **extra):
    """A failure envelope carrying the reason the daemon refused.

    Key order is ``ok``, ``code``, ``error`` when a code is given and
    ``ok``, ``error`` otherwise -- the order the daemon already emitted, so a
    byte-for-byte comparison of old and new frames still matches.
    """
    response = {"ok": False}
    if code is not None:
        response["code"] = code
    response["error"] = str(error)
    response.update(extra)
    return response


def response_ok(response):
    """Whether *response* is an envelope that reports success.

    The client's single definition of success: a response that is not a dict,
    or that is a dict without ``ok`` true, is a failure -- never a silent
    success by assumption.
    """
    return isinstance(response, dict) and bool(response.get("ok"))


def response_error(response, default="unknown error"):
    """The reason a response failed, for a message the user will read."""
    if not isinstance(response, dict):
        return default
    error = response.get("error")
    if error is None or error == "":
        return default
    return str(error)


# ── Request ids ────────────────────────────────────────────────────────────


def new_request_id(pid, counter, stamp=None):
    """A request id that is unique per client process and command.

    Deliberately plain text with no structure to parse: its only job is to
    appear in the daemon log next to the same value the CLI printed, so a
    timed-out command can be matched to what the daemon actually did.  The
    protocol treats it as optional, so an older daemon simply ignores it.
    """
    if stamp is None:
        stamp = ""
    return "{0}-{1}{2}".format(pid, counter, ("-" + str(stamp)) if stamp else "")
