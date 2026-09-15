# metrics plan

## Current Status

- [x] Repair Search final-query selection, truncated-task status and equal-query aggregation.
- [x] Compare opposite context/final outcomes with the pinned official summarizer.

Evidence-based Shopping/Travel scoring, repeated-query alignment, reasoning paper
aggregation and unmeasured/error semantics are implemented. Official aggregation
has a direct unequal-paper-length parity test. Search qrel recall is not reported.

## Verification

Tests: contract fixtures and direct official parity in test_memoryarena_official_parity.py.
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

## Independent acceptance repairs completed

The final audit closes all discovered defects within the bounded local scope.
See docs/datasets/memoryarena-acceptance-fixes.md and its verification manifest:
110 independent checks and 8 final runtime/layering checks pass. The original
real model run remains historical evidence, not a new full-dataset result.
