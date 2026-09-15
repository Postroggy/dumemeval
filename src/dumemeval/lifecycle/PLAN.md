# lifecycle plan

## Current Status

Task scopes, independent environment guidance, explicit failure status and per-attempt
memory transfer isolation are implemented. Failed checkpoints are rerun.

## Verification

Tests: memory-disabled environment guidance and partial execution status in test_memoryarena_contracts.py.
The full upstream baseline already has failing tests/type checks; compare results
against the root PLAN.md baseline rather than claiming a clean repository.

## Next Steps / Owner

Codex owns local implementation and checks. The operator supplies the real model,
services and assets. Track acceptance and remaining runtime work in root PLAN.md.

- [x] Verify the scoped memory observation correction and unmeasured aggregation (root PLAN.md).

## Completed local acceptance (2026-09-15)

The scoped work above is verified. Root PLAN.md and
docs/datasets/memoryarena-acceptance-verification.json record the real on/off run,
asset-dependent scene checks, focused tests and remaining platform limitations.
