using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;

namespace Cts.Agent
{
    public delegate object Handler(Request request, Session session);

    // Maps method names to handlers and turns any line into exactly one reply line.
    // Handle never throws: a malformed line, an unknown method and a handler fault
    // each become an error reply.
    public sealed class Router
    {
        readonly Dictionary<string, Handler> _handlers = new Dictionary<string, Handler>(StringComparer.Ordinal);
        readonly Dictionary<object, KeyValuePair<string, Stopwatch>> _running = new Dictionary<object, KeyValuePair<string, Stopwatch>>();

        // Called with a handler fault that was turned into an `internal` reply.
        public Action<string, Exception> OnHandlerFault { get; set; }

        // Called with one activity line per answered, non-skipped request.
        public Action<string> OnActivity { get; set; }

        // Optional pre-dispatch gate, consulted before the handler runs for a
        // method that exists: return an error to answer with instead of running
        // it, or null to proceed.  The agent uses it to refuse UI-thread work
        // while a modal dialog is open.
        public Func<Request, ProtocolException> Gate { get; set; }

        // Optional: the agent's modal snapshot. A dialog that opened while a
        // handler ran is named in its result as dialogs_seen: one the IDE
        // showed and closed again on its own leaves no other trace.
        public ModalState Modal { get; set; }

        public void Register(string method, Handler handler)
        {
            if (string.IsNullOrEmpty(method)) throw new ArgumentException("method is required", "method");
            if (handler == null) throw new ArgumentNullException("handler");
            if (_handlers.ContainsKey(method)) throw new InvalidOperationException("method already registered: " + method);
            _handlers.Add(method, handler);
        }

        public IEnumerable<string> Methods
        {
            get
            {
                var names = new List<string>(_handlers.Keys);
                names.Sort(StringComparer.Ordinal);
                return names;
            }
        }

        public string Handle(string line, Session session)
        {
            if (line.Length > Protocol.MaxLineLength)
                return Replies.Fail(null, ErrorCodes.BadRequest, "line longer than " + Protocol.MaxLineLength + " characters");

            Request request;
            try { request = Request.Parse(line); }
            catch (ProtocolException e)
            {
                return Replies.Fail(Request.TryReadId(line), e.Code, e.Message);
            }

            bool ok = false;
            string code = null;
            var token = new object();
            var clock = Stopwatch.StartNew();
            lock (_running) _running[token] = new KeyValuePair<string, Stopwatch>(request.Method, clock);
            try
            {
                return Dispatch(request, session, ref ok, ref code);
            }
            finally
            {
                lock (_running) _running.Remove(token);
                ReportActivity(request, ok, code, clock.ElapsedMilliseconds);
            }
        }

        // One method called from inside the agent (test.run's steps, the FSM
        // window's live read): the same modal gate and activity line as a
        // request on the pipe, and a refusal comes back as the
        // ProtocolException it was.
        public IDictionary<string, object> Call(string method, Dictionary<string, object> parameters, Session session)
        {
            var request = new Dictionary<string, object> { { "id", method }, { "method", method }, { "params", parameters } };
            var reply = Json.Parse(Handle(Json.Serialize(request), session)) as IDictionary<string, object>;
            object value;
            if (reply != null && reply.TryGetValue("ok", out value) && Equals(value, true))
                return reply.TryGetValue("result", out value) && value is IDictionary<string, object> ? (IDictionary<string, object>)value : new Dictionary<string, object>();
            var error = reply != null && reply.TryGetValue("error", out value) ? value as IDictionary<string, object> : null;
            object code = null, message = null;
            error?.TryGetValue("code", out code);
            error?.TryGetValue("message", out message);
            throw new ProtocolException(code as string ?? ErrorCodes.Internal, message as string ?? method + " gave no answer");
        }

        // The requests being answered now, each with how long it has run, longest first.
        public List<KeyValuePair<string, long>> Running()
        {
            lock (_running)
                return _running.Values.Select(run => new KeyValuePair<string, long>(run.Key, run.Value.ElapsedMilliseconds))
                    .OrderByDescending(run => run.Value).ToList();
        }

        string Dispatch(Request request, Session session, ref bool ok, ref string code)
        {
            Handler handler;
            if (!_handlers.TryGetValue(request.Method, out handler))
                return Replies.Fail(request.Id, code = ErrorCodes.UnknownMethod, "unknown method '" + request.Method + "'");

            try
            {
                var gate = Gate;
                if (gate != null)
                {
                    var blocked = gate(request);
                    if (blocked != null)
                        return Replies.Fail(request.Id, code = blocked.Code, blocked.Message, blocked.Details);
                }
                var epoch = Modal != null ? Modal.Epoch : 0L;
                var value = handler(request, session);
                var seen = Modal != null && !request.Method.StartsWith("dialog.", StringComparison.Ordinal) ? Modal.OpenedSince(epoch) : new ModalWindow[0];
                if (seen.Length > 0 && value is IDictionary<string, object> answer)
                    value = new Dictionary<string, object>(answer) { ["dialogs_seen"] = seen.Select(window => (object)window.ToData()).ToList() };
                var result = Replies.Ok(request.Id, value);
                ok = true;
                return result;
            }
            catch (ProtocolException e)
            {
                return Replies.Fail(request.Id, code = e.Code, e.Message, e.Details);
            }
            catch (JsonException e)
            {
                // A handler returned something the protocol cannot carry.
                Report(request.Method, e);
                return Replies.Fail(request.Id, code = ErrorCodes.Internal, "result cannot be serialized: " + e.Message);
            }
            catch (Exception e)
            {
                Report(request.Method, e);
                return Replies.Fail(request.Id, code = ErrorCodes.Internal, request.Method + ": " + e.Message);
            }
        }

        // One line per answered request, for the agent log.  A fault
        // in the sink must not affect the reply.
        void ReportActivity(Request request, bool ok, string code, long elapsedMs)
        {
            var report = OnActivity;
            if (report == null || !ActivityLog.IsReported(request.Method, elapsedMs)) return;
            try { report(ActivityLog.Format(request.Method, request.Params, ok, code, elapsedMs)); }
            catch { }
        }

        void Report(string method, Exception e)
        {
            var report = OnHandlerFault;
            if (report == null) return;
            try { report(method, e); } catch { }
        }
    }
}
