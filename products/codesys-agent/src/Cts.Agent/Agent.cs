// Entry point, called from the loader script. Starts the pipe server and the event
// forwarding, then returns: the script ends, the agent keeps running on its own threads.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;

namespace Cts.Agent
{
    public sealed partial class AgentHost
    {
        public const string AnchorKey = "cts-agent";
        const int UiTimeoutMs = 3000;

        readonly Ide _ide;
        readonly EventBus _bus = new EventBus();
        readonly Router _router = new Router();
        readonly ModalState _modal = new ModalState();
        readonly FileLog _log;
        readonly DateTime _startedUtc = DateTime.UtcNow;
        readonly OnlineEvents _online;
        readonly ObjectJournal _journal = new ObjectJournal();
        readonly TimeoutProfileCache _timeouts = new TimeoutProfileCache();
        readonly ObjectEvents _objectEvents;
        readonly ModalWatcher _modalWatcher;
        readonly ModalProbe _modalProbe;
        readonly DialogAnswerer _dialogs;
        readonly VarsService _vars;
        readonly DevTools _dev;
        readonly PipeServer _pipe;
        readonly QuickWidget _widget;
        readonly MirrorRefresh _mirror;
        readonly string _pipeName;
        readonly string _options;
        bool _stopped;
        readonly bool _noEvents;

        AgentHost(string logPath, string options)
        {
            //: The raw switches, kept for dev.reload: re-normalising an already
            //: normalised string would grow a comma per reload.
            _options = options ?? "";
            options = "," + (options ?? "").ToLowerInvariant().Replace(" ", "") + ",";
            _noEvents = options.Contains(",no-events,");
            _log = new FileLog(logPath);
            _pipeName = "cts-agent-" + Process.GetCurrentProcess().Id;
            _ide = new Ide();
            _ide.Modal = _modal;
            _modalWatcher = new ModalWatcher(_modal, _bus, _log);
            _modalProbe = new ModalProbe(_modalWatcher, _modal, _log);
            _ide.Probe = _modalProbe;
            _dialogs = new DialogAnswerer(_ide, _modal, _modalWatcher, _modalProbe, _log);
            _bus.OnSubscriberError = e => _log.Write("event subscriber failed: " + e.Message);
            _router.OnHandlerFault = (m, e) => _log.Write("handler " + m + " failed: " + e);
            // Every request the router answers also becomes one line in the agent log.
            _router.OnActivity = _log.Write;
            // While a modal dialog is up only the UI-free methods answer; this
            // gate turns everything else into dialog_blocked before its handler
            // runs.  It confirms the cached snapshot with one fresh look before
            // refusing, so a dialog the user just dismissed does not refuse the
            // next command.  UiCall's epoch guard is the second line of defence,
            // for a dialog that opens between this check and the UI thread
            // starting the work.
            _router.Gate = request => ModalGate.Check(request.Method, _modal, _modalProbe)
                ?? ModalGate.CheckBusy(request.Method, _router.Running().Select(run => run.Key));
            _vars = new VarsService(_ide, new VarCache(), _log);
            RegisterMethods();
            // dev.* exists only when asked for: the discovery tools are not part
            // of the production surface.
            if (options.Contains(",dev,"))
            {
                _dev = new DevTools(_ide, _bus, _log, logPath, _options);
                _dev.Register(_router);
            }
            _online = new OnlineEvents(_ide, _bus, _log, options.Contains(",enrich,"));
            _ide.Journal = _journal;
            _objectEvents = new ObjectEvents(_ide, _journal, _log);
            // The variable watches are dropped when the IDE says the session
            // moved; a login, a logout or a download invalidates what we hold.
            _online.OnRaised = _vars.OnOnlineEvent;
            _pipe = new PipeServer(_pipeName, _router, _bus, _log);
            _widget = new QuickWidget(_ide, _modal, _log, _router);
            _mirror = new MirrorRefresh(_ide, _journal, _modal, _pipe, _widget, _log);
        }

        // Called from the IronPython loader. Stops a previous instance (from any build
        // of this DLL) found in the AppDomain, then starts a new one. Returns a one-line
        // status for the script to print.
        //
        // options: comma-separated switches, for diagnosing a misbehaving IDE.
        //   no-events  do not subscribe to the IDE's online events at all
        //   enrich     add the application's state to each online event (asks the UI thread)
        public static string Start(string logPath, string options)
        {
            var notes = "";
            var previous = AppDomain.CurrentDomain.GetData(AnchorKey);
            if (previous != null)
            {
                try
                {
                    previous.GetType().GetMethod("Stop").Invoke(previous, null);
                    notes = "replaced the previous agent; ";
                }
                catch (Exception e)
                {
                    notes = "previous agent did not stop cleanly (" + e.Message + "); ";
                }
            }
            var host = new AgentHost(logPath, options);
            host._log.Write("==== start pid=" + Process.GetCurrentProcess().Id
                + " clr=" + Environment.Version + " 64bit=" + Environment.Is64BitProcess
                + " version=" + Cts.Cli.CliRun.Build()
                + " asm=" + typeof(AgentHost).Assembly.Location);
            if (!host._noEvents)
            {
                host._online.Start();
                host._objectEvents.Start();
            }
            else host._log.Write("online and object events disabled by option no-events");
            host._modalWatcher.Start();
            host._pipe.Start();
            host._widget.Start();
            host._mirror.Start();
            AppDomain.CurrentDomain.SetData(AnchorKey, host);
            host._log.Write("pipe " + host._pipeName + " ready");
            return notes + "agent " + Cts.Cli.CliRun.Build() + " listening on \\\\.\\pipe\\" + host._pipeName
                + ", " + host._online.Count + " online events" + (string.IsNullOrEmpty(options) ? "" : " [" + options + "]");
        }

        public void Stop()
        {
            if (_stopped) return;
            _stopped = true;
            _online.Stop();
            _objectEvents.Stop();
            _modalWatcher.Stop();
            if (_dev != null) _dev.Stop();
            _mirror.Stop();
            _widget.Stop();
            _pipe.Stop();
            if (ReferenceEquals(AppDomain.CurrentDomain.GetData(AnchorKey), this))
                AppDomain.CurrentDomain.SetData(AnchorKey, null);
            _log.Write("==== stop");
        }

        // The menu entry, the toolbar button and the startup script of an IDE
        // `cts project open --launch` started (cts install writes the stub that
        // calls this): starts the agent unless one runs in this IDE, then opens
        // the quick window. The startup script gets no window and no box that
        // would hold it until someone clicks: what it prints is returned.
        public static string Menu()
        {
            var launched = Environment.GetEnvironmentVariable("CTS_LAUNCHED") != null;
            Environment.SetEnvironmentVariable("CTS_LAUNCHED", null);
            var running = AppDomain.CurrentDomain.GetData(AnchorKey);
            if (running == null)
            {
                try
                {
                    Start(Path.Combine(Path.GetTempPath(), "cts-agent.log"), Environment.GetEnvironmentVariable("CTS_AGENT_OPTIONS") ?? "");
                }
                catch (Exception e)
                {
                    Say("The cts agent did not start:\n" + e.Message);
                    return "";
                }
            }
            if (launched)
                return "The cts agent " + (running == null ? "is running" : "was already running") + " in this CODESYS.\n\n"
                    + "Press " + Key() + " in CODESYS at any time for the quick window: Disk -> IDE, IDE -> Disk, merge, compare, "
                    + "branches, commit and settings (7 there changes the key).\n\n"
                    + "cts commands in a terminal (cts status, cts export, ...) reach this IDE too. The agent stays until CODESYS closes.";
            var host = AppDomain.CurrentDomain.GetData(AnchorKey);
            try
            {
                // By name: the agent running may come from another build of this DLL.
                host.GetType().GetMethod("ShowQuick").Invoke(host, null);
            }
            catch (Exception e)
            {
                Say("The running cts agent cannot open the quick window (" + (e.InnerException ?? e).Message + "); restart CODESYS.");
            }
            return "";
        }

        // The chord that opens the quick window, as the user's defaults.json names it.
        static string Key()
        {
            var defaults = UserDefaults.Path;
            try
            {
                return (File.Exists(defaults) ? QuickKey.FromDefaults(File.ReadAllText(defaults)) : QuickKey.Default).Text;
            }
            catch (IOException) { return QuickKey.Default.Text; }
            catch (UnauthorizedAccessException) { return QuickKey.Default.Text; }
        }

        static void Say(string text)
        {
            System.Windows.Forms.MessageBox.Show(text, "cds-text-sync", System.Windows.Forms.MessageBoxButtons.OK, System.Windows.Forms.MessageBoxIcon.Error);
        }

        // Called by name from Menu through the AppDomain anchor.
        public void ShowQuick()
        {
            _widget.ShowQuick();
        }

        // ---- methods

        void RegisterMethods()
        {
            Session.RegisterBuiltIns(_router);

            // No IDE call at all: answers even when the UI thread is blocked.
            _router.Register("ping", (req, s) => new Dictionary<string, object>
            {
                { "pong", true },
                { "uptime_s", (DateTime.UtcNow - _startedUtc).TotalSeconds },
            });

            _router.Register("hello", (req, s) => Hello());

            _router.Register("state", (req, s) =>
                _ide.OnUiUnguarded("state", StartTimeout.Parse(req, UiTimeoutMs), () => new Dictionary<string, object>
                {
                    { "project", _ide.ProjectState() },
                }));

            // Unguarded like `state`: a dialog on screen is exactly when the
            // caller needs to know what the IDE holds.
            _router.Register("project.status", (req, s) =>
            {
                var status = _ide.OnUiUnguarded("project.status", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.ProjectStatus());
                var last = LastBuild.Brief(_ide.LastBuildRecord, status.ContainsKey("path") ? Convert.ToString(status["path"]) : "", _journal.LastChange);
                if (last != null) status["last_command"] = last;
                return status;
            });
            _router.Register("project.tree", (req, s) => _ide.OnUi("project.tree", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.Tree((int)req.Int("depth", 0))));
            // Persist the project after an agent-path import (`cts import --save`).
            _router.Register("project.save", (req, s) => _ide.OnUi("project.save", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.SaveProject()));
            // Give the project its id for a sync folder (`cts set-sync-folder`).
            _router.Register("project.syncfolder", (req, s) => _ide.OnUi("project.syncfolder", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.SetSyncFolder(req.String("path", ""), req.String("id", ""), req.Bool("save", false), req.Bool("dry_run", false))));
            // The commit the IDE's code came from, after an import or a commit.
            _router.Register("project.source", (req, s) => _ide.OnUi("project.source", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.MarkSource(req.String("source", ""), req.String("when", ""))));
            // Simulation on the active application's device (`cts project simulate`).
            _router.Register("project.simulation", (req, s) => _ide.OnUi("project.simulation", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.SetSimulation(req.Bool("enable"))));
            // The login credentials for this IDE session (`cts project set-credentials`).
            _router.Register("project.credentials", (req, s) => _ide.OnUi("project.credentials", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.SetCredentials(req.String("username", ""), req.String("password", ""))));
            // The project's deny list (`cts permissions`); read-only, never gated.
            _router.Register("project.permissions", (req, s) => _ide.OnUi("project.permissions", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.Permissions()));
            // The projects open in the IDE; open one as primary, close the primary
            // (`cts project list|open|close`).  Loading a large project takes a while,
            // which the finish backstop allows.
            _router.Register("project.list", (req, s) => _ide.OnUi("project.list", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.ListProjects()));
            _router.Register("project.open", (req, s) =>
            {
                // A load leaves work queued on the UI thread -- the task
                // configuration adds its calls again -- whose object events come
                // after OpenProject returns; a call queued behind that work keeps
                // them cts's own too.
                using (_journal.Own())
                {
                    _journal.EventSeen(true);
                    var opened = _ide.OnUi("project.open", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.OpenProjectFile(req.String("path", "")));
                    try { _ide.OnUiUnguarded("project.open settle", UiTimeoutMs, () => true); }
                    catch (ProtocolException e) { _log.Write("project.open: the load did not settle: " + e.Message); }
                    return opened;
                }
            });
            _router.Register("project.close", (req, s) =>
            {
                var closed = _ide.OnUi("project.close", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.CloseProject(req.Bool("discard", false)));
                _journal.EventSeen(true);
                return closed;
            });
            // The devices and their applications (`cts project list-devices`).
            _router.Register("project.devices", (req, s) => _ide.OnUi("project.devices", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.Devices(req.String("device", ""))));
            // The installed device descriptions (`cts project device-types`).
            _router.Register("project.device_types", (req, s) => _ide.OnUi("project.device_types", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.DeviceTypes(req.String("filter", ""))));
            // Update Device: another type or version for a device (`cts project change-device`).
            _router.Register("project.change_device", (req, s) => _ide.OnUi("project.change_device", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.ChangeDevice(req.String("device", ""), (int)req.Int("type"), req.String("id"), req.String("version", ""))));
            // The messages of one IDE message category (`cts read-log`).
            _router.Register("messages.read", (req, s) => _ide.OnUi("messages.read", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.ReadMessages(req.String("category", ""), req.Int("last", 0), req.Bool("clear", false))));
            RegisterOnlineMethods();
            RegisterObjectMethods();

            // What the modal watcher currently sees.  Read-only and, like ping,
            // answered without going through the UI thread, so it stays
            // available while a dialog is open (see ModalGate).
            _router.Register("dialog.probe", (req, s) => DialogProbe());

            // Answer the dialog that is blocking the IDE: set its options and
            // press its button, with the caller's names checked against a live
            // read first.  It has to run while a dialog is up, which
            // is why it is in the modal gate's allowlist; nothing is clicked
            // until every name has been matched.
            _router.Register("dialog.answer", (req, s) => _dialogs.Run(req));
#if DEBUG
            // The quick window worked from the pipe, for its tests (QuickWidget.Drive).
            _router.Register("widget.snapshot", (req, s) => _widget.Snapshot());
            _router.Register("widget.drive", (req, s) => _widget.Drive(
                req.Params.TryGetValue("steps", out var steps) ? steps as IEnumerable<object> : null,
                (int)req.Int("timeout_ms", 60000)));
#endif

            _router.Register("methods", (req, s) => new List<string>(_router.Methods));

            // Native PLC variable read/write.
            _vars.Register(_router);

            // The JSON test plans of a sync folder's .test, run through the
            // methods above (`cts verify --with-test`).  Not on the UI thread:
            // each step's call takes it for itself, and a wait sleeps here.
            _router.Register(TestPlans.Method, (req, s) =>
            {
                _ide.OnUi(TestPlans.Method, StartTimeout.Parse(req, UiTimeoutMs), () => { _ide.RequireKey(DenyRules.RunTests); return 0; });
                var clock = Stopwatch.StartNew();
                return TestPlans.Run(req.String("folder", ""), req.String("file", ""), (method, parameters) => Local(method, parameters, s),
                    ms => Thread.Sleep(TimeSpan.FromMilliseconds(ms)), () => clock.ElapsedMilliseconds);
            });

            // The ST tests of a test application in simulation (`cts test`),
            // through the methods above like test.run.
            _router.Register(AppTests.Method, (req, s) =>
            {
                _ide.OnUi(AppTests.Method, StartTimeout.Parse(req, UiTimeoutMs), () => { _ide.RequireKey(DenyRules.RunTests); return 0; });
                var clock = Stopwatch.StartNew();
                return AppTests.Run(req.String("application", ""), req.Int("wait_ms", 0), (method, parameters) => Local(method, parameters, s),
                    ms => Thread.Sleep(TimeSpan.FromMilliseconds(ms)), () => clock.ElapsedMilliseconds);
            });

            // The objects the IDE changed outside cts since the last take.
            _router.Register("journal.take", (req, s) => JournalTake(req));
        }

        // The modal snapshot: what is open right now, and the epoch a caller can
        // compare against a later probe to see that something changed.  Reads
        // the watcher's state only -- no IDE call, so it cannot block.
        Dictionary<string, object> DialogProbe()
        {
            return new Dictionary<string, object>
            {
                { "dialogs", OpenDialogs() },
                { "epoch", _modal.Epoch },
                { "poll_ms", _modalWatcher.LastPollMs },
                { "poll_count", _modalWatcher.Polls },
            };
        }

        List<object> OpenDialogs()
        {
            var dialogs = new List<object>();
            foreach (var window in _modal.Current) dialogs.Add(window.ToData());
            return dialogs;
        }

        // One method of this agent called from inside another (test.run's
        // steps): the same router, modal gate and activity line as a request
        // on the pipe, and a refusal comes back as the ProtocolException it was.
        IDictionary<string, object> Local(string method, Dictionary<string, object> parameters, Session session)
        {
            var request = new Dictionary<string, object> { { "id", method }, { "method", method }, { "params", parameters } };
            var reply = Json.Parse(_router.Handle(Json.Serialize(request), session)) as IDictionary<string, object>;
            object value;
            if (reply != null && reply.TryGetValue("ok", out value) && Equals(value, true))
                return reply.TryGetValue("result", out value) && value is IDictionary<string, object> ? (IDictionary<string, object>)value : new Dictionary<string, object>();
            var error = reply != null && reply.TryGetValue("error", out value) ? value as IDictionary<string, object> : null;
            object code = null, message = null;
            error?.TryGetValue("code", out code);
            error?.TryGetValue("message", out message);
            throw new ProtocolException(code as string ?? ErrorCodes.Internal, message as string ?? method + " gave no answer");
        }

        Dictionary<string, object> JournalTake(Request req)
        {
            var taken = _journal.Take();
            var names = new Dictionary<Guid, string>();
            if (taken.Count > 0)
            {
                try
                {
                    var guids = taken.Select(c => c.Guid).ToList();
                    var now = new Dictionary<Guid, string>();
                    _ide.OnUi("journal.take", StartTimeout.Parse(req, UiTimeoutMs), () =>
                    {
                        names = _ide.NamesOf(guids);
                        now = _ide.TextsOf(guids);
                        return 0;
                    });
                    taken = ObjectJournal.Changed(taken, now);
                }
                catch (Exception e) { _log.Write("journal names not read: " + e.Message); }
            }
            var changes = new List<object>();
            foreach (var change in taken)
            {
                string name;
                names.TryGetValue(change.Guid, out name);
                changes.Add(new Dictionary<string, object>
                {
                    { "guid", change.Guid.ToString() },
                    { "name", name ?? change.Name },
                    { "kinds", change.Kinds },
                    { "last", change.Last },
                });
            }
            return new Dictionary<string, object> { { "changes", changes } };
        }

        Dictionary<string, object> Hello()
        {
            var proc = Process.GetCurrentProcess();
            string product = null, productVersion = null;
            try
            {
                var v = FileVersionInfo.GetVersionInfo(proc.MainModule.FileName);
                product = v.ProductName;
                productVersion = v.ProductVersion;
            }
            catch { }

            var hello = new Dictionary<string, object>
            {
                { "protocol", Protocol.Version },
                { "agent_version", Cts.Cli.CliRun.Build() },
                { "pid", proc.Id },
                { "process", proc.ProcessName },
                { "product", product },
                { "product_version", productVersion },
                { "is_64bit", Environment.Is64BitProcess },
                { "clr", Environment.Version.ToString() },
                { "started", _startedUtc },
                { "pipe", _pipeName },
                { "methods", new List<string>(_router.Methods) },
                { "user_changes", _journal.Count },
            };
            try
            {
                var project = _ide.OnUiUnguarded("hello", 1500, () => _ide.ProjectState());
                hello["project"] = project;
                if (project != null && project.ContainsKey("path") && !string.IsNullOrEmpty(project["path"] as string)) hello["ide_stamp"] = _journal.Stamp;
                object folder;
                project.TryGetValue("sync_folder", out folder);
                hello["timeout_profile"] = _timeouts.For(folder as string);
            }
            catch (ProtocolException e)
            {
                // A busy UI thread (a download, a modal dialog) must not make the agent
                // look dead: say so and still answer.
                hello["project"] = null;
                hello["ui_busy"] = e.Code == ErrorCodes.Busy;
                hello["ui_error"] = e.Message;
                hello["timeout_profile"] = _timeouts.Last;
            }
            return hello;
        }
    }
}
