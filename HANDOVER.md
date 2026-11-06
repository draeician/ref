# HANDOVER - unified ref consolidation

This is the bilateral communication log for Pi and OpenCode during the consolidation of ref, ref-api, and refwatch. Read [HANDOFF.md](HANDOFF.md) for the existing project record and [the complete plan](docs/plans/unified-ref-consolidation.md) for scope, evidence, decisions, phase gates, and acceptance criteria.

## Current state

- Date: 2026-11-06.
- Status: proposed plan published for review; implementation has not started.
- Planning branch: `docs/unified-ref-consolidation-plan`.
- Baseline main: `80c6e379106a73c047cd517e56207bc62d558d7f`.
- Plan introduced by commit: `2f059ca40c8d8c6957107928145987919856c90b`.
- Plan task: [.codex/tasks/review/6f93b2a1-unified-ref-consolidation-plan.md](.codex/tasks/review/6f93b2a1-unified-ref-consolidation-plan.md).
- Current owner: ChatGPT, architectural planning and source review only.
- Proposed implementation agents: Pi and OpenCode. Neither has claimed implementation work through this file yet.
- Authorized work in this planning branch: evaluation and documentation of the requested plan. No application implementation, production investigation via mutation, migration, deployment, package upgrade, repository-history import, release, or merge has been authorized by this document.
- Next action: Drae reviews the proposed decisions and authorizes the documentation merge/P0 scope. Pi claims P0 only after that authorization. P1 live read-only inventory has its own explicit scope gate; do not advance automatically.

## Communication contract

`HANDOVER.md` is the detailed bilateral execution log for this initiative. `HANDOFF.md` remains the project-level index and historical record; P0 appends a concise pointer and reconciles outdated current-state text without erasing historical evidence. The master checklist lives only in the plan; do not create a competing completion checklist here.

Before work, read root AGENTS.md and project_spec.md when present, `.codex/AGENTS.md`, relevant task files, HANDOFF.md, this file, and the plan. At the inspected baseline the root AGENTS.md and project_spec.md do not exist; P0 reconciles entrypoint documentation. Do not guess that missing files or unavailable tools were inspected.

Claim one authorized task before coding. Use a dedicated branch from updated main and a separate worktree for parallel work. Record owner, branch, scope and stop point. Do not touch another agent's task without explicit reassignment. Task directory and status must agree: `.codex/tasks/wip/` -> `review/` -> `done/`. Do not reorganize historical tasks as unrelated cleanup.

Each owner commits and pushes intended changes, records the tested SHA and exact verification evidence, requests independent review and stops. The other agent reviews the actual diff and independently checks behavior. ChatGPT reviews pushed evidence before recommending acceptance; Drae controls authorization. A failing required check blocks review. Unavailable or unrun checks are gaps, not passes. No weakening checks to make a task green.

Only after approval may the assigned agent move a task to done, merge, push main and remove the authorized feature branch/worktree. Deployment, data mutation, release publication and retiring old repositories/installations require the applicable explicit approval. Never force-push shared history, discard unrelated work, or install globally with pip.

Append accepted consequential decisions to `docs/DECISION_JOURNAL.md` when P0 establishes it. Proposals in the plan are not accepted decisions. Keep all tokens, private channel content, raw production logs, archives and machine-local sensitive manifests outside Git. Public evidence must be sanitized.

Shared-file ownership is serialized. Pi and OpenCode append their own entries in their task branches. The integration owner preserves both entries during reconciliation. Do not overwrite the other agent's evidence or claim approval on their behalf.

## Entry template

```text
### <UTC timestamp> - <agent> - <CLAIM | WIP | BLOCKED | REVIEW-REQUEST | REVIEW | APPROVED | CLOSED>
Task:
Owner:
Authorized scope / authorizer:
Branch / worktree:
Starting SHA:
Work done:
Decisions or questions:
Verification commands and exact outcomes:
Tested commit SHA:
Pushed commit SHA:
Evidence paths / CI / PR:
Failures, blockers and limits:
Independent reviewer and outcome:
Next action:
Stop point:
```

The tested SHA identifies code actually verified. A commit cannot contain its own final hash in its contents; record subsequent documentation commits separately or use PR/CI metadata to identify the final head. Do not mislabel a prior run as verification of later code changes.

## Bilateral log

### 2026-11-06 - ChatGPT - REVIEW-REQUEST (planning)

Task: `6f93b2a1-unified-ref-consolidation-plan`.

Work done: reviewed the pinned ref, refwatch and ol sources; documented current write/routing/discovery paths, uncertain runtime topology, proposed single-writer architecture, playlist context rules, structured persistence receipts, direct Discord HTTP integration, attachment/statement preservation, privacy-gated import, lossless offline reconciliation, install-aware GitHub update checks, phased ownership, verification gates, deployment and rollback requirements. Published the plan on a documentation-only feature branch.

Important findings: archive globals come from bundled defaults; ordinary CLI startup can touch a local archive before API routing; the existing archive lock is process-local; Reddit recursion bypasses the API-level child policy; playlist behavior differs by entry point; both API and watcher success classification depend on printed output. These are source findings, not proof of the OpenCRT incident's runtime cause.

Evidence: the plan's pinned source references and the operator-provided journal discussed during planning. The raw production journal is intentionally not copied into this public repository.

Verification limits: source inspection only. No SSH/runtime archive inspection and no application tests executed during the review. The container could not resolve the public source-download host, so a local checkout/test gate was not available. Repository readback, changed-file scope and any CI evidence for this planning branch are reported in its PR; do not infer test success from source review.

No application code, live service configuration, archive data, package installations, Discord messages or old repository visibility was changed. No implementation phase is checked off. No claim is made that all existing archives are already unified or that a data migration is definitely required.

Next action: review the planning PR and approve/amend P0 decisions. Pi then owns the authorized documentation-contract phase; OpenCode independently reviews it. Stop before application implementation and production changes.
