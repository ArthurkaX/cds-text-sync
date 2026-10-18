// AgentHost's registrations of the object methods (objects.*, project.export, project.skeleton).

namespace Cts.Agent
{
    public sealed partial class AgentHost
    {
        void RegisterObjectMethods()
        {
            _router.Register("objects.find", (req, s) => _ide.OnUi("objects.find", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.FindObjects(req.String("name", ""), req.String("path", ""), req.String("app", ""))));
            _router.Register("objects.text", (req, s) => _ide.OnUi("objects.text", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.ReadObjectText(req.String("guid"))));
            // Every text object in one call, for a bulk disk<->IDE read without a
            // whole-project export.  Reuses objects.text per object.
            _router.Register("objects.texts", (req, s) =>
            {
                var guids = TextsParams.Guids(req);
                var startMs = (int)StartTimeout.Parse(req);
                return _ide.OnUi("objects.texts", startMs, () => _ide.ReadObjectsText(guids));
            });
            // The IDE snapshot the engine compares, written to `path` from one
            // ExportObject per object;
            // `guids` keeps only those objects (`cts read-object --body`).
            _router.Register("project.export", (req, s) => _ide.OnUi("project.export", (int)StartTimeout.Parse(req),
                () => { var reply = _ide.ExportSnapshot(req.String("path", ""), TextsParams.Guids(req)); reply["ide_stamp"] = _journal.Stamp; return reply; }));
            _router.Register("project.skeleton", (req, s) =>
            {
                var startMs = (int)StartTimeout.Parse(req);
                return _ide.OnUi("project.skeleton", startMs, () =>
                {
                    var reply = _ide.ProjectSkeleton();
                    reply["ide_stamp"] = _journal.Stamp;
                    return reply;
                });
            });
            _router.Register("objects.settext", (req, s) => _ide.OnUi("objects.settext", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.SetObjectText(req.String("guid"), TextEdit.From(req))));
            // Creates one object under a parent GUID through the IDE's object
            // factory (the agent's own path, so a new object no longer needs a
            // whole-project export) and removes one by GUID.  Both refuse while
            // an application is online, like objects.settext.
            _router.Register("objects.create", (req, s) => _ide.OnUi("objects.create", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.CreateObject(ObjectCreate.From(req))));
            _router.Register("objects.delete", (req, s) => _ide.OnUi("objects.delete", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.DeleteObject(ObjectDelete.From(req))));
            // One object's content from its disk .xml (a kind with no text form),
            // and the per-object export its read-back compares.
            _router.Register("objects.replace", (req, s) => _ide.OnUi("objects.replace", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.ReplaceObject(req.String("guid"), req.String("xml"), req.Strings("properties"))));
            _router.Register("objects.import", (req, s) => _ide.OnUi("objects.import", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.ImportObject(req.String("parent_guid"), req.String("xml"))));
            _router.Register("objects.export", (req, s) => _ide.OnUi("objects.export", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.ExportObjects(TextsParams.Guids(req), ExportParams.Known(req))));
            _router.Register("objects.move", (req, s) => _ide.OnUi("objects.move", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.MoveObject(ObjectMove.From(req))));
            _router.Register("objects.rename", (req, s) => _ide.OnUi("objects.rename", StartTimeout.Parse(req, UiTimeoutMs), () => _ide.RenameObject(ObjectRename.From(req))));

            // The persisted field tree of one object (or of one of its meta
            // properties), and a write to one leaf of it.  Both are the object
            // manager directly; the write refuses while an application is online.
            _router.Register("objects.fields", (req, s) => _ide.OnUi("objects.fields", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.Fields(req.String("guid"), req.String("prop", ""), (int)req.Int("depth", 4))));
            _router.Register("objects.setfield", (req, s) => _ide.OnUi("objects.setfield", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.SetField(req.String("guid"), req.String("path"), req.String("value"), req.String("prop", ""))));
            // A row added to or removed from one of those lists (a text list's
            // TextList); same online refusal and permission as setfield.
            _router.Register("objects.listadd", (req, s) => _ide.OnUi("objects.listadd", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.ListAdd(req.String("guid"), ListInsert.From(req))));
            _router.Register("objects.listremove", (req, s) => _ide.OnUi("objects.listremove", StartTimeout.Parse(req, UiTimeoutMs),
                () => _ide.ListRemove(req.String("guid"), ListEdit.ListPath(req), (int)req.Int("index"))));
        }
    }
}
