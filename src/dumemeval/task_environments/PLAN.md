# task_environments plan

## Current Status

- [x] Repair client identity persistence across a lost response and process restart.
- [x] Reproduce gateway-to-client response loss and assert exactly one official action.
- [x] Disable official worker SDK automatic replay at construction and verify a lost judge response.

- [x] Verify official BM25 retrieval with the pinned corpus and offline tokenizer.
- [x] Respect selected Search assets and explicit Shopping items-file overrides.

Managed worker ownership, scoped gateway, four scenario strategies, preparation
checks, asset fingerprints and correlated evidence are implemented.

## Verification

Tests cover transport contracts plus actual pinned Math/Phys HTTP services, the
mounted tool script, official reasoning/judging routing, capability expiry and
cleanup. In addition to fixture tests, a real Harbor/GPT-5.5 Math smoke completed
two sessions with official tools and judge responses through the pinned upstream
OpenAI backend. Runtime evidence records completed cleanup. A separate synthetic
Harbor canary verified memory-file persistence across two fresh conversations.
The actual Travel/Shopping/Search tools and the complete two-round controlled
Math experiment have now passed; see the root acceptance record.
The full upstream baseline already has failing tests/type checks; compare results
against the root PLAN.md baseline rather than claiming a clean repository.

## Next Steps / Owner

Codex owns local implementation and checks. The operator supplies the real model,
services and assets. Track acceptance and remaining runtime work in root PLAN.md.

The completed evidence records the upstream Shopping seed limitation and pinned
Search tokenizer/index. The independent audit's delivery gaps are now repaired and revalidated.

## Completed local acceptance (2026-09-15)

The scoped work above is verified. Root PLAN.md and
docs/datasets/memoryarena-acceptance-verification.json record the real on/off run,
asset-dependent scene checks, focused tests and remaining platform limitations.

## Independent acceptance repairs completed

The final audit closes all discovered defects within the bounded local scope.
See docs/datasets/memoryarena-acceptance-fixes.md and its verification manifest:
110 independent checks and 8 final runtime/layering checks pass. The original
real model run remains historical evidence, not a new full-dataset result.
