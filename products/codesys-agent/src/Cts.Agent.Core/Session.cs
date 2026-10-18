using System;
using System.Collections.Generic;
using System.IO;
using System.Threading;

namespace Cts.Agent
{
    // One client connection. Requests are served in order on the thread that calls
    // Run; events from the bus are written from whatever thread publishes them.
    // Both go through one lock, so a reply and an event never interleave inside a line.
    public sealed class Session
    {
        readonly TextReader _reader;
        readonly TextWriter _writer;
        readonly Router _router;
        readonly EventBus _bus;
        readonly object _writeLock = new object();
        readonly HashSet<string> _patterns = new HashSet<string>(StringComparer.Ordinal);
        volatile bool _closed;
        volatile bool _requestsDone;

        // Events are written by a thread of their own: they are raised on whatever thread the
        // IDE uses (often the UI thread), and a client that stops reading must never be able
        // to block it. The queue is bounded; when it is full the oldest event is dropped.
        public const int MaxQueuedEvents = 1000;
        readonly Queue<string> _outbox = new Queue<string>();
        readonly object _outboxLock = new object();

        public Session(TextReader reader, TextWriter writer, Router router, EventBus bus)
        {
            _reader = reader;
            _writer = writer;
            _router = router;
            _bus = bus;
        }

        public bool IsClosed { get { return _closed; } }

        // Runs once, right after a reply line has been written.  dev.reload uses
        // it to swap the agent out only once its caller has been answered -- the
        // new host stops this one, and with it this connection.  Never throws.
        public Action AfterReply { get; set; }

        // Serves requests until the client disconnects or the connection breaks.
        public void Run()
        {
            IDisposable subscription = _bus.Subscribe(OnBusEvent);
            var pump = new Thread(PumpEvents) { IsBackground = true, Name = "cts-agent-events" };
            pump.Start();
            try
            {
                string line;
                while (!_closed && (line = _reader.ReadLine()) != null)
                {
                    if (line.Trim().Length == 0) continue;
                    Send(_router.Handle(line, this));
                    var afterReply = AfterReply;
                    if (afterReply != null)
                    {
                        AfterReply = null;
                        try { afterReply(); } catch (Exception) { }
                    }
                }
            }
            catch (IOException) { }
            catch (ObjectDisposedException) { }
            // An overlapped pipe disposed under a pending read (agent stop) cancels the read.
            catch (OperationCanceledException) { }
            finally
            {
                _requestsDone = true;
                subscription.Dispose();
                // Let events already queued reach a client that is still listening, briefly.
                pump.Join(500);
                _closed = true;
                lock (_outboxLock) { Monitor.PulseAll(_outboxLock); }
            }
        }

        // ---- event subscription (used by the built-in subscribe/unsubscribe methods)

        public void Subscribe(IEnumerable<string> patterns)
        {
            lock (_patterns)
            {
                foreach (var p in patterns) _patterns.Add(p);
            }
        }

        public void Unsubscribe(IEnumerable<string> patterns)
        {
            lock (_patterns)
            {
                foreach (var p in patterns) _patterns.Remove(p);
            }
        }

        public string[] Subscriptions
        {
            get
            {
                lock (_patterns)
                {
                    var all = new List<string>(_patterns);
                    all.Sort(StringComparer.Ordinal);
                    return all.ToArray();
                }
            }
        }

        // "*" matches everything, "online.*" matches "online.state", anything else is exact.
        public static bool Matches(string pattern, string eventName)
        {
            if (pattern == "*") return true;
            if (pattern.EndsWith(".*", StringComparison.Ordinal))
                return eventName.StartsWith(pattern.Substring(0, pattern.Length - 1), StringComparison.Ordinal);
            return pattern == eventName;
        }

        void OnBusEvent(string name, string line)
        {
            if (_closed) return;
            lock (_patterns)
            {
                var wanted = false;
                foreach (var p in _patterns)
                {
                    if (Matches(p, name)) { wanted = true; break; }
                }
                if (!wanted) return;
            }
            lock (_outboxLock)
            {
                if (_outbox.Count >= MaxQueuedEvents)
                {
                    _outbox.Dequeue();
                }
                _outbox.Enqueue(line);
                Monitor.Pulse(_outboxLock);
            }
        }

        void PumpEvents()
        {
            while (true)
            {
                string line;
                lock (_outboxLock)
                {
                    while (_outbox.Count == 0)
                    {
                        // Stop once the requests are over and the queue is drained.
                        if (_closed || _requestsDone) return;
                        Monitor.Wait(_outboxLock, 100);
                    }
                    line = _outbox.Dequeue();
                }
                Send(line);
            }
        }

        void Send(string line)
        {
            if (_closed) return;
            lock (_writeLock)
            {
                try
                {
                    _writer.Write(line);
                    _writer.Write('\n');
                    _writer.Flush();
                }
                catch (IOException) { _closed = true; }
                catch (ObjectDisposedException) { _closed = true; }
                catch (OperationCanceledException) { _closed = true; }
            }
        }

        // Registers subscribe / unsubscribe / subscriptions on a router.
        public static void RegisterBuiltIns(Router router)
        {
            router.Register("subscribe", (req, session) =>
            {
                session.Subscribe(Patterns(req));
                return new Dictionary<string, object> { { "subscriptions", session.Subscriptions } };
            });
            router.Register("unsubscribe", (req, session) =>
            {
                session.Unsubscribe(Patterns(req));
                return new Dictionary<string, object> { { "subscriptions", session.Subscriptions } };
            });
            router.Register("subscriptions", (req, session) =>
                new Dictionary<string, object> { { "subscriptions", session.Subscriptions } });
        }

        static List<string> Patterns(Request req)
        {
            object v;
            if (!req.Params.TryGetValue("events", out v) || v == null)
                throw new ProtocolException(ErrorCodes.BadParams, "missing parameter 'events'");
            var list = v as IList<object>;
            if (list == null) throw new ProtocolException(ErrorCodes.BadParams, "parameter 'events' must be an array of strings");
            var result = new List<string>();
            foreach (var item in list)
            {
                var s = item as string;
                if (string.IsNullOrEmpty(s)) throw new ProtocolException(ErrorCodes.BadParams, "'events' must contain non-empty strings");
                result.Add(s);
            }
            return result;
        }
    }
}
