using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    // Forwards IOnlineManager events to the event bus as `online.*` events.
    internal sealed class OnlineEvents
    {
        // IOnlineManager event name -> protocol event name
        static readonly KeyValuePair<string, string>[] Map =
        {
            new KeyValuePair<string, string>("AfterApplicationLogin", "online.application_login"),
            new KeyValuePair<string, string>("AfterApplicationLogout", "online.application_logout"),
            new KeyValuePair<string, string>("ApplicationStateChanged", "online.application_state"),
            new KeyValuePair<string, string>("OperatingStateChanged", "online.operating_state"),
            new KeyValuePair<string, string>("AfterDeviceLogin", "online.device_login"),
            new KeyValuePair<string, string>("AfterDeviceLogout", "online.device_logout"),
            new KeyValuePair<string, string>("BeforeApplicationDownload", "online.before_download"),
            new KeyValuePair<string, string>("AfterApplicationDownload", "online.after_download"),
        };

        readonly Ide _ide;
        readonly EventBus _bus;
        readonly FileLog _log;
        readonly IdeEvents _events;
        readonly bool _enrich;

        // enrich=false (the default): a handler only reads the event arguments and queues the
        // event; it never calls back into the IDE. The IDE raises these events from inside its own
        // operations (often with internal locks held, on a thread that is not the UI thread), and a
        // synchronous call back from the handler can deadlock it.
        // enrich=true: a pool thread later asks the UI thread for the application's state, with a
        // deadline, and publishes it with the event.
        public OnlineEvents(Ide ide, EventBus bus, FileLog log, bool enrich)
        {
            _ide = ide;
            _bus = bus;
            _log = log;
            _events = new IdeEvents(log);
            _enrich = enrich;
        }

        public int Count { get { return _events.Count; } }

        // Called with the protocol event name as each event is raised, before it
        // is published.  The agent uses it to drop cached state (the variable
        // watches) the moment the IDE says the session moved.  Runs on the
        // thread that raised the event: cheap and non-blocking only.
        public Action<string> OnRaised { get; set; }

        public void Start()
        {
            _events.Start(_ide.OnlineManager, _ide.OnlineManagerType, "online", Map, OnEvent);
        }

        public void Stop()
        {
            _events.Stop();
        }

        // Runs on the thread that raised the event, inside the IDE's own operation:
        // it must stay cheap and must not call into the IDE.
        void OnEvent(string name, EventArgs e)
        {
            try
            {
                var hook = OnRaised;
                if (hook != null) hook(name);
            }
            catch (Exception hookError)
            {
                _log.Write("online event hook " + name + " failed: " + hookError.Message);
            }
            try
            {
                var data = new Dictionary<string, object>
                {
                    { "thread", System.Threading.Thread.CurrentThread.ManagedThreadId },
                };
                var gp = e.GetType().GetProperty("GuidObject");
                if (gp != null) data["guid"] = ((Guid)gp.GetValue(e, null)).ToString();

                // One line per event; the log is append-only under a lock and never throws.
                _log.Write("event " + name + " thread=" + data["thread"]
                    + (data.ContainsKey("guid") ? " guid=" + data["guid"] : ""));
                if (!_enrich || !data.ContainsKey("guid"))
                {
                    _bus.Publish(name, data);
                    return;
                }
                var guid = new Guid((string)data["guid"]);
                System.Threading.ThreadPool.QueueUserWorkItem(_ =>
                {
                    try
                    {
                        var info = _ide.OnUi("online event " + name, 2000, () => _ide.ApplicationInfo(guid));
                        foreach (var kv in data) info[kv.Key] = kv.Value;
                        _bus.Publish(name, info);
                    }
                    catch (Exception ex)
                    {
                        data["detail_error"] = ex.Message;
                        _bus.Publish(name, data);
                    }
                });
            }
            catch (Exception ex)
            {
                _log.Write("event " + name + " failed: " + ex);
            }
        }
    }
}
