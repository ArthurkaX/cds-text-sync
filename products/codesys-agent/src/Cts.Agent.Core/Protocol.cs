// Wire protocol: one UTF-8 JSON object per line, in both directions.
//
//   request  {"id": <string|number>, "method": "name", "params": {...}}
//   reply    {"id": <same>, "ok": true,  "result": ...}
//            {"id": <same>, "ok": false, "error": {"code": "...", "message": "..."}}
//   event    {"event": "name", "seq": N, "time": "<ISO-8601 UTC>", "data": ...}
//
// Events are pushed by the agent to connections that subscribed; they carry no id.
using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    public static class Protocol
    {
        // The major part changes when a client written for the old one would misbehave.
        public const string Version = "1.0";

        // Lines longer than this are answered with bad_request and not parsed.
        // A large project's screen is about 10 MB of XML, which objects.replace
        // carries in one request.
        public const int MaxLineLength = 16 * 1024 * 1024;
    }

    public static class ErrorCodes
    {
        public const string BadJson = "bad_json";
        public const string BadRequest = "bad_request";
        public const string UnknownMethod = "unknown_method";
        public const string BadParams = "bad_params";
        public const string Internal = "internal";
        public const string Busy = "busy";
        public const string Timeout = "timeout";
        public const string Unavailable = "unavailable";

        // A modal dialog is open on the IDE's UI thread and the call needs that
        // thread; the message names the dialog and error.data.dialogs carries
        // the full snapshot (see ModalErrors).
        public const string DialogBlocked = "dialog_blocked";

        // A dialog answer was refused because the dialog is not the one the
        // caller acted on -- it was replaced since it was read, or it did not
        // keep a choice that was applied to it.  Nothing was pressed, and
        // error.data.dialogs carries the dialog as it is now.
        public const string DialogChanged = "dialog_changed";
    }

    // A handler throws this to answer with a specific error code.
    public sealed class ProtocolException : Exception
    {
        public string Code { get; private set; }

        // Optional structured detail the client can act on (e.g. the dialogs
        // that blocked a call); null for codes that carry only a message.  It
        // becomes the reply's error.data.  (Not named Data: Exception already
        // has an IDictionary called Data.)
        public object Details { get; private set; }

        public ProtocolException(string code, string message) : this(code, message, null) { }

        public ProtocolException(string code, string message, object data) : base(message)
        {
            Code = code;
            Details = data;
        }
    }

    public sealed class Request
    {
        // The id exactly as the client sent it (string, number or null); echoed back.
        public object Id { get; private set; }
        public string Method { get; private set; }
        public IDictionary<string, object> Params { get; private set; }

        public Request(object id, string method, IDictionary<string, object> parameters)
        {
            Id = id;
            Method = method;
            Params = parameters ?? new Dictionary<string, object>();
        }

        // Parses one line. Throws ProtocolException(bad_json | bad_request); the
        // exception carries the id when it could be read, via TryReadId.
        public static Request Parse(string line)
        {
            object root;
            try { root = Json.Parse(line); }
            catch (JsonException e) { throw new ProtocolException(ErrorCodes.BadJson, e.Message); }

            var obj = root as IDictionary<string, object>;
            if (obj == null) throw new ProtocolException(ErrorCodes.BadRequest, "a request must be a JSON object");

            object id;
            obj.TryGetValue("id", out id);
            if (id != null && !(id is string) && !(id is long))
                throw new ProtocolException(ErrorCodes.BadRequest, "id must be a string or an integer");

            object m;
            var method = obj.TryGetValue("method", out m) ? m as string : null;
            if (string.IsNullOrEmpty(method))
                throw new ProtocolException(ErrorCodes.BadRequest, "method is required");

            object p;
            IDictionary<string, object> parameters = null;
            if (obj.TryGetValue("params", out p) && p != null)
            {
                parameters = p as IDictionary<string, object>;
                if (parameters == null) throw new ProtocolException(ErrorCodes.BadParams, "params must be an object");
            }
            return new Request(id, method, parameters);
        }

        // Best effort: the id of a line that failed Parse, so the error reply can carry it.
        public static object TryReadId(string line)
        {
            try
            {
                var obj = Json.Parse(line) as IDictionary<string, object>;
                object id;
                if (obj != null && obj.TryGetValue("id", out id) && (id is string || id is long)) return id;
            }
            catch (JsonException) { }
            return null;
        }

        // ---- typed parameter access; a missing or mistyped value is bad_params

        public string String(string name, string fallback = null)
        {
            object v;
            if (!Params.TryGetValue(name, out v) || v == null)
            {
                if (fallback != null) return fallback;
                throw new ProtocolException(ErrorCodes.BadParams, "missing parameter '" + name + "'");
            }
            var s = v as string;
            if (s == null) throw new ProtocolException(ErrorCodes.BadParams, "parameter '" + name + "' must be a string");
            return s;
        }

        // An array of non-empty strings, or null when the parameter is absent.
        public string[] Strings(string name)
        {
            object raw;
            if (!Params.TryGetValue(name, out raw) || raw == null) return null;
            var list = raw as IList<object>;
            if (list == null)
                throw new ProtocolException(ErrorCodes.BadParams, "parameter '" + name + "' must be an array of strings");
            var strings = new string[list.Count];
            for (var i = 0; i < list.Count; i++)
            {
                var text = list[i] as string;
                if (string.IsNullOrEmpty(text))
                    throw new ProtocolException(ErrorCodes.BadParams, "parameter '" + name + "' must contain only non-empty strings");
                strings[i] = text;
            }
            return strings;
        }

        public long Int(string name, long? fallback = null)
        {
            object v;
            if (!Params.TryGetValue(name, out v) || v == null)
            {
                if (fallback.HasValue) return fallback.Value;
                throw new ProtocolException(ErrorCodes.BadParams, "missing parameter '" + name + "'");
            }
            if (!(v is long)) throw new ProtocolException(ErrorCodes.BadParams, "parameter '" + name + "' must be an integer");
            return (long)v;
        }

        public bool Bool(string name, bool? fallback = null)
        {
            object v;
            if (!Params.TryGetValue(name, out v) || v == null)
            {
                if (fallback.HasValue) return fallback.Value;
                throw new ProtocolException(ErrorCodes.BadParams, "missing parameter '" + name + "'");
            }
            if (!(v is bool)) throw new ProtocolException(ErrorCodes.BadParams, "parameter '" + name + "' must be true or false");
            return (bool)v;
        }
    }

    public static class Replies
    {
        public static string Ok(object id, object result)
        {
            return Json.Serialize(new Dictionary<string, object>
            {
                { "id", id },
                { "ok", true },
                { "result", result },
            });
        }

        public static string Fail(object id, string code, string message)
        {
            return Fail(id, code, message, null);
        }

        // `data` is optional structured detail.  When it is present the error
        // gains a "data" member; a client written before it simply ignores the
        // extra key, so the envelope stays backward compatible.
        public static string Fail(object id, string code, string message, object data)
        {
            var error = new Dictionary<string, object>
            {
                { "code", code },
                { "message", message },
            };
            if (data != null) error["data"] = data;
            return Json.Serialize(new Dictionary<string, object>
            {
                { "id", id },
                { "ok", false },
                { "error", error },
            });
        }
    }
}
