# Codex Web Agent + GitHub Workflow Guide

A practical guide to working with Codex web agents, GitHub issues, pull requests, and local testing.
Use this as a reference when debugging, iterating, or verifying fixes in your projects.  We will be
using my 'ref' repo as an example below.

---

## 🧭 0. Notation / Placeholders

* `<REPO>` — e.g. `draeician/ref`
* `<ISSUE_NUMBER>` — e.g. `7`
* `<PR_NUMBER>` — e.g. `8`
* `<BRANCH>` — e.g. `codex/add-pytest-module-for-reference-sanitization`
* `<URL>` — a test input (e.g. a YouTube link)

Retrieve key info:

```bash
gh pr list -L 10                     # lists PR numbers & branches
gh pr view <PR_NUMBER> --json headRefName  # shows branch name
```

---

## 🐛 1. Create the Issue

Create a GitHub issue before asking Codex to fix a bug. Include:

* **Title:** concise problem summary
* **Reproduction steps:** commands, inputs, environment info
* **Expected vs. actual behavior**
* **Logs/evidence:** copy/paste snippets
* Add labels like `codex`, `bug` and assign the agent if possible.

---

## 🤖 2. Start the Codex Task

From the Codex UI, **click “Ask”** (not “Code”) and write:

> “Work on `<REPO>` Issue #`<ISSUE_NUMBER>`. Reproduce the bug, add a failing test, implement a fix, run tests, and open a **Draft PR** with `Fixes #<ISSUE_NUMBER>` in the body. Request my review before marking ready.”

Why “Ask”?

* ✅ Continues or starts a *task* tied to the repo.
* ❌ “Code” is one-off generation and breaks the task context.

---

## 📦 3. Create the Draft PR

Once Codex proposes changes, create a **Draft PR**.
Make sure the PR body contains:

```
Fixes #<ISSUE_NUMBER>
```

This links the PR and auto-closes the issue upon merge.

---

## 🧪 4. Local Verification Loop

### A. Pull the PR Branch

```bash
git fetch origin --prune
gh pr checkout <PR_NUMBER>   # preferred
# or:
git fetch origin pull/<PR_NUMBER>/head:codex-pr-<PR_NUMBER>
git switch codex-pr-<PR_NUMBER>
```

Check current branch:

```bash
git branch --show-current
```

---

### B. Setup a Virtual Environment

If you see “externally-managed-environment”:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r requirements-dev.txt || true
```

Install any missing packages (e.g. `bs4`, `youtube-transcript-api`):

```bash
pip install beautifulsoup4 youtube-transcript-api rich pytest
```

---

### C. Reproduce the Bug on `main`

```bash
git switch main
git pull
pytest -q
```

Expect the bug or failing test.

---

### D. Test the Fix Branch

```bash
git switch <BRANCH>
pytest -q
pytest -q tests/test_references_sanitization.py   # run only new test if needed
```

---

### E. Manual CLI Reproduction

```bash
python -m ref_cli.cli -v "<URL>"
```

Inspect output:

```bash
grep -nA4 -B2 "<unique-string>" ~/references/references.md
```

✅ Expect: short, sanitized message (e.g., `Transcript unavailable`)
❌ Avoid: provider URLs, prompt text, or support instructions.

---

## 🔁 5. Feedback & Iteration

If the fix is incomplete:

* Comment directly **in the PR** (preferred) or in the **task chat**.
* Include:

  * Command(s) you ran
  * Python version & package versions
  * Output snippets showing the bug
  * **Clear acceptance criteria**

Example:

> “I ran `python -m ref_cli.cli -v "<URL>"` on branch `<BRANCH>`.
> `references.md` still contains provider text (`Please create an issue...`).
> Please sanitize all transcript failure messages to short, neutral strings and update tests accordingly.”

---

## 🛠️ 6. Handling Common Scenarios

| Situation                                  | Action                                                                                                                                        |
| ------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| **Diff shows in Codex UI but not locally** | Codex hasn’t pushed from its sandbox → click **Create draft PR** in Codex UI, then `git fetch origin && gh pr checkout <PR_NUMBER>`           |
| **“Start task” appears again**             | Task ended. Start a new one with:<br>`Start a new writable iteration on branch <BRANCH> (PR #<PR_NUMBER>). Do not create a new branch or PR.` |
| **Tests fail with missing modules**        | `pip install -e . && pip install -r requirements-dev.txt`                                                                                     |
| **CLI subcommand not recognized**          | Check `--help` and adjust command syntax (e.g. `python -m ref_cli.cli -v "<URL>"`)                                                            |
| **Branch name unknown**                    | `gh pr view <PR_NUMBER> --json headRefName`                                                                                                   |
| **PR not linked to issue**                 | Edit PR description → add `Fixes #<ISSUE_NUMBER>`                                                                                             |
| **Agent keeps opening new PRs**            | Prefix instructions with:<br>`Push commits to existing branch <BRANCH> (PR #<PR_NUMBER>). Do not create a new branch or PR.`                  |
| **Codex task is QA-only / read-only**      | Archive it. Start a new task with “Start a new **writable** iteration…”                                                                       |

---

## 🧹 7. Cleaning Up Stale Tasks

If multiple unfinished tasks reference the same PR, archive the old ones.
They do **not** affect the code or PR — just Codex’s internal state.
This helps Codex stay focused on your current iteration.

---

## ✅ 8. Final Merge Checklist

* [ ] Tests pass locally (`pytest -q`)
* [ ] Manual CLI run produces sanitized output
* [ ] No provider guidance in `references.md`
* [ ] CI is green
* [ ] PR body contains `Fixes #<ISSUE_NUMBER>`
* [ ] Scope limited to this bug
* [ ] PR is marked **Ready for review**

---

## 📎 9. Quick Command Reference

```bash
# List PRs
gh pr list -L 10

# Checkout PR locally
gh pr checkout <PR_NUMBER>

# Setup env
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Run tests
pytest -q
pytest -q tests/test_references_sanitization.py

# Run CLI manually
python -m ref_cli.cli -v "<URL>"

# Inspect output
grep -nA4 -B2 "<unique-fragment>" ~/references/references.md

# Get PR branch
gh pr view <PR_NUMBER> --json headRefName

# Compare diff
git diff main..<BRANCH> --stat
```

---

### 🧠 Tips & Best Practices

* Always **start tasks with “Ask”**, not “Code.”
* Keep one active Codex task per PR. Archive old ones.
* Include `Fixes #<ISSUE_NUMBER>` in PRs to auto-close issues.
* Add acceptance criteria in feedback so Codex knows when it’s “done.”
* Use **Draft PRs** until you’ve validated the fix locally.
