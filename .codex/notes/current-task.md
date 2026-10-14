# Current task — ref-cli

- **State:** QA FAILED on PR #16 at reviewed SHA `d2b2a028253cbc09dd2dc94b28696ee139b3eafb`; probe-ownership correction IMPLEMENTED on the same branch/PR and rewound original feature is NOT accepted — awaiting independent re-review. Not merged or deployed.
- **Active development branch:** `fix/issue-15-ref-api-disconnect`; default branch `main` remains at `276ea2afdfd8ea401f1849ba50b847225487f9ee`.
- **Current corrective task:** [e6c9124b — Issue #15 probe-ownership and disconnect-claims correction](../tasks/e6c9124b-issue-15-probe-ownership-correction.md).
- **Original task:** [b3e718cf — Issue #15 incident/cooldown](../tasks/b3e718cf-issue-15-ref-api-disconnect.md), remains awaiting acceptance; do not advance roadmap.
- **Pull request:** https://github.com/draeician/ref/pull/16 (draft; updated on this same PR).
- **Incident:** https://github.com/draeician/ref/issues/15
- **Handoff:** [agent-handoff.md](agent-handoff.md).

## Correction implemented (implementer's turn, not yet independently re-reviewed)
- Cross-process single-flight recovery-probe lease (bounded, atomic, in the cooldown marker under the short file lock) — exactly one probe after expiry across threads AND independent OS processes; others route through queue-first/pending-file fallback; routine (no-marker) fetches are never serialized.
- Epoch/owner-aware cooldown clearing: a stale successful probe can never erase a newer cooldown; a confirmed block always takes precedence (never extends an active cooldown; one transition WARNING per epoch).
- Cooldown re-check before the enhanced→legacy fallback; bounded lease/backoff so a crashed owner or failed probe never wedges or stampedes ingestion; hardened marker parsing (malformed/non-finite/implausible metadata never throws).
- Claims corrected: the cooldown reduces provider load; it does NOT fix the systemd stop-in-flight RemoteDisconnected, which remains an OPEN production validation gate.

## Quality gate
- Corrected provider concurrency tests (threads + real OS processes) demonstrated failures at the reviewed SHA (two probes) and pass after the fix; focused/full pytest and compileall green; new remote SHA must have both push and PR GitHub Actions green; then independent re-review. Production stop/restart validation remains unapproved and open.

## Next actor
Architect: independently re-review corrected draft PR #16; do not merge/deploy until user-authorized cutover plus live stop-in-flight validation.
