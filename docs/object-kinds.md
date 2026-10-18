# Object kinds

Working catalog of CODESYS object kinds for the per-object sync (C# agent,
`IObjectManager`): what each kind holds, how it goes to disk, and whether it can
be read, replaced and created object by object. One row per kind; details per
kind below the table. Sources: live runtime-reflection probes and per-object
exports of a 1.5k-object customer project (2026-10-10); type and member names
only, no vendor code.

Disk form (target): **st** = text file with cts pragmas for the fields that are
not part of the text; **csv** = table; **xml** = CompactXml archive only (no
text form). Status columns: `ok` proven live, `?` not checked yet, `no` fails.

| Kind | Type GUID | Seen | Text | Disk form | Export | Replace | Create |
|---|---|---|---|---|---|---|---|
| DeviceObject | `225bfe47-7336-4dbc-9419-4105a7c831fa` | 332 | - | xml | ok | ok (no-op) | ? |
| DUTObject | `2db5746d-d284-4425-9f7f-2663a34b0ebc` | 310 | yes | st | ok | ok (text) | ok |
| POUObject | `6f9dac99-8de1-4efc-8465-68ac443b7d08` | 203 | yes | st | ok | ok (text, xml) | ok |
| FolderObject | `738bea1e-99bb-4f04-90bb-a7a567e74e3a` | 155 | - | xml | ok | ? | ok (tree) |
| EmbeddedFileObject | `9001d745-b9c5-4d77-90b7-b29c3f77a23b` | 149 | - | xml | ok | ? | ? |
| POUMethodObject | `f8a58466-d7f6-439f-bbb8-d4600e41d099` | 60 | yes | st | ok | ok (text) | ok |
| TextListObject | `2bef0454-1bd3-412a-ac2c-af0f31dbc40f` | 57 | table | csv | ok | ok (fields) | ok |
| VisualObject | `f18bec89-9fef-401d-9953-2f11739a6808` | 55 | embedded | xml | ok | ok (reorders; agent objects.replace) | ? |
| AlarmGroupObject | `21f4ed1d-ec95-4666-820e-4abf64d93d6b` | 46 | - | xml | ok | ? | ok (2 nodes) |
| GVLObject | `ffbfa93a-b94d-45fc-a329-229860183b1d` | 45 | yes | st | ok | ok (text) | ok |
| PropertyAccessorObject | `792f2eb6-721e-4e64-ba20-bc98351056db` | 34 | yes | st | ok | ok (text) | ok (with property) |
| PropertyObject | `5a3b8626-d3e9-4f37-98b5-66420063d91e` | 17 | yes | st | ok | ok (text) | ok |
| SlotDeviceObject | `085766fd-043e-4545-8e8d-d651d56d5d3b` | 12 | - | xml | ok | ok | ? |
| ExternalFileObject | `a56744ff-693f-4597-95f9-0e1c529fffc2` | 8 | - | xml | ok | ? | ? |
| TaskObject | `98a2708a-9b18-4f31-82ed-a1465b24fa2d` | 6 | - | xml | ok | ok (fields) | ok |
| TaskPOUCallObject (hidden) | `413e2a7d-adb1-4d2c-be29-6ae6e4fab820` | 6 | - | xml | ok | ? | ? |
| AlarmClassObject | `b8b46f61-c7c1-4259-87e4-26fe674798f9` | 5 | - | xml | ok | ? | ? |
| HiddenTransientImagePoolObject (hidden) | `8e687a04-7ca7-42d3-be06-fcbda676c5ef` | 2 | - | xml | ok | ? | ? |
| LibManObject | `adb5cb65-8e1d-4a00-b70a-375ea27582f3` | 2 | - | xml | ok | ? | ? |
| SymbolConfigObject | `21d4fe94-4123-4e23-9091-ead220afbd1f` | 1 | - | xml | ok | ? | ? |
| ProjectInfoObject | `085afe48-c5d8-4ea5-ab0d-b35701fa6009` | 1 | - | xml | ok | ? | ? |
| PlcLogicObject | `40b404f9-e5dc-42c6-907f-c89f4a517386` | 1 | - | xml | ok | ? | ? |
| TraceObject | `f7aa3620-8073-4c91-b6ec-86ed9eb60303` | 1 | - | xml | ok | ? | ? |
| ApplicationObject | `639b491f-5557-464c-af91-1471bac9f549` | 1 | - | xml | ok | ? | ? |
| WorkspaceObject | `8753fe6f-4a22-4320-8103-e553c4fc8e04` | 1 | - | xml | ok | ? | ? |
| DatabaseFileAlarmStorageObject | `5bd56248-46fc-4108-be33-ed01ad87d070` | 1 | - | xml | ok | ? | ? |
| VisualManagerObject | `4d3fdb8f-ab50-4c35-9d3a-d4bb9bb9a628` | 1 | - | xml | ok | ? | ? |
| WebVisualizationObject | `0fdbf158-1ae0-47d9-9269-cd84be308e9d` | 1 | - | xml | ok | ? | ? |
| GlobalTextListObject | `63784cbb-9ba0-45e6-9d69-babf3f040511` | 1 | table | csv | ok | ok | ? |
| ImagePoolObject | `bb0b9044-714e-4614-ad3e-33cbdf34d16b` | 1 | - | xml | ok | ? | ok |
| TaskConfigObject | `ae1de277-a207-4a28-9efb-456c06bd52f3` | 1 | - | xml | ok | ? | ? |
| ExplicitConnector | `e9159722-55bc-49e5-8034-fbd278ef718f` | 1 | - | xml | ok | ? | ? |
| AlarmConfigurationObject | `c0a56ce5-14a3-4757-ac56-3eab44c974b3` | 1 | - | xml | ok | ? | ? |
| ActionObject | `8ac092e5-3128-4e26-9e7e-11016c6684f2` | 0 | yes | st | ok | ok (text) | ok |
| TransitionObject | `a10c6218-cb94-436f-91c6-e1652575253d` | 0 | yes | st | ? | ? | ok |
| InterfaceObject | `6654496c-404d-479a-aad2-8551054e5f1e` | 0 | yes | st | ok | ok (text) | ok |
| InterfaceMethodObject | `f89f7675-27f1-46b3-8abb-b7da8e774ffd` | 0 | yes | st | ok | ? | ok |
| AbstractPOUMethodObject | `62ebfd1c-d342-43e5-8efb-f22b6d8e4a04` | 0 | yes | st | ? | ? | ? |
| POUObjectCheckFunction | `c3fc9989-e24b-4002-a2c7-827a0a2595f4` | 0 | yes | st | ? | ? | ? |
| NVLObject | `722bc402-e00b-490a-8138-0a7d01b3426e` | 0 | yes | st | ? | ? | no (wizard) |
| VarPersistentObject | `261bd6e6-249c-4232-bb6f-84c2fbeef430` | 0 | yes | st | ? | ? | ok |
| TasklocalGVLObject | `c2cda7a9-0ba4-4146-b563-22a42fa0eb72` | 0 | yes | st | ? | ? | ok |
| RecipeManObject | `09ecc42e-586d-4a08-932f-5bdcac20bb55` | 0 | - | xml | ? | ? | ? |
| RecipeDefinitionObject | `6b3dfb6a-1865-4356-a39b-1fe0ef89651c` | 0 | table | csv? | ? | ? | ? |
| UnitConversionObject | `9031c721-d39f-4557-8a8f-ab12b4a71ebc` | 0 | - | xml | ? | ? | ? |

Rows with Seen 0 come from the runtime metadata of CODESYS 3.5.22.30 (classes
with a TypeGuid that implement `IObject`), not from a project yet. Export `ok`:
CompactXml per-object export equals the object's entry in `export_native`
(1509/1509 on the bench). The two hidden kinds are not in `export_native` and
are skipped. Text `embedded`: the visualization carries generated text inside
its element tree, not a user document.

## Implementations (embedded in POU, method, action, transition)

The body of a text-bearing kind is an embedded implementation object; its kind
decides whether the body can be text.

| Implementation | Type GUID | Body |
|---|---|---|
| STImplementationObject | `3b83b776-fb25-43b8-99f2-3c507c9143fc` | text (st) |
| VarDeclObject (declaration) | `a9ed5b7e-75c5-4651-af16-d2c27e98cb94` | text (st) |
| SFCImplementationObject | `74f81948-1328-492c-b6c1-a9ea72048b28` | graphical (xml) |
| CFCImplementationObject | `32d3375e-c010-41e2-9e43-b2fbf4f2b374` | graphical (xml) |
| PageOrientedCFCImplementationObject | `30124a67-851d-45eb-873a-0374fa1cfa68` | graphical (xml) |
| LadderImplementationObject | `f0fda5b8-8c48-4377-bbd5-c49444e4d26e` | graphical (xml) |
| NWLImplementationObject (FBD/LD/IL networks) | `25e509de-33d4-4447-93f8-c9e4ea381c8b` | graphical (xml) |

A POU with a graphical body keeps its declaration as text; the body stays xml.

## Object properties (meta `Properties`, outside the text)

Attached to the meta object, not to the object itself; candidates for cts
pragmas on text kinds.

Full scan of the bench (2026-10-10, all 669 text objects: 310 DUT, 203 POU,
60 method, 45 GVL, 34 accessor, 17 property): apart from the text and the
folder, the only non-default values are `ExcludeFromBuild=True` (41 POUs) and
`LinkAlways=True` (2 GVLs). `IsGet` of an accessor follows from its name, the
other object fields (`POULevel`, `SpecialFunc`, `AddAttributeSubsequent`,
`ParameterList`, `NetVarProperties`) keep their defaults everywhere. So a text
kind on disk needs only its text, its path and the BuildProperty pragmas.

| Property | Type GUID | Settable members | Seen on |
|---|---|---|---|
| BuildProperty | `24568a24-c491-472c-a21f-ee5d33859fab` | ExcludeFromBuild, ExcludeFromBuildLocal, External, EnableSystemCall, LinkAlways, CompilerDefines, Undefines, MemoryReserveForOnlineChange | 55 of 203 POUs (41 ExcludeFromBuild=True), 3 GVLs (2 LinkAlways=True), 1 DUT |
| SVFoldersProperty | `829a18f2-c514-4f6e-9634-1df173429203` | (folder membership) | almost every object; structural, comes from the path |
| VisualProperty | `477d844b-9b2a-407e-90a4-d36fd6dde2fc` | VisuSizeMode, UsageType, Size, IsStartVisu, Internal, … | visualizations |
| TextListPropertiesObject | `9db18249-9fcf-4264-a9de-410a659a36b3` | Internal, DownloadForApplication | text lists |
| ImagePoolPropertiesObject | `a67e96c6-3fd3-4d25-a9ff-723c6b2f78cb` | DownloadOnlyUsedImages, Internal, SymbolTextList, DownloadByVisu | image pools |
| ObjectAccessProperty | `66e0aa87-603e-4e95-b7ac-da3c4a099b35` | (access rights) | ? |
| DeviceProperty | `cdadfc2b-8598-4621-ad56-5b1df7db910f` | (device identification) | devices |
| `657bb752-68e4-4ef6-a654-6d13f38a3c55` | not in public metadata | ? | ? |

## API (proven 2026-10-10)

- Export: `IObjectManager2.ExportObject(handle, guid, metaStream, objectStream, writer)`,
  writer `CompactXmlArchiveWriter` `{47B44770-18B8-4f47-92CC-AD8DD6B5B1B9}`.
- Read into an object without placing it: `IObjectManager2.ImportObject(meta, object, reader, out parent, out guid, out obj, out name, out properties)`,
  reader `CompactXmlArchiveReader` `{6F129F88-6420-403f-B776-7752427BD61F}`.
- Replace: `GetObjectToModify(handle, guid)` -> `IMetaObject2.ReplaceObject(obj)` -> `SetObject(meta, true, null)`.
  A MetaObject property travels separately: `IMetaObject.RemoveProperty(typeGuid)`, then
  `AddProperty(property)` with the one `ImportObject` read from the file (a property's key is the
  `TypeGuid` attribute of its class). The Library Manager writes its placeholder resolutions back
  as properties after its libraries change (persisted on save).
  The agent's `objects.replace` reads the documents from the disk `.xml` entry
  (its `MetaObject`/`Object` members re-rooted): the reader takes the export's
  canonical form (Timestamp dropped, entry indentation) unchanged, live on a
  visualization and a device (~0.1 s each).
- Write text: `GetObjectToModify(handle, guid)` -> `Object.Interface.TextDocument.Text = s`
  and/or `Object.Implementation.TextDocument.Text = s` -> `SetObject(meta, true, null)`.
  Every text kind exposes `Interface` as `IVarDeclObject` and `Implementation` as
  `IImplementationObject` (action: body only; accessor: body, declaration `VAR END_VAR`).
  50-170 ms. The text is stored verbatim: LF stays LF (only the archive writer emits
  CRLF), non-ASCII and pragmas survive, the compiler sees the change. A write bumps
  `TimeStamp` and `UniqueIdGenerator`, so writing the old text back is not a byte-equal undo.
  Unreferenced POUs are not compiled: a build does not prove their text.
- Create: `AddObject(handle, parent, guid, obj, name, -1)`; the caller chooses the guid.
  Without an XML template, the way the IDE's "Add Object" does it (proven live):
  `IObjectManager.ObjectFactoryManager.Factories` (80 factories; no system
  instance of the manager) -> factory `Create(string[] batchArguments)` ->
  `AddObject` -> factory `ObjectCreated(handle, guid, batchArguments)` (the
  3-argument form when present, once: it adds children such as property
  accessors). `AcceptsParentObject(IObject parent)` answers the parent
  constraint. 100-550 ms per object on the bench.
- Batch arguments: build the factory's wizard page (`WizardPage`, or
  `IObjectFactory3.GetWizardPage(handle, parent)` for methods), call
  `Control.CreateControl()` so the page loads its language list, then
  `CreateBatchArgumentsFromWizardPage(page)` returns the defaults. The
  declaration argument becomes the Interface text verbatim; the body starts
  as empty ST. The language guid is the `TypeGuid` of the implementation
  factory (public metadata); the page's `SelectLanguage(name)` does not switch it:

| Language | Guid |
|---|---|
| ST | `cc393387-a21c-4f68-a3e3-84c36951965d` |
| SFC | `ba020298-5c00-4558-8da5-551cff5b4aa9` |
| CFC | `a4e3bc72-255d-4cf1-93a5-3d12da67b2e1` |
| CFC (page-oriented) | `13c55f2e-a820-4b3a-8a86-f42bd395d87f` |
| FBD/LD/IL networks | `c2e2244b-c806-41b4-8ad3-7a0e25ce1393` |
| LD | `29148beb-8dd2-4bb8-8b77-ab9fe196c1ba` |
| IL | `7ced0289-1a1e-4049-afc8-6b798c73f499` |
| Ladder | `9cb75521-cc3e-44e6-a4f7-e66d155fada2` |


| Factory | Batch arguments (defaults) |
|---|---|
| POUObjectFactory | `[Guid.Empty, language, "", declaration, "4"]` |
| POUMethodObjectFactory | `[Guid.Empty, declaration, language, "False"]` |
| PropertyObjectFactory | `[Guid.Empty, declaration, language, "False", "True" (Get), "True" (Set)]` |
| ActionObjectFactory | `[language]` |
| DUTObjectFactory | `[Guid.Empty, declaration]` |
| InterfaceObjectFactory | `[Guid.Empty, declaration]` |
| GVLObjectFactory, FolderObjectFactory | `[]` (no wizard arguments) |
| InterfaceMethodObjectFactory | `[Guid.Empty, declaration]` |
| InterfacePropertyObjectFactory | `[Guid.Empty, declaration]` (`PROPERTY <name> : <type>`) |
| VarPersistentObjectFactory | `[]`; text starts as `{attribute 'qualified_only'} VAR_GLOBAL PERSISTENT RETAIN END_VAR` |
| TransitionObjectFactory | `[language]` (under an SFC POU) |
| NVLObjectFactory | none: its wizard page needs the project's GVLs and task names and fails standalone |
- Read fields: every kind implements `IArchivable`; `SerializableValueNames` and
  `GetSerializableValue(name)` return the persisted field tree (the same names as
  the CompactXml archive). Values are scalars, nested archivables, or
  `ArrayList`/`Hashtable`/`LList` collections of them. The same holds for the
  meta object's `Properties`. All 33 kinds of the bench in 1.4 s.
- Write fields: `GetObjectToModify` -> walk the path with `GetSerializableValue`
  (`Watchdog.Time.Time`, `TextList[0].LanguageTexts[0]`) ->
  `SetSerializableValue(name, value)` with the old value's type (string, enum,
  primitive), or `IList[i] = value` for a list item -> `SetObject(meta, true, null)`.
  7-150 ms (2 s on a device). Proven on task fields, text list rows (non-ASCII),
  `TextListPropertiesObject` and a device IO mapping; code generation sees task
  changes. Adding and removing
  list items: clone an item (`ICloneable`, deep), set its fields, `IList.Insert`;
  remove with `IList.RemoveAt`; then `SetObject`. 40-130 ms. Proven on text list
  rows and task calls (`PouList`, the call appears in the generated task code).
  An empty list has nothing to clone: build the item with its public `()` ctor
  (`_3S.CoDeSys.TaskObject.PouObject`, `_3S.CoDeSys.TextList.TextListRow`).
- Generated code: `ILanguageModelProvider.GetLanguageModel()` returns the
  `<language-model>` XML with the implicit IEC code the compiler gets (task info,
  IO-config GVLs, text-list and alarm FBs). It is read-only and not a disk form.
  On `VisualManagerObject` it raises a debug assertion dialog that blocks the IDE:
  never call it there.
- Delete: `RemoveObject(handle, guid)`.
- Meta properties: `IMetaObject.Properties` and `GetProperty(Guid)` read them,
  `AddProperty(IObjectProperty)` adds one the object lacks, `RemoveProperty(Guid)`
  drops it (the object must be checked out with `GetObjectToModify` and committed
  with `SetObject`). A property is created by type: its public class name (e.g.
  `BuildProperty`, `24568a24-c491-472c-a21f-ee5d33859fab`) found among the loaded
  assemblies as an `IObjectProperty`, then the public parameterless constructor.
- Change detection: `IMetaObject.TimeStamp` (persisted) and `ObjectModified/Added/Removed` events.

## Per kind

### POUObject
- Text: `Interface.TextDocument` (declaration), `Implementation.TextDocument` (body).
- Non-text, user-settable (pragma candidates): `Level` (POULevel, `Standard`
  everywhere on the bench), `KindOfCheckFunction` (xml `SpecialFunc`, `None`),
  `AddAttributeSubsequent` (`False`), plus BuildProperty.
- Volatile: `LineInfoPersistence` (`<guid>_Impl_LineIds`/`_Decl_LineIds`),
  `UniqueIdGenerator`.
- Replace: ok, 30-80 ms, round trip byte-identical. Create: ok from an XML
  template and through POUObjectFactory (PROGRAM, FUNCTION_BLOCK, FUNCTION
  with return type; the kind follows from the declaration text).
- Members: method (POUMethodObjectFactory, under FB or PROGRAM), action
  (ActionObjectFactory, under PROGRAM), property (PropertyObjectFactory, under
  FB; Get/Set accessors are created by `ObjectCreated` from the arguments).

### DUTObject, GVLObject
- Text: `Interface.TextDocument` only. Non-text: BuildProperty (1 DUT on the
  bench). Volatile: `LineInfoPersistence`, `UniqueIdGenerator`.

### FolderObject
- Folders sit at the project root (Parent = Guid.Empty, all 155 on the bench).
  Where a folder or object appears in the tree is the `SVFoldersProperty`
  dictionary ParentObjects {structured view guid -> parent folder or
  Application}; the bench has one view, `d9b2b2cc-ea99-4c3b-aa42-1e5c49e65b84`.
- Create in the tree (proven): `GetStructuredView(handle, sv).GetNode(parent)
  .AddObject(guid, factoryObject, name, -1)`, then the factory's `ObjectCreated`.
  The new guid is found by name among `GetNode(parent).Children`. A folder stays
  a root object with SVFoldersProperty {sv -> Application or outer folder}; a POU
  added to a folder node gets ParentObjectGuid = Application and SVFoldersProperty
  {sv -> folder}, the same shape as the bench objects.
- Move: `ISVNode.MoveObject(newParentNode, -1)`, 30-55 ms; only SVFoldersProperty
  changes. Moving straight under Application removes the property entry.

### DeviceObject (IO mapping)
- The device stays xml, but its IO mapping is a table: under
  `ConnectorList.InnerList[c].HostParameterSet.Params[p].DalaElement` (and its
  `SubElements.elements[e]`, `BaseType`) sits `IoMapping` {`Mappings.Mappings[k]`
  {Id, Variable}, IecAddress, AutomaticAddress}. `Variable` is the mapped
  variable (`Application.PN41.CMD_...`); writing it through the field path works.
  Candidate disk form: one csv per device with channel, variable, address.
- Volatile: `PositionId`, `EditorPositionId` on the parameter elements; an
  element saved without them gets them when a later session opens the device.
  `PlaceholderResolution` (placeholder -> library, rebuilt from the PC's
  installed libraries) is not compared either, and the export writes it as
  `<Null>`: the IDE fills it again as soon as the device is replaced from the
  file (measured on a device resolving IoDrvEthernet; the build is unchanged).

### TaskObject
- Fields: `Kindoftask` (Cyclic, Freewheeling, …), `Priority`, `Interval`
  {Time, Unit}, `Watchdog` {Enabled, Time {Time, Unit}, Sensitivity}, `Event`,
  `ExternalEvent`, `PouList` [{Name, Comment}], `Core2`, `TaskGroup`,
  `WithinSPSTimeSlicing`, `SynchTask`, parameter lists (`IntervalParameters`, …).
- Volatile: `TaskGuid`, `EventPOUGuid` (generated code).
- Field writes reach the code generator: Task Configuration's language model
  shows the new `nPriority`/`KindOf`/`bWatchdog`, and an enabled watchdog without
  a time becomes `{error '<task>: The watchdog time is invalid.'}`.
- Create: `TaskObjectFactory` args `[]` under Task Configuration (wizard has no
  batch overload); starts as Cyclic, priority 1, `t#4ms`, empty `PouList`. A new
  task with one call shows up as `CallTask__<task>` in the generated code.

### TextListObject, GlobalTextListObject
- Fields: `Languages` [string], `TextList` [TextListRow {TextID, TextDefault,
  LanguageTexts [string, one per language]}]: a table with the columns
  ID, Default, then one per language.
- Property: TextListPropertiesObject {DownloadForVisu, DownloadForApplication, Internal}.
- Volatile: `GuidInit`, `GuidReInit`, `GuidExitX`, `UniqueIdGenerator`.
- Create: `TextListObjectFactory` args `[]` under Application, ~2 s; starts
  with one empty row and no languages. `GlobalTextListObjectFactory` is a
  different factory (one per project, root only): pick factories by exact class
  name, a substring match picks the Global one.

### ImagePoolObject
- Fields: `BitmapPool` [ImagePoolItem {BitmapID, FileID, ItemID}]; `FileID`
  names an EmbeddedFileObject (`<guid>|<original path>`), whose `Data` holds the bytes.
- Create: `ImagePoolObjectFactory` args `[]` under Application.

### AlarmGroupObject, AlarmClassObject
- Group: `Alarms` {key -> Alarm {ID, ObservationType (e.g. DigitalObservation
  {Expression, Comparison, ExpressionToCompare}), AlarmClass {Name, Guid},
  LatchVariable1.., MinPendingTime, Deactivation}}, `TextListReference`,
  `Deactivation`, `AlarmStorage`.
- Class: `Priority`, `AcknowledgeMethod`, `Archiving`, `NotificationActions`,
  `DisplayOptions`, `ReAlarmTime`.
- Volatile: `LanguageModelData` (generated-code guids), `InternalID`.
- Create: `AlarmGroupObjectFactory` args `[]` under the Alarm Configuration
  object, ~3.6 s. `ObjectCreated` adds a second node with the same name, which
  `TextListReference` points to: most likely the group's own text list (type not
  checked).

### TraceObject
- Fields: `TraceSettings`, `Record` {TaskName, BufferEntries, Trigger*,
  `VariableList` [TraceVariable {VariableName, GraphColor, …}]}.

### Hidden kinds
- TaskPOUCallObject and `__VisualizationStyle` get new guids in every IDE
  session, and the style carries a per-session temp path: never sync them.
  The application's own copy of the style is exported; its default bitmaps
  sit under the session's temp directory and take a new `ItemID` in every
  session, so the normal form ignores both.

### VisualObject
- Replace: ok, but key/value lists come back in another order
  (`ieccodeconversion_array`/`DefaultArraySize`, `conditionalshow`/
  `DisplayFrameReferencesConfiguration`): the normal form sorts these lists by
  key, keeping each pair together.
- Once, between IDE sessions, six table-control visualizations differed
  without an edit: `LibraryId` `visuelemswincontrols` 4.5.0.0 vs 4.10.0.0 and
  extra `''NORMAL__COMMENT` entries. A later session (3.5.22.30) compared all
  of a large project's visualizations unchanged, so the normal form keeps both.
