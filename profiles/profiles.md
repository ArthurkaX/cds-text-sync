# Type Profiles

This folder contains JSON profile files that map CODESYS runtime GUIDs to
semantic kinds used by cds-text-sync.

Profiles are not only for supporting different CODESYS forks. They also let you
adjust how object types are handled in your project without changing code:

- add GUID mappings for fork-specific or vendor-specific object types
- exclude some types from export with `skip`
- force a type to export as `native_xml` instead of textual ST
- merge several GUIDs into one existing semantic kind
- reclassify ambiguous objects by parent or name so nested elements are handled
  as the right kind

## Available Profiles

- **default.json** — Default profile for CODESYS 3.5 SP20+ with context rules
- **template.json** — Template for creating custom profiles

## How to Add a Custom Profile

1. Copy `template.json` to a new file (e.g., `my_custom.json`)
2. Edit the `name`, `label`, `description`, and `guid_aliases` fields
3. Optionally add `context_rules`, `sync_profile_overrides`, or `sync_direction_overrides`
4. Save it in this folder with a `.json` extension
5. Select the profile in the Parameters dialog

The profile appears automatically — no code changes needed.

## File Format

```json
{
  "name": "my_custom",
  "label": "My Custom Profile",
  "description": "Short description of this profile",
  "extends": "default",
  "guid_aliases": {
    "my_custom_type": [
      "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    ]
  },
  "sync_profile_overrides": {
    "my_custom_type": "native_xml"
  },
  "sync_direction_overrides": {
    "library_manager": "export_only"
  },
  "context_rules": [
    {
      "when_kind": "softmotion_pool",
      "when_parent_kind": "device",
      "then_kind": "device_module"
    }
  ]
}
```

## Fields

| Field | Required | Description |
|---|---|---|
| `name` | yes | Unique ID. Must match filename without `.json` |
| `label` | yes | Display name in the UI |
| `description` | no | What this profile is for |
| `extends` | no | Inherit all aliases from another profile |
| `guid_aliases` | yes | `{semantic_kind: [guid, ...]}` mapping. Multiple GUIDs can point to the same kind to merge vendor-specific variants into one handling rule |
| `sync_profile_overrides` | no | `{semantic_kind: "textual"\|"native_xml"\|"skip"}` for new or remapped kinds |
| `sync_direction_overrides` | no | `{semantic_kind: "bidirectional"\|"export_only"\|"import_only"\|"disabled"}` to control sync direction per kind |
| `context_rules` | no | Reclassify ambiguous GUIDs by parent or name when the same raw type should be treated differently in different contexts |

## sync_profile Values

- `textual` — export as ST source files (pou, gvl, dut, itf)
- `native_xml` — export as CODESYS XML (task_config, visu, alarm_config)
- `skip` — do not export (property_accessor, task, device)

Typical uses:

- mark fork-specific configuration objects as `native_xml`
- suppress noisy generated objects with `skip`
- remap vendor-specific GUIDs to an existing kind such as `visu` or `device_module`

## sync_direction Values

- `bidirectional` — export and import normally
- `export_only` — export and compare normally, but do not import from disk back into CODESYS
- `import_only` — allow import from disk, but skip export to disk
- `disabled` — exclude this kind from both directions

## context_rules Fields

| Field | Required | Description |
|---|---|---|
| `when_kind` | yes | The semantic_kind to match |
| `when_parent_kind` | no | Match only if parent has this semantic_kind |
| `when_name_suffix` | no | Match only if object name ends with this (case-insensitive) |
| `then_kind` | yes | The replacement semantic_kind for this object in that context |

This is how you can treat child elements differently from top-level objects. For
example, a GUID that normally maps to one kind can be remapped to another kind
when it appears under a specific parent, effectively grouping those nested
elements into the handling of that target kind.

## extends (Inheritance)

When `extends` is set, the profile inherits all `guid_aliases`, `context_rules`,
`sync_profile_overrides`, and `sync_direction_overrides` from the base profile.
Your own entries are merged on top:

- `guid_aliases`: new kinds are added, existing kinds get additional GUIDs appended
- `context_rules`: your rules run after the base rules
- `sync_profile_overrides`: your overrides take precedence
- `sync_direction_overrides`: your direction overrides take precedence

## Sharing

Profile JSON files are plain text and can be committed to git, shared via email,
or posted in issue trackers. To use someone else's profile, just drop the file
in this folder.

## Discovery

Run the Discover script to find unknown GUIDs in your project. It will suggest
a profile JSON you can create to resolve them.
