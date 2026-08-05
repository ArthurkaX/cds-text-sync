# cds-static-analyzer

Human-facing static analysis for exported CODESYS Structured Text (`.st`).

The implementation is in `src/cds_static_analyzer`. The repository CLI keeps
the existing `cts analyze` command as a composition/facade over this package.
This product does not read visualization XML and does not run inside CODESYS.
