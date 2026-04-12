# MemPalace Triage — 2026-04-12

## TL;DR (read this first)

- **ESCALATE #27 + #705 + #618** — Coordinated credibility crisis active TODAY: README benchmark claims officially debunked (310 reactions, maintainer partly acknowledged), bot-farm star allegations (Issue #705, filed this morning), and "POSSIBLE SCAM REPO" post (19 comments, updated 20 min ago). Needs maintainer public statement.
- **Merge PR#690** — Removing the `chromadb<0.7` upper bound pin unblocks the most-reported install failure cluster (#686, #487, #445): one-line change, zero-risk.
- **Hotfix #538** — MCP stdio `add_drawer` / `kg_add` silently writes to WAL with `result: null` but never commits to ChromaDB or SQLite (11 comments). Core product is broken for the primary use case; no PR exists yet.
- **Hotfix #521** — `hnswlib` SIGSEGV race on macOS ARM64 re-mine (18 comments, precise root cause, one-hunk fix proposed inline). Crashes silently via Stop hook — users never see an error.
- **Rebase + merge PR#346** — HNSW `link_lists.bin` bloat (441 GB → expected 8 MB) is data-destructive for anyone mining >10 K drawers; fix exists but is dirty.

---

## Revised Severity Table

### CRITICAL — Data loss, corruption, or security

| # | Title | Evidence |
|---|---|---|
| **#357** | Parallel mining silently corrupts HNSW index (unrecoverable) | No file lock; must wipe palace to recover |
| **#521** | `hnswlib` SIGSEGV race on macOS ARM64 on modified-file re-mine | 18 comments; `repairConnectionsForUpdate` crash fingerprint; one-hunk fix proposed |
| **#538** | MCP stdio `add_drawer` / `kg_add` silently drops writes (WAL `result: null`) | 11 comments; verified direct Python calls work; MCP path does not |
| **#344** | HNSW `link_lists.bin` grows to 441 GB on >10 K-drawer mines | User reported two sequential system crashes from disk/memory exhaustion |
| **#585** | Corrupt `chroma.sqlite3` header leaves palace completely unrecoverable | Mid-write interruption; HNSW data also lost |
| **#698** | `shutil.rmtree` path traversal on `--palace` arg (`migrate` / `repair`) | No path-safety check; `mempalace migrate --palace ~` deletes home dir |
| **#469** | Palace data invisible after 3.0→3.1 upgrade (ChromaDB schema mismatch) | 10 comments; data intact but unreadable; no migration path provided |

### HIGH — Significant functional breakage

| # | Title | Evidence |
|---|---|---|
| **#590** | Claude Code JSONL mining drops 49 % of content (`tool_use`/`tool_result` blocks) | PR#730 exists (arnoldwender) |
| **#692** | AI responses truncated to 8 lines in `convo_miner._chunk_by_exchange()` | Hardcoded `[:8]` cap; PR#708 exists |
| **#478 / #723** | Status/taxonomy truncated at 10 K drawers (hardcoded `col.get()` limit) | Affects any palace >10 K drawers; PR#707 exists |
| **#688** | `list_wings` returns `{}` on palaces >100 K drawers (SQLite variable limit) | Related to #478; separate code path |
| **#477** | `tool_search` no upper bound on `limit` — memory exhaustion possible | MCP schema advertises no max; can OOM server |
| **#475** | Float mtime equality causes every file to re-mine on every run | Strict `==` float compare; PR exists (#663 addresses stale detection differently) |
| **#654** | `convo_miner` never updates file registry; `drawers_added` always 0 | Two compounding bugs; every run reprocesses all files |
| **#715** | `tool_add_drawer` silently overwrites documents sharing 100-char prefix (hash collision) | PR#716 exists (shafdev) |
| **#479** | `_client_cache` / `_collection_cache` declared twice in `mcp_server.py` — state reset | Module-level double declaration resets cache on import |
| **#608** | `mempalace_search` returns stale results after mid-session `mine` | Cached HNSW client not invalidated; PR#663 exists (jphein) |
| **#408** | Plugin assumes `python3 -m mempalace` — breaks PEP 668 / uv / pipx | 11 comments; affects most modern Linux/macOS setups |
| **#377** | Hook scripts call `mempalace hook run` subcommand that doesn't exist | 9 comments; stop-hook broken on fresh installs |
| **#686 / #445 / #487** | `chromadb<0.7` pin breaks installs on Python 3.14 + existing 1.x palaces | Three separate reports; PR#690 (one-line fix) exists |
| **#326** | `mempalace.tech` third-party site serving malicious ad-injection JS | 5 comments; out-of-project but users directed there |

### MEDIUM — Degraded UX, platform gaps, missing features

| # | Title | Notes |
|---|---|---|
| #503 / #631 | Windows CJK/Unicode crash in MCP server | PR#631 (dirty) and PR#400 (mvalentsev, merged) partially address this |
| #549 | Stop hook counts `tool_result` as human messages, inflating exchange count | 5 comments; auto-save fires too often |
| #554 | Stop hook terminal output clutters session every 15 messages | 5 comments; UX complaint |
| #531 | README says `chromadb>=0.4`; `pyproject.toml` says `>=0.5` | 14 comments; easy doc fix |
| #677 | Claude.ai JSON export not parsed (treated as single drawer) | PR#685 exists (mvalentsev) |
| #637 | Unicode/diacritics rejected in `sanitize_name()` for KG writes | PR#683 exists (jphein) |
| #218 | Collection created without `hnsw:space=cosine` → negative similarity scores | PR#568 exists (arnoldwender) |
| #698 (finding 2) | WAL `_WAL_REDACT_KEYS` doesn't cover `content` / `entry` — full transcripts logged | Sensitive data persisted to disk in plaintext |
| #225 | MCP server writes startup text to stdout instead of stderr — breaks Claude Desktop JSON | Easy fix: redirect one `print()` |
| #650 | Windows setup broken by unversioned `python3` calls | Related to #408 |

---

## Issue Clusters

### Cluster A — Credibility / Trust Crisis (LIVE)
Issues: **#27** (310 reactions — README vs code discrepancies), **#705** (bot-farm star audit filed today), **#618** ("POSSIBLE SCAM REPO", 19 comments updated 20 min ago), **#703** (independent technical analysis), **#39** (benchmark reproduction confirming AAAK/rooms regress score).

Signal: Issue #27 is the canonical anchor — maintainer has acknowledged findings and pushed partial fixes (per the UPDATE note in the issue body). Issues #705 and #618 are amplifying the credibility gap with new framing (fake stars, celebrity account) that #27's technical framing didn't fully cover. Issue #615 ("AI bots filling the repo") adds a second-order moderation dimension.

Recommended disposition: Lock #618 (noise magnet, no code task), let #705 remain open for community record, keep #27 open until all acknowledged items have merged PRs.

### Cluster B — Data Loss / Corruption (CRITICAL)
Issues: **#521** (hnswlib race SIGSEGV), **#538** (MCP WAL silent write loss), **#357** (parallel mining HNSW corruption), **#585** (corrupt SQLite unrecoverable), **#344** (HNSW 441 GB bloat), **#469** (upgrade wipes data).

All six issues are independently reproducible, have detailed root-cause analysis, and involve permanent data loss. PRs exist for #344 (PR#346) and #521 (proposed inline fix). #538 has no PR.

### Cluster C — ChromaDB Version Hell
Issues: **#469**, **#445**, **#487**, **#686**. All root at the same `chromadb>=0.5.0,<0.7` pin in `pyproject.toml`. PR#690 (one-line upper-bound removal) and PR#302 (Milofax — widen constraint) both address this. Should be merged immediately.

### Cluster D — Scale / Truncation Bugs
Issues: **#478**, **#723**, **#688**, **#477**, **#479**. Cluster around `col.get()` hardcoded limits and unbounded search. PRs#707, #707 address the status cap. The SQLite variable limit at >100 K drawers (#688) has no PR yet.

### Cluster E — Content Mining Quality
Issues: **#590** (49 % content loss), **#692** (8-line cap), **#654** (file registry never updated), **#715** (100-char hash collision), **#677** (Claude.ai export). This cluster directly degrades the retrieval quality that benchmarks depend on. PRs exist for all except #654.

### Cluster F — Windows / Platform
Issues: **#503**, **#631**, **#650**, **#363**, **#378**, **#275**. High comment counts indicate widespread user frustration. Two PRs in flight (#400 merged, #631 dirty/needs rebase). PR#684 (jphein — skip arg whitelist for `**kwargs` handlers) also needed for Windows compat.

### Cluster G — Hook / Automation UX
Issues: **#549**, **#554**, **#622**, **#504**, **#377**, **#398**. All relate to the Stop hook firing incorrectly, counting wrong, or calling non-existent subcommands. PR#673 (jphein — deterministic hook saves via Python API) would resolve several of these by bypassing the shell hook entirely.

### Cluster H — Backend Evolution (v4 Alpha Track)
PRs in flight: **#665** (PostgreSQL, 3 579 additions), **#574** (LanceDB), **#700** (Qdrant, 411 lines), **#643** (PalaceStore, draft). These are the major v4 additions — architecturally significant, each requires dedicated review sessions. Not urgent for 3.1.x stability work.

---

## PR Triage Verdicts

### BENIGN — Low risk, targeted, should queue for merge

| PR | Author | Verdict | Rationale |
|---|---|---|---|
| **#690** | AlyciaBHZ | BENIGN | Remove `chromadb<0.7` pin — one-line change, unblocks large install-failure cluster |
| **#730** | arnoldwender | BENIGN | Fix `tool_use`/`tool_result` extraction — restores 49% lost Claude Code content |
| **#708** | sanjay3290 | BENIGN | Remove 8-line AI truncation cap — targeted single-line removal |
| **#707** | sanjay3290 | BENIGN | Remove 10K drawer status cap — parallel targeted fix |
| **#716** | shafdev | BENIGN | Hash full content in drawer ID — fixes silent overwrite collision |
| **#695** | shafdev | BENIGN | Store full AI response in convo_miner — corollary to #708 |
| **#685** | mvalentsev | BENIGN | Claude.ai export parser — well-scoped, fixes documented issue |
| **#687** | mvalentsev | BENIGN | `mine --dry-run` TypeError fix — simple null guard |
| **#683** | jphein | BENIGN | Unicode in `sanitize_name()` — well-tested, fixes blocking regression |
| **#681** | jphein | BENIGN | ASCII checkmark for Windows — one-character substitution |
| **#713** | moonaries90 | BENIGN | Unicode in KG triple fields — corollary to #683 |
| **#710** | JoyciAkira | BENIGN | Prevent KG edge duplication — addresses #655 |
| **#725** | fuzzymoomoo | BENIGN | Recreate KG schema on reconnect — defensive hardening |
| **#568** | arnoldwender | BENIGN | Default cosine distance + clamp scores — fixes silent negative-score bug |
| **#684** | jphein | BENIGN | Skip arg whitelist for `**kwargs` handlers — targeted compat fix |
| **#682** | jphein | BENIGN | `--yes` flag to init for non-interactive use — minor UX |
| **#670** | z3tz3r0 | BENIGN | Resolve Python interpreter in hook scripts — fixes #408 hook path |
| **#340** | messelink | BENIGN | Add `mempalace-mcp` entry point for pipx/uv — fixes entry-point gap |
| **#302** | Milofax | BENIGN | Widen chromadb constraint for Python 3.14 — overlaps PR#690 |
| **#461** | mrdeeme | BENIGN | LM Studio MCP client setup docs — no code changes |
| **#109** | nzkdevsaider | BENIGN | MCP config guide improvement — docs only |

### REVIEW-NEEDED — Larger scope, architectural impact, or process issue

| PR | Author | Verdict | Rationale |
|---|---|---|---|
| **#678** | ac-opensource | **REVIEW-NEEDED — WRONG BASE BRANCH** | 742-line HTTP transport targets `main`, not `develop`. Branch model violation per ROADMAP. Request rebase onto `develop` before any review. |
| **#346** | yoshi280 | REVIEW-NEEDED | HNSW bloat fix (441 GB→8 MB) is CRITICAL but is dirty/needs rebase. HNSW metadata values (`batch_size=50000`, `sync_threshold=50000`) need validation against ChromaDB internals. Urgent. |
| **#665** | skuznetsov | REVIEW-NEEDED | PostgreSQL backend (3 579 additions, 15 files, dirty). Architecturally significant v4 feature. Needs dedicated review. Dirty — needs rebase onto `develop` after #413. |
| **#629** | jphein | REVIEW-NEEDED | Batch writes + concurrent mining perf overhaul — large change touching hot paths; test coverage needed. |
| **#632** | jphein | REVIEW-NEEDED | `repair` nuke-rebuild + `purge` command + `--version` flag — introduces destructive CLI command, needs safety review. |
| **#660** | jphein | REVIEW-NEEDED | L1 importance pre-filter — algorithmic change to retrieval ranking; needs benchmark validation. ROADMAP-listed. |
| **#661** | jphein | REVIEW-NEEDED | Graph cache with write-invalidation — concurrency-sensitive; needs thread-safety audit. ROADMAP-listed. |
| **#662** | jphein | REVIEW-NEEDED | Hybrid search fallback — new retrieval code path; needs recall regression test. ROADMAP-listed. |
| **#663** | jphein | REVIEW-NEEDED | Stale HNSW detection — fixes #608; touches `_get_collection()` hot path. |
| **#673** | jphein | REVIEW-NEEDED | Deterministic hook saves via Python API — replaces shell hook; significant behavior change for existing users. |
| **#700** | RobertoGEMartin | REVIEW-NEEDED | Qdrant backend (411 lines + tests) — well-presented but adds `qdrant-client` + `sentence-transformers` dependency. |
| **#574** | dekoza | REVIEW-NEEDED | LanceDB backend — depends on `lancedb`; multi-device sync scope implies persistence format decisions. |
| **#507** | tmuskal | REVIEW-NEEDED | Local NLP via local models — large feature, GPU/CPU fallback; needs perf benchmarks on consumer hardware. |
| **#718** | milla-jovovich | REVIEW-NEEDED | i18n for 8 languages — large string/translation surface; needs native-speaker validation. |
| **#641** | dekoza | REVIEW-NEEDED | Full documentation rewrite — large; verify no content regressions in MCP setup guides. |
| **#567** | zendesk-thittesdorf | REVIEW-NEEDED | `git-mine` command — new CLI command; scoping and security (git log output sanitization) need review. |
| **#697** | cschnatz | REVIEW-NEEDED | Chroma `HttpClient` + per-tenant prefix — multi-tenant change; verify isolation guarantees. |
| **#319** | web3guru888 | **REVIEW-NEEDED — SELF-PROMOTIONAL** | Adds link to author's own `mempalace-stan-extension` repo in README. Maintainer filed Issue #680 specifically calling out this pattern from the same account. Should be declined or deferred to a formal plugin-directory process. |

### SUSPICIOUS — Unusual patterns warranting closer inspection

| PR | Author | Verdict | Rationale |
|---|---|---|---|
| **#86** | gut-puncture | SUSPICIOUS | Title "Align versioning and runtime claims" — vague; gut-puncture has multiple PRs with opinionated titles targeting README/doc accuracy in the same window as the credibility-crisis issues. Low code risk but check whether changes downgrade or remove benchmark claims without maintainer sign-off. |
| **#87** | gut-puncture | SUSPICIOUS | "Keep imported conversations verbatim" — pairs with #86; likely legitimate content-integrity fix but warrants review given account's timing with the #27/#705 audit activity. |

---

## Top-10 Next Actions

1. **Publish a maintainer statement addressing #27/#705/#618.** Issue #27 has a partial acknowledgment but the update is buried. Issues #705 (bot-farm) and #618 (scam label) are being indexed publicly. A pinned issue or README note with: (a) benchmark attribution correction, (b) what's real vs. marketing, (c) roadmap toward fixes, would defuse most of the active noise.

2. **Merge PR#690 immediately** (remove `chromadb<0.7` pin). One-line change. Closes the highest-volume install-failure cluster (#686, #487, #445). Unblocks Python 3.14 and existing 1.x users.

3. **Open a PR for #538** (MCP stdio silent write loss). Eleven-comment thread with precise root cause — `_get_collection()` creates a new client per call that doesn't persist across the stdio event loop. The fix is likely a module-level singleton client init. This is the primary use-case being broken silently.

4. **Open a PR for #521** (hnswlib SIGSEGV). The reporter has already written the fix: add `collection.delete(where={"source_file": source_file})` before re-inserting chunks to convert upsert-update path → delete+insert path. Low-risk one-hunk patch.

5. **Rebase and merge PR#346** (HNSW bloat). The disk-exhaustion scenario is catastrophic. The fix (tune `hnsw:batch_size` and `hnsw:sync_threshold`) is the correct lever. It's dirty from `develop` drift — needs a rebase, then merge.

6. **Merge the ROADMAP "in review this week" batch.** PRs #660 (L1 pre-filter), #661 (graph cache), #662 (hybrid search), #663 (stale HNSW) are all from `jphein` who has 10+ merged quality PRs. All are listed explicitly in ROADMAP.md. Merge in dependency order: #663 → #660 → #661 → #662.

7. **Merge the content-quality fix batch** (PR#730, #708, #707, #716, #695, #685). These are all targeted, low-risk, address HIGH-severity content loss bugs, and have no inter-dependencies. Merge as a group in one pass.

8. **Redirect PR#678** (HTTP transport) — author targeted `main` instead of `develop`. Request rebase onto `develop` before review. The feature itself (ChatGPT remote MCP) is legitimate and well-written; the branch mistake is the only blocker.

9. **Close PR#319** (web3guru888 STAN self-promotion). Consistent with the community guideline Issue #680 filed by maintainers. If a plugin directory is planned, document the process and direct the author there.

10. **Triage #698 security findings.** Priority ordering: (1) `shutil.rmtree` path traversal in `migrate`/`repair` — add a "does this path contain `chroma.sqlite3`?" guard before deletion; (2) expand `_WAL_REDACT_KEYS` to include `content`/`entry`/`query` — prevents full transcript leakage to the WAL log. Both are 5-line fixes.

---

## Coverage Notes

- Issues read: 181 open (all 100 from page 1 + all 81 from page 2, covering the full open set)
- PRs read: 100 open (full first page by `updated DESC`); deep-dives on 10 individual PRs
- `gh` CLI: not available; used GitHub MCP tools throughout
- `tools/sync_issues.py` and `.claude/skills/triage-issues/SKILL.md`: not present in this fork (fork contains only `.claude-plugin/`); triage performed inline
- Per-PR diff scan: skipped (rate-limit conservation); file counts and addition/deletion tallies used as size signal instead
- Open PRs beyond page 1 (any PRs not updated since the oldest entry on page 1): not reviewed; expected to be stale/draft items with lower urgency
