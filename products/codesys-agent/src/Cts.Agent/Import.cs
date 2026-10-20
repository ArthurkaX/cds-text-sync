// `objects.import {parent_guid, xml}`: a new object made from its disk `.xml`
// (an export entry) below `parent_guid`, for the kinds that have no text form
// -- a visualization, a task, a device.  The entry is deserialized as
// `objects.replace` does and placed as `objects.create` places a new object
// (through the structured view below a folder).  It keeps the entry's guid
// while the project has no object with it, so the file and the IDE agree after
// the import.  The entry's MetaObject properties (a visualization's size and
// usage) go onto the new object: AddObject takes the object alone, and the
// IDE would otherwise leave it with none.  Same online refusal and deny key as
// `objects.create`.
using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        // Below *parentGuidText*, or at the project's top level with *atRoot*,
        // as for objects.create.
        public Dictionary<string, object> ImportObject(string parentGuidText, bool atRoot, string xml)
        {
            RefuseWhileOnline();
            RequirePermission("objects.import");
            if (atRoot == (parentGuidText.Length > 0)) throw new ProtocolException(ErrorCodes.BadParams, "pass parent_guid or root, one of them");
            var parentGuid = atRoot ? Guid.Empty : ParseObjectGuid(parentGuidText);
            var documents = EntryDocuments.Parse(xml);
            var handle = ProjectHandle();
            var parent = atRoot ? null : ObjectMeta(handle, parentGuid, "GetObjectToRead");
            string name;
            Array properties;
            var created = Deserialize(ImportObjectMethod(), documents, out name, out properties);
            if (string.IsNullOrEmpty(name))
                throw new ProtocolException(ErrorCodes.BadParams, "the entry's MetaObject has no Name");
            var guid = (bool)Manager("ExistsObject", handle, documents.Guid) ? Guid.NewGuid() : documents.Guid;
            if (parent != null && IsFolder(parent))
            {
                Guid placed;
                SvAddObject(SvNode(handle, parentGuid, out _), created, name, guid, out placed);
                return FinishImport(handle, placed, properties);
            }
            var add = _objectManagerIface.GetMethod("AddObject");
            if (add == null) throw new ProtocolException(ErrorCodes.Unavailable, "IObjectManager.AddObject is not present in this IDE");
            try
            {
                add.Invoke(_objectManager, new object[] { handle, parentGuid, guid, created, name, -1 });
            }
            catch (Exception e)
            {
                throw new ProtocolException(ErrorCodes.BadParams,
                    "cannot import '" + name + "' " + Where(parent) + ": " + Invocation.Cause(e).Message);
            }
            return FinishImport(handle, guid, properties);
        }

        // The new object gets the entry's properties; one that cannot take them
        // is removed again, so a failed import leaves no half object behind.
        Dictionary<string, object> FinishImport(int handle, Guid guid, Array properties)
        {
            if (properties != null && properties.Length > 0)
            {
                var guids = new List<string>();
                foreach (var property in properties)
                {
                    if (property == null) continue;
                    var propertyGuid = PropertyGuid(property);
                    // The file's folder placement would move the object out of
                    // the folder SvAddObject just put it in.
                    if (propertyGuid != new Guid(ObjectKinds.FolderPlacementProperty)) guids.Add(propertyGuid.ToString("D"));
                }
                try
                {
                    Modify("objects.import", Id(guid), (parsed, meta) =>
                    {
                        CarryProperties(meta, properties, guids.ToArray());
                        return null;
                    });
                }
                catch
                {
                    try { RemoveObject(handle, guid); } catch { }
                    throw;
                }
            }
            return FinishCreate(handle, guid, null);
        }
    }
}
