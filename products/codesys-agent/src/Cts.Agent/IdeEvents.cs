using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    // Handlers on one IDE manager's events, found by name: an event this
    // IDE lacks is logged and left out.
    internal sealed class IdeEvents
    {
        readonly FileLog _log;
        readonly List<Action> _unsubscribe = new List<Action>();

        internal IdeEvents(FileLog log)
        {
            _log = log;
        }

        internal int Count { get { return _unsubscribe.Count; } }

        // *map*: the manager's event -> the name *raised* gets with the
        // event's arguments, on the thread that raised it.
        internal void Start(object manager, Type declared, string what, IEnumerable<KeyValuePair<string, string>> map, Action<string, EventArgs> raised)
        {
            var handle = typeof(Sink).GetMethod("Handle");
            foreach (var pair in map)
            {
                var ev = declared.GetEvent(pair.Key) ?? manager.GetType().GetEvent(pair.Key);
                if (ev == null) { _log.Write(what + " event not found: " + pair.Key); continue; }
                try
                {
                    var d = Delegate.CreateDelegate(ev.EventHandlerType, new Sink(raised, pair.Value), handle);
                    ev.AddEventHandler(manager, d);
                    _unsubscribe.Add(() => ev.RemoveEventHandler(manager, d));
                }
                catch (Exception e)
                {
                    _log.Write("subscribe " + pair.Key + " failed: " + e.Message);
                }
            }
            _log.Write("subscribed to " + _unsubscribe.Count + " " + what + " events");
        }

        internal void Stop()
        {
            foreach (var u in _unsubscribe)
            {
                try { u(); } catch (Exception e) { _log.Write("unsubscribe failed: " + e.Message); }
            }
            _unsubscribe.Clear();
        }

        sealed class Sink
        {
            readonly Action<string, EventArgs> _raised;
            readonly string _name;
            public Sink(Action<string, EventArgs> raised, string name) { _raised = raised; _name = name; }
            public void Handle(object sender, EventArgs e) { _raised(_name, e); }
        }
    }
}
