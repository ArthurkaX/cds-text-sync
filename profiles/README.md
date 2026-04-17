# Type Profiles

This folder contains JSON profile files that map CODESYS runtime GUIDs to
semantic kinds used by cds-text-sync.

## Available Profiles

- **default.json** — Default profile for CODESYS 3.5 SP20+ with context rules
- **template.json** — Template for creating custom profiles

## How to Add a Custom Profile

1. Copy `template.json` to a new file (e.g., `my_custom.json`)
2. Edit the `name`, `label`, `description`, and `guid_aliases` fields
3. Optionally add `context_rules` or `sync_profile_overrides`
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
| `guid_aliases` | yes | `{semantic_kind: [guid, ...]}` mapping |
| `sync_profile_overrides` | no | `{semantic_kind: "textual"\|"native_xml"\|"skip"}` for new kinds |
| `context_rules` | no | Reclassify ambiguous GUIDs by parent or name |

## sync_profile Values

- `textual` — export as ST source files (pou, gvl, dut, itf)
- `native_xml` — export as CODESYS XML (task_config, visu, alarm_config)
- `skip` — do not export (property_accessor, task, device)

## context_rules Fields

| Field | Required | Description |
|---|---|---|
| `when_kind` | yes | The semantic_kind to match |
| `when_parent_kind` | no | Match only if parent has this semantic_kind |
| `when_name_suffix` | no | Match only if object name ends with this (case-insensitive) |
| `then_kind` | yes | The replacement semantic_kind |

## extends (Inheritance)

When `extends` is set, the profile inherits all `guid_aliases`, `context_rules`,
and `sync_profile_overrides` from the base profile. Your own entries are merged
on top:

- `guid_aliases`: new kinds are added, existing kinds get additional GUIDs appended
- `context_rules`: your rules run after the base rules
- `sync_profile_overrides`: your overrides take precedence

## Sharing

Profile JSON files are plain text and can be committed to git, shared via email,
or posted in issue trackers. To use someone else's profile, just drop the file
in this folder.

## Discovery

Run the Discover script to find unknown GUIDs in your project. It will suggest
a profile JSON you can create to resolve them.
