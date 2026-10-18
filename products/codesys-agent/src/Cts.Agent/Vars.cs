// `vars.read` / `vars.write`: read and write PLC variables natively.
//
// The chain is the one a live probe established, and every step here is reflection-only, like the rest of this DLL:
//
//   engine.Projects.PrimaryProject.ActiveApplication            -> Guid
//   ILanguageModelManager.GetVarReference(guid, "GVL.n")        -> IVarRef
//   IOnlineManager.CreateWatch(varRef)                          -> IOnlineVarRef
//   IOnlineVarRef.Value / .State                                -> value, state
//   IOnlineVarRef.PreparedValue = <v>; IOnlineApplication.WriteVariables([watch])
//
// Everything runs on the UI thread through Ide.OnUi with a start deadline
// (StartTimeout): if the UI thread does not start the work in time the call
// answers `busy` and never runs late.
//
// Watches are cached (VarCache) so a repeated read of one expression costs a
// single hop; the cache is emptied on any online event and on a project change
// (AgentHost wires that), because the IDE warns that a watch built before a
// download answers "Invalid expression" afterwards.
using System;
using System.Collections.Generic;
using System.Globalization;

namespace Cts.Agent
{
    internal sealed partial class VarsService
    {
        //: A watch for one expression: what `vars.read`/`vars.write` cache.
        sealed class Watch
        {
            public object VarRef;
            public object OnlineVarRef;
            // The CLR type the last successful read returned, when there was one.
            // It is what a write converts its JSON value to, so the IDE receives
            // exactly the type it reports; null until a read has been seen.
            public Type ValueType;
            // The IEC type name of the expression ("WORD", "INT", "STRING(40)"),
            // reported with each read.  Null when the IDE gave none.
            public string IecType;
            // The expression type's TypeClass (a boxed vendor enum): what the
            // IDE's literal converters need to spell a read and parse a write.
            // Neither the CLR type nor the value tells WORD from UINT; this does.
            public object TypeClass;
        }

        readonly Ide _ide;
        readonly VarCache _cache;
        readonly VarWatchPolicy _policy;
        readonly FileLog _log;
        readonly IecLiterals _literals;
        Type _languageModelManagerType;
        object _languageModelManager;

        public VarsService(Ide ide, VarCache cache, FileLog log)
        {
            _ide = ide;
            _cache = cache;
            _policy = new VarWatchPolicy(cache);
            _log = log;
            _literals = new IecLiterals(LanguageModelManager);
        }

        public void Register(Router router)
        {
            router.Register(Vars.Read, Read);
            router.Register(Vars.Write, Write);
        }

        // Called by AgentHost on each online event; the policy decides which of
        // them make the cached watches untrustworthy.
        public void OnOnlineEvent(string name)
        {
            _policy.OnOnlineEvent(name);
        }

        // ---- methods

        Dictionary<string, object> Read(Request req, Session session)
        {
            var names = Vars.Names(req);
            var app = Vars.Application(req);
            var startMs = StartTimeout.Parse(req);
            var envelope = _ide.OnUi("vars.read", startMs, () => ReadOnUi(app, names));
            // Wait off the UI thread, so the IDE delivers the first monitoring
            // value between attempts and nothing else runs nested inside a read.
            var timer = System.Diagnostics.Stopwatch.StartNew();
            while (VarReadPolicy.ShouldRetry(envelope) && timer.ElapsedMilliseconds < VarReadPolicy.RetryForMs)
            {
                System.Threading.Thread.Sleep(VarReadPolicy.RetryPauseMs);
                envelope = _ide.OnUi("vars.read", startMs, () => ReadOnUi(app, names));
            }
            return envelope;
        }

        Dictionary<string, object> Write(Request req, Session session)
        {
            var values = Vars.Values(req);
            var app = Vars.Application(req);
            var startMs = StartTimeout.Parse(req);
            return _ide.OnUi("vars.write", startMs, () => WriteOnUi(app, values));
        }

        // ---- on the UI thread

        Dictionary<string, object> ReadOnUi(string appSpec, List<string> names)
        {
            var results = new List<object>();
            Guid guid;
            var application = ResolveApplication(appSpec, out guid);
            _policy.OnApplication(guid.ToString());
            var online = application != null;
            var loggedIn = online && IsLoggedIn(application);

            foreach (var name in names)
            {
                if (application == null)
                {
                    results.Add(Vars.FailedResult(name, Vars.Codes.UnknownApplication,
                        "no online application: " + (appSpec ?? "the project has no ActiveApplication"),
                        null));
                    continue;
                }
                results.Add(ReadOne(guid, name));
            }
            return Vars.ReadEnvelope(online, loggedIn, guid == Guid.Empty ? null : guid.ToString(), results);
        }

        // Every value is prepared first and all go to the PLC in one
        // WriteVariables call, so it takes them in the same cycle (the IDE's
        // "Write values"); one that cannot be prepared writes none.
        Dictionary<string, object> WriteOnUi(string appSpec, List<KeyValuePair<string, object>> values)
        {
            _ide.RequireKey(DenyRules.WriteVariable);
            var results = new object[values.Count];
            Guid guid;
            var application = ResolveApplication(appSpec, out guid);
            _policy.OnApplication(guid.ToString());
            var online = application != null;
            var loggedIn = online && IsLoggedIn(application);
            var envelope = new Func<Dictionary<string, object>>(() =>
                Vars.WriteEnvelope(online, loggedIn, guid == Guid.Empty ? null : guid.ToString(), new List<object>(results)));

            if (application == null)
            {
                for (var i = 0; i < values.Count; i++)
                    results[i] = Vars.FailedResult(values[i].Key, Vars.Codes.UnknownApplication,
                        "no online application: " + (appSpec ?? "the project has no ActiveApplication"), null);
                return envelope();
            }
            var watches = new Watch[values.Count];
            var prepared = new object[values.Count];
            var refused = new List<string>();
            for (var i = 0; i < values.Count; i++)
            {
                results[i] = Prepare(guid, values[i].Key, values[i].Value, out watches[i], out prepared[i]);
                if (results[i] != null) refused.Add(values[i].Key);
            }
            if (refused.Count > 0)
            {
                for (var i = 0; i < values.Count; i++)
                    if (results[i] == null)
                        results[i] = Vars.FailedResult(values[i].Key, Vars.Codes.NotWritten,
                            "not written: " + string.Join(", ", refused) + " could not be written with it", null);
                return envelope();
            }
            try { WriteVariables(application, watches); }
            catch (Exception e)
            {
                for (var i = 0; i < values.Count; i++)
                    results[i] = Vars.FailedResult(values[i].Key, Vars.Codes.WriteFailed,
                        values.Count == 1 ? NotAValue(values[i].Key, values[i].Value, watches[i], e)
                            : "the IDE refused the values written together: " + Message(e), null);
                return envelope();
            }
            // No implicit read-back: the caller decides whether to read, and
            // `text` is what a read should then show ("hello" -> "'hello'").
            for (var i = 0; i < values.Count; i++)
                results[i] = Vars.WrittenResult(values[i].Key, values[i].Value, LiteralText(watches[i], prepared[i]));
            return envelope();
        }

        object ReadOne(Guid guid, string name)
        {
            Watch watch;
            string state;
            try
            {
                watch = GetWatch(guid, name);
                state = Vars.StateText(Get(watch.OnlineVarRef, "State"));
            }
            catch (Exception e)
            {
                return Vars.FailedResult(name, Classify(e, Vars.Codes.ReadFailed), Message(e), null);
            }

            object value;
            try
            {
                value = Get(watch.OnlineVarRef, "Value");
            }
            catch (Exception e)
            {
                // Offline the watch exists but has no value: State is still the
                // honest answer, and the message names the reason.
                return Vars.FailedResult(name, Classify(e, Vars.Codes.ReadFailed), Message(e), state);
            }

            if (value != null) watch.ValueType = value.GetType();
            string typeName;
            bool isScalar;
            var json = VarValue.ToJson(value, out typeName, out isScalar);
            if (!isScalar)
                return Vars.FailedResult(name, Vars.Codes.NotScalar,
                    name + " is " + (watch.IecType ?? typeName ?? "not a single value")
                    + ": read its members or elements one by one", state);
            return Vars.ReadResult(name, json, typeName, state, watch.IecType, LiteralText(watch, value));
        }

        // The value as the IDE spells it ("WORD#5", "TRUE", "'text'"), or null
        // when its converter cannot: an enum value already is its own text
        // ("E_Mode.Run"), so a string the converter refuses is shown as it is.
        string LiteralText(Watch watch, object value)
        {
            if (watch.TypeClass != null)
            {
                try { return _literals.Text(value, watch.TypeClass); }
                catch (Exception e) { _log.Write("vars: no literal for " + watch.IecType + ": " + e.Message); }
            }
            return value as string;
        }

        // What a written string becomes before the IDE gets it.  The CLI sends the
        // user's text; the IDE's own literal parser reads it for the expression's
        // type ("16#FF", "T#2s", "REAL#1.5", "'text'").  A STRING also takes bare
        // text as its content, and anything the parser refuses goes to the IDE
        // unchanged, for it to accept or refuse: an enum member ("E_Mode.Run",
        // "Run"), also in the typed form ST code uses ("E_Mode#Run").
        object Prepared(Watch watch, string text)
        {
            if (watch.TypeClass == null) return text;
            var isString = IsStringClass(watch.TypeClass);
            try
            {
                var value = _literals.Value(text.Trim(), watch.TypeClass);
                if (!isString || value is string) return value;
            }
            catch (Exception e)
            {
                if (!isString) _log.Write("vars: not a literal for " + watch.IecType + ": " + e.Message);
            }
            if (isString) return text;
            var trimmed = text.Trim();
            var hash = trimmed.IndexOf('#');
            if (hash > 0 && string.Equals(trimmed.Substring(0, hash), watch.IecType, StringComparison.OrdinalIgnoreCase))
                return trimmed.Substring(0, hash) + "." + trimmed.Substring(hash + 1);
            return trimmed;
        }

        static bool IsStringClass(object typeClass)
        {
            var name = Convert.ToString(typeClass, CultureInfo.InvariantCulture);
            return name == "String" || name == "WString";
        }

        // The watch with its PreparedValue set, or the failed result that says
        // why the value cannot be written (null when it can).
        object Prepare(Guid guid, string name, object json, out Watch watch, out object prepared)
        {
            watch = null;
            prepared = null;
            if (!VarValue.IsWritableShape(json))
                return Vars.FailedResult(name, Vars.Codes.BadParams,
                    "value must be a bool, a number or a string, not " + Shape(json), null);
            try
            {
                watch = GetWatch(guid, name);
            }
            catch (Exception e)
            {
                return Vars.FailedResult(name, Classify(e, Vars.Codes.WriteFailed), Message(e), null);
            }
            try
            {
                var text = json as string;
                prepared = text != null ? Prepared(watch, text) : VarValue.FromJson(json, watch.ValueType, name);
            }
            catch (ProtocolException e)
            {
                return Vars.FailedResult(name, e.Code, e.Message, null);
            }
            try { Set(watch.OnlineVarRef, "PreparedValue", prepared); }
            catch (Exception e)
            {
                return Vars.FailedResult(name, Vars.Codes.WriteFailed, NotAValue(name, json, watch, e), null);
            }
            return null;
        }

        static string NotAValue(string name, object json, Watch watch, Exception e)
        {
            return json is string
                ? Quote((string)json) + " is not a value for " + name + " (" + (watch.IecType ?? "its type") + "): " + Message(e)
                : Message(e);
        }

        // ---- reflection helpers

        static object Get(object target, string property)
        {
            var info = DevReflection.ResolveProperty(target.GetType(), false, property);
            try { return info.GetValue(target, null); }
            catch (Exception e) { throw Unwrap(e, property); }
        }

        static void Set(object target, string property, object value)
        {
            var info = DevReflection.ResolveProperty(target.GetType(), false, property);
            if (info.GetSetMethod() == null)
                throw new ProtocolException(ErrorCodes.Unavailable, property + " has no setter");
            try { info.SetValue(target, value, null); }
            catch (Exception e) { throw Unwrap(e, property + " = ..."); }
        }

        static Exception Unwrap(Exception e, string what)
        {
            var cause = Invocation.Cause(e);
            var protocol = cause as ProtocolException;
            if (protocol != null) return protocol;
            return new IdeCallException(what + ": " + cause.GetType().Name + ": " + cause.Message);
        }

        static string Message(Exception e)
        {
            var ide = e as IdeCallException;
            if (ide != null) return ide.Message;
            return e.Message;
        }

        // Classify a failure into one of the per-name codes by what the IDE said,
        // so the client can tell "not logged in" from "not exported" without
        // matching on our message text.
        static string Classify(Exception e, string fallback)
        {
            var text = Message(e) ?? "";
            if (text.IndexOf("Not logged in", StringComparison.OrdinalIgnoreCase) >= 0
                || text.IndexOf("NoMonitoringValue", StringComparison.OrdinalIgnoreCase) >= 0)
                return Vars.Codes.NotLoggedIn;
            if (text.IndexOf("Invalid expression", StringComparison.OrdinalIgnoreCase) >= 0
                || text.IndexOf("not exported", StringComparison.OrdinalIgnoreCase) >= 0)
                return Vars.Codes.NotExported;
            return fallback;
        }

        static string Quote(string text)
        {
            return "'" + text + "'";
        }

        static string Shape(object json)
        {
            if (json == null) return "null";
            if (json is System.Collections.IDictionary) return "an object";
            if (json is System.Collections.IList) return "an array";
            return json.GetType().Name;
        }
    }

    // A call that failed inside the IDE: the message already carries the
    // member and the vendor exception, so the caller shows it as-is.
    internal sealed class IdeCallException : Exception
    {
        public IdeCallException(string message) : base(message) { }
    }
}
