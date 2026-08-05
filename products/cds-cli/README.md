# cds-cli

The user-facing command-line composition layer for the repository products.

This package owns argument parsing, command dispatch, daemon transport
coordination, output formatting, and compatibility entry points. Domain
implementations remain in `cds_text_sync`, `cds_static_analyzer`, and the
separate CODESYS host product.

The historical `cts` and `cds-text-sync` entry points continue to resolve to
`cds_cli.main`.
