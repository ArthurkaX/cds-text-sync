// Request parsing for `objects.create` and `objects.delete`, kept out of the
// IDE-facing file so the shape rules are unit-tested without a CODESYS process.
//
//   objects.create {"parent_guid" | "root": true, "kind", "type_guid"?, "name", "declaration"?, "implementation"?, "accessors"?}
//   objects.delete {"guid"}
//
// A GUID must parse and must not be empty: RemoveObject on an empty GUID killed
// the CODESYS process once, so the empty case never reaches the IDE.  A name
// must not be empty.  `kind` is mapped to the type GUIDs of the IDE factory's
// object by ObjectKinds; `type_guid` names the exact one among them.  `declaration` and `implementation` are optional -- absent
// leaves the kind's own default text in place, an empty string clears it.
// `accessors` is a PROPERTY's {"Get": "<body>", "Set": "<body>"} map.
using System;
using System.Collections.Generic;
using System.Linq;
using Cts.Sync;

namespace Cts.Agent
{
    public static class ObjectKinds
    {
        // A METHOD below an interface is a different object than a METHOD below
        // a POU (an interface method, not a POU method); Ide picks it when the
        // parent refuses the POU factory, so the caller keeps saying "method".
        public static IReadOnlyList<Guid> InterfaceMethodTypes => TypeKinds.All.Guids("itf_method");

        // The IDE's type GUID of a folder (Sync/TypeKinds.json
        // guid_aliases.folder): a create whose parent has it is placed through
        // the structured view, never through AddObject.
        public const string FolderType = "738bea1e-99bb-4f04-90bb-a7a567e74e3a";

        // The meta property that says which structured-view node (folder) an
        // object sits in: the IDE's own placement, never a file's.
        public const string FolderPlacementProperty = "829a18f2-c514-4f6e-9634-1df173429203";

        // The type GUID of the Structured Text implementation, as an Add
        // Object dialog's language list names it (TypeGuidString).
        public const string StructuredText = "cc393387-a21c-4f68-a3e3-84c36951965d";

        // The type GUIDs of every kind cts may create (Sync/TypeKinds.json
        // guid_aliases, the protocol's "interface" is its "itf"), the one a
        // factory's object class carries in its TypeGuid attribute.  A factory
        // is picked by that GUID, never by its class name, its array index or
        // its display Name: those move between versions, forks and locales.
        // A kind with several aliases (persistent variables) tries each.
        public static IReadOnlyList<Guid> TypeGuids(string kind)
        {
            var name = (kind ?? "").ToLowerInvariant();
            if (Array.IndexOf(Creatable, name) < 0)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "cannot create kind '" + kind + "'; supported kinds: " + string.Join(", ", Creatable));
            return TypeKinds.All.Guids(name == "interface" ? "itf" : name);
        }

        static readonly string[] Creatable = { "gvl", "persistent_gvl", "task_local_gvl", "pou", "method", "action", "property", "dut", "interface", "folder" };

        // A POU, METHOD and ACTION have an implementation part next to their
        // declaration; a GVL's and a DUT's text is one declaration block, and a
        // PROPERTY carries its body in its Get/Set accessors, so an implementation
        // for one of those is a caller mistake and is refused before the IDE is
        // asked anything.
        public static bool HasImplementation(string kind)
        {
            switch ((kind ?? "").ToLowerInvariant())
            {
                case "pou":
                case "method":
                case "action": return true;
                default: return false;
            }
        }

        // Only a PROPERTY takes the accessor bodies; every other kind refuses them.
        public static bool HasAccessors(string kind)
        {
            return (kind ?? "").ToLowerInvariant() == "property";
        }
    }

    public sealed class ObjectCreate
    {
        // Guid.Empty with AtRoot: the project root, what the POUs view shows
        // at its top and every application shares.
        public Guid ParentGuid { get; private set; }
        public bool AtRoot { get; private set; }
        public string Kind { get; private set; }
        // The kind's type GUIDs, the exact one a file names (`type_guid`) first.
        public IReadOnlyList<Guid> TypeGuids { get; private set; }
        public string Name { get; private set; }
        // The structured view the object is placed through (a folder create,
        // or a create whose parent is a folder); absent for a plain AddObject.
        public Guid? StructuredView { get; private set; }
        public bool HasDeclaration { get; private set; }
        public string Declaration { get; private set; }
        public bool HasImplementation { get; private set; }
        public string Implementation { get; private set; }
        //: A PROPERTY's accessor bodies, keyed "Get"/"Set"; empty for other kinds.
        public IDictionary<string, string> Accessors { get; private set; }

        public static ObjectCreate From(Request req)
        {
            var kind = req.String("kind");
            var typeGuids = ObjectKinds.TypeGuids(kind);
            if (req.Params.ContainsKey("type_guid"))
            {
                var exact = ParseGuid(req.String("type_guid"), "type_guid");
                if (!typeGuids.Contains(exact))
                    throw new ProtocolException(ErrorCodes.BadParams,
                        "type_guid " + exact.ToString("D") + " is not a " + kind.ToLowerInvariant() + " type");
                typeGuids = new[] { exact }.Concat(typeGuids.Where(guid => guid != exact)).ToList();
            }
            var name = req.String("name");
            if (name.Length == 0)
                throw new ProtocolException(ErrorCodes.BadParams, "parameter 'name' must not be empty");
            object raw;
            var hasDeclaration = req.Params.TryGetValue("declaration", out raw) && raw != null;
            var hasImplementation = req.Params.TryGetValue("implementation", out raw) && raw != null;
            if (hasImplementation && !ObjectKinds.HasImplementation(kind))
                throw new ProtocolException(ErrorCodes.BadParams,
                    "kind '" + kind + "' has no implementation");
            if (hasDeclaration && (kind ?? "").ToLowerInvariant() == "folder")
                throw new ProtocolException(ErrorCodes.BadParams,
                    "kind 'folder' has no text");
            var accessors = new Dictionary<string, string>();
            if (req.Params.TryGetValue("accessors", out raw) && raw != null)
            {
                if (!ObjectKinds.HasAccessors(kind))
                    throw new ProtocolException(ErrorCodes.BadParams,
                        "kind '" + kind + "' has no accessors");
                var map = raw as IDictionary<string, object>;
                if (map == null)
                    throw new ProtocolException(ErrorCodes.BadParams, "parameter 'accessors' must be an object");
                foreach (var pair in map)
                {
                    if (pair.Key != "Get" && pair.Key != "Set")
                        throw new ProtocolException(ErrorCodes.BadParams,
                            "accessor '" + pair.Key + "' is not Get or Set");
                    var body = pair.Value as string;
                    if (body == null)
                        throw new ProtocolException(ErrorCodes.BadParams,
                            "accessor '" + pair.Key + "' must be a string body");
                    accessors[pair.Key] = body;
                }
            }
            var atRoot = req.Bool("root", false);
            if (atRoot && req.Params.ContainsKey("parent_guid"))
                throw new ProtocolException(ErrorCodes.BadParams, "pass parent_guid or root, not both");
            return new ObjectCreate
            {
                ParentGuid = atRoot ? Guid.Empty : ParseGuid(req.String("parent_guid"), "parent_guid"),
                AtRoot = atRoot,
                Kind = kind.ToLowerInvariant(),
                TypeGuids = typeGuids,
                Name = name,
                StructuredView = ParseStructuredView(req),
                HasDeclaration = hasDeclaration,
                Declaration = hasDeclaration ? req.String("declaration") : null,
                HasImplementation = hasImplementation,
                Implementation = hasImplementation ? req.String("implementation") : null,
                Accessors = accessors,
            };
        }

        // The text to write after AddObject; null when the caller named no part.
        public TextEdit Edit()
        {
            if (!HasDeclaration && !HasImplementation) return null;
            return TextEdit.Of(HasDeclaration, Declaration, HasImplementation, Implementation);
        }

        // The optional `structured_view` parameter: the SV the object is
        // placed through. Null when the caller named none (a plain AddObject).
        internal static Guid? ParseStructuredView(Request req)
        {
            var text = req.String("structured_view", "");
            if (text.Length == 0) return null;
            Guid guid;
            if (!Guid.TryParse(text, out guid) || guid == Guid.Empty)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "parameter 'structured_view' must be a GUID: " + text);
            return guid;
        }

        // A missing, mistyped, empty or unparsable GUID is bad_params here, before
        // the IDE is asked anything.
        internal static Guid ParseGuid(string text, string parameter)
        {
            Guid guid;
            if (!Guid.TryParse(text, out guid))
                throw new ProtocolException(ErrorCodes.BadParams, "parameter '" + parameter + "' must be a GUID: " + text);
            if (guid == Guid.Empty)
                throw new ProtocolException(ErrorCodes.BadParams, "parameter '" + parameter + "' must not be the empty GUID"
                    + (parameter == "parent_guid" ? "; root: true names the project's top level" : ""));
            return guid;
        }
    }

    public sealed class ObjectDelete
    {
        public Guid Guid { get; private set; }

        public static ObjectDelete From(Request req)
        {
            return new ObjectDelete { Guid = ObjectCreate.ParseGuid(req.String("guid"), "guid") };
        }
    }

    public sealed class ObjectMove
    {
        public Guid Guid { get; private set; }
        // Guid.Empty with AtRoot: the top of the POUs tab, as for objects.create.
        public Guid ParentGuid { get; private set; }
        public bool AtRoot { get; private set; }

        public static ObjectMove From(Request req)
        {
            var atRoot = req.Bool("root", false);
            if (atRoot && req.Params.ContainsKey("parent_guid"))
                throw new ProtocolException(ErrorCodes.BadParams, "pass parent_guid or root, not both");
            return new ObjectMove
            {
                Guid = ObjectCreate.ParseGuid(req.String("guid"), "guid"),
                ParentGuid = atRoot ? Guid.Empty : ObjectCreate.ParseGuid(req.String("parent_guid"), "parent_guid"),
                AtRoot = atRoot,
            };
        }
    }

    public sealed class ObjectRename
    {
        public Guid Guid { get; private set; }
        public string Name { get; private set; }

        public static ObjectRename From(Request req)
        {
            var name = req.String("name");
            if (name.Length == 0)
                throw new ProtocolException(ErrorCodes.BadParams, "parameter 'name' must not be empty");
            return new ObjectRename { Guid = ObjectCreate.ParseGuid(req.String("guid"), "guid"), Name = name };
        }
    }
}
