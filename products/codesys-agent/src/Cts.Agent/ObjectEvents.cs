using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    // Feeds the object journal from IObjectManager's events.
    internal sealed class ObjectEvents
    {
        // IObjectManager event -> journal kind.  ObjectModifying is the one
        // raised for every change (ObjectModified misses some refactoring edits).
        static readonly KeyValuePair<string, string>[] Map =
        {
            new KeyValuePair<string, string>("ObjectModifying", "modified"),
            new KeyValuePair<string, string>("ObjectModified", "seen"),
            new KeyValuePair<string, string>("ObjectAdded", "added"),
            new KeyValuePair<string, string>("ObjectRenamed", "renamed"),
            new KeyValuePair<string, string>("ObjectMoved", "seen"),
            new KeyValuePair<string, string>("ObjectPropertyChanged", "seen"),
            new KeyValuePair<string, string>("ObjectRemoved", "removed"),
            new KeyValuePair<string, string>("ProjectLoaded", "loaded"),
            new KeyValuePair<string, string>("ProjectCreated", "session"),
            new KeyValuePair<string, string>("ProjectOpened", "session"),
            new KeyValuePair<string, string>("ProjectClosed", "session"),
            new KeyValuePair<string, string>("ProjectUnloaded", "session"),
        };

        static readonly string[] GuidProperties = { "ObjectGuid", "NewGuid", "RootObjectGuid" };
        static readonly string[] NameProperties = { "NewName", "Name" };

        readonly Ide _ide;
        readonly ObjectJournal _journal;
        readonly FileLog _log;
        readonly IdeEvents _events;

        public ObjectEvents(Ide ide, ObjectJournal journal, FileLog log)
        {
            _ide = ide;
            _journal = journal;
            _log = log;
            _events = new IdeEvents(log);
        }

        public void Start()
        {
            _events.Start(_ide.ObjectManager, _ide.ObjectManagerType, "object", Map, OnEvent);
        }

        public void Stop()
        {
            _events.Stop();
        }

        // Runs inside the IDE's own operation.  Reads the arguments, and on an
        // object's first "modified" its text, which the edit has not changed yet.
        void OnEvent(string kind, EventArgs e)
        {
            try
            {
                _journal.EventSeen(kind == "loaded" || kind == "session");
                if (kind == "loaded") return;
                // "seen": an event only the stamp counts; the journal of user
                // edits keeps to the events it always read.
                if (kind == "session" || kind == "seen") return;
                var guid = Read<Guid>(e, GuidProperties);
                // A load adds every task call again under a new guid, at times
                // seconds after the open returned.  A call has no export of its
                // own: a call the user adds changes its task, which compare sees.
                if (kind == "added" && _ide.IsTaskCall(guid)) return;
                _journal.Changed();
                string before = null;
                if (kind == "modified" && _journal.IsNew(guid))
                {
                    string text;
                    if (_ide.TextsOf(new[] { guid }).TryGetValue(guid, out text)) before = text;
                }
                _journal.Record(guid, kind, Read<string>(e, NameProperties), before);
            }
            catch (Exception error)
            {
                _log.Write("object event " + kind + " not recorded: " + error.Message);
            }
        }

        static T Read<T>(object args, string[] names)
        {
            foreach (var name in names)
            {
                var property = args.GetType().GetProperty(name);
                if (property != null && property.PropertyType == typeof(T)) return (T)property.GetValue(args, null);
            }
            return default(T);
        }
    }
}
