using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Threading;

namespace Cts.Agent
{
    internal sealed partial class DevTools
    {
        // ---- dev.listen / dev.unlisten

        Dictionary<string, object> Listen(Request req)
        {
            var rootSpec = req.String("root");
            var steps = DevPath.Parse(req.Params);
            var eventName = req.String("event");
            var target = Walk(rootSpec, steps);

            int id;
            lock (_lock)
            {
                _nextId++;
                id = _nextId;
            }

            var listener = _ide.OnUi("dev.listen " + eventName, StepTimeoutMs,
                () => Attach(id, target, eventName));
            lock (_lock) { _listeners[id] = listener; }

            return new Dictionary<string, object>
            {
                { "id", id },
                { "event", listener.Info.Name },
                { "handler", listener.Info.EventHandlerType.FullName },
                { "target_type", TypeName(target) },
            };
        }

        Dictionary<string, object> Unlisten(Request req)
        {
            var id = (int)req.Int("id");
            Listener listener;
            lock (_lock)
            {
                _listeners.TryGetValue(id, out listener);
                _listeners.Remove(id);
            }
            if (listener == null) return new Dictionary<string, object> { { "removed", false } };
            Remove(listener);
            return new Dictionary<string, object> { { "removed", true } };
        }

        Listener Attach(int id, DevTarget target, string eventName)
        {
            var isStatic = target.IsStatic;
            var type = isStatic ? (Type)target.Value : target.Value.GetType();
            var info = DevListen.ResolveEvent(type, isStatic, eventName);
            var handler = DevListen.Build(info.EventHandlerType, args => Publish(id, info.Name, args));
            info.AddEventHandler(target.Value, handler);
            return new Listener
            {
                Id = id,
                Info = info,
                Target = target.Value,
                Handler = handler,
            };
        }

        void Remove(Listener listener)
        {
            try
            {
                var here = listener.Target;
                _ide.OnUi("dev.unlisten " + listener.Info.Name, 5000,
                    () => { listener.Info.RemoveEventHandler(here, listener.Handler); return true; });
            }
            catch (Exception e)
            {
                _log.Write("dev listener " + listener.Id + " did not detach: " + e.Message);
            }
        }

        // Runs on whatever thread raised the event, inside the IDE's own
        // operation: cheap, no IDE calls, never throws.
        void Publish(int id, string name, object[] args)
        {
            try
            {
                var sender = args != null && args.Length > 0 ? args[0] : null;
                var payload = args != null && args.Length > 1 ? args[1] : null;
                _bus.Publish("dev.event", new Dictionary<string, object>
                {
                    { "id", id },
                    { "event", name },
                    { "thread", Thread.CurrentThread.ManagedThreadId },
                    { "sender_type", sender == null ? null : sender.GetType().FullName },
                    { "args", DevListen.Snapshot(payload) },
                });
            }
            catch (Exception e)
            {
                _log.Write("dev.event " + name + " failed: " + e.Message);
            }
        }

        // ---- dev.reload

        // Prototype: swap in a freshly built pair of agent DLLs without restarting
        // CODESYS.  The bytes are loaded here, but the new host is only started
        // once this reply has been written -- the new Start stops this host, and
        // with it the pipe this request came on.
        //
        // Measured on .NET Framework 4.8: an AssemblyResolve handler does NOT bind
        // the new Agent to the new Core. Reference binding is by assembly identity,
        // and only the *first* assembly of a given identity is ever bound; a second
        // copy with the same identity (the release version of both) is ignored, and with no
        // unresolved reference the resolve event never fires. So the new Agent binds
        // the old Core silently. Bumping the identity (Version in Directory.Build.props) is what
        // makes the new bytes the bound ones (the reply's `bound_core_location`
        // names the folder when the old Core was chosen, empty when the new bytes
        // were). Each reload leaves one more copy in the AppDomain: it cannot be
        // unloaded (see `loaded_agents`).
        Dictionary<string, object> Reload(Request req, Session session)
        {
            var dir = req.String("dir");
            if (string.IsNullOrEmpty(dir))
                throw new ProtocolException(ErrorCodes.BadParams, "missing parameter 'dir'");
            var agentPath = Path.Combine(dir, "Cts.Agent.dll");
            var corePath = Path.Combine(dir, "Cts.Agent.Core.dll");
            if (!File.Exists(agentPath))
                throw new ProtocolException(ErrorCodes.BadParams, "no Cts.Agent.dll in " + dir);

            var newCore = File.Exists(corePath) ? Assembly.Load(File.ReadAllBytes(corePath)) : null;
            var newAgent = Assembly.Load(File.ReadAllBytes(agentPath));
            var type = newAgent.GetType("Cts.Agent.AgentHost");
            if (type == null)
                throw new ProtocolException(ErrorCodes.Unavailable, "no Cts.Agent.AgentHost in " + agentPath);
            var start = type.GetMethod("Start", new[] { typeof(string), typeof(string) });
            if (start == null)
                throw new ProtocolException(ErrorCodes.Unavailable, "AgentHost.Start(string, string) not found");

            // `_bus` is a Cts.Agent.Core type: its runtime FieldType is the Core
            // the new Agent actually bound, so the reply can report it (an empty
            // Location means the byte-loaded copy, the agent folder means the old
            // one already in the AppDomain).
            var busField = type.GetField("_bus", BindingFlags.NonPublic | BindingFlags.Instance);
            var boundCore = busField == null ? null : busField.FieldType.Assembly;
            var boundLocation = boundCore == null ? null : boundCore.Location;

            var logPath = _logPath;
            var options = _options;
            session.AfterReply = () =>
            {
                try
                {
                    _ide.OnUi("dev.reload start", 15000, () =>
                    {
                        _log.Write("dev.reload: " + start.Invoke(null, new object[] { logPath, options }));
                        return true;
                    });
                }
                catch (Exception e)
                {
                    _log.Write("dev.reload start failed: " + e.Message);
                }
            };

            return new Dictionary<string, object>
            {
                { "agent", agentPath },
                { "core", File.Exists(corePath) ? corePath : null },
                { "new_agent", newAgent.FullName },
                { "new_core", newCore == null ? null : newCore.FullName },
                { "bound_core", boundCore == null ? null : boundCore.FullName },
                { "bound_core_location", boundLocation },
                { "loaded_agents", CountLoaded("Cts.Agent") },
                { "loaded_cores", CountLoaded("Cts.Agent.Core") },
            };
        }

        // How many copies of one identity this AppDomain holds: the reload cannot
        // unload the old ones, so this only ever grows (2, 3, ... per reload).
        static int CountLoaded(string name)
        {
            var n = 0;
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
                if (asm.GetName().Name == name) n++;
            return n;
        }
    }
}
