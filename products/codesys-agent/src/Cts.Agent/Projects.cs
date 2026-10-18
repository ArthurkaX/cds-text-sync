// `project.list`, `project.open {path}` and `project.close` (`cts project
// list|open|close`): the projects open in the IDE, through IProjects. The
// libraries the IDE loads for a project are projects too, and are left out of
// the list. Opening and closing refuse what would bring up a modal prompt:
// unsaved changes, and an online session on close. `discard` closes with the
// unsaved changes lost (`cts project update` replaces the file anyway). Both are cts's own writes
// to the journal: loading or closing a project is not a user's edit.
using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        public Dictionary<string, object> ListProjects()
        {
            var found = new List<object>();
            foreach (var project in AllProjects())
            {
                var primary = (bool)Prop(_projectIface, project, "Primary");
                if (!primary && (bool)Prop(_projectIface, project, "Library")) continue;
                var path = PathOf(project);
                found.Add(new Dictionary<string, object>
                {
                    { "name", ProjectFiles.DisplayName(path) },
                    { "path", path },
                    { "primary", primary },
                });
            }
            return new Dictionary<string, object> { { "projects", found }, { "count", found.Count } };
        }

        public Dictionary<string, object> OpenProjectFile(string path)
        {
            ProjectFiles.RequireOpenable(path);
            RequirePermission("project.open");
            var matching = AllProjects().FirstOrDefault(p => ProjectFiles.SamePath(PathOf(p), path));
            var primary = PrimaryProject();
            string replaced = null;
            if (primary != null)
            {
                if (matching != null && ProjectFiles.SamePath(PathOf(primary), path)) return Opened(primary, path, true);
                // As the IDE's File -> Open: a saved, offline project gives way.
                if (LoggedInApplications().Length > 0)
                    throw new ProtocolException(ErrorCodes.BadParams,
                        "The open project is online with the PLC. Run `cts disconnect`, then `cts project open`.");
                if (IsDirty(primary)) throw ProjectFiles.Unsaved("The primary project", "`cts project close`");
                replaced = ProjectFiles.DisplayName(PathOf(primary));
                if (!Close(primary)) throw new ProtocolException(ErrorCodes.Internal, "CODESYS did not close the project " + replaced);
            }
            // A failed primary open can leave the file loaded as a project that
            // is not primary; it has to go before the file opens again.
            if (matching != null) CloseLeftover(matching, true);

            // What the IDE's own File -> Open passes: without the language
            // model a project builds, but a login cannot generate its code.
            var attributes = new[] { ProjectAttribute("Primary"), ProjectAttribute("ProvidesLanguageModel") };
            var open = NeedMethod(_projectsIface, "OpenProject", new[] { typeof(string), typeof(Guid[]) },
                "IProjects.OpenProject is not present in this IDE");
            object opened;
            try { opened = open.Invoke(Prop(_engineIface, _engine, "Projects"), new object[] { path, attributes }); }
            catch (Exception e)
            {
                var leftover = AllProjects().FirstOrDefault(p => ProjectFiles.SamePath(PathOf(p), path));
                if (leftover != null) CloseLeftover(leftover, false);
                throw new ProtocolException(ErrorCodes.Internal, "Project open error: " + Invocation.Cause(e).Message);
            }
            if (opened == null || !(bool)Prop(_projectIface, opened, "Primary"))
            {
                if (opened != null) CloseLeftover(opened, false);
                throw new ProtocolException(ErrorCodes.Internal,
                    "Project opened but did not become primary; close it in CODESYS and retry.");
            }
            var data = Opened(opened, path, false);
            if (replaced != null) data["closed"] = replaced;
            return data;
        }

        public Dictionary<string, object> CloseProject(bool discard)
        {
            var project = OpenProject();
            RequirePermission("project.close");
            if (LoggedInApplications().Length > 0)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "The project is online with the PLC. Run `cts disconnect`, then `cts project close`.");
            if (IsDirty(project) && !discard) throw ProjectFiles.Unsaved("The project", "`cts project close`");
            var name = ProjectFiles.DisplayName(PathOf(project));
            if (!Close(project)) throw new ProtocolException(ErrorCodes.Internal, "CODESYS did not close the project " + name);
            return new Dictionary<string, object> { { "closed", name } };
        }

        Dictionary<string, object> Opened(object project, string path, bool alreadyOpen)
        {
            var data = new Dictionary<string, object> { { "opened", path } };
            if (alreadyOpen) data["already_open"] = true;
            data["name"] = ProjectFiles.DisplayName(PathOf(project));
            return data;
        }

        // Closes a project that is not primary unless that would lose changes:
        // before an open that is a refusal, after a failed one it is left alone.
        void CloseLeftover(object project, bool refuseUnsaved)
        {
            if (IsDirty(project))
            {
                if (refuseUnsaved) throw ProjectFiles.Unsaved("The requested project", "retry");
                return;
            }
            Close(project);
        }

        bool Close(object project)
        {
            return (bool)NeedMethod(_projectIface, "Close", Type.EmptyTypes, "IProject.Close is not present in this IDE")
                .Invoke(project, null);
        }

        bool IsDirty(object project)
        {
            return (bool)Prop(_projectIface, project, "Dirty");
        }

        string PathOf(object project)
        {
            return Convert.ToString(Prop(_projectIface, project, "Path")) ?? "";
        }

        IEnumerable<object> AllProjects()
        {
            var projects = (Array)Prop(_projectsIface, Prop(_engineIface, _engine, "Projects"), "Projects");
            return projects == null ? Enumerable.Empty<object>() : projects.Cast<object>();
        }

        Guid ProjectAttribute(string name)
        {
            var field = FindType("_3S.CoDeSys.Core.ProjectAttributes").GetField(name);
            if (field == null) throw new ProtocolException(ErrorCodes.Unavailable, "ProjectAttributes." + name + " is not present in this IDE");
            return (Guid)field.GetValue(null);
        }
    }
}
