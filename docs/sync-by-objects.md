# Sync by objects: the disk form and the import without a manifest

Status: implemented; import, export, sync and compare work this way.

## Disk form

- **Text objects are `.st` only.** A POU or interface is one file with its
  methods, properties (GET/SET) and actions inside; a GVL or DUT is one file.
  No `.xml` beside a text object.
- **Layout of one file** (`Sync/StViewReader.cs` in the agent): the owner first, closed by
  its END keyword, then one block per member, each closed by its own END
  keyword. ACTION follows CODESYS V2's text export (`ACTION A_Reset:` …
  `END_ACTION`). Declaration and implementation are split by
  `// --- implementation ---`; a part without it has no implementation text.

  ```
  FUNCTION_BLOCK FB_Valve
  VAR
      xOpen : BOOL;
  END_VAR
  // --- implementation ---
  <body>
  END_FUNCTION_BLOCK

  METHOD M_Toggle : BOOL
  // --- implementation ---
  xOpen := NOT xOpen;
  M_Toggle := xOpen;
  END_METHOD

  PROPERTY P_Open : BOOL
  GET
  // --- implementation ---
  P_Open := xOpen;
  END_GET
  END_PROPERTY

  ACTION A_Reset:
  xOpen := FALSE;
  END_ACTION
  ```

- **Settings outside the text** (exclude from build, link always, an object
  kind the text cannot tell apart) go in the `(* cds-text-sync: … *)` pragma
  line above the part they belong to, non-default values only (above
  `ACTION A_Reset:` for an action, which has no declaration). An object with
  a setting the pragma does not know keeps an `.xml` beside the file, without
  the text (`StPragma.cs` lists what counts as a setting).
- **Tables** (text lists) are `.csv`, with an `.xml` for the rest of the list
  and no rows. **Everything else** (devices,
  visualisations, tasks, image pools) is `.xml`, without volatile fields.

## Identity

An object is its path in the IDE's structured view: the folders, the file
name, then the member names inside the file
(`Application/FB_Valve/P_Open/Get`). `StViewReader.Read` reads a view into
such objects; `ViewExport` writes objects back as files.

The GUID comes from the IDE: one `project.tree` call per command gives every
path's GUID. Nothing on disk records GUIDs, so there is no manifest.

## What changed where

Three states, compared per object in the normal form:

- **disk**: the working tree, read with `StViewReader.Read`;
- **base**: `refs/cts/base`, the view when disk and IDE last agreed (every
  export and import moves it), read the same way from its blobs; a base that
  is not the commit cts left there (kept in `.git/cts/base.own`) stops the
  sync instead of deciding by it;
- **IDE**: `objects.texts` for the objects in question.

| disk vs base | IDE vs base | import does |
|---|---|---|
| same | same | nothing |
| same | changed | nothing (`--force` writes the disk text) |
| changed | same | write the text (`objects.settext`) |
| changed | changed alike | nothing to write; the base moves |
| changed | changed otherwise, edits apart | merge each text (`git merge-file`) into the IDE and the file, named under `merged` |
| changed | changed otherwise, edits overlap | a conflict: left as it is, named under `conflicts`, exit 2 (`--force` writes it) |
| added | not in the IDE | create (`objects.create`), parent from the path; a folder of the path the IDE lacks is created first |
| removed | same | delete (`objects.delete`, permission `delete_pou`) |
| one removed, one added, same kind and text | | rename (`objects.rename`) or move (`objects.move`) or both, then write |
| same or changed | not in the IDE | nothing; changed, refused (`--force` creates it) |
| not in the base | added | nothing (`--force` deletes it, permission `delete_pou`; a folder too when all in it goes) |

`--force` puts what it overwrites or deletes in the IDE on
`refs/cts/overwritten` before the first change: a text object in its file,
an `.xml` object as its `.xml`, a text list whose rows it changes as its
`.xml` and `.csv`, an object only the IDE has in the file the export would
write it to.

A renamed POU file (`FB_Motor.st` to `FB_Drive.st`, its header too) is a
rename: the object keeps its GUID and its members move with it. A file moved
into another folder (`git mv`) is a move the same way: the object goes into
that folder in the IDE, a new folder is created first and gets its
`.cds-object.xml` as `cts export` writes it, and nothing is deleted. A rename or
delete whose old file still has an `.xml` beside it (the old layout, or an
object with a setting the pragma cannot carry) is refused, since that `.xml`
is the object too.

Without a base (a fresh clone, no export yet) the IDE stands in for it: what
differs is written, what the IDE lacks is created, nothing is deleted or
renamed, and no base is recorded (`cts export` records it).

`.st` files always go by objects, and so do the other view files: a changed
`.xml` or text-list `.csv` goes by objects too: its path in the tree gives the object (a
container's `<dir>/.cds-object.xml` is the object of its directory), the base
says whether the disk and the IDE changed it (`objects.export`, the object's
MetaObject and Object as the members of its export entry, for an `.xml`,
`objects.fields` for a `.csv`, both in the normal form), and the file is
written (`objects.replace`, or row by row), left as a conflict (exit 2,
`--force` writes it), or, when the IDE already holds it, only moves the
base. A new `.xml` is imported below the object of its folder
(`objects.import`, named like the file: its MetaObject `Name` must match);
the folders the IDE lacks below the nearest one it has are made first, as
for a new `.st`, and what the IDE adds when it places the object (the
folder property) goes into the file;
the agent keeps the file's GUID unless the project has it (a copied file), and
the file then takes the GUID the IDE gave the object. A removed `.xml` deletes
its object when nothing is below it in the IDE; an object the IDE changed
since the base is a conflict instead. A folder whose directory is gone from
disk goes too once the import deletes everything below it (its own
`.cds-object.xml` gone with it, or never written); an empty folder the user
made stays, and so does one that still holds an object after the import. Without a base every file is compared
with the IDE: what differs is written, what the IDE lacks is imported. A file
this cannot carry (the `.xml` of a text object's settings, a new
container, a removed container but an emptied folder, a new file none of whose folders the IDE has, a csv that is not a text
list) refuses the import before anything is written, with the reason; so
does a sync folder that is not a git repository, or a plan the `.st` part
cannot carry. There is no whole-project import, no import per file and no
manifest any more.

`cts sync` runs the same plan both ways. Its output labels each change
`disk -> IDE` or `IDE -> disk`, and each merged change `merged`. An object
unchanged on disk that the IDE changed is put into its `.st` file in place
(the other objects of the file must read back unchanged, or it stays a conflict), and `--take ide` does the
same for a conflict. A text object new in the IDE (neither disk nor base
knows it) goes into a new `.st` file of the one-file layout, its new members
inside, and joins the base; a new member (method, property, action, accessor)
of an object already on disk is added to that object's file as the export lays
it out, and joins the base with it. A file not in the export's layout (edited
by hand, or the old one-file-per-member layout) would change elsewhere too:
the new member is only named under `ide_new_members` (`cts export` writes it). An object
with no text form new in the IDE (a visualization, a text list) gets the
`.xml` (and `.csv`) the export writes for it: the agent exports just the
objects no view file on disk or in the base stands for, so a project whose
objects all have their files exports nothing.
An object with no text form that only the IDE changed (an `.xml` unchanged on
disk whose `objects.export` is not the base any more) is written to its
`.xml` byte for byte as `cts export` writes it, a text list's `.csv` with it,
and named under `to_disk`.
An object the IDE no longer has (deleted or renamed there) is named under `ide_removed` and leaves the disk: its `.xml` and `.csv` go; a `.st` only the IDE changed goes with its last object, or is written as the IDE renders it when that holds the file's other objects (otherwise it stays, named). A change the plan cannot carry (a rename or
delete beside an `.xml`, a file other than a `.st` the import cannot carry by objects, no base yet)
refuses the whole sync with the reason.
