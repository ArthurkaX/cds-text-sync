// The project's deny list, enforced by the agent for every gated method.
//
// The list is the `deny` of the sync folder's cds-text-sync.json: no file or
// no `deny` -> the defaults below, an entry matches by equality or by prefix,
// and a file that cannot be read fails closed because the user's deny list is
// then unknown.
using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    public static class DenyRules
    {
        //: The built-in deny list.
        public static readonly string[] DefaultDeny =
        {
            "reset_plc",
            "reset_plc --kind origin",
            "create_boot_app",
            "plc_upload",
        };

        //: Where the list lives and how durable that is, as `cts permissions`
        //: reports it.
        public const string StoredIn = "the sync folder's cds-text-sync.json, key 'deny'";
        public const string Persistence =
            "Tracked in the project's repository: every clone has it, a change shows in git "
            + "and takes effect on the next command. Without a sync folder the defaults apply. "
            + "A person changes it in the IDE (quick window, Settings, Permissions); no cts command does.";

        //: Every key a command answers to, with what it stands for, in the
        //: groups and the order the quick window lists them.
        public static readonly IList<PermissionKey> Catalog = new[]
        {
            Project("sync_import_text", "Write objects into the project"),
            Project("delete_pou", "Delete objects from the project"),
            Project("save_project", "Save the project"),
            Project("build", "Build the application"),
            Project("set_sync_folder", "Set the project's sync folder"),
            Project("set_simulation_mode", "Switch simulation on or off"),
            Project("change_device", "Change a device's type or version"),
            Project("project_open", "Open a project"),
            Project("project_close", "Close the project"),
            Plc(Connect, "Log in to the PLC"),
            Plc(Disconnect, "Log out of the PLC"),
            Plc(Download, "Download to the PLC"),
            Plc(StartPlc, "Start the application"),
            Plc(StopPlc, "Stop the application"),
            Plc(ResetKinds.DenyKey, "Reset the application (any kind)"),
            Plc(ResetKinds.OriginDenyKey, "Reset origin (erase all)"),
            Plc(CreateBootApp, "Create the boot application"),
            Plc(WriteVariable, "Write PLC variables"),
            Plc(RunTests, "Run the .test plans on the PLC"),
            Plc(SetCredentials, "Give the IDE the PLC login"),
            Files(PlcUpload, "Change the PLC's files (put, rm, mkdir, mv)"),
            Files(PlcFetch, "Fetch a file from the PLC"),
            Files(PlcFiles, "List the PLC's files and applications"),
            Files(PlcLog, "Read the PLC's runtime log"),
            Files(AppChecksums.DenyKey, "Read the PLC's code checksums"),
            Files(ReadLog, "Read the IDE's message log"),
        };

        static PermissionKey Project(string key, string what) { return new PermissionKey(key, what, "The project"); }
        static PermissionKey Plc(string key, string what) { return new PermissionKey(key, what, "The PLC"); }
        static PermissionKey Files(string key, string what) { return new PermissionKey(key, what, "PLC files and logs"); }

        //: Error code for a permission refusal, so the CLI can recognise it.
        public const string Forbidden = "forbidden";

        //: The key a PLC variable write answers to (`vars.write`).  Not one of
        //: KeyFor's: a variable write changes the PLC, not the project.
        public const string WriteVariable = "write_variable";

        //: The key `messages.read` answers to (`cts read-log`): a read, so not
        //: one of KeyFor's either.
        public const string ReadLog = "read_log";

        //: The key `plc.files` and `plc.info` answer to (`cts plc ls`, `cts plc info`): reads too.
        public const string PlcFiles = "plc_files";

        //: The keys the PLC's file changes (`plc.upload`, `plc.remove`,
        //: `plc.mkdir`, `plc.move`), `plc.fetch` and `plc.log`/`plc.loggers`
        //: answer to, the commands they serve (`cts plc put|rm|mkdir|mv`,
        //: `cts plc get`, `cts plc-log`).
        public const string PlcUpload = "plc_upload";
        public const string PlcFetch = "plc_fetch";
        public const string PlcLog = "plc_log";

        //: The keys `app.start`, `app.stop`, `app.bootapp` and `app.logout`
        //: answer to.
        public const string StartPlc = "start_plc";
        public const string StopPlc = "stop_plc";
        public const string CreateBootApp = "create_boot_app";
        public const string Disconnect = "disconnect_from_device";

        //: The key `test.run` (`cts verify --with-test`) and `test.app`
        //: (`cts test`) answer to; each step's own method answers to its key
        //: as well.
        public const string RunTests = "run_tests";

        //: The key `project.credentials` answers to (`cts project set-credentials`).
        public const string SetCredentials = "set_credentials";

        //: The key `app.login` answers to (`cts connect`), the device address
        //: it sets included.
        public const string Connect = "connect_to_device";

        //: The key `app.download` answers to (`cts download`), a start after it
        //: answers to StartPlc as well.
        public const string Download = "download";

        // The deny list governs commands, but the agent performs some of them
        // itself; this fixes which key each agent write method answers to, so a
        // client that routes a write through the agent cannot pick a weaker key
        // than the command it stands for.  A method with no entry is a bug here,
        // not a request, and is refused rather than silently allowed.
        public static string KeyFor(string agentMethod)
        {
            switch (agentMethod)
            {
                case "objects.delete": return "delete_pou";
                case "app.build": return "build";
                case "app.login": return Connect;
                case "project.save": return "save_project";
                case "project.syncfolder": return "set_sync_folder";
                case "project.simulation": return "set_simulation_mode";
                case "project.change_device": return "change_device";
                case "project.open": return "project_open";
                case "project.close": return "project_close";
                case "objects.rename":
                case "objects.move":
                case "objects.settext":
                case "objects.create":
                case "objects.import":
                case "objects.setfield":
                case "objects.listadd":
                case "objects.listremove":
                case "objects.replace":
                case "project.source": return "sync_import_text";
            }
            return null;
        }

        // Throws the refusal `Check` produced for the key `agentMethod` stands
        // for; a write handler calls this after the online check, before editing.
        public static void RequireWrite(string raw, bool readable, string agentMethod)
        {
            var key = KeyFor(agentMethod);
            if (key == null)
                throw new ProtocolException(ErrorCodes.Internal, "no deny key for " + agentMethod);
            Require(raw, readable, key);
        }

        // An unreadable config is a refusal, never a fallback to the defaults:
        // the defaults are not the user's deny list.
        const string Unreadable =
            "The sync folder's cds-text-sync.json is unreadable; refusing permission-gated "
            + "commands until it is fixed";

        // (allowed, reason) for one command.  `readable` is false when the
        // file exists but could not be read at all; `raw` is "" when there is
        // no file.
        public static bool Check(string raw, bool readable, string method, out string reason)
        {
            var deny = DenyList(raw, readable);
            if (deny == null)
            {
                reason = Unreadable;
                return false;
            }
            var by = BlockedBy(deny, method);
            reason = by == null ? ""
                : by == method ? "Forbidden by the deny list (deny list includes '" + method + "')"
                : "Forbidden by the deny list (pattern '" + by + "' matches '" + method + "')";
            if (by != null && method == ResetKinds.DenyKey && BlockedBy(deny, "download") == null)
                reason += "; cts download, which the list allows, also starts the application again from its initial values";
            return by == null;
        }

        // Throws the refusal `Check` produced; used by a handler before it edits.
        public static void Require(string raw, bool readable, string method)
        {
            string reason;
            if (!Check(raw, readable, method, out reason))
                throw new ProtocolException(Forbidden, reason);
        }

        // What `project.permissions` answers (`cts permissions`): the deny
        // list in force, where it lives, and `config_error` when the file cannot
        // be read -- the defaults shown are then not the user's, and every
        // gated command is refused.
        public static Dictionary<string, object> Describe(string raw, bool readable)
        {
            var deny = DenyList(raw, readable);
            var data = new Dictionary<string, object> { { "deny", new List<object>(deny ?? new List<string>(DefaultDeny)) } };
            data["stored_in"] = StoredIn;
            data["persistence"] = Persistence;
            if (deny == null)
                data["config_error"] = "cds-text-sync.json is unreadable; permission-gated "
                    + "commands are refused until it is fixed";
            return data;
        }

        // The deny list in force: the file's, or the defaults without one;
        // null when the file cannot be read (every gated command is refused).
        public static List<string> DenyList(string raw, bool readable)
        {
            if (!readable) return null;
            if (string.IsNullOrEmpty(raw)) return new List<string>(DefaultDeny);
            List<string> deny;
            return TryParseDeny(raw, out deny) ? deny : null;
        }

        // The entry of *deny* that refuses *key*: itself, or one it starts
        // with ("reset_plc" over "reset_plc --kind origin"); null when allowed.
        public static string BlockedBy(IEnumerable<string> deny, string key)
        {
            string prefix = null;
            foreach (var denied in deny)
            {
                if (denied == key) return denied;
                if (prefix == null && denied.Length > 0 && key.StartsWith(denied, StringComparison.Ordinal)) prefix = denied;
            }
            return prefix;
        }

        // The settings file *raw* (cds-text-sync.json, "" when there is none)
        // with *key* switched: denied when it was allowed, allowed when the
        // list names it.  A file without "deny" starts from the defaults, so
        // the list is explicit from then on.  Refused: a key no command
        // answers to, one another entry refuses as a prefix, and a file that
        // is not a settings object.
        public static string Toggle(string raw, string key)
        {
            var known = false;
            foreach (var entry in Catalog) known |= entry.Key == key;
            if (!known) throw new ProtocolException(ErrorCodes.BadParams, "no command answers to '" + key + "'");
            IDictionary<string, object> config = new Dictionary<string, object>();
            List<string> deny = new List<string>(DefaultDeny);
            if (!string.IsNullOrEmpty(raw))
            {
                object parsed;
                try { parsed = Json.Parse(raw); }
                catch (JsonException) { parsed = null; }
                config = parsed as IDictionary<string, object>;
                if (config == null || !TryParseDeny(raw, out deny))
                    throw new ProtocolException(ErrorCodes.BadParams, Unreadable);
            }
            var by = BlockedBy(deny, key);
            if (by == key) deny.RemoveAll(denied => denied == key);
            else if (by != null)
                throw new ProtocolException(ErrorCodes.BadParams, "'" + key + "' is refused by '" + by + "': allow that first");
            else deny.Add(key);
            config["deny"] = deny;
            return Json.Pretty(config) + "\n";
        }

        // The deny list from the settings JSON, or false when it is anything but
        // a JSON object whose "deny" (when it has one) is an array of entries.
        static bool TryParseDeny(string raw, out List<string> deny)
        {
            deny = null;
            object parsed;
            try { parsed = Json.Parse(raw); }
            catch (JsonException) { return false; }
            var config = parsed as IDictionary<string, object>;
            if (config == null) return false;
            object value;
            // A settings file without "deny" keeps the default deny list.
            if (!config.TryGetValue("deny", out value)) { deny = new List<string>(DefaultDeny); return true; }
            if (value == null) return false;
            var list = value as IEnumerable<object>;
            if (list == null) return false;
            deny = new List<string>();
            foreach (var item in list) deny.Add(Convert.ToString(item));
            return true;
        }
    }

    //: One key of DenyRules.Catalog.
    public sealed class PermissionKey
    {
        public PermissionKey(string key, string what, string group)
        {
            Key = key;
            What = what;
            Group = group;
        }

        public string Key { get; private set; }
        //: What the key stands for, as the quick window names it.
        public string What { get; private set; }
        public string Group { get; private set; }
    }
}
