# Task 6f93b2a1 - unified ref consolidation plan

Status: review
Owner: ChatGPT (architecture and documentation only)
Branch: docs/unified-ref-consolidation-plan
Base: 80c6e379106a73c047cd517e56207bc62d558d7f
Date: 2026-11-06
Reviewers: Drae; proposed independent execution reviewers Pi and OpenCode

## Request and scope

Evaluate bringing refwatch into the ref repository as a direct Discord API client; preserve YouTube/Reddit discovery and establish playlist policy; determine actual archive destinations before planning a lossless merge; add GitHub freshness checks with installation-aware upgrade guidance; provide a phased, verifiable Pi/OpenCode plan and root HANDOVER.md.

This task publishes planning documentation only. It does not authorize application changes, service restarts, live re-ingestion, data migration, package upgrades, release publication, private-history import, merge, or repository retirement.

## Deliverables

- [x] Proposed plan recorded in `docs/plans/unified-ref-consolidation.md`.
- [x] Pinned source findings distinguished from unverified runtime hypotheses.
- [x] Phase ownership, branch names, dependencies, constraints, tests and stop points specified.
- [x] Root `HANDOVER.md` established with bilateral coordination and evidence rules.
- [x] Migration, privacy, acknowledgment, dependency, release and rollback gates specified.
- [ ] Independent plan review completed; reviewer and evidence recorded.
- [ ] Proposed product decisions approved or amended by Drae.
- [ ] Applicable documentation merge authorization recorded and executed by the assigned agent.
- [ ] Post-merge scope, main state and authorized branch cleanup independently verified.

The checked boxes above attest only to documents published in this branch, not application implementation or acceptance. All implementation/production checkboxes in the master plan remain unchecked.

## Source inspection

- ref: `80c6e379106a73c047cd517e56207bc62d558d7f`.
- refwatch: `6697a9c4c5ce143e21caf027fdb2db40e420e373`.
- ol: `e2433f0861b64fb09cb08fcdf1b74e2251e8dc9b`.

Primary evidence is linked in the plan. No raw production data or secret-bearing configuration belongs in this repository.

Confirmed source issues include path initialization from package defaults, local bootstrap before ordinary API dispatch, process-local locking, inconsistent discovery entry points and playlist policy, and stdout-derived success. None proves the physical destination or loss mechanism of the reported OpenCRT capture. Runtime inventory is explicitly deferred to authorized P1.

## Verification performed and limits

GitHub reads were used to inspect the pinned source files and repository structure. Application code and live systems were not executed. An attempt to download source into the isolated container failed with `curl: (6) Could not resolve host: codeload.github.com`; therefore no local checkout-based full verification gate was run. Do not claim that tests passed.

The planning PR must show only this task file, `HANDOVER.md`, and `docs/plans/unified-ref-consolidation.md`. Repository readback and branch comparison establish publication and scope. CI status must be checked against the actual final PR head and reported separately; documentation inspection is not a substitute for the required gate before marking ready for implementation.

Plan introduced by `2f059ca40c8d8c6957107928145987919856c90b`; HANDOVER introduced by `3f38d7b21fc6791e05f0b792c0d1cb8b74ae8bb3`. The commit containing this task is identified by the PR head, not an invented self-referential SHA.

## Next action and stop point

Drae reviews the proposal and authorizes documentation merge/P0 as appropriate. Pi and OpenCode use section 13 of the plan for their first scoped prompts. No automatic progression to P1 or application implementation. Keep existing HANDOFF.md history intact; P0 reconciles the project index with HANDOVER.md.

Stop after publishing the documentation branch and draft review request. No main merge or production action in this planning task.
