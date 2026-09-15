# Plan

- [x] Allow the judge to supply a delivery-safe retry predicate; retain existing default behavior.

- [x] Pass the optional runtime version through to Harbor and provenance.
- [x] Verify the installed Harbor schema and version propagation without Docker.

## Independent acceptance repairs completed

The final audit closes all discovered defects within the bounded local scope.
See docs/datasets/memoryarena-acceptance-fixes.md and its verification manifest:
110 independent checks and 8 final runtime/layering checks pass. The original
real model run remains historical evidence, not a new full-dataset result.
