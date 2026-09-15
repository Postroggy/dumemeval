# datasets specification

Identity, positive sampling, aligned rounds/backgrounds, and travel base plans are implemented. Runtime tools are owned by execution/environment integration, not data adapters.

## Current Architecture

```mermaid
flowchart LR
    Pinned datasets --> ScenarioValidation --> EvalTask
```

## Target Architecture

```mermaid
flowchart LR
    Pinned datasets --> ScenarioValidation --> EvalTask
```

The local contract above is implemented. Remaining end-to-end work and boundaries
are in the root PLAN.md and docs/datasets/memoryarena.md. Dependencies follow
GOVERNANCE.md; benchmark differences do not belong in the session runner.
