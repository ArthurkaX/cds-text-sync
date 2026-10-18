using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using Cts.Agent;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    public static partial class CliCommands
    {
        // The commands that read and change the project, and answer the IDE's dialogs.
        static CliCommand[] ProjectCommands => new[]
        {
            new CliCommand
            {
                Name = "project-tree",
                Summary = "Show the CODESYS project tree",
                Description = "The IDE's object tree. The answer lists every object that holds others, by the path --folder and project-view use, with how many objects are under it; --json or --pretty shows the whole tree.",
                TimeoutKey = "project_tree",
                Options = new[] { CliOption.Int("--depth", "depth", "Tree depth, 0 = unlimited (default: 0)") },
                Execute = Agent("project.tree"),
                Build = data =>
                {
                    var answer = new Answer()
                        .Add("children", data.ContainsKey("children") ? (object)Count(data["children"]) : null)
                        .Add("name", Value(data, "name") as string == "" ? null : Value(data, "name"));
                    foreach (var line in Containers(data, "")) answer.Detail(line);
                    return answer;
                },
            },
            new CliCommand
            {
                Name = "project",
                Sub = "close",
                Summary = "Close the current project in CODESYS",
                Description = "Closes the project. The agent refuses while it is online or has unsaved changes.",
                TimeoutKey = "project_close",
                Execute = Agent("project.close"),
                Build = data => new Answer().Add("closed", Value(data, "closed")),
            },
            new CliCommand
            {
                Name = "project",
                Sub = "list",
                Summary = "List all open projects in CODESYS",
                Description = "Lists all open projects in CODESYS.",
                TimeoutKey = "project_list",
                Execute = Agent("project.list"),
                Build = data =>
                {
                    var projects = Items(data, "projects").OfType<IDictionary<string, object>>().ToList();
                    var answer = new Answer().Add("count", Value(data, "count") ?? projects.Count);
                    foreach (var project in projects)
                    {
                        var path = Convert.ToString(Value(project, "path"), CultureInfo.InvariantCulture) ?? "";
                        answer.Detail(path + (Equals(Value(project, "primary"), true) ? " (primary)" : ""));
                    }
                    return answer;
                },
            },
            new CliCommand
            {
                Name = "project",
                Sub = "list-devices",
                Summary = "List the project's devices and their applications",
                Description = "Lists the project's devices with the description each one is (type, id, version: what "
                    + "`cts project change-device` takes), their applications and online state; --device keeps the devices "
                    + "whose name contains it.",
                TimeoutKey = "list_devices",
                Options = new[] { CliOption.Text("--device", "device", "NAME", "Device name filter") },
                Execute = Agent("project.devices"),
                Build = Devices,
            },
            new CliCommand
            {
                Name = "project",
                Sub = "device-types",
                Summary = "List the device descriptions installed in this IDE",
                Description = "Lists the device descriptions CODESYS has installed (Tools > Device Repository), each with the "
                    + "type, id and version `cts project change-device` takes. --filter keeps those whose name, vendor or id "
                    + "contains it.\n\n"
                    + "  cts project device-types --filter \"Control for Linux\"",
                Seconds = 60,
                Options = new[] { CliOption.Text("--filter", "filter", "TEXT", "Part of the name, vendor or id") },
                Execute = Agent("project.device_types"),
                Build = data =>
                {
                    var answer = new Answer().Add("count", Value(data, "count"));
                    foreach (var device in Items(data, "devices").OfType<IDictionary<string, object>>())
                        answer.Detail("--type " + Value(device, "type") + " --id \"" + Value(device, "id") + "\" --version "
                            + Value(device, "version") + "  " + Value(device, "name") + " (" + Value(device, "vendor") + ")");
                    return answer;
                },
            },
            new CliCommand
            {
                Name = "project",
                Sub = "change-device",
                Summary = "Give a device another type or version (Update Device)",
                Description = "Does what the IDE's Update Device does: the device becomes the installed description named by "
                    + "--type, --id and --version (without --version: the highest one installed), and its parameters, the "
                    + "objects below it and its libraries follow the new description. Default device: the one above the active "
                    + "application; --device names another. Needs an offline project and does not save it: run cts sync "
                    + "--save to bring the changed objects to disk, then cts build. `cts project device-types` lists the "
                    + "installed descriptions, `cts project list-devices` what each device is now.\n\n"
                    + "  cts project change-device --type 4102 --id \"0000 0005\" --version 4.11.0.0",
                Seconds = 300,
                Options = new[]
                {
                    CliOption.Text("--device", "device", "NAME", "The device (default: the one above the active application)"),
                    CliOption.Int("--type", "type", "Device type number, as device-types lists it"),
                    CliOption.Text("--id", "id", "ID", "Device id, as device-types lists it"),
                    CliOption.Text("--version", "version", "VERSION", "Device version (default: the highest installed)"),
                },
                Execute = call =>
                {
                    if (!call.Options.Params.ContainsKey("type") || !call.Options.Params.ContainsKey("id"))
                        throw new CliFailure("project-change-device", "usage", "--type and --id are required",
                            "cts project device-types", 2);
                    return call.Call("project.change_device", new Dictionary<string, object>(call.Options.Params));
                },
                Build = data =>
                {
                    var before = Value(data, "before") as IDictionary<string, object>;
                    var after = Value(data, "after") as IDictionary<string, object>;
                    return new Answer()
                        .Add("device", Value(data, "device"))
                        .Add("version", after == null ? null : Value(after, "version"))
                        .Detail("was type " + Value(before, "type") + " id " + Value(before, "id") + " version " + Value(before, "version"))
                        .Detail("now " + Value(data, "name") + ": type " + Value(after, "type") + " id " + Value(after, "id") + " version " + Value(after, "version"))
                        .Detail("Next: cts sync --save");
                },
            },
            new CliCommand
            {
                Name = "scan",
                Summary = "List the PLCs the gateway finds on the network",
                Description = "What the device editor's Scan Network shows: every CODESYS runtime the gateway (default: "
                    + "Gateway-1) reaches, with its name, type and node address, and the IP that address stands for on this "
                    + "PC's network when one network fits (ip=, what `cts connect --ip` takes). Read-only: nothing logs in and the project does "
                    + "not change. Use it when `cts connect --ip` finds no PLC: the PLC may have another address on the "
                    + "gateway's network.",
                Seconds = 60,
                Options = new[] { CliOption.Text("--gateway", "gateway", "NAME", "Gateway name (default: Gateway-1)") },
                Execute = Agent("app.scan"),
                Build = data =>
                {
                    var answer = new Answer().Add("gateway", Value(data, "gateway")).Add("plcs", Value(data, "count"));
                    foreach (var plc in Items(data, "plcs").OfType<IDictionary<string, object>>())
                        answer.Detail(string.Join(" ", plc.Where(pair => pair.Key != "name").Select(pair => pair.Key + "=" + pair.Value)
                            .Prepend(Convert.ToString(Value(plc, "name"), CultureInfo.InvariantCulture))));
                    return answer;
                },
            },
            new CliCommand
            {
                Name = "project",
                Sub = "simulate",
                Summary = "Enable or disable simulation mode",
                Description = "Toggles simulation mode and saves the project. Needs an offline project.",
                TimeoutKey = "set_simulation_mode",
                Arguments = "on|off",
                Execute = call =>
                {
                    if (call.Options.Arguments.Count != 1 || (call.Options.Arguments[0] != "on" && call.Options.Arguments[0] != "off"))
                        throw new CliFailure("project-simulate", "usage", "expected on|off", "cts project simulate --help", 2);
                    return call.Call("project.simulation", new Dictionary<string, object> { { "enable", call.Options.Arguments[0] == "on" } });
                },
                Build = data => new Answer()
                    .Add("device", Value(data, "device"))
                    .Add("simulation", Value(data, "after"))
                    .Add("changed", !Equals(Value(data, "before"), Value(data, "after")))
                    .Add("saved", Value(data, "saved")),
            },
            new CliCommand
            {
                Name = "project",
                Sub = "set-credentials",
                Summary = "Set PLC login credentials for this IDE session",
                Description = "Sets credentials in IDE memory for later device login prompts; the password is never printed.",
                TimeoutKey = "set_credentials",
                Options = new[]
                {
                    CliOption.Needed("--username", "username", "U", "Username"),
                    CliOption.Text("--password", "password", "P", "Password"),
                },
                Execute = call => call.Call("project.credentials", new Dictionary<string, object>
                {
                    { "username", call.Options.Params["username"] },
                    { "password", call.Options.Params.TryGetValue("password", out var password) ? password : "" },
                }),
                Build = data => new Answer().Add("username", Value(data, "username")),
            },
            new CliCommand
            {
                Name = "dialog",
                Summary = "Read the modal IDE dialog, and answer it without a click",
                Description = "What is on screen right now: `ok dialog dialogs=0`, or the dialog the IDE waits on, the same line "
                    + "a refused command ends with:\n\n"
                    + "  ok dialog dialogs=1 id=3f9a1c02 title=CODESYS\n"
                    + "  blocked by a dialog [id 3f9a1c02]: CODESYS - The application changed since last download. What do\n"
                    + "  you want to do? - options: (*) Login with online change, ( ) Login with download, [ ] Update boot\n"
                    + "  application - buttons: [OK] [Cancel] [Details...]\n\n"
                    + "`cts dialog answer` chooses its options and presses a button. Both are answered by the agent, not the "
                    + "IDE's UI thread, so they work exactly when the IDE is blocked. The id is a short fingerprint of what the "
                    + "dialog says: the same dialog keeps it, and answer --id refuses when it has been replaced. cts never leaves "
                    + "this dialog behind itself (download, connect and build choose their online-change option); it comes from "
                    + "a person or CODESYS, and can always be answered by hand in the IDE too.",
                Seconds = 5,
                Execute = Agent("dialog.probe"),
                Build = data =>
                {
                    var dialogs = Dialogs.Of(data, "dialogs");
                    var first = Items(data, "dialogs").OfType<IDictionary<string, object>>().FirstOrDefault();
                    var answer = new Answer().Add("dialogs", dialogs.Count);
                    if (first != null) answer.Add("id", Value(first, "fingerprint")).Add("title", Value(first, "title"));
                    return dialogs.Count > 0 ? answer.Detail(ModalErrors.BlockLine(dialogs)) : answer;
                },
            },
            new CliCommand
            {
                Name = "dialog",
                Sub = "answer",
                Summary = "Choose the dialog's options and press one of its buttons",
                Description = "The agent reads the dialog again and checks every name against that read: a name that is not there "
                    + "or matches two controls, or an id that has changed, is refused with the dialog as it is now, and nothing "
                    + "is clicked. Case is ignored and the & of a mnemonic is optional (--press OK matches '&OK'). --choose "
                    + "selects a radio button or ticks a check box, --uncheck clears a check box, --press is the button that "
                    + "submits; the chosen options are read back before anything is pressed. A button that opens another dialog "
                    + "is handled: the answer says whether the dialog closed and which one replaced it. Exit 0 when it closed, "
                    + "1 when it is still open or the answer was refused.\n\n"
                    + "  cts dialog answer --choose \"Login without any change\" --press OK\n"
                    + "  cts dialog answer --id 3f9a1c02 --choose \"Update boot application\" --press OK",
                Options = new[]
                {
                    CliOption.Many("--choose", "choose", "OPTION", "Option to select (a radio) or tick (a check box); repeatable"),
                    CliOption.Many("--uncheck", "uncheck", "OPTION", "Check box to clear; repeatable (a radio cannot be cleared)"),
                    CliOption.Needed("--press", "press", "BUTTON", "the button to press, by its caption, e.g. OK or Cancel"),
                    CliOption.Text("--id", "id", "FINGERPRINT", "The id `cts dialog` printed; refused if the dialog on screen is no longer that one"),
                },
                Execute = Agent("dialog.answer"),
                Build = data =>
                {
                    var closed = Equals(Value(data, "closed"), true);
                    var pressed = Value(data, "pressed");
                    var answer = new Answer()
                        .Add("closed", closed)
                        .Add("pressed", pressed is string ? pressed : pressed == null ? null : string.Join(",", Items(data, "pressed")))
                        .Add("id", Value(data, "id"))
                        .Detail(Answered(data));
                    if (closed) return answer;
                    var next = Dialogs.Of(data, "next");
                    answer.Partial().Detail(Equals(Value(data, "covered"), true) ? Covered : StillOpen);
                    return next.Count > 0 ? answer.Detail(ModalErrors.BlockLine(next)) : answer;
                },
            },
            new CliCommand
            {
                Name = "plc-crc",
                Summary = "Compare the PLC code with the IDE and its recorded source",
                Description = "Reads app.crc and the download ref refs/cts/plc/<code id> in the sync folder.",
                Execute = PlcCrcCommand.Execute,
                Build = PlcCrcCommand.Build,
            },
            HeadlessCrcCommand.Command,
        };
    }
}
