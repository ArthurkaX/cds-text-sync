
namespace Cts.Cli
{
    public static partial class CliCommands
    {
        // The commands that move code between the IDE and the sync folder.
        static CliCommand[] SyncCommands => new[]
        {
            new CliCommand
            {
                Name = "export",
                Summary = "Write the open project's IDE objects to the editable view",
                Description = "Exports the open project through the in-IDE agent and writes its files to the sync folder's view. When the IDE stamp matches the last export, answers from git. --full walks the IDE even if it reports no change. --force always walks the IDE. Use --full after project changes that may not raise object events, such as project settings, project information, library-manager data, or device parameters.",
                TimeoutKey = "sync_export_text",
                Options = new[]
                {
                    CliOption.Text("--sync-folder", "sync_folder", "PATH", "The sync folder (default: the one the open project names); must match the project's folder"),
                    CliOption.Switch("--force", "force", "Save the disk view on refs/cts/overwritten, then replace edited files and remove object files the IDE no longer writes"),
                    CliOption.Switch("--full", "full", "Walk the IDE even if it reports no change"),
                    CliOption.Switch("--tool", "conflict_tool", "Then merge each object the disk changed too; one whose edits overlap opens side by side in the merge program, the IDE's text on the right, and what is saved there goes to both"),
                    CliOption.Many("--take", "take", "[KEY=]SIDE", "Then merge each object the disk changed too; one whose edits overlap takes the disk's or the IDE's text, and that text goes to both: disk or ide for every one, KEY=disk|ide for one (KEY: its file, or the key its conflict names)"),
                },
                Execute = ExportCommand.Execute,
                Build = ExportCommand.Build,
            },
            new CliCommand
            {
                Name = "compare",
                Summary = "Compare the editable view with the open IDE project",
                Description = "Compares the working view with the IDE's current export and uses refs/cts/base to identify which side changed. --all includes unchanged view files. --tool opens a file comparison; --against names a ref for that comparison. The first line's ide= says how the IDE side was read: exported (read from the IDE now), cached (no IDE object changed since the last read, so that read was reused: it is exact), unchanged (nothing changed in the IDE since the last sync); --full reads the IDE again in any case.",
                TimeoutKey = "sync_compare_text",
                Options = new[]
                {
                    CliOption.Text("--sync-folder", "sync_folder", "PATH", "The sync folder (default: the one the open project names)"),
                    CliOption.Switch("--all", "all", "Include unchanged files"),
                    CliOption.Switch("--tool", "tool", "Open the configured comparison tool"),
                    CliOption.Switch("--full", "full", "Read the whole IDE instead of reusing the previous compare's view"),
                    CliOption.Text("--against", "against", "REF", "Compare the IDE snapshot with a branch, tag, or commit"),
                },
                Execute = CompareCommand.Execute,
                Build = CompareCommand.Build,
            },
            new CliCommand
            {
                Name = "import",
                Summary = "Carry the editable text view into the open IDE project",
                Description = "Applies the shared compare plan. --dry-run shows that plan without writing. --force keeps overwritten IDE text on refs/cts/overwritten before replacing it.",
                TimeoutKey = "sync_compare_text",
                Options = new[]
                {
                    CliOption.Text("--sync-folder", "sync_folder", "PATH", "Sync folder (must match the open project)"),
                    CliOption.Switch("--dry-run", "dry_run", "Show the import plan without writing"),
                    CliOption.Switch("--all", "all", "Include unchanged objects in the plan"),
                    CliOption.Switch("--save", "save", "Save the project after a successful import"),
                    CliOption.Switch("--force", "force", "Keep overwritten IDE text before carrying disk text"),
                    CliOption.Switch("--allow-unapplied", "allow_unapplied", "Acknowledge objects that could not be read back"),
                    CliOption.Switch("--tool", "conflict_tool", "An object whose IDE and disk edits overlap opens side by side in the merge program, the disk's text on the right; what is saved there goes to both"),
                    CliOption.Many("--take", "take", "[KEY=]SIDE", "An object both sides changed in the same lines takes the disk's or the IDE's text, and that text goes to both: disk or ide for every one, KEY=disk|ide for one (KEY: its file, or the key its conflict names)"),
                    CliOption.Many("--include-ignored", "include_ignored", "PATH", "A file of the view Git's ignore rules match that this import compares and carries like any other (repeatable)"),
                },
                Execute = ImportCommand.Execute,
                Build = ImportCommand.Build,
            },
            new CliCommand
            {
                Name = "sync",
                Summary = "Carry the IDE's edits into the folder and the folder's into the IDE",
                Description = "What cts compare lists goes where it is missing: an object the IDE changed is written to its file (text, XML or text list), one changed on disk is imported, and one both sides changed is merged. Edits that overlap are a conflict: --take chooses a side, for every one or one object, --tool opens them in the merge program. --save saves the project after a successful sync that changed it.",
                TimeoutKey = "sync_compare_text",
                Options = new[]
                {
                    CliOption.Text("--sync-folder", "sync_folder", "PATH", "Sync folder (must match the open project)"),
                    CliOption.Switch("--save", "save", "Save the project after a successful sync"),
                    CliOption.Many("--take", "take", "[KEY=]SIDE", "An object both sides changed in the same lines takes the disk's or the IDE's text, and that text goes to both: disk or ide for every one, KEY=disk|ide for one (KEY: its file, or the key its conflict names)"),
                    CliOption.Switch("--tool", "conflict_tool", "An object whose IDE and disk edits overlap opens side by side in the merge program, the disk's text on the right; what is saved there goes to both"),
                },
                Execute = ImportCommand.Execute,
                Build = ImportCommand.Build,
            },
            new CliCommand
            {
                Name = "fmt",
                Arguments = "[NAME]",
                ArgumentLimit = 1,
                Summary = "Lay out the IDE's Structured Text",
                Description = "Align declaration groups, indent implementation blocks, put each statement on its own line and break IF conditions at their top-level AND/OR. It moves only whitespace between lines and statements: spacing inside a statement (x:=1) stays as written. NAME (or Parent.Name) picks one object, else every text object. Without --write this reports what would change; --json includes before and after texts; cts fmt NAME --write writes it into the IDE. Only the IDE changes: in a project with a sync folder, cts sync then writes the new layout into the files. It needs the IDE agent but no sync folder. --disk lays out the sync folder's .st files instead and needs no IDE; with --write only the files change, and cts import carries them into the IDE.",
                Seconds = 120,
                Options = new[]
                {
                    CliOption.Text("--guid", "guid", "GUID", "One object by its GUID"),
                    CliOption.Switch("--write", "write", "Write formatted text into the IDE (with --disk: into the files)"),
                    CliOption.Int("--if-timestamp", "if_timestamp", "With --guid: write only while the object's TimeStamp is the one a preview showed (not needed for a plain write)"),
                    CliOption.Switch("--disk", "disk", "Lay out the sync folder's files, not the IDE's text"),
                    CliOption.Text("--sync-folder", "sync_folder", "PATH", "With --disk: the sync folder (default: the one around the current folder, else the open project's)"),
                },
                LocalExecute = FmtCommand.Disk,
                LocalWhen = options => options.Params.ContainsKey("disk"),
                Execute = FmtCommand.Execute,
                Build = FmtCommand.Build,
            },
            new CliCommand
            {
                Name = "read-object",
                Arguments = "[NAME]",
                ArgumentLimit = 1,
                Summary = "Read one project object from the IDE",
                Description = "Read an object by name, path or GUID. --body renders the same .st or XML file cts export writes.",
                Options = new[]
                {
                    CliOption.Switch("--body", "body", "Return the exported object body"),
                    CliOption.Text("--body-file", "body_file", "PATH", "Write the body to a file"),
                    CliOption.Text("--path", "path", "PATH", "Object path in the IDE tree"),
                    CliOption.Text("--name", "name", "NAME", "Object name"),
                    CliOption.Text("--guid", "guid", "GUID", "Object GUID"),
                },
                Execute = ReadObjectCommand.Execute,
                Build = ReadObjectCommand.Build,
            },
            new CliCommand
            {
                Name = "agent",
                Sub = "list",
                Summary = "List the in-IDE agents on this machine, one per open IDE",
                Description = "Ask every cts-agent pipe on this machine for its hello and print one line per agent: pid, product and version, agent version, protocol, and the open project. An agent that does not answer is reported with its error. --timeout is the per-agent hello timeout (default: 3).",
                Seconds = 3,
                Discover = (host, options) => AgentChoice.Discover(host, options.Timeout ?? 3),
            },
            new CliCommand
            {
                Name = "set-sync-folder",
                Arguments = "[PATH]",
                ArgumentLimit = 1,
                Summary = "Choose the project's sync folder on this machine and make it a git repository root",
                Description = "The project carries an id (cts-project-id in Project Information), the same in every copy of the .project file; the sync folder names it in cds-text-sync.json, and this machine remembers the folder for it in %LOCALAPPDATA%\\cds-text-sync\\projects.json. A copy of the file opened anywhere finds its folder again; one opened from inside a clone of the project uses that clone. The folder becomes a git repository root: a folder without a repository gets `git init`, cts' .gitignore and .gitattributes, cds-text-sync.json and a first commit of those files; an existing repository root only gets what is missing, uncommitted. A folder inside another repository, not at its root, or one that belongs to another project, is refused and nothing is stored.",
                ArgumentHelp = "Absolute path, or ./path relative to the CODESYS project file. Omit to use the sync folder the project file lies in, else a <project>-cts folder beside it.",
                Options = new[]
                {
                    CliOption.Switch("--new-id", "new_id", "The project is a copy made for another plant: give it a new id and the folder as a repository of its own. A copied folder that still names the project, while this PC has the project's own folder elsewhere, takes the new id."),
                    CliOption.Switch("--owner", "owner", "Make this machine the project's owner, the one that publishes the project file (cts commit --publish) and changes its libraries. The machine that gives the project its id is its owner already; one owner per team."),
                    CliOption.Switch("--colleague", "colleague", "Make this machine a colleague's: it takes the published project file (cts project update), and its IDE's Library Manager stays off the disk. Without --owner or --colleague the machine keeps its role."),
                    CliOption.Switch("--save", "save", "Save the CODESYS project after giving it its id. This also saves any other pending IDE edits."),
                },
                Execute = SetSyncFolder.Execute,
                Build = SetSyncFolder.Build,
            },
        };
    }
}
