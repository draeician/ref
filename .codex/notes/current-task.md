# Current task — ref-cli

- **State:** QA FAILED on PR #16 at reviewed SHA `d2b2a028253cbc09dd2dc94b28696ee139b3eafb`; narrow correction QUEUED, not merged or deployed.
- **Active development branch:** `fix/issue-15-ref-api-disconnect`; default branch `main` remains at `276ea2afdfd8ea401f1849ba50b847225487f9ee`.
- **Current corrective task:** [e6c9124b — Issue #15 probe-ownership and disconnect-claims correction](../tasks/e6c9124b-issue-15-probe-ownership-correction.md).
- **Original task:** [b3e718cf — Issue #15 incident/cooldown](../tasks/b3e718cf-issue-15-ref-api-disconnect.md), remains awaiting acceptance; do not advance roadmap.
- **Pull request:** https://github.com/draeician/ref/pull/16 (draft; update this same PR).
- **Incident:** https://github.com/draeician/ref/issues/15
- **Handoff:** [agent-handoff.md](agent-handoff.md).
- **Independently verified at reviewed SHA:** branch discipline preserved; 307 tests passed in each completed GitHub Actions push/PR job on the exact reviewed SHA. Passing CI does NOT cover two cooldown ownership races.
- **Blocking findings:** probe lock released before provider call, older success can erase a newer ban, malformed marker metadata may throw, and PR language overstates resolution of systemd stop-in-flight HTTP disconnect.
- **Quality gate:** corrected provider concurrency tests (threads + independent processes) → focused/full pytest and compile → new remote SHA with both green workflows → independent QA. Production stop/restart validation remains unapproved and open.
- **Next actor:** OpenCode implementer reads correction task and uses existing branch + draft PR. No direct `main` push, merge or production change.

## Recovery

Read `.codex/AGENTS.md`, `.codex/AGENTS_WORKFLOW.md`, `.codex/modes/CODER.md`, `README.md`, `docs/LOCAL_TRANSCRIBE_QUEUE_INTEGRATION.md`, this pointer, both task files and the handoff. Check branch state and WIP before touching any local checkout. Use the correction task as current work until independent review passes.
