using System;
using System.Collections.Generic;
using System.Threading;

namespace Cts.Agent
{
    // Fan-out of agent events. A line is built once and handed to every subscriber;
    // a subscriber that throws is dropped from that delivery, never from the bus.
    public sealed class EventBus
    {
        readonly object _lock = new object();
        readonly List<Action<string, string>> _subscribers = new List<Action<string, string>>();
        long _seq;

        // Called with a subscriber's failure (for logging); never throws.
        public Action<Exception> OnSubscriberError { get; set; }

        // handler(eventName, line)
        public IDisposable Subscribe(Action<string, string> handler)
        {
            if (handler == null) throw new ArgumentNullException("handler");
            lock (_lock) { _subscribers.Add(handler); }
            return new Subscription(this, handler);
        }

        public int SubscriberCount
        {
            get { lock (_lock) { return _subscribers.Count; } }
        }

        public void Publish(string name, object data)
        {
            if (string.IsNullOrEmpty(name)) throw new ArgumentException("event name is required", "name");
            var seq = Interlocked.Increment(ref _seq);
            var line = Json.Serialize(new Dictionary<string, object>
            {
                { "event", name },
                { "seq", seq },
                { "time", DateTime.UtcNow },
                { "data", data },
            });
            Action<string, string>[] snapshot;
            lock (_lock) { snapshot = _subscribers.ToArray(); }
            foreach (var s in snapshot)
            {
                try { s(name, line); }
                catch (Exception e)
                {
                    var report = OnSubscriberError;
                    if (report != null)
                    {
                        try { report(e); } catch { }
                    }
                }
            }
        }

        sealed class Subscription : IDisposable
        {
            readonly EventBus _bus;
            readonly Action<string, string> _handler;

            public Subscription(EventBus bus, Action<string, string> handler)
            {
                _bus = bus;
                _handler = handler;
            }

            public void Dispose()
            {
                lock (_bus._lock) { _bus._subscribers.Remove(_handler); }
            }
        }
    }
}
