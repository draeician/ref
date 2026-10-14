# Current task — ref-cli

- **State:** QUEUED; implementation not started or verified.
- **Active development branch:** `fix/issue-15-ref-api-disconnect` (never implement directly on `main`).
- **Starting main commit:** `276ea2afdfd8ea401f1849ba50b847225487f9ee`.
- **Task:** [b3e718cf — Issue #15 ref-api disconnect](../tasks/b3e718cf-issue-15-ref-api-disconnect.md).
- **Incident:** https://github.com/draeician/ref/issues/15
- **Handoff:** [agent-handoff.md](agent-handoff.md)
- **Quality gate:** initial root-cause investigation → minimal tested fix → full pytest/compile → draft PR → required GitHub Actions success on **final remote SHA** → independent architectural review. No merge/deploy until explicit user authorization.
- **Next actor:** OpenCode implementer; read task + repository instructions before coding.
- **Deferred:** asynchronous-ingest redesign, broad SSRF hardening, proxy rotation; see task file.

## Repository recovery

Read `.codex/AGENTS.md`, `.codex/AGENTS_WORKFLOW.md`, `.codex/modes/CODER.md`, `README.md`, `docs/LOCAL_TRANSCRIBE_QUEUE_INTEGRATION.md`, this file, the linked task and handoff; then inspect `git status`, remote heads, open PR and exact-SHA CI. Prior `main` includes PR #14 and must not be changed directly.
