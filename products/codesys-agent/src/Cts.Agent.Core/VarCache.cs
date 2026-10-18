// The watch cache behind `vars.read` / `vars.write`.
//
// Resolving one expression costs the IDE three calls: GetVarReference,
// CreateWatch and the read or write itself.  GetVarReference and CreateWatch
// answer the same object for the same (application, expression) as long as the
// application is the same and the session has not moved, so both are kept and a
// repeated read of the same variable costs a single hop to the UI thread.
//
// The cache is deliberately blunt about invalidation: an application's watches
// are dropped on any online event (login, logout, a state change, a download --
// the IDE itself warns that watches built before a download answer "Invalid
// expression" afterwards) and everything is dropped on a project change.  A
// bounded size keeps a long session that reads many one-off expressions from
// growing without limit; the oldest entry goes first.
using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    public sealed class VarCache
    {
        //: Enough for every leaf of a normal GVL several times over, small
        //: enough that the objects held cannot matter.
        public const int DefaultCapacity = 1024;

        readonly int _capacity;
        readonly Dictionary<string, object> _entries;
        readonly Queue<string> _order = new Queue<string>();
        readonly object _lock = new object();

        public VarCache() : this(DefaultCapacity) { }

        public VarCache(int capacity)
        {
            if (capacity < 1) throw new ArgumentOutOfRangeException("capacity");
            _capacity = capacity;
            _entries = new Dictionary<string, object>(StringComparer.Ordinal);
        }


        public int Count { get { lock (_lock) return _entries.Count; } }

        // The key for one watch: the application it belongs to and the exact
        // expression text.  The application is part of it because two
        // applications in one IDE resolve the same text to different variables.
        public static string Key(string application, string expression)
        {
            return (application ?? "") + "\n" + (expression ?? "");
        }

        public bool TryGet(string key, out object value)
        {
            lock (_lock) { return _entries.TryGetValue(key, out value); }
        }

        // The cached value, or `factory()` installed under the key.  The factory
        // runs outside the lock: it calls into the IDE, and holding the cache
        // lock across an IDE call would let a wedged UI thread block every other
        // reader.  Two threads racing the same new key both run the factory; the
        // last one wins, which is harmless (both are watches for the same
        // expression) and cheaper than a second lock.
        public object GetOrAdd(string key, Func<object> factory)
        {
            object cached;
            if (TryGet(key, out cached)) return cached;

            var created = factory();

            lock (_lock)
            {
                object raced;
                if (_entries.TryGetValue(key, out raced)) return raced;
                _entries[key] = created;
                _order.Enqueue(key);
                while (_order.Count > _capacity)
                {
                    var oldest = _order.Dequeue();
                    _entries.Remove(oldest);
                }
            }
            return created;
        }

        // Forget everything: a new project, or an event whose meaning is "the
        // watches you hold are no longer trustworthy".
        public void Clear()
        {
            lock (_lock)
            {
                _entries.Clear();
                _order.Clear();
            }
        }
    }
}
