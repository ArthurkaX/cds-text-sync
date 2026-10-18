using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace Cts.Agent
{
    // The widget's settings page: the sync folder, the compare and merge programs, the key, this PC's role and the permissions.
    public static partial class WidgetMenu
    {
        // The settings page: the sync folder, chosen in a folder dialog, or,
        // while this machine has none for the project, the folder *suggested*
        // for it (ProjectInfo.Suggested): typed, with the suggestion already in
        // the line (or picked in the dialog the line opens), for a project
        // that has no id yet, and picked in the dialog for one that has
        // (*known*: its folder is a clone somewhere); the compare and the
        // merge program from *tools* (the JSON of `cts tool --json`), this
        // window's key from *config* (the JSON of `cts config show --json`),
        // typed into the user's defaults.json.  With a sync folder, this PC's
        // role and the permissions follow, the deny list in force (*deny*,
        // null when the file cannot be read).
        public static List<WidgetItem> Settings(string syncFolder, string suggested, bool known, string tools, string config,
            IList<string> deny, bool owner)
        {
            var folder = new WidgetItem { Key = '1', Label = "Sync folder", Args = new[] { "set-sync-folder" } };
            if (syncFolder.Length > 0)
            {
                folder.Picks = "The sync folder: the git repository the project's files are kept in";
                folder.Initial = syncFolder;
                folder.Hint = "cts set-sync-folder";
            }
            else if (known)
            {
                folder.Picks = "Where is this project's repository? Pick your clone of it";
                folder.Initial = suggested;
                folder.Hint = "Enter: pick your clone";
            }
            else
            {
                folder.Asks = "sync folder, ./ is beside the project file";
                folder.Picks = "Where should the project's files be kept? Pick or make a folder";
                folder.Initial = suggested;
                folder.Hint = "not set";
            }
            var items = new List<WidgetItem> { folder };
            if (Field(ParsedOrNull(tools), "open") is IDictionary<string, object> opener) items.Add(Opener(opener, (char)('1' + items.Count)));
            var settings = Field(ParsedOrNull(config), "settings");
            var key = Field(settings, "quick_key");
            if (key != null)
            {
                var text = Text(key.ContainsKey("value") ? key["value"] : null);
                items.Add(new WidgetItem
                {
                    Key = (char)('1' + items.Count),
                    Label = "Quick window key",
                    Args = new[] { "config", "set", "quick_key" },
                    Asks = "quick window key, e.g. Ctrl+Shift+Q",
                    Initial = text,
                    Hint = text + " · " + Convert.ToString(key.ContainsKey("source") ? key["source"] : "", CultureInfo.InvariantCulture),
                });
            }
            if (syncFolder.Length == 0) return items;
            items.Add(Role(syncFolder, owner, (char)('1' + items.Count)));
            items.Add(new WidgetItem
            {
                Key = (char)('1' + items.Count),
                Label = "Permissions",
                Opens = WidgetPage.Permissions,
                Disabled = deny != null ? null : "cds-text-sync.json is unreadable: fix the file",
                Hint = deny != null
                    ? string.Format(CultureInfo.InvariantCulture, "{0} of {1} blocked",
                        DenyRules.Catalog.Count(entry => DenyRules.BlockedBy(deny, entry.Key) != null),
                        DenyRules.Catalog.Count)
                    : "unreadable",
            });
            return items;
        }

        // The permissions page: a row per group of the catalog, how many of
        // its keys *deny* blocks, opening the group's check boxes.
        public static List<WidgetItem> PermissionGroups(IList<string> deny)
        {
            return DenyRules.Catalog.GroupBy(entry => entry.Group).Select((group, i) =>
            {
                var boxes = Permissions(deny, group);
                return new WidgetItem
                {
                    Key = (char)('1' + i),
                    Label = group.Key,
                    Opens = WidgetPage.Permissions,
                    Choices = boxes,
                    Hint = string.Format(CultureInfo.InvariantCulture, "{0} of {1} blocked", boxes.Count(box => box.Current), boxes.Count),
                };
            }).ToList();
        }

        // A group's check boxes: each key, ticked when *deny* blocks it.  A
        // key another entry refuses as a prefix ("reset_plc" over its origin
        // kind) is ticked and greyed with that entry.
        static List<WidgetItem> Permissions(IList<string> deny, IEnumerable<PermissionKey> keys)
        {
            return keys.Select((entry, i) =>
            {
                var by = DenyRules.BlockedBy(deny, entry.Key);
                return new WidgetItem
                {
                    Key = i < 9 ? (char)('1' + i) : '\0',
                    Label = entry.What,
                    Toggles = entry.Key,
                    Current = by != null,
                    Disabled = by != null && by != entry.Key ? "blocked by " + by + ": allow that first" : null,
                    Hint = entry.Key,
                };
            }).ToList();
        }

        // The open program's row: what it uses and whether the user chose it,
        // and the list it opens -- auto, then each program installed (and a
        // chosen one that is not), the one in force marked.
        static WidgetItem Opener(IDictionary<string, object> tool, char key)
        {
            var value = tool.ContainsKey("value") ? tool["value"] as string : null;
            var uses = tool.ContainsKey("uses") ? tool["uses"] as string : null;
            var names = ((tool.ContainsKey("installed") ? tool["installed"] as IList<object> : null) ?? new List<object>())
                .Select(name => Convert.ToString(name, CultureInfo.InvariantCulture)).ToList();
            if (value != null && !names.Contains(value)) names.Add(value);
            var choices = new[] { "auto" }.Concat(names).Select((name, i) =>
            {
                var here = name == (value ?? "auto");
                return new WidgetItem
                {
                    Key = i < 9 ? (char)('1' + i) : '\0',
                    Label = name == "auto" ? "Whatever is installed" + (value == null && uses != null ? " (" + Program(uses) + ")" : "") : Program(name),
                    Args = new[] { "tool", "open", name },
                    Disabled = here ? "in use already" : null,
                    Hint = here ? "current" : "cts tool open " + name,
                    Current = here,
                };
            }).ToList();
            return new WidgetItem
            {
                Key = key,
                Label = "Open the folder in",
                Opens = WidgetPage.Choices,
                Choices = choices,
                Hint = (uses != null ? Program(uses) : "none installed") + " · " + (value != null ? "chosen" : "auto"),
            };
        }

        // This PC's part in the team: the owner publishes the project file
        // and keeps its libraries, a colleague takes the published file.
        static WidgetItem Role(string syncFolder, bool owner, char key)
        {
            var choices = new[] { true, false }.Select((ownerRow, i) => new WidgetItem
            {
                Key = (char)('1' + i),
                Label = ownerRow ? "Owner: publishes the project file, keeps its libraries and settings (one PC per team)" : "Colleague: takes the published project file",
                Args = new[] { "set-sync-folder", syncFolder, ownerRow ? "--owner" : "--colleague" },
                Disabled = ownerRow == owner ? "in use already" : null,
                Hint = ownerRow == owner ? "current" : "cts set-sync-folder --" + (ownerRow ? "owner" : "colleague"),
                Current = ownerRow == owner,
            }).ToList();
            return new WidgetItem { Key = key, Label = "This PC", Opens = WidgetPage.Choices, Choices = choices, Hint = owner ? "owner" : "colleague" };
        }

        static string Program(string name)
        {
            switch (name)
            {
                case "desktop": return "GitHub Desktop";
                case "winmerge": return "WinMerge";
                case "kdiff3": return "KDiff3";
                case "vscode": return "VS Code";
                case "zed": return "Zed";
                case "explorer": return "Explorer";
                default:
                    // A program's full path: its file name.
                    var file = name.Substring(name.LastIndexOfAny(new[] { '\\', '/' }) + 1);
                    var dot = file.LastIndexOf('.');
                    return dot > 0 ? file.Substring(0, dot) : file;
            }
        }

        static object ParsedOrNull(string json)
        {
            try { return Json.Parse(json ?? ""); }
            catch (JsonException) { return null; }
        }

        // The object *name* of the JSON object *value*, or null.
        static IDictionary<string, object> Field(object value, string name)
        {
            var map = value as IDictionary<string, object>;
            return map != null && map.ContainsKey(name) ? map[name] as IDictionary<string, object> : null;
        }

        static string Text(object value)
        {
            if (value == null) return "";
            if (value is bool) return (bool)value ? "true" : "false";
            return Convert.ToString(value, CultureInfo.InvariantCulture);
        }
    }
}
