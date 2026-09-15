# datasets plan

## Current Status

Identity, positive sampling, aligned rounds/backgrounds, and travel base plans are implemented. Runtime tools are owned by execution/environment integration, not data adapters.

## Verification

Tests: test_memoryarena_contracts.py and test_memoryarena_cli.py.
The full upstream baseline already has failing tests/type checks; compare results
against the root PLAN.md baseline rather than claiming a clean repository.

## Next Steps / Owner

Codex owns local implementation and checks. The operator supplies the real model,
services and assets. Track acceptance and remaining runtime work in root PLAN.md.
