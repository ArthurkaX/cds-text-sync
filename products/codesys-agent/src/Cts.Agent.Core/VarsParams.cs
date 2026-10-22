// Request parsing and result shaping for `vars.read` / `vars.write`, kept out
// of the IDE-facing file so both are tested without a CODESYS process.
//
//   vars.read  {"names": ["GVL.n", ...], "app"?: "<name|guid>", "start_timeout_ms"?}
//   vars.write {"values": {"GVL.n": 1234, ...}, "app"?: "<name|guid>", "start_timeout_ms"?}
//
// A read answers
//
//   {"online": true, "logged_in": true, "application": "<guid>",
//    "application_state": "run", "operating_state": "program_loaded",
//    "results": [{"name","ok":true,"value":<json>,"type":"System.UInt32","state":"Good"}]}
//
// and a name that failed carries `ok:false`, the `state` it was in and an
// `error` object instead of `value`.  One bad name never fails the whole call.
//
// A write answers `{"application", "logged_in", "results":[...], "written": n}`
// with one result per name: `{"name","ok":true,"written":true,"value":<as sent>,"text"?}`
// or `{"name","ok":false,"error":{...}}`.  Reading back is deliberately not part
// of a write; the caller decides whether to read.
using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    public static class Vars
    {
        public const string Read = "vars.read";
        public const string Write = "vars.write";

        // Per-name failure codes.  These live inside a successful result, so they
        // are not the wire's error codes; they say *why that name* failed.
        public static class Codes
        {
            public const string BadParams = "bad_params";
            public const string NotLoggedIn = "not_logged_in";
            public const string NotExported = "not_exported";
            public const string ReadFailed = "read_failed";
            public const string WriteFailed = "write_failed";
            // A value written together with one that could not be: not sent.
            public const string NotWritten = "not_written";
            public const string UnknownApplication = "unknown_application";
            public const string NotScalar = "not_scalar";
        }

        // ---- request

        // The `names` array: every entry a non-empty string.  Duplicates are kept
        // (the caller gets one result per requested name, in order).
        public static List<string> Names(Request req)
        {
            object raw;
            req.Params.TryGetValue("names", out raw);
            var list = raw as IList<object>;
            if (list == null)
                throw new ProtocolException(ErrorCodes.BadParams, "parameter 'names' must be an array of strings");
            if (list.Count == 0)
                throw new ProtocolException(ErrorCodes.BadParams, "parameter 'names' is empty");
            var names = new List<string>(list.Count);
            foreach (var item in list)
            {
                var name = item as string;
                if (string.IsNullOrEmpty(name))
                    throw new ProtocolException(ErrorCodes.BadParams, "parameter 'names' must contain only non-empty strings");
                names.Add(name);
            }
            return names;
        }

        // The `values` object as (name, json value) pairs, in the order the client
        // wrote them.
        public static List<KeyValuePair<string, object>> Values(Request req)
        {
            object raw;
            req.Params.TryGetValue("values", out raw);
            var map = raw as IDictionary<string, object>;
            if (map == null)
                throw new ProtocolException(ErrorCodes.BadParams, "parameter 'values' must be an object mapping names to values");
            if (map.Count == 0)
                throw new ProtocolException(ErrorCodes.BadParams, "parameter 'values' is empty");
            var pairs = new List<KeyValuePair<string, object>>(map.Count);
            foreach (var pair in map)
            {
                if (string.IsNullOrEmpty(pair.Key))
                    throw new ProtocolException(ErrorCodes.BadParams, "parameter 'values' has an empty name");
                pairs.Add(pair);
            }
            return pairs;
        }

        // Optional `app`: an application name or a GUID, resolved by the agent.
        // Absent means the project's ActiveApplication.
        public static string Application(Request req)
        {
            var app = req.String("app", "");
            return app.Length == 0 ? null : app;
        }

        // ---- result shaping

        // `iec` is the IEC type name ("WORD", "INT", "STRING(40)") or null when
        // the IDE did not give one.  `text` is the value as the IDE spells it
        // (``WORD#5``, ``REAL#1E-05``, ``'text'``, ``E_Mode.Run``), from its own
        // literal converter; null when the converter had no answer.
        public static Dictionary<string, object> ReadResult(string name, object value, string typeName, string state, string iec, string text = null)
        {
            var result = new Dictionary<string, object>
            {
                { "name", name },
                { "ok", true },
                { "value", value },
                { "type", typeName },
                { "iec", iec },
                { "state", state },
            };
            if (text != null) result["text"] = text;
            return result;
        }

        public static Dictionary<string, object> FailedResult(string name, string code, string message, string state)
        {
            return new Dictionary<string, object>
            {
                { "name", name },
                { "ok", false },
                { "state", state },
                { "error", new Dictionary<string, object> { { "code", code }, { "message", message } } },
            };
        }

        // `text` is the written value as the IDE spells it, what a read-back
        // shows when the write took effect; null when the converter had none.
        public static Dictionary<string, object> WrittenResult(string name, object value, string text)
        {
            var result = new Dictionary<string, object>
            {
                { "name", name },
                { "ok", true },
                { "written", true },
                { "value", value },
            };
            if (text != null) result["text"] = text;
            return result;
        }

        public static Dictionary<string, object> ReadEnvelope(bool online, bool loggedIn, string application, List<object> results)
        {
            return new Dictionary<string, object>
            {
                { "online", online },
                { "logged_in", loggedIn },
                { "application", application },
                { "results", results },
            };
        }

        public static Dictionary<string, object> WriteEnvelope(bool online, bool loggedIn, string application, List<object> results)
        {
            var envelope = ReadEnvelope(online, loggedIn, application, results);
            envelope["written"] = results.OfType<IDictionary<string, object>>().Count(m => m.TryGetValue("ok", out var ok) && Equals(ok, true));
            return envelope;
        }

        // The state enum the IDE reports, as text for the wire.
        public static string StateText(object state)
        {
            return state == null ? null : Convert.ToString(state);
        }
    }
}
