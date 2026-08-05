# cds-static-analyzer

Human-facing static analysis for exported CODESYS Structured Text (`.st`).

The implementation is in `src/cds_static_analyzer`. The repository CLI keeps
the existing `cts analyze` command as a composition/facade over this package.
The public analyzer API reads only `.st` files and does not run inside CODESYS.

The legacy XML/task/visualization projection belongs to the sync product and
is available only through the explicit `cds_text_sync.analyze_compat` adapter
for repository compatibility. It is not part of the analyzer product
contract.
