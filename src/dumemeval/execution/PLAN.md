# Execution plan

## Current Status

EnvironmentExecutor binds registered runtimes around HarborBridge. Tool resources
are read-only, agent versions are passed through, and trial artifacts are sanitized.

## Milestones

- [x] Add optional task scope and generic runtime bindings.
- [x] Wire a provider-backed environment executor without benchmark branches.
- [x] Preserve failures and enforce explicit mock selection.
- [ ] Validate actual Harbor mounts, tools, native memory settings and traces.

Codex owns implementation. Acceptance is a real scoped environment tool call
whose host evidence is attached to the correct session and cleaned up on failure.
