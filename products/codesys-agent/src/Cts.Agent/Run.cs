// `app.start` / `app.stop`: run or stop the application the IDE is logged in
// to, `app.bootapp`: store it on the PLC as the boot application, `app.reset`:
// reset it, and `app.logout`: end every online session of the project.
//
// IOnlineApplication has no start or stop; the IDE's own Online -> Start/Stop
// commands go through OnlineCommandHelper, a static class of the online
// commands plug-in:
//
//   OnlineCommandHelper.CanStart(appGuid) / Start(appGuid)
//   OnlineCommandHelper.CanStop(appGuid)  / Stop(appGuid)
//
// The boot application is IOnlineApplication3.CreateBootProject, what the
// IDE's Online -> Create boot application runs once OnlineCommandHelper's
// CanCreateBootApplication allows it.
//
// A reset is IOnlineApplication.Reset(ResetOption), what the IDE's Online ->
// Reset warm/cold/origin runs (without their confirmation dialog) once
// OnlineCommandHelper.CanReset allows it.
//
// `app.download` is a full download, what the IDE's Online -> Download runs
// while logged in: OnlineCommandHelper.Download(appGuid, bOnlineChange: false),
// which stops the application and resets its variables, without a dialog.
// Logged out, it logs in first through OnlineCommandHelper.LoginWithParameters
// with Regular | ForceDownload | SuppressAllDialogs | SuppressAllErrorPopups:
// that login downloads a changed or missing application by itself and only
// logs in to an unchanged one, so the Download after it is what makes every
// case the same full download.  A session to a PLC that holds no application
// (after an origin reset, state "none") cannot take a Download ("Download
// failed: Unknown reason"); it is ended and logged in to again, which creates
// the application.
//
// `app.activate {application}` makes that application the project's active one
// (IProject.ActiveApplication, what the IDE's Set Active Application sets); the
// project does not count it as a change.
//
// `app.crc` compares the ids of the code and data on the PLC
// (IOnlineApplication.CodeId / DataId, as of the login) with those of the code
// the IDE generated last (ILanguageModelManager.GetCompiledIds), see
// AppChecksums.
//
// Like a variable read it never logs in: it uses the session the user (or
// `cts connect`) opened, and says so when there is none.  The deny list keys
// are `start_plc`, `stop_plc`, `create_boot_app`,
// `reset_plc` (`reset_plc --kind origin` for an origin reset), `plc_crc`,
// `disconnect_from_device` and `download` (with `start_plc` for its start);
// the download alone logs in when there is no session.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        //: Start and Stop return before the runtime has switched; how long the
        //: answer waits for the state it asked for, polled off the UI thread.
        const int RunSettleMs = 5000;
        const int RunPollMs = 100;

        // Run or stop on the UI thread, then wait (off it) until the runtime
        // reports the state asked for, so the answer is the state it is in.
        public Dictionary<string, object> RunApplication(bool start, int startMs)
        {
            var what = start ? "app.start" : "app.stop";
            var result = OnUi(what, startMs, () => RunOnUi(start));
            var wanted = start ? "run" : "stop";
            var timer = Stopwatch.StartNew();
            while ((string)result["application_state"] != wanted && timer.ElapsedMilliseconds < RunSettleMs)
            {
                Thread.Sleep(RunPollMs);
                result["application_state"] = OnUi(what, startMs, () => ApplicationStateOf(ActiveApplication()));
            }
            return result;
        }

        Dictionary<string, object> RunOnUi(bool start)
        {
            string raw; bool readable;
            DenyConfig(out raw, out readable);
            DenyRules.Require(raw, readable, start ? DenyRules.StartPlc : DenyRules.StopPlc);
            var guid = LoggedInActiveApplication();
            var helper = FindType("_3S.CoDeSys.OnlineCommands.OnlineCommandHelper");
            var name = start ? "Start" : "Stop";
            var args = new object[] { guid };
            // Can* is false when the application is already in that state (or
            // the IDE would grey the command out): nothing to do then.
            var can = NeedMethod(helper, "Can" + name, new[] { typeof(Guid) }, "OnlineCommandHelper.Can" + name + " is not present in this IDE");
            var changed = (bool)can.Invoke(null, args);
            if (changed)
            {
                var run = NeedMethod(helper, name, new[] { typeof(Guid) }, "OnlineCommandHelper." + name + " is not present in this IDE");
                try { run.Invoke(null, args); }
                catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, name + ": " + Invocation.Cause(e).Message); }
            }
            return new Dictionary<string, object>
            {
                { "state", start ? "started" : "stopped" },
                { "changed", changed },
                { "application", NameOf(ReadMeta(ProjectHandle(), guid)) },
                { "application_state", ApplicationStateOf(guid) },
            };
        }

        //: LoginServiceFlags Regular | ForceDownload | SuppressAllDialogs |
        //: SuppressAllErrorPopups: no question and no message box on the UI
        //: thread, and a changed application is downloaded, not changed online.
        const int DownloadLoginFlags = 1 | 4 | 256 | 512;

        //: The application state of a session to a PLC without the application,
        //: and of one just downloaded before the runtime has it.
        const string NoApplication = "none";

        // Download on the UI thread and wait (off it) until the runtime reports
        // the stopped application, then start it when asked, waiting for it to
        // run like `app.start` does.
        public Dictionary<string, object> DownloadApplication(bool start, int startMs)
        {
            var result = OnUi("app.download", startMs, () => DownloadOnUi(start));
            var timer = Stopwatch.StartNew();
            while ((string)result["application_state"] == NoApplication && timer.ElapsedMilliseconds < RunSettleMs)
            {
                Thread.Sleep(RunPollMs);
                result["application_state"] = OnUi("app.download", startMs, () => ApplicationStateOf(ActiveApplication()));
            }
            result["started"] = false;
            if (start)
            {
                var run = RunApplication(true, startMs);
                result["started"] = true;
                result["application_state"] = run["application_state"];
            }
            return result;
        }

        Dictionary<string, object> DownloadOnUi(bool start)
        {
            RequireKey(DenyRules.Download);
            if (start) RequireKey(DenyRules.StartPlc);
            var guid = ActiveApplication();
            if (guid == Guid.Empty)
                throw new ProtocolException(ErrorCodes.BadParams, "the project has no active application");
            var application = NameOf(ReadMeta(ProjectHandle(), guid));
            var helper = FindType("_3S.CoDeSys.OnlineCommands.OnlineCommandHelper");
            var loggedIn = IsLoggedIn(guid);
            if (loggedIn && ApplicationStateOf(guid) == NoApplication)
            {
                NeedMethod(helper, "Logout", new[] { typeof(Guid) }, "OnlineCommandHelper.Logout is not present in this IDE")
                    .Invoke(null, new object[] { guid });
                loggedIn = false;
            }
            if (!loggedIn) LogIn(helper, guid, application);
            var download = NeedMethod(helper, "Download", new[] { typeof(Guid), typeof(bool) }, "OnlineCommandHelper.Download is not present in this IDE");
            try { download.Invoke(null, new object[] { guid, false }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "Download: " + Invocation.Cause(e).Message); }
            return new Dictionary<string, object>
            {
                { "downloaded", true },
                { "logged_in", !loggedIn },
                { "application", application },
                { "plc", PlcTarget() },
                { "application_state", ApplicationStateOf(guid) },
            };
        }

        void LogIn(Type helper, Guid guid, string application)
        {
            var flags = FindType("_3S.CoDeSys.OnlineCommands.LoginServiceFlags");
            var login = NeedMethod(helper, "LoginWithParameters",
                new[] { typeof(Guid), flags, FindType("_3S.CoDeSys.OnlineCommands.OnlineChangeDialogHandlerDelegate"),
                    FindType("_3S.CoDeSys.OnlineCommands.LoginDialogHandlerDelegate"), typeof(bool) },
                "OnlineCommandHelper.LoginWithParameters is not present in this IDE");
            object answer;
            try { answer = login.Invoke(null, new[] { guid, Enum.ToObject(flags, DownloadLoginFlags), null, null, false }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "Login to " + application + ": " + Invocation.Cause(e).Message); }
            if (!(answer is bool) || !(bool)answer || !IsLoggedIn(guid))
                throw new ProtocolException(ErrorCodes.Internal, "Login to " + application
                    + " failed; nothing was downloaded. Check that the PLC is reachable and its gateway is running.");
        }

        bool IsLoggedIn(Guid guid)
        {
            var app = ApplicationOf(guid);
            var loggedIn = app == null ? null : Prop(OnlineApplicationType, app, "IsLoggedIn");
            return loggedIn is bool && (bool)loggedIn;
        }

        // The active application, which must be logged in.
        Guid LoggedInActiveApplication()
        {
            var guid = ActiveApplication();
            if (guid == Guid.Empty)
                throw new ProtocolException(ErrorCodes.BadParams, "the project has no active application");
            if (!IsLoggedIn(guid))
                throw new ProtocolException(ErrorCodes.BadParams, "Not connected. Run 'cts connect' first.");
            return guid;
        }

        public Dictionary<string, object> CreateBootApplication()
        {
            string raw; bool readable;
            DenyConfig(out raw, out readable);
            DenyRules.Require(raw, readable, DenyRules.CreateBootApp);
            var guid = LoggedInActiveApplication();
            var helper = FindType("_3S.CoDeSys.OnlineCommands.OnlineCommandHelper");
            var can = NeedMethod(helper, "CanCreateBootApplication", new[] { typeof(Guid) }, "OnlineCommandHelper.CanCreateBootApplication is not present in this IDE");
            var application = NameOf(ReadMeta(ProjectHandle(), guid));
            if (!(bool)can.Invoke(null, new object[] { guid }))
                throw new ProtocolException(ErrorCodes.BadParams, "The IDE cannot create a boot application for " + application
                    + " now: Online -> Create boot application is not available (does the device support one?).");
            var create = NeedMethod(FindType("_3S.CoDeSys.Core.Online.IOnlineApplication3"), "CreateBootProject", Type.EmptyTypes, "IOnlineApplication3.CreateBootProject is not present in this IDE");
            try { create.Invoke(ApplicationOf(guid), null); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "Create boot application: " + Invocation.Cause(e).Message); }
            return new Dictionary<string, object>
            {
                { "state", "boot_application_created" },
                { "application", application },
                { "application_state", ApplicationStateOf(guid) },
            };
        }

        public Dictionary<string, object> ResetApplication(string kind, bool force)
        {
            var option = ResetKinds.Option(kind, force);
            string raw; bool readable;
            DenyConfig(out raw, out readable);
            DenyRules.Require(raw, readable, ResetKinds.KeyOf(option));
            var guid = LoggedInActiveApplication();
            var helper = FindType("_3S.CoDeSys.OnlineCommands.OnlineCommandHelper");
            var can = NeedMethod(helper, "CanReset", new[] { typeof(Guid) }, "OnlineCommandHelper.CanReset is not present in this IDE");
            var application = NameOf(ReadMeta(ProjectHandle(), guid));
            if (!(bool)can.Invoke(null, new object[] { guid }))
                throw new ProtocolException(ErrorCodes.BadParams, "The IDE cannot reset " + application + " now: Online -> Reset is not available.");
            var resetOption = FindType("_3S.CoDeSys.Core.Online.ResetOption");
            var reset = NeedMethod(OnlineApplicationType, "Reset", new[] { resetOption }, "IOnlineApplication.Reset is not present in this IDE");
            try { reset.Invoke(ApplicationOf(guid), new[] { Enum.ToObject(resetOption, option) }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "Reset: " + Invocation.Cause(e).Message); }
            var result = new Dictionary<string, object>
            {
                { "state", "reset" },
                { "kind", ResetKinds.NameOf(option) },
                { "application", application },
            };
            // An origin reset leaves nothing on the PLC to have a state.
            try { result["application_state"] = ApplicationStateOf(guid); }
            catch (Exception e) { result["application_state_error"] = Invocation.Cause(e).Message; }
            return result;
        }

        public Dictionary<string, object> ApplicationChecksums()
        {
            RequireKey(AppChecksums.DenyKey);
            var guid = LoggedInActiveApplication();
            var models = FindType("_3S.CoDeSys.Core.LanguageModel.ILanguageModelManager");
            var ids = new object[] { guid, Guid.Empty, Guid.Empty };
            NeedMethod(models, "GetCompiledIds", new[] { typeof(Guid), typeof(Guid).MakeByRefType(), typeof(Guid).MakeByRefType() },
                "ILanguageModelManager.GetCompiledIds is not present in this IDE").Invoke(SystemInstance(models.FullName), ids);
            var app = ApplicationOf(guid);
            return AppChecksums.Compare(NameOf(ReadMeta(ProjectHandle(), guid)),
                AppChecksums.OfId((Guid)Prop(OnlineApplicationType, app, "CodeId")),
                AppChecksums.OfId((Guid)Prop(OnlineApplicationType, app, "DataId")),
                AppChecksums.OfId((Guid)ids[1]),
                AppChecksums.OfId((Guid)ids[2]));
        }

        string ApplicationStateOf(Guid guid)
        {
            return Convert.ToString(Prop(OnlineApplicationType, ApplicationOf(guid), "ApplicationState")).ToLowerInvariant();
        }

        //: Said when a logout did not end the session: a session the IDE's own
        //: UI owns can survive it, and the user has to end it there.
        const string StillOnline = "The IDE is still online with the PLC; the session was not ended. "
            + "Log out in CODESYS: Online -> Logout, then repeat the command.";

        // Every logged-in application, not just the active one: any of them
        // online makes the project refuse edits, so `cts disconnect` ends them all
        // and says so only once none is left.  *only* ends that application's
        // session alone (test.app logs its test application out).
        public Dictionary<string, object> Logout(string application)
        {
            var only = application.Length == 0 ? Guid.Empty : ParseObjectGuid(application);
            string raw; bool readable;
            DenyConfig(out raw, out readable);
            DenyRules.Require(raw, readable, DenyRules.Disconnect);
            var applications = only == Guid.Empty ? LoggedInApplications() : IsLoggedIn(only) ? new[] { ApplicationOf(only) } : new object[0];
            var logout = NeedMethod(OnlineApplicationType, "Logout", Type.EmptyTypes, "IOnlineApplication.Logout is not present in this IDE");
            var errors = new List<string>();
            foreach (var app in applications)
            {
                try { logout.Invoke(app, null); }
                catch (Exception e) { errors.Add(Invocation.Cause(e).Message); }
            }
            if (only == Guid.Empty ? LoggedInApplications().Length > 0 : IsLoggedIn(only))
                throw new ProtocolException(ErrorCodes.Internal, StillOnline + (errors.Count > 0 ? " (" + string.Join("; ", errors) + ")" : ""));
            var result = new Dictionary<string, object>
            {
                { "state", "disconnected" },
                { "was_connected", applications.Length > 0 },
                { "online_after", false },
            };
            if (applications.Length == 0)
                result["note"] = "No live online session was found: nothing to disconnect. The IDE was already offline.";
            return result;
        }

        public Dictionary<string, object> ActivateApplication(string application)
        {
            var guid = ParseObjectGuid(application);
            var handle = ProjectHandle();
            var meta = ReadMeta(handle, guid);
            if (!Prop(_metaObjectIface, meta, "Object").GetType().GetInterfaces().Any(i => i.Name == "IApplicationObject"))
                throw new ProtocolException(ErrorCodes.BadParams, NameOf(meta) + " is not an application");
            var previous = ActiveApplication();
            _projectIface.GetProperty("ActiveApplication").SetValue(OpenProject(), guid, null);
            return new Dictionary<string, object>
            {
                { "application", NameOf(meta) },
                { "previous", previous == Guid.Empty ? null : NameOf(ReadMeta(handle, previous)) },
            };
        }
    }
}
