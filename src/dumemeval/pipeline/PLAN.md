# pipeline plan

- [x] Add durable, content-addressed benchmark scoring checkpoints.
- [x] Verify real pipeline resume does not invoke the judge again; changed inputs invalidate results.
- [x] Verify pending/corrupt checkpoints fail closed and persisted data is redacted.

The issue #4 local boundary is implemented and regression-checked. Tests cover
missing evidence, controlled-input mismatches, serialization and package layering.
Root PLAN.md and the verification manifest record real-runtime acceptance gaps;
fixture success does not complete those checks.

- [x] Verify the scoped memory observation correction and unmeasured aggregation (root PLAN.md).

## Completed local acceptance (2026-09-15)

The scoped work above is verified. Root PLAN.md and
docs/datasets/memoryarena-acceptance-verification.json record the real on/off run,
asset-dependent scene checks, focused tests and remaining platform limitations.

## Independent acceptance repairs completed

The final audit closes all discovered defects within the bounded local scope.
See docs/datasets/memoryarena-acceptance-fixes.md and its verification manifest:
110 independent checks and 8 final runtime/layering checks pass. The original
real model run remains historical evidence, not a new full-dataset result.
