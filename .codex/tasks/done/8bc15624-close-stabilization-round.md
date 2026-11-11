# [ops] Close the ref stabilization round

- **Task ID:** `8bc15624`
- **Owner:** OpenCode
- **State:** DONE
- **Lifecycle:** `.codex/tasks/wip/` → `.codex/tasks/review/` → `.codex/tasks/done/`; this record is in `.codex/tasks/done/` after PR #41 was reviewed, merged, and post-merge CI passed.
- **Branch:** `chore/close-stabilization-round` (merged and deleted)
- **Base:** `origin/main` = `b9bbffac64ff84f4c25ecd5053c03eb6d25d4d96`
- **Related tasks:** `19294572` (DONE), `7d2c9e41` (remains REVIEW)
- **Delivery PR:** [#41](https://github.com/draeician/ref/pull/41) — merged.
- **Merge commit:** `bcf864e775626004215236e8f93341feb453df73`.
- **Closure branch:** `docs/close-stabilization-round-8bc15624` (docs-only
  closure PR; not merged).
- **Authorization:** Repository documentation, task lifecycle, and Git housekeeping
  only. No production changes, mounts, service restarts, queue/archive
  modifications, backlog replay, new features, or deletion of unmerged branches.

## Claim

```
[CLAIM] 8bc15624 Close the ref stabilization round
repo: draeician/ref@chore/close-stabilization-round
actor: OpenCode  role: Housekeeping/documentation
task-file: .codex/tasks/wip/8bc15624-close-stabilization-round.md
plan:
- Record cancellation of the additional NFSv3 producer mount
- Preserve existing NFSv4.2 producer and NFSv3/NLM worker mounts
- Close completed task 19294572; keep 7d2c9e41 in REVIEW
- Audit and classify branches without deleting unmerged work
- Record actionable remaining work and verification evidence
- Open a docs-only housekeeping PR; stop for review
```

## Scope

- Record the final stabilization architecture decision in `HANDOFF.md`, the
  append-only Decision Journal, and both NFS investigation documents.
- Reconcile task `19294572` to `done/` with State `DONE`.
- Keep task `7d2c9e41` in `review/` with State `REVIEW`.
- Classify local and remote branches; delete nothing unmerged.
- Record actionable follow-ups without authorizing implementation.
- Run documentation, test, lint, syntax, and consistency checks.

## Acceptance checks

1. The additional NFSv3 producer mount is explicitly **superseded and not
   authorized**; the existing NFSv4.2 producer and NFSv3/NLM worker mounts are
   retained; `/mnt/ref-queue-v3` is not installed; queue identity/UUID and NFS/NLM
   safety validation are preserved.
2. The investigation documents and HANDOFF preserve historical evidence while
   marking the proposal superseded.
3. The Decision Journal records the decision append-only.
4. Task `19294572` is in `.codex/tasks/done/` with State `DONE` and verified
   completion evidence.
5. Task `7d2c9e41` remains in `.codex/tasks/review/` with State `REVIEW`.
6. Branch classifications are recorded; `docs/unified-ref-consolidation-plan`
   (draft PR #29) and `fix/youtube-auto-show-notes-api` (unmerged divergent work)
   are preserved.
7. Remaining work is recorded as follow-ups, not authorization.
8. Verification includes tests, lint, syntax, docs checks, `git diff --check`,
   secret scan, task/path consistency, and no production-change evidence.
9. A docs-only housekeeping PR is open with exact-head CI passing; the task is in
   `review/`; nothing is merged.

## Preflight

- Working tree clean on `main` at `b9bbffac64ff84f4c25ecd5053c03eb6d25d4d96`.
- `origin/main` fetched and equal to local `main`.
- No `AGENTS.md` or `project_spec.md` exists in the repository root; the
  applicable instructions are `.codex/AGENTS.md` and
  `.codex/AGENTS_WORKFLOW.md`.
- The Decision Journal is the append-only
  `## 4. Architectural decisions (Decision Journal)` section in `HANDOFF.md`.
- Task records read: `19294572-nfs-v3-producer-cutover-preflight.md` and
  `7d2c9e41-deploy-remote-api-queue-fix.md`.

## Final architecture decision

The additional NFSv3 producer mount is **cancelled, superseded, and not
authorized**:

- Keep the existing NFSv4.2 producer mount on `minion-26`.
- Keep the existing NFSv3/NLM worker mount on `aether`.
- Do not install `/mnt/ref-queue-v3`.
- Do not weaken NFS/NLM safety validation.
- Preserve the shared queue identity/UUID
  `8c6fc098-8cbe-41ae-9689-dd759797a582`.

Cross-protocol producer safety remains **unproven** and requires a separate
read-only audit; this round does not claim it has been demonstrated.

## Branch audit

| Branch | Classification | Evidence | Action |
| --- | --- | --- | --- |
| `main` | Canonical | `b9bbffa`; equals `origin/main` | Keep |
| `docs/unified-ref-consolidation-plan` | Open draft PR #29 | 3 commits ahead / 44 behind; not merged | Preserve |
| `fix/youtube-auto-show-notes-api` | Unmerged divergent work | 6 commits ahead / 144 behind; no PR; all six commits absent from `main` (`git cherry` all `+`) | Preserve pending separate review |

No merged housekeeping branch was eligible for deletion. The two preserved
branches are not authorization to merge or delete them.

## Remaining work

1. Run a separate read-only audit of cross-protocol producer safety; do not claim
   it is proven.
2. Investigate the origin of the 1,373 pending `origin=ref`, `priority=20` jobs.
3. Investigate the recreated 529-line `transcript-pending.md`; do not replay or
   delete it.
4. Track worker GPU crashes/core-dumps and empty-transcript failures.
5. Complete the outstanding remote-client deployment, including nomnom access.
6. Design a safe historical transcript recovery path; no bulk replay.
7. Review the existing unrelated GitHub issues (#17, #12, #4, #3) and draft PR
   #29 separately.

These are follow-ups only, not authorization to implement them.

## Verification

All commands were run from the repository root on branch
`chore/close-stabilization-round`.

### Tests

```bash
PYTHONPATH=src uv run --no-project --python 3.13 --with pytest --with httpx \
  --with fastapi --with 'uvicorn[standard]' --with requests \
  --with beautifulsoup4 --with python-dotenv \
  --with google-api-python-client --with pyyaml --with colorama --with yt-dlp \
  --with youtube-transcript-api --with argcomplete \
  python -m pytest -q
```

Result: **597 passed, 1 warning** (upstream `StarletteDeprecationWarning` about
`httpx`/`TestClient`; unrelated to this diff).

### Syntax and lint

```bash
python3 -m compileall -q src tests          # ok
uvx ruff check --target-version py312 --select E9,F63,F7,F82 src tests
```

Result: `compileall` passed; targeted ruff gate **All checks passed** on Python
3.12 (the CI target). An initial ruff run without `--target-version` inferred
Python 3.7 from package metadata and reported false syntax errors for `:=` and
parenthesized `with`; re-running against the CI target passed.

Limitation: the full default ruleset
(`uvx ruff check --target-version py312 src tests`) reports **926 pre-existing**
errors across the existing codebase. This documentation/task-only diff does not
attempt to fix them; the CI syntax/undefined-name gate is used instead.

### Documentation checks

- Markdown fences balanced in every changed Markdown file: `HANDOFF.md` (2),
  both investigation documents (48 and 152), both task records (2), and this
  task (2). Verified with a Python fence-parity check over all six files.
- No lingering `review/` path for `19294572`; the only references are the
  historical merge-closure note in `HANDOFF.md` and the preserved preflight
  claim block inside the task record.

### Repository hygiene

```bash
git diff --check
```

Result: clean.

- Secret scan over `git diff` for private keys, AWS/GitHub/Slack/OpenAI-style
  tokens, and `password`/`token` assignments: **no credential-shaped matches**.
- Production-change scan over changed paths: **no** production config, service,
  mount, queue, or archive paths changed. The diff is documentation and task
  metadata only.
- Task path/state consistency:
  - `.codex/tasks/done/19294572-...md` exists with State `DONE`;
  - `.codex/tasks/review/7d2c9e41-...md` exists with State `REVIEW`;
  - no copy of `19294572` remains in `review/`;
  - at the time of PR #41, this task was in `review/` with State `REVIEW`;
    it moved to `done/` with State `DONE` only after merge and post-merge CI
    (see below).
- Branch preservation: `origin/docs/unified-ref-consolidation-plan` =
  `ad2aae34f222f32ea02ab3386898cf559ec87823` (draft PR #29) and
  `origin/fix/youtube-auto-show-notes-api` =
  `8446400bf902746282c5c198edc5d8e73a53e153` (six unmerged divergent commits)
  were unchanged at the time of PR #41. No branch was deleted during that review
  round; only the merged housekeeping branch was deleted afterward (see below).

### Limitations

- No live host, mount, service, queue, or archive access was used. Host findings
  remain the historical read-only observations already recorded in the
  investigation documents.
- Cross-protocol producer safety is **not** proven by this round.
- Branch CI for this branch is confirmed after push and recorded on the
  housekeeping PR; it does not substitute for review by ChatGPT or merge approval
  by Drae.

### Merge, post-merge CI, and cleanup (2026-11-10/11)

- PR #41 head matched the approved HEAD
  `d663ac13ed3725320a53dbd8bb79190f980539a4`; PR state `OPEN`, mergeable
  `MERGEABLE`, merge state `CLEAN`; exact-head CI run `42925244767` (`tests`,
  `pull_request`) completed **success**.
- Merged with a **normal merge commit** (no squash/rebase/force-push):
  `bcf864e775626004215236e8f93341feb453df73`, parents
  `b9bbffac64ff84f4c25ecd5053c03eb6d25d4d96` and
  `d663ac13ed3725320a53dbd8bb79190f980539a4`. The approved head is an ancestor
  of `origin/main`.
- Post-merge `main` CI: run `42928999802` (`tests`, `push`) completed **success**
  on `bcf864e775626004215236e8f93341feb453df73`. GitHub created the push run
  about 11 minutes after the merge; it was not skipped.
- Branch cleanup: local `chore/close-stabilization-round` deleted with
  `git branch -d`; remote `origin/chore/close-stabilization-round` deleted and
  confirmed absent with `git ls-remote --heads origin`. Only `main` and the two
  preserved branches remain.
- Preserved as required: `7d2c9e41` in `review/` with State `REVIEW`, draft PR
  #29 (`docs/unified-ref-consolidation-plan`), and
  `fix/youtube-auto-show-notes-api`.

## Result

Documentation-only stabilization closure, merged via PR #41:

- `HANDOFF.md` records the final decision, the branch audit, the follow-up list,
  and a new append-only Decision Journal item 9.
- Both NFS investigation documents retain their historical observations and
  proposed procedures but are explicitly marked **superseded / not authorized**.
- `19294572` is closed as `DONE` with verified PR #39/#40 merge and CI evidence.
- `7d2c9e41` remains in `review/` with State `REVIEW`; production work is not
  marked DONE.
- No mount was installed and no production change was made.
- The merged housekeeping branch was deleted locally and remotely after merge;
  no unmerged branch was deleted.

This task is `DONE` after review, merge, and successful post-merge CI. A separate
docs-only closure PR records the merge/CI/cleanup evidence; it remains open for
ChatGPT review and is **not** merged by this task.
