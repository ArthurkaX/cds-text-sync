using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts plc`: the PLC the active application's device points at -- what it
    // runs, and its files -- without a login: each command connects for its run.
    internal static class PlcCommand
    {
        const string Offline = " Works with the IDE offline: it connects to the device for the command and leaves a login as it was.";

        internal static IList<CliCommand> Commands => new[]
        {
            new CliCommand
            {
                Name = "plc", Sub = "info",
                Summary = "Show the PLC's runtime and the applications it holds",
                Description = "The runtime version, the device and its node name, and each application on the PLC with its state "
                    + "and the project it was downloaded from." + Offline,
                Seconds = 90,
                Execute = call => call.Call("plc.info", new Dictionary<string, object>()),
                Build = Info,
            },
            new CliCommand
            {
                Name = "plc", Sub = "ls",
                Summary = "List a directory on the PLC",
                Description = "The entries of one directory on the PLC, its root by default: directories end in '/', files show "
                    + "their size and last write time (UTC)." + Offline + "\n\n"
                    + "  cts plc ls PlcLogic/Application",
                Arguments = "[PATH]", ArgumentLimit = 1,
                Seconds = 90,
                Execute = call => call.Call("plc.files", new Dictionary<string, object> { { "path", Arguments(call, 0)[0] ?? "" } }),
                Build = Listing,
            },
            new CliCommand
            {
                Name = "plc", Sub = "get",
                Summary = "Copy a file from the PLC to this PC",
                Description = "Copies FILE from the PLC into the current folder, or to --out (a file, or a folder to put it in), "
                    + "then checks the copy against the CRC32 the PLC gives for its file." + Offline + "\n\n"
                    + "  cts plc get PlcLogic/Application/Application.crc --out C:/Temp",
                Arguments = "FILE", ArgumentLimit = 1,
                Seconds = 330,
                Options = new[] { CliOption.Text("--out", "output", "PATH", "The file to write, or the folder to put it in (default: the current folder)") },
                Execute = Get,
                Build = data => Checked(new Answer().Add("file", Value(data, "file")).Add("saved_to", Value(data, "saved_to")).Add("size", Value(data, "size")), data),
            },
            new CliCommand
            {
                Name = "plc", Sub = "put",
                Summary = "Copy a file of this PC to the PLC",
                Description = "Writes SRC to DEST on the PLC (default: its name in the PLC's root), replacing a file there and "
                    + "making missing directories, then checks it against the CRC32 the PLC gives for it. The deny list key is "
                    + "plc_upload, denied by default." + Offline + "\n\n"
                    + "  cts plc put recipe.csv PlcLogic/recipes/recipe.csv",
                Arguments = "SRC [DEST]", ArgumentLimit = 2,
                Seconds = 330,
                Execute = call =>
                {
                    var given = Arguments(call, 1);
                    return call.Call("plc.upload", new Dictionary<string, object> { { "src", Path.GetFullPath(given[0]) }, { "dest", given[1] ?? "" } });
                },
                Build = data => Checked(new Answer().Add("destination", Value(data, "destination")).Add("size", Value(data, "size")), data),
            },
            new CliCommand
            {
                Name = "plc", Sub = "rm",
                Summary = "Remove a file or a directory from the PLC",
                Description = "Removes PATH from the PLC: a file, or an empty directory; --recursive removes a directory with what "
                    + "it holds. The deny list key is plc_upload, denied by default." + Offline,
                Options = new[] { CliOption.Switch("--recursive", "recursive", "Remove a directory with what it holds") },
                Arguments = "PATH", ArgumentLimit = 1,
                Seconds = 90,
                Execute = call => call.Call("plc.remove", new Dictionary<string, object> { { "path", Arguments(call, 1)[0] }, { "recursive", call.Options.Params.ContainsKey("recursive") } }),
                Build = data => new Answer().Add("removed", Value(data, "removed")).Add("directory", Value(data, "is_directory")).Add("entries", Value(data, "entries")),
            },
            new CliCommand
            {
                Name = "plc", Sub = "mkdir",
                Summary = "Make a directory on the PLC",
                Description = "Makes the directory PATH on the PLC. The deny list key is plc_upload, denied by default." + Offline,
                Arguments = "PATH", ArgumentLimit = 1,
                Seconds = 90,
                Execute = call => call.Call("plc.mkdir", new Dictionary<string, object> { { "path", Arguments(call, 1)[0] } }),
                Build = data => new Answer().Add("created", Value(data, "created")),
            },
            new CliCommand
            {
                Name = "plc", Sub = "mv",
                Summary = "Move or rename a file or a directory on the PLC",
                Description = "Gives FROM the path TO on the PLC. The deny list key is plc_upload, denied by default." + Offline,
                Arguments = "FROM TO", ArgumentLimit = 2,
                Seconds = 90,
                Execute = call =>
                {
                    var given = Arguments(call, 2);
                    return call.Call("plc.move", new Dictionary<string, object> { { "from", given[0] }, { "to", given[1] } });
                },
                Build = data => new Answer().Add("from", Value(data, "from")).Add("to", Value(data, "to")).Add("directory", Value(data, "is_directory")),
            },
        };

        // The command's arguments, null for an optional one not given; fewer
        // than `needed` is a usage error (more, the parser refuses).
        static string[] Arguments(CliCall call, int needed)
        {
            var given = call.Options.Arguments;
            if (given.Count < needed)
                throw new CliFailure("plc-" + call.Command.Sub, "usage", "expected " + call.Command.Arguments, "cts plc " + call.Command.Sub + " --help", 2);
            return Enumerable.Range(0, call.Command.ArgumentLimit).Select(i => i < given.Count ? given[i] : null).ToArray();
        }

        static IDictionary<string, object> Get(CliCall call)
        {
            var file = Arguments(call, 1)[0];
            var output = Path.GetFullPath(call.Options.Text("output", "."));
            if (Directory.Exists(output)) output = Path.Combine(output, file.Replace('\\', '/').TrimEnd('/').Split('/').Last());
            return call.Call("plc.fetch", new Dictionary<string, object> { { "file", file }, { "output", output } });
        }

        static Answer Checked(Answer answer, IDictionary<string, object> data)
        {
            if (data.ContainsKey("crc32")) return answer.Add("crc32", data["crc32"]);
            return answer.Add("crc32", "unchecked").Detail("unchecked: " + Value(data, "unchecked"));
        }

        static Answer Info(IDictionary<string, object> data)
        {
            var applications = Items(data, "applications").OfType<IDictionary<string, object>>().ToList();
            var answer = new Answer().Add("runtime", Value(data, "runtime")).Add("device", Value(data, "device"))
                .Add("node", Value(data, "node")).Add("applications", applications.Count);
            foreach (var application in applications)
                answer.Detail(Value(application, "name") + " " + Value(application, "state")
                    + (application.ContainsKey("project") ? ", from project " + Value(application, "project") + ", changed " + Value(application, "last_change") : "")
                    + (application.ContainsKey("compiler") ? ", compiler " + Value(application, "compiler") : ""));
            return answer.Whole();
        }

        static Answer Listing(IDictionary<string, object> data)
        {
            var files = Items(data, "files").OfType<IDictionary<string, object>>()
                .OrderBy(f => !Equals(Value(f, "is_directory"), true)).ThenBy(f => Convert.ToString(Value(f, "name")), StringComparer.OrdinalIgnoreCase).ToList();
            var answer = new Answer().Add("path", Convert.ToString(Value(data, "path")).Length == 0 ? "." : Value(data, "path")).Add("count", files.Count);
            foreach (var file in files)
                answer.Detail(Equals(Value(file, "is_directory"), true)
                    ? Value(file, "name") + "/"
                    : string.Format(CultureInfo.InvariantCulture, "{0}  {1}  {2}", Value(file, "name"), Value(file, "size"),
                        Convert.ToString(Value(file, "last_write_time")).Replace('T', ' ').TrimEnd('Z')));
            return answer.Whole();
        }
    }
}
