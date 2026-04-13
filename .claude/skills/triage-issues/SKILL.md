---
name: triage-issues
description: >
  Deep triage pass over MemPalace/mempalace issues and PRs that goes beyond
  what sync_issues.py can do with heuristics alone. Re-reads issue
  bodies and PR diffs to produce: real severity assessment, semantic
  deduplication, malicious-PR review, and a ranked next-action list.
  Writes TRIAGE.md. Use when the user says "triage issues", "triage
  report", invokes /triage-issues, or asks for a deep review of the backlog.
---

# Deep Triage — MemPalace Issues & PRs

You are running a full triage pass on `MemPalace/mempalace`. The heuristic
script `sync_issues.py` does keyword classification and pattern-based
PR flagging; your job is to do the part heuristics cannot: actually read
bodies and diffs, judge context, and produce an actionable report.

**Output:** `TRIAGE.md` (overwrite, don't version). Keep it short and
decision-oriented — not a dump of everything you read.

**Scope by default:** open issues classified CRITICAL or HIGH by the
heuristic, plus all open PRs flagged for review. If the user passes a
different scope (e.g., "just PR review", "include medium"), follow that.

## Workflow

### Step 1 — Refresh heuristic data

Run `python sync_issues.py` to regenerate `ISSUES.md`. If the
file is less than 1 hour old, it's fine to skip (use `--no-cache` if you
suspect staleness). Read `ISSUES.md` to get the current CRITICAL /
HIGH lists and flagged PRs.

### Step 2 — Real severity assessment

For each issue in CRITICAL + HIGH:

1. Fetch the body: `gh issue view <N> --repo MemPalace/mempalace --json title,body,labels,state,comments`
2. Read it. Decide:
   - Is this an actual defect, or a feature request / RFC / question?
   - Is it reproducible? Does it have steps / versions / stack traces?
   - How bad is it in practice? (e.g., "data gone after upgrade" is
     catastrophic; "status count off by 1" is cosmetic)
   - Is there an in-flight PR addressing it? (check `ISSUES.md`
     "Recently merged" and "Open PRs" sections, or search:
     `gh pr list --repo MemPalace/mempalace --search "in:title,body <N>"`)
3. Assign a **revised severity**: CRITICAL / HIGH / MEDIUM / NOT-A-BUG.
4. Write 1-2 sentence rationale per item.

Stop re-assessing after ~20 items or when you've covered all true
CRITICAL+HIGH. If you need to stop early, say so in the report.

### Step 3 — Semantic deduplication

Look at the revised CRITICAL+HIGH list. Find clusters — issues that
describe the *same underlying bug* reported by different people. Common
patterns to watch for in MemPalace:

- ChromaDB version pin chaos (0.6/1.x compatibility) — #686, #445, #469
  have been grouped before; check for new entries.
- HNSW index bloat / corruption / segfault — #344, #357, #521, #525
- Windows CJK / Unicode encoding — #503, #363, #535
- Hook script path / python3 resolution — #378, #398, #408, #545, #650
- Silent MCP failures / pagination — #338, #478, #477
- Chunk size / embedding model mismatch — #390

For each cluster: pick a **canonical** issue (the clearest / most
actionable / oldest open), list the dupes, and note the consolidated
scope. Do not auto-close anything — the output is a recommendation.

### Step 4 — PR malicious review

Read the "PRs flagged for review" section of `ISSUES.md`. For each
flagged PR, you must decide if the heuristic red flags are real.

For every flagged PR:
1. Fetch the diff: `gh pr diff <N> --repo MemPalace/mempalace | head -400`
   (head is usually enough; fetch full if you need more)
2. Fetch metadata: `gh pr view <N> --repo MemPalace/mempalace --json title,body,author,files,additions,deletions`
3. Judge each flag:
   - `curl | sh` — is it the legit uv installer in docs, or actual code
     that executes on install?
   - `eval()` — is it in a benchmark/test evaluator, or user-input-driven?
   - URL to unfamiliar domain — is it a real third-party service (ChatGPT,
     Ollama, etc.) or data exfiltration?
   - Touches `pyproject.toml` — does it pin/unpin deps for a real reason,
     or sneak in a new dep?
   - Touches hook scripts — is it fixing Windows python3 resolution, or
     inserting an exec step?
4. Tag each PR:
   - **BENIGN** — red flags are false positives (most common outcome)
   - **REVIEW-NEEDED** — legit concerns, maintainer should read carefully
   - **SUSPICIOUS** — likely malicious; recommend close/block

Write a one-line verdict per PR. If you tag SUSPICIOUS, be explicit about
what you saw.

### Step 5 — Next-action ranking

Given:
- Revised CRITICAL/HIGH issues (step 2)
- Consolidated clusters (step 3)
- Open PRs addressing them (cross-reference by `#NNN` in PR titles/bodies)
- What was recently merged (last 14 days — from `ISSUES.md`)

Produce **Top 10 actions** the maintainer should take next. Rank by
(severity × blast radius) / effort. For each action:

- What the action is (close dupes, merge PR, revert, investigate, file
  missing issue, etc.)
- Which issues/PRs it resolves
- Why now — blocking what? affecting how many users?
- Effort estimate in rough buckets: trivial / small / medium / large

### Step 6 — Write `TRIAGE.md`

**Every issue or PR reference must be a markdown link to GitHub.** Use the
format `[#NNN](https://github.com/MemPalace/mempalace/issues/NNN)` — GitHub
redirects `/issues/NNN` to `/pull/NNN` automatically when the number is a
PR, so one URL pattern covers both. This applies to the TL;DR, severity
tables, cluster lists, PR triage, and next-action lines — anywhere you
name an issue or PR.

Structure:

```markdown
# MemPalace Triage Report

> Generated YYYY-MM-DD from ISSUES.md and live issue/PR bodies.
> Scope: open CRITICAL + HIGH + flagged PRs.

## TL;DR

3-5 bullets. What needs attention this week. Be specific.
- **ESCALATE [#27](https://github.com/MemPalace/mempalace/issues/27)** — <reason>

## Revised Severity

| # | Title | Heuristic | Revised | Rationale | In-flight |
|---|---|---|---|---|---|
| [#NNN](https://github.com/MemPalace/mempalace/issues/NNN) | ... |

## Issue Clusters

### Cluster: <short name>
- Canonical: [#N](https://github.com/MemPalace/mempalace/issues/N) — <why>
- Dupes: [#A](...), [#B](...), [#C](...)
- Scope: <one line>
- Action: <close dupes / file tracking issue / etc>

(repeat)

## PR Triage

### BENIGN (N)
- [#N](https://github.com/MemPalace/mempalace/issues/N) `branch` — <why the flags are false positives>

### REVIEW-NEEDED (N)
- [#N](...) `branch` — <real concerns>

### SUSPICIOUS (N)
- [#N](...) `branch` — <what's wrong>

## Top 10 Next Actions

1. **<action>** — Resolves [#A](...), [#B](...). Reason: <one line>. Effort: trivial.
2. ...
```

Overwrite `TRIAGE.md`. Do not keep dated copies.

## Notes

- **Don't fabricate severity.** If the issue body is empty and title is
  ambiguous, say "insufficient info" rather than guessing.
- **Don't auto-close.** This is a recommendation report; the user acts.
- **Cache is your friend.** Don't refetch what `ISSUES.md` already
  has — only fetch bodies/diffs for items that need real reading.
- **If you hit rate limits**, stop gracefully and note in the report what
  you didn't finish. Don't retry in a tight loop.
- **Cross-reference `develop` branch** to distinguish fixes already landed
  from ones still in open PRs. Locally, if a maintainer clone of
  `MemPalace/mempalace` is available, use `git log --oneline develop -50`
  on it. Remotely, query the upstream via `gh` / MCP tools instead.
- **Tool availability varies.** Use `gh` CLI if available; otherwise fall
  back to MCP GitHub tools (`mcp_github_list_issues`, `mcp_github_list_pull_requests`,
  `mcp_github_issue_read`, `mcp_github_pull_request_read`) or stdlib urllib
  against the public API. Pick what works in the current session.

## Common mistakes to avoid

- Regenerating `ISSUES.md` every time when it's already fresh
  (wastes 2-3 minutes of `gh pr diff` calls).
- Marking a PR SUSPICIOUS just because the author is a first-time
  contributor with a large diff. First-time contributors built 80% of
  the open PRs. Require actual evidence of bad intent.
- Burying the TL;DR. The user opens this report to decide what to do
  TODAY — the first 100 lines should give them that.
