# verifier plan

## Current Status

- [x] Disable implicit SDK retries and limit judge replay to explicit rejection.
- [x] Verify a lost judge HTTP response results in one request, including outer resume.

Search parser supports the official plain and two bold-label formats. Raw confidence
and parse errors remain available to the Search calculator.

- [x] Correct Responses answer extraction, exposed by a real gpt-5.5 proxy probe.
- [x] Verify multiple output text blocks and exclusion of reasoning/refusal content.
- [x] Repeat the real framework judge probe after the fix (PROXY_JUDGE_OK).

The regression test failed against the previous client. After the fix, 26 client
and verifier tests pass. The real proxy probe also passes with gpt-5.5(medium).

## Verification

Tests: direct Search parser and shared Math/Phys parser parity against pinned official source.
The full upstream baseline already has failing tests/type checks; compare results
against the root PLAN.md baseline rather than claiming a clean repository.

## Next Steps / Owner

Codex owns local implementation and checks. The operator supplies the real model,
services and assets. Track acceptance and remaining runtime work in root PLAN.md.

## Independent acceptance repairs completed

The final audit closes all discovered defects within the bounded local scope.
See docs/datasets/memoryarena-acceptance-fixes.md and its verification manifest:
110 independent checks and 8 final runtime/layering checks pass. The original
real model run remains historical evidence, not a new full-dataset result.
