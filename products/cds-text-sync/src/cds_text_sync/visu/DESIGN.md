# Catalog schema for CODESYS visu element types

Each element type is described by a JSON file under `cds_text_sync/visu/catalog/<type>.json`.
Adding a new element type = adding one JSON file — no code changes to the engine.

## Top-level keys

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `type` | yes | string | Short machine name used by `cts visu add --type <name>` |
| `visualElementTypeName` | yes | string | CODESYS element class, e.g. `VisuFbElemSimple` |
| `visualElementName` | no | string | Friendly display name, e.g. `Rectangle` |
| `visualElementIsRectangle` | no | bool | Whether the element block has `VisualElementIsRectangle=True` |
| `elementVersion` | no | int | Value of `<Single Name="ElementVersion" Type="byte">` (default 1) |
| `description` | no | string | Human-readable description shown by `cts visu describe` |
| `shape_member_id` | no | int | Member id for the shape discriminator (e.g. 564465120) |
| `shape_variants` | no | dict | Mapping of friendly shape names to `VISU_ST_*` values |
| `default_shape` | no | string | Default shape variant name |
| `geometry` | yes | dict | Maps geometry roles to member ids: `{x, y, width, height, center_x, center_y}` |
| `params` | yes | dict | Settable property definitions per parameter name |
| `optional_bindings` | no | dict | Variable binding slots (e.g. `fill_var`, `text_var`) |
| `invariants` | no | list | Validation rules for `check` |
| `base_members` | yes | list | Ground-truth ordered list of member blocks |
| `font_descriptor` | no | dict | Default full font descriptor struct for member 3729828405 |

## `params` entry schema

Each key is a friendly parameter name used by `cts visu add --<name>`.

| Sub-key | Required | Description |
|---------|----------|-------------|
| `member_id` | yes | Numeric member id (long) |
| `kind` | yes | Value kind: `int`, `short`, `uint`, `string`, `bool`, `color`, `shape` |
| `geometry` | no | If true, the param is a geometry role (x/y/w/h) |
| `canonical_name` | no | Default `CanonicalName` for color params |
| `requires` | no | If `"textid"`, the param requires a Text ID when non-empty |
| `doc` | no | Human-readable description |

## `base_members` entry schema

Each entry corresponds to exactly one `<Single Type="{c694e3a2...}">` member
block, in declaration order (must match the ground truth order).

| Key | Required | Description |
|-----|----------|-------------|
| `id` | yes | Numeric member id |
| `form` | yes | `"scalar"`, `"color"`, or `"font_descriptor"` |
| `value_type` | for scalar | XML type attribute, e.g. `"string"`, `"int"`, `"short"`, `"uint"`, `"bool"` |
| `value` | for scalar | Default value as string |
| `color` | for color | Default ARGB int as string (e.g. `"-16777216"`) |
| `canonical_name` | for color | Default CanonicalName (e.g. `"BasicElement-Frame-Color"`) |
| `role` | no | Optional semantic role: `"x"`, `"y"`, `"width"`, `"height"`, `"center_x"`, `"center_y"`, `"shape"`, `"text"` |

## Invariants schema

| Sub-key | Required | Description |
|---------|----------|-------------|
| `id` | yes | Short identifier for the rule |
| `rule` | yes | Human-readable rule description |
| `severity` | yes | `"error"`, `"warning"`, or `"auto"` |

## Adding a new element type

1. Ground-truth: export a real element from CODESYS IDE as `.xml`.
2. Create `cds_text_sync/visu/catalog/<name>.json` following the schema above.
3. If the element uses a new visualElementTypeName, the engine handles it generically.
4. No code changes to `builder.py`, `catalog.py`, or `commands.py` needed.
