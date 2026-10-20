using System;
using System.Collections.Generic;
using System.IO;
using Cts.Agent;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts project new --path P`: a new empty project or library from the
    // installation's Templates\Empty.project, as CODESYS' own New Project
    // makes one (its Empty library template is that file saved as .library).
    public static class ProjectNewCommand
    {
        const string Verb = "project-new";

        public static readonly CliCommand Command = new CliCommand
        {
            Name = "project",
            Sub = "new",
            Summary = "Make a new empty project or library file",
            Description = "Writes PATH from Templates\\Empty.project of the newest CODESYS under Program Files (or --codesys): a .project "
                + "is an empty project, a .library an empty library, as CODESYS' New Project makes them. No IDE is needed; cts project open "
                + "then opens it, and cts lib add gives a library its Library Manager.",
            Options = new[]
            {
                CliOption.Needed("--path", "path", "P", "The new file, ending .project or .library"),
                CliOption.Text("--codesys", "codesys", "EXE", "CODESYS.exe whose template it takes (default: the newest installed)"),
            },
            LocalExecute = New,
            Build = data => new Answer().Add("created", Value(data, "created")).Add("kind", Value(data, "kind"))
                .Detail("template " + Value(data, "template"))
                .Detail("Next: cts project open --path " + ProcessArgs.Quote(Convert.ToString(Value(data, "created"))) + (Equals(Value(data, "kind"), "library")
                    ? "; a library to install needs Company, Title and Version in its Project Information" : "")),
        };

        static IDictionary<string, object> New(CliOptions options, IAgentHost host, string work)
        {
            var path = Path.GetFullPath(Path.Combine(work, Convert.ToString(options.Params["path"])));
            var extension = Path.GetExtension(path).ToLowerInvariant();
            if (extension != ".project" && extension != ".library")
                throw new CliFailure(Verb, "usage", "--path ends .project (a project) or .library (a library)", "cts project new --help", 2);
            if (File.Exists(path)) throw Refused(path + " exists already");
            var codesys = options.Params.TryGetValue("codesys", out var given) ? Path.GetFullPath(Convert.ToString(given))
                : ProjectOpenCommand.Newest(ProjectOpenCommand.Executables(ProjectOpenCommand.ProgramFiles()));
            if (codesys == null) throw Refused("no CODESYS.exe under Program Files; name it with --codesys");
            var template = Path.Combine(Path.GetDirectoryName(Path.GetDirectoryName(codesys)), "Templates", "Empty.project");
            if (!File.Exists(template)) throw Refused("no template at " + template);
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.Copy(template, path);
            return new Dictionary<string, object> { { "created", path }, { "kind", extension == ".library" ? "library" : "project" }, { "template", template } };
        }

        static CliFailure Refused(string message) => new CliFailure(Verb, "refused", message, "cts project new --help", 2);
    }
}
