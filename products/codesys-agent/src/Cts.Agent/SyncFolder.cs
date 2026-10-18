// `project.syncfolder` (`cts set-sync-folder`).  A dry run answers the
// project's id and the folder *path* points to -- without one, the folder
// ProjectInfo.Suggested offers -- and is refused when the write would be, so
// cts prepares the folder's git repository and registers it on this machine
// before anything is stored.  The write gives the project the id cts chose
// (`cts-project-id` in Project Information) and saves the project when asked.
using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        public Dictionary<string, object> SetSyncFolder(string path, string id, bool save, bool dryRun)
        {
            var project = OpenProject();
            var file = Convert.ToString(Prop(_projectIface, project, "Path"));
            var projectInfo = FindProjectInfo(Handle(project));
            var current = projectInfo == null ? "" : ProjectText(projectInfo, ProjectInfo.IdProperty);
            if (dryRun)
            {
                RefuseWhileOnline();
                RequirePermission("project.syncfolder");
                var folder = (path ?? "").Trim().Length > 0 ? ProjectInfo.Anchor(path, file)
                    : ProjectInfo.Suggested(file);
                if (folder == "")
                    throw new ProtocolException(ErrorCodes.BadParams, "The project has not been saved: save it first, or give an absolute path.");
                return new Dictionary<string, object>
                {
                    { "project_id", current },
                    { "sync_folder", folder },
                    { "name", ProjectFiles.DisplayName(file) },
                    { "dry_run", true },
                };
            }
            if (string.IsNullOrEmpty(id)) throw new ProtocolException(ErrorCodes.BadParams, "project.syncfolder requires an 'id', or 'dry_run'");
            var answer = new Dictionary<string, object> { { "project_id", id }, { "changed", id != current } };
            if (id != current)
            {
                if (projectInfo == null) AddProjectInfo(Handle(project));
                Modify("project.syncfolder", Id(_infoGuid), (guid, meta) =>
                {
                    var info = Prop(_metaObjectIface, meta, "Object");
                    _projectInfoIface.GetMethod("PutValue").Invoke(info, new object[] { ProjectInfo.IdProperty, id });
                    return null;
                });
                answer["saved"] = false;
                if (save)
                {
                    try { SaveProject(); answer["saved"] = true; }
                    catch (ProtocolException e) { answer["save_error"] = e.Message; }
                }
                if (!(bool)answer["saved"])
                    answer["unsaved"] = "The project's id changed in memory but was not saved. "
                        + "Save the project in CODESYS or re-run with --save.";
            }
            var found = ProjectInfo.SyncFolder(id, file, ProjectInfo.RegistryPath());
            if (found != "") answer["sync_folder"] = found;
            return answer;
        }

        // `project.source`: `cts-source` in Project Information, the commit the
        // IDE's code came from with when; written only when the label differs
        // from the one there, so a run that carried nothing leaves the project
        // unmodified.  A project with no Project Information gets none: it has
        // no sync folder either.
        public Dictionary<string, object> MarkSource(string source, string when)
        {
            var projectInfo = FindProjectInfo(Handle(OpenProject()));
            var changed = projectInfo != null && ProjectInfo.SourceOf(ProjectText(projectInfo, ProjectInfo.SourceProperty)) != source;
            if (changed)
                Modify("project.source", Id(_infoGuid), (guid, meta) =>
                {
                    var info = Prop(_metaObjectIface, meta, "Object");
                    _projectInfoIface.GetMethod("PutValue").Invoke(info, new object[] { ProjectInfo.SourceProperty, ProjectInfo.Source(source, when) });
                    return null;
                });
            return new Dictionary<string, object> { { "changed", changed } };
        }

        // A new project has no Project Information object until someone opens
        // that dialog; it is made here the same way, through its own factory,
        // at the project root, so the id has a place to go.
        void AddProjectInfo(int handle)
        {
            RefuseWhileOnline();
            RequirePermission("project.syncfolder");
            var manager = Prop(_objectManagerIface, _objectManager, "ObjectFactoryManager");
            var factory = ((Array)Prop(manager.GetType(), manager, "Factories")).Cast<object>().FirstOrDefault(candidate =>
                Prop(candidate.GetType(), candidate, "ObjectType") is Type type && _projectInfoIface.IsAssignableFrom(type));
            if (factory == null) throw new ProtocolException(ErrorCodes.Unavailable, "this IDE has no factory for Project Information");
            try
            {
                var created = factory.GetType().GetMethod("Create", Type.EmptyTypes).Invoke(factory, null);
                _objectManagerIface.GetMethod("AddObject").Invoke(_objectManager,
                    new object[] { handle, Guid.Empty, Guid.NewGuid(), created, "Project Information", -1 });
            }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "create Project Information: " + Invocation.Cause(e).Message); }
            if (FindProjectInfo(handle) == null)
                throw new ProtocolException(ErrorCodes.Internal, "the new Project Information object is not in the project");
        }
    }
}
