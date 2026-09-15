# Issue #4 execution plan

## Current status

Independent acceptance repairs are complete. The independent reviewer closed the
original and follow-up counterexamples and passed all 15 criteria within the
agreed bounded scope. Historical real experiments remain evidence for their
execution-time source; the fixes have separate fresh-environment regression evidence.
The user requested runnable verification, not a full benchmark run. The final
acceptance record is docs/datasets/memoryarena-acceptance.md and its verification
JSON; the selected sanitized evidence archive is memoryarena-evidence.zip.

## Acceptance repairs (2026-09-15)

- [x] Score Search's final combined query only, including truncation and query-weighted aggregation parity.
- [x] Persist the mounted tool client's pending request across process retries and test lost responses.
- [x] Checkpoint scoring with evidence/configuration/source identity and no uncertain automatic replay.
- [x] Prevent implicit SDK and verifier retries after uncertain judge delivery.
- [x] Remove the shopping CLI fixture's dependence on host JAVA_HOME configuration.
- [x] Document setup from zero and verify a fresh dependency environment with bounded checks.
- [x] Have the independent reviewer repeat the adversarial acceptance probes and update the evidence record.

The repair design is docs/datasets/memoryarena-acceptance-fixes.md. Codex owns these
repairs. No full benchmark run or unrelated baseline migration is in scope.

## Historical acceptance claims (superseded where noted above)

- [x] Pin official source/data; record five scenarios, licenses and implementation differences.
- [x] Use the existing unified CLI, adapters, environment registry and metrics pipeline.
- [x] Preserve task/session/round/step identities and official scoring/aggregation.
- [x] Own worker preparation, startup, readiness, reset, failure and cleanup.
- [x] Exercise actual Math and Phys HTTP services and fixed-input scorer parity.
- [x] Prepare all five final CLI configurations with real dependencies/assets.
- [x] Verify actual Travel flights, Shopping search/click/purchase and Search retrieval/document tools.
- [x] Pin all 100,195 Search corpus documents, BM25 index and offline tokenizer.
- [x] Run real Harbor/GPT-5.5 medium on/off arms on one complete two-round Math row.
- [x] Match all control fingerprints and actual task instruction bytes across arms.
- [x] Verify first-round memory write and second-session read/update from real evidence.
- [x] Verify distinct native conversations, disabled native auto memory and off-arm mount absence.
- [x] Produce parseable JSON, readable Markdown and an unambiguous zero score delta.
- [x] Keep memory counts evidence-based; missing observations remain null/n/a.
- [x] Verify duplicate-delivery handling, failures, cancellation, scope isolation and cleanup.
- [x] Preserve benchmark/backend boundaries in the core execution chain.
- [x] Package redacted traces and document exact reproduction and platform limits.

## Repair verification

The independent reviewer ran 110 focused checks in the fresh environment; all
passed. Eight additional successful official runtime/layering checks passed after
the SDK policy change. Nine source files pass focused mypy, and ruff/format and
wheel/sdist builds pass. The pipeline's seven existing mypy diagnostics are in
functions whose AST is unchanged from HEAD; they are not new failures.

See docs/datasets/memoryarena-acceptance-fixes.md and its verification manifest
for the before/after probes, exact commands and source/artifact hashes. The fresh
environment installs all 122 locked packages, passes dependency checks, clones the
pinned official revision, prepares Math row 39 and builds the native agent image.
The new client also passes actual Linux Docker lost-response probes.

No new model inference, full benchmark sweep, fresh account login or native Linux
host deployment was performed. Login and platform prerequisites remain explicit.

## Historical verification evidence

The controlled run is results/memoryarena/controlled-final-20260915: each arm
completed 2/2 sessions, both official paper scores are 1.0, and comparison warnings
are empty. The enabled arm has two observed file-change events and one structured
read; the second session's read matches the first snapshot. This is not a memory
benefit claim. Travel/Shopping/Search transport fixtures and their worker cleanup
are in results/memoryarena/official-assets-20260915.

This finishing pass ran 25 distinct targeted checks, including memory observation,
Search assets and module dependencies. Changed surfaces pass mypy (8 source files),
ruff/format and package checks. The historical official scorer parity record has
28 fixed-input checks and 3 actual Math/Phys HTTP checks. Earlier full-suite and
baseline migration failures remain recorded in memoryarena-local-verification.json;
no additional full test suite or dataset run was requested or performed.

The only behavior refinement after the controlled run is Search snippet-limit
input validation, outside the Math execution path; a CLI string was also formatted.
Both execution-time sources are archived and reconstruct the exact code fingerprint; their final form has
passed focused tests and type checks.

## Boundaries and owner

Codex owns the local implementation, diagnostics and evidence. No push, PR or
external publication has been performed. The independent acceptance gaps are closed
within the documented local verification boundary.

Shopping used a first-1,000-product transport fixture on this 16 GB Windows machine;
its full catalog is downloaded and the full configuration is prepared. The
upstream wall-clock randomness remains labelled uncontrolled, so Math supplies
the ablation. Search uses the official BM25 option; dense embeddings and qrel
recall are not claimed. Linux routing is documented but not locally exercised.
The existing repository's unrelated evaluation-model migration remains out of scope.

Update SPEC.md and this plan when those implementation boundaries change. Never
replace a missing experiment with a fixture result or an unmeasured score with zero.
