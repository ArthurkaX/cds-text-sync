// `app.build`: compile the active application (`cts build`) with
// ILanguageModelManager.Compile, as the IDE's Build does, and answer the
// messages Compile leaves in the compiler category -- the ones the IDE's
// Messages view shows under "Build".  The category is the message storage's
// one whose TypeGuid is the build category the scripting API names.  The
// outcome is also kept in the agent's memory (`last_command` in
// `project.status`), for a CLI that stopped waiting.  The project is not
// saved; the deny list key is `build`.
//
// Compile leaves out every object no task calls.  With `all_objects` the
// IDE's check of every object of the application runs first
// (ILanguageModelManager15.CheckAllApplicationObjects, into the same
// category, so the category still ends with the compile's messages) and its
// messages are answered as `checked_messages`.  It costs about as much again
// as the compile, so it is asked for.
//
// A library project has no application: its build is the IDE's own command
// "Check all Pool Objects" (batch `project checkall`), which leaves its
// messages in the same category.  With `install` and no error message it then
// runs the IDE's "Save Project and Install into Library Repository" (batch
// `file saveandinstall`), so that also answers to `save_project`.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        // Written on the UI thread, read by `project.status`: one reference swap.
        volatile Dictionary<string, object> _lastBuild;

        public Dictionary<string, object> LastBuildRecord { get { return _lastBuild; } }

        public Dictionary<string, object> Build(bool install, bool allObjects)
        {
            RequirePermission("app.build");
            var project = OpenProject();
            var handle = Handle(project);
            var path = Convert.ToString(Prop(_projectIface, project, "Path"));
            var application = ActiveApplication();
            var library = application == Guid.Empty && ProjectFiles.IsLibrary(path);
            if (application == Guid.Empty && !library)
                throw new ProtocolException(ErrorCodes.BadParams, "No active application found to build.");
            if (install && !library)
                throw new ProtocolException(ErrorCodes.BadParams, "install is for a library project; this project has an application.");
            if (allObjects && library)
                throw new ProtocolException(ErrorCodes.BadParams, "all_objects is for an application; a library's check already reads every object.");
            if (install) RequirePermission("project.save");
            var storageIface = FindType("_3S.CoDeSys.Core.Messages.IMessageStorage");
            var storage = SystemInstance(storageIface.FullName);
            // A freshly opened IDE registers the build category with its first
            // compile: until then there is nothing to clear.
            var categoryIface = FindType("_3S.CoDeSys.Core.Messages.IMessageCategory");
            var read = NeedMethod(storageIface, "GetMessages", new[] { categoryIface }, "IMessageStorage.GetMessages is not present in this IDE");
            var category = CompilerCategory(storageIface, storage);
            var objects = new Dictionary<Guid, object>();

            var timer = Stopwatch.StartNew();
            List<Dictionary<string, object>> checkedAll = null;
            if (allObjects)
            {
                CheckAllObjects(application);
                category = category ?? CompilerCategory(storageIface, storage);
                checkedAll = category == null ? new List<Dictionary<string, object>>() : ReadMessages(handle, read, storage, category, objects);
            }
            if (category != null) storageIface.GetMethod("ClearMessages").Invoke(storage, new[] { category });
            // The check has no verdict of its own: its messages are the verdict.
            var compiled = library ? RunBatchCommand("project checkall") : Compile(application);
            var elapsed = timer.Elapsed.TotalSeconds;

            category = category ?? CompilerCategory(storageIface, storage);
            if (category == null)
                throw new ProtocolException(ErrorCodes.Unavailable, "the IDE has no build message category after the compile");
            var messages = ReadMessages(handle, read, storage, category, objects);
            var answer = new Dictionary<string, object>
            {
                { "application", library ? ProjectFiles.DisplayName(path) : NameOf(ReadMeta(handle, application)) },
                { "project_path", path },
                { "compiled", compiled },
                { "elapsed_seconds", Math.Round(elapsed, 3) },
                { "messages", messages.Cast<object>().ToList() },
            };
            if (checkedAll != null) answer["checked_messages"] = checkedAll.Cast<object>().ToList();
            if (library) answer["kind"] = "library";
            if (install) Install(handle, answer, messages.Select(m => (string)m["severity"]));
            _lastBuild = LastBuild.Record(answer, messages.Select(m => (string)m["severity"]), DateTime.UtcNow);
            return answer;
        }

        bool Compile(Guid application)
        {
            var compilerIface = FindType("_3S.CoDeSys.Core.LanguageModel.ILanguageModelManager");
            var compile = NeedMethod(compilerIface, "Compile", new[] { typeof(Guid) }, "ILanguageModelManager.Compile is not present in this IDE");
            try { return (bool)compile.Invoke(SystemInstance(compilerIface.FullName), new object[] { application }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "Compile: " + Invocation.Cause(e).Message); }
        }

        void CheckAllObjects(Guid application)
        {
            var checkerIface = FindType("_3S.CoDeSys.Core.LanguageModel.ILanguageModelManager15");
            var check = NeedMethod(checkerIface, "CheckAllApplicationObjects", new[] { typeof(Guid) },
                "ILanguageModelManager15.CheckAllApplicationObjects is not present in this IDE");
            try { check.Invoke(SystemInstance("_3S.CoDeSys.Core.LanguageModel.ILanguageModelManager"), new object[] { application }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "CheckAllApplicationObjects: " + Invocation.Cause(e).Message); }
        }

        List<Dictionary<string, object>> ReadMessages(int handle, System.Reflection.MethodInfo read, object storage, object category, Dictionary<Guid, object> objects)
        {
            var messages = new List<Dictionary<string, object>>();
            foreach (var message in (Array)read.Invoke(storage, new[] { category }))
                messages.Add(BuildMessage(handle, message, objects));
            return messages;
        }

        // Installs the checked library unless the check found an error;
        // `installed` says which, `library` names the repository entry the
        // install wrote ("Title, Version (Company)", as the IDE lists it), and
        // `install_error` says why an install failed.
        void Install(int handle, Dictionary<string, object> answer, IEnumerable<string> severities)
        {
            int errors;
            LastBuild.Count(severities, out errors, out _);
            answer["installed"] = false;
            if (errors > 0) return;
            try
            {
                RunBatchCommand("file saveandinstall");
                answer["installed"] = true;
                var projectInfo = FindProjectInfo(handle);
                if (projectInfo != null)
                    answer["library"] = string.Format("{0}, {1} ({2})", ProjectValue(projectInfo, "Title"),
                        ProjectValue(projectInfo, "Version"), ProjectValue(projectInfo, "Company"));
            }
            catch (ProtocolException e) { answer["install_error"] = e.Message; }
        }

        // Runs the IDE command a CODESYS batch line names (`project checkall`)
        // with its batch arguments, as the menu would, without its dialogs:
        // true once it returned.
        bool RunBatchCommand(string name, params string[] arguments)
        {
            var tokens = name.Split(' ');
            var managerIface = FindType("_3S.CoDeSys.Core.ICommandManager");
            var find = NeedMethod(managerIface, "GetBatchCommand", new[] { typeof(string[]) }, "ICommandManager.GetBatchCommand is not present in this IDE");
            var command = find.Invoke(Prop(_engineIface, _engine, "CommandManager"), new object[] { tokens });
            if (command == null) throw new ProtocolException(ErrorCodes.Unavailable, "this IDE has no command '" + name + "'");
            var run = NeedMethod(FindType("_3S.CoDeSys.Core.Commands.ICommand"), "ExecuteBatch", new[] { typeof(string[]) }, "ICommand.ExecuteBatch is not present in this IDE");
            try { run.Invoke(command, new object[] { arguments }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, name + ": " + Invocation.Cause(e).Message); }
            return true;
        }

        // The build's message category, or null while the IDE has none.
        object CompilerCategory(Type storageIface, object storage)
        {
            foreach (var category in (Array)Prop(storageIface, storage, "Categories"))
                if (CategoryGuid(category) == MessageCategories.Build) return category;
            return null;
        }

        // One message: severity, the code
        // the Messages view shows (prefix and four-digit number, "C0032"),
        // text, and the name and `guid` of the object it is about (no guid,
        // and "" for a library's).  A message that points into the object's
        // text also says where (AddPlace); `objects` keeps each object read
        // once per build.
        Dictionary<string, object> BuildMessage(int handle, object message, Dictionary<Guid, object> objects)
        {
            var messageIface = FindType("_3S.CoDeSys.Core.Messages.IMessage");
            var numbered = FindType("_3S.CoDeSys.Core.Messages.IMessage4");
            var prefix = numbered.IsInstanceOfType(message) ? Convert.ToString(Prop(numbered, message, "Prefix")) : "";
            var number = numbered.IsInstanceOfType(message) ? Prop(numbered, message, "Number") : null;
            var code = number != null && Convert.ToUInt32(number) > 0 ? prefix + Convert.ToUInt32(number).ToString("D4") : prefix;
            var answer = new Dictionary<string, object>
            {
                { "severity", Convert.ToString(Prop(messageIface, message, "Severity")) },
                { "code", code },
                { "text", Convert.ToString(Prop(messageIface, message, "Text")) },
                { "object", "" },
            };
            var guid = (Guid)Prop(messageIface, message, "ObjectGuid");
            var owner = (int)Prop(messageIface, message, "ProjectHandle");
            if (guid == Guid.Empty || owner != handle) return answer;
            object meta;
            try { meta = ReadMeta(handle, guid); }
            catch { return answer; /* gone since the build: the message still stands */ }
            if (meta == null) return answer;
            answer["object"] = NameOf(meta);
            answer["guid"] = Id(guid);
            try
            {
                object obj;
                if (!objects.TryGetValue(guid, out obj))
                    objects[guid] = obj = Prop(_metaObjectIface, meta, "Object");
                AddPlace(answer, obj, Convert.ToInt64(Prop(messageIface, message, "Position")),
                    Convert.ToInt32(Prop(messageIface, message, "PositionOffset")));
            }
            catch { /* a text the IDE cannot read back: the message still stands */ }
            return answer;
        }

        // Where in the object's text a message points: a text message's
        // Position is the id of a line of the declaration's or the
        // implementation's TextDocument, its PositionOffset the column from 0.
        // `part`, the 1-based `part_line` and `column` in that part's text and
        // the line's text (`line_text`) go into the answer; a position that is
        // no line of either part (a graphical body, a device) adds nothing.
        static void AddPlace(Dictionary<string, object> answer, object obj, long position, int offset)
        {
            foreach (var part in new[] { "Interface", "Implementation" })
            {
                var doc = PartDocument(obj, part);
                var find = doc == null ? null : doc.GetType().GetMethod("FindLineById", new[] { typeof(long) });
                var text = doc == null ? null : doc.GetType().GetMethod("GetLineText", new[] { typeof(int) });
                if (find == null || text == null) continue;
                var line = (int)find.Invoke(doc, new object[] { position });
                if (line < 0) continue;
                answer["part"] = part == "Interface" ? "declaration" : "implementation";
                answer["part_line"] = line + 1;
                answer["column"] = offset + 1;
                answer["line_text"] = Convert.ToString(text.Invoke(doc, new object[] { line }));
                return;
            }
        }
    }
}
