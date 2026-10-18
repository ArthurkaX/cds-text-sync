using System;
using System.Collections.Generic;
using System.Threading;

namespace Cts.Agent
{
    // The objects the IDE changed outside cts: a GUID set fed by the object
    // manager's events, taken by the CLI and reported to its caller.  An event
    // only says "may have changed": a modified object keeps the text it had at
    // its first event, and Take's caller drops it when the text is the same
    // again (opened for edit, or typed and undone).  Changes made while cts
    // writes (Own) are not recorded: an agent write and a tree edit look the
    // same in the events (Editor is null).
    public sealed class ObjectJournal
    {
        readonly object _lock = new object();
        readonly Dictionary<Guid, Change> _changes = new Dictionary<Guid, Change>();
        readonly List<Guid> _order = new List<Guid>();
        int _own;
        Guid _session = Guid.NewGuid();
        long _events;
        // When an object last changed, by cts or by the user: a build before
        // it says nothing about the project as it is.
        DateTime _lastChange;

        public string Stamp
        {
            get { lock (_lock) { return _session.ToString("N") + ":" + _events.ToString(System.Globalization.CultureInfo.InvariantCulture); } }
        }

        public void EventSeen(bool projectLoaded = false)
        {
            lock (_lock)
            {
                if (projectLoaded) { _session = Guid.NewGuid(); _events = 0; }
                else _events++;
            }
        }

        // An object was added, changed, renamed or removed just now.
        public void Changed()
        {
            lock (_lock) { _lastChange = DateTime.UtcNow; }
        }

        public DateTime LastChange
        {
            get { lock (_lock) { return _lastChange; } }
        }

        // The agent methods that change the project: those with a deny key.
        public static bool IsWrite(string method)
        {
            return DenyRules.KeyFor(method) != null;
        }

        // While the result is not disposed, events are cts's own.
        public IDisposable Own()
        {
            Interlocked.Increment(ref _own);
            return new OwnScope(this);
        }

        public int Count
        {
            get { lock (_lock) { return _changes.Count; } }
        }

        // Whether an event for this object starts a new change: then the caller
        // reads the object's text first and passes it to Record as `before`.
        public bool IsNew(Guid guid)
        {
            if (guid == Guid.Empty || Volatile.Read(ref _own) > 0) return false;
            lock (_lock) { return !_changes.ContainsKey(guid); }
        }

        // Runs on the thread that raised the event: cheap, never calls the IDE.
        // `before` (null: unknown) counts only for the object's first event.
        public void Record(Guid guid, string kind, string name, string before = null)
        {
            if (guid == Guid.Empty || Volatile.Read(ref _own) > 0) return;
            lock (_lock)
            {
                Change change;
                if (!_changes.TryGetValue(guid, out change))
                {
                    _changes[guid] = change = new Change { Guid = guid, Before = before };
                    _order.Add(guid);
                }
                if (!change.Kinds.Contains(kind)) change.Kinds.Add(kind);
                if (!string.IsNullOrEmpty(name)) change.Name = name;
                change.Last = DateTime.UtcNow;
            }
        }

        // Every change since the last Take, oldest first; the journal is then empty.
        public List<Change> Take()
        {
            lock (_lock)
            {
                var taken = new List<Change>();
                foreach (var guid in _order) taken.Add(_changes[guid]);
                _changes.Clear();
                _order.Clear();
                return taken;
            }
        }

        // The taken changes without those only modified whose text is again what
        // it was (`now`: the current texts; a missing or null one is unknown).
        public static List<Change> Changed(IEnumerable<Change> taken, IDictionary<Guid, string> now)
        {
            var changed = new List<Change>();
            foreach (var change in taken)
            {
                string text;
                var same = change.Kinds.Count == 1 && change.Kinds[0] == "modified" && change.Before != null
                    && now.TryGetValue(change.Guid, out text) && text == change.Before;
                if (!same) changed.Add(change);
            }
            return changed;
        }

        public sealed class Change
        {
            public Guid Guid;
            public string Name;
            public string Before;
            public readonly List<string> Kinds = new List<string>();
            public DateTime Last;
        }

        sealed class OwnScope : IDisposable
        {
            ObjectJournal _journal;

            public OwnScope(ObjectJournal journal) { _journal = journal; }

            public void Dispose()
            {
                var journal = Interlocked.Exchange(ref _journal, null);
                if (journal != null) Interlocked.Decrement(ref journal._own);
            }
        }
    }
}
