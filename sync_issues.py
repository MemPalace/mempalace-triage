#!/usr/bin/env python3
"""Sync docs/ISSUES.md with live state of MemPalace/mempalace.

Personal triage tool — not for upstream.

Value adds over a raw `gh` dump:
  - Heuristic severity classification (CRITICAL / HIGH / normal)
  - Noise detection (thanks, short titles, duplicates) — segregated for review
  - Suspicious-PR flagging (CI tampering, exec patterns, first-time contributors)
  - Cross-reference issues/PRs to mempalace modules (from CLAUDE.md)
  - Delta detection against the previous snapshot

Usage:
    python sync_issues.py                    # regenerate ISSUES.md
    python sync_issues.py --audit-prs        # print suspicious PR report
    python sync_issues.py --noise-report     # print noise candidates
    python sync_issues.py --no-cache         # bypass cache, fetch fresh
    python sync_issues.py --dry-run          # show what would change
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

# ─── Configuration ────────────────────────────────────────────────────────────

REPO = "MemPalace/mempalace"
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "ISSUES.md"
CACHE_DIR = ROOT / ".cache"
CACHE_TTL = timedelta(hours=6)

# Modules we cross-reference against. Names here match the CLAUDE.md table.
MEMPALACE_MODULES = [
    "palace.py", "miner.py", "convo_miner.py", "searcher.py", "mcp_server.py",
    "config.py", "normalize.py", "dialect.py", "palace_graph.py", "hooks_cli.py",
    "version.py", "layers.py", "knowledge_graph.py", "cli.py",
    "split_mega_files.py", "entity_detector.py",
]
# Also match bare module names without .py
MODULE_BARE_NAMES = {m[:-3] for m in MEMPALACE_MODULES if m.endswith(".py")}

# ─── Heuristic keyword banks ──────────────────────────────────────────────────

CRITICAL_KEYWORDS = [
    # crashes / corruption / data loss
    r"\bsegfault\b", r"\bEXC_BAD_ACCESS\b", r"\bOOM\b",
    r"\bdata loss\b", r"\bdata gone\b", r"\blost data\b",
    r"\bcorrupt\w*\b", r"\bunrecoverable\b", r"\bdestroy\w*\b",
    r"\bfills disk\b", r"\bterabytes?\b", r"\binfinite recursion\b",
    # security
    r"\bmalicious\b", r"\bexploit\b", r"\bshell injection\b",
    r"\bpath traversal\b", r"\bapi key exposure\b", r"\brce\b",
    # catastrophic semantics
    r"\bsingle point of failure\b", r"\bSPOF\b",
    r"\bpalace data gone\b", r"\bbreaks existing\b",
]

HIGH_KEYWORDS = [
    r"\bsilent(ly)? (fail|skip|drop|truncate|return|ingest)\w*\b",
    r"\bmemory exhaustion\b", r"\bdenial of service\b", r"\bDoS\b",
    r"\brace condition\b", r"\brace on\b",
    r"\bsurrogate error\b", r"\bencoding (crash|error|failure)\b",
    r"\bstale (cache|index|results)\b",
    r"\bre-process\w* every\b",
]

NOISE_TITLE_PATTERNS = [
    r"^null$", r"^TLDR$", r"^new issue$", r"^test$", r"^asdf",
    r"^hello,?( world)?[!?.]?$",
    r"^(thank you|thanks|谢谢|merci|gracias|danke)[!.]?$",
    r"^\W+$",  # only punctuation/emoji
]

NOISE_BODY_PATTERNS = [
    r"^(thank you|thanks|appreciate)",
    r"^(hi|hello)[,!. ]",
    # Note: empty body alone is NOT noise — many real bugs have title-only reports.
]

# Title signals that override noise detection even if body is empty / short
SUBSTANTIVE_TITLE_MARKERS = re.compile(
    r"\b(bug|error|crash|fail|broken|segfault|hang|corrupt|data loss|"
    r"regression|cannot|can't|doesn't|does not|unable|timeout|exception|"
    r"v\d+\.\d+|Python \d|Windows|Linux|macOS|[a-z_]+\.py|"
    r"[A-Z]{2,}[a-z]*Error)",
    re.IGNORECASE,
)

# ─── Suspicious PR indicators ─────────────────────────────────────────────────

SENSITIVE_PATHS = [
    (r"^\.github/workflows/", "modifies CI workflow"),
    (r"^\.github/actions/", "modifies CI action"),
    (r"^pyproject\.toml$", "changes dependencies / build config"),
    (r"^setup\.py$", "changes install script"),
    (r"^setup\.cfg$", "changes install config"),
    (r"^conftest\.py$", "import-time test hook"),
    (r"^\.pre-commit-config\.yaml$", "modifies pre-commit hooks"),
    (r"^hooks/.*\.(sh|py|bash|zsh|fish|ps1)$",
     "changes hook scripts (user-facing exec)"),
    (r"^LICENSE$", "modifies LICENSE"),
    (r"^\.git(ignore|attributes)$", "modifies git config"),
    (r"^uv\.lock$", "changes locked deps"),
]

DIFF_RED_FLAGS = [
    # (pattern, reason, exclude_if_pattern)  — exclude_if_pattern skips common FPs
    (r"(?<![.\w])eval\s*\(", "eval() call", None),
    (r"(?<![.\w])exec\s*\(", "exec() call", None),
    (r"\b__import__\s*\(", "dynamic __import__", None),
    # compile( often means re.compile / sqlite3 compile — require bare builtin
    (r"(?<![.\w])compile\s*\(['\"]",
     "builtin compile() on a string literal", None),
    (r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True",
     "subprocess shell=True", None),
    (r"\bos\.system\s*\(", "os.system() call", None),
    (r"\bos\.popen\s*\(", "os.popen() call", None),
    (r"curl\s+[^|]*\|\s*(bash|sh|zsh)", "curl pipe to shell", None),
    (r"wget\s+[^|]*\|\s*(bash|sh|zsh)", "wget pipe to shell", None),
    (r"[A-Za-z0-9+/]{160,}={0,2}", "long base64-like string", None),
    (r"https?://(?!github\.com|raw\.githubusercontent\.com|pypi\.org|"
     r"files\.pythonhosted\.org|docs\.python\.org|python\.org|"
     r"anthropic\.com|openai\.com|chatgpt\.com|claude\.com|claude\.ai|"
     r"cursor\.com|cursor\.sh|openrouter\.ai|huggingface\.co|"
     r"chromadb|trychroma\.com|"
     r"www\.mempalace|mempalace\.tech|mempalace\.ai|"
     r"readthedocs\.io|sentry\.io|schema\.org|w3\.org|en\.wikipedia\.org|"
     r"microsoft\.com|apple\.com|jetbrains\.com|mozilla\.org|"
     r"ollama\.com|ollama\.ai|lancedb\.com|qdrant\.tech|tidbcloud\.com|"
     r"example\.com|localhost|127\.0\.0\.1)"
     r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "URL to unfamiliar domain", None),
    (r"\bnc\s+-e\b|\bnetcat\b.*\b-e\b", "netcat -e (reverse shell marker)",
     None),
]

# ─── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class Issue:
    number: int
    title: str
    state: str
    labels: list[str]
    author: str
    body: str
    created_at: str
    closed_at: str | None
    # derived
    severity: str = "normal"
    is_noise: bool = False
    noise_reason: str = ""
    modules: list[str] = field(default_factory=list)


@dataclass
class PR:
    number: int
    title: str
    state: str
    labels: list[str]
    author: str
    body: str
    branch: str
    created_at: str
    merged_at: str | None
    closed_at: str | None
    files: list[str] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    # derived
    suspicious_flags: list[str] = field(default_factory=list)  # hard flags
    context_notes: list[str] = field(default_factory=list)     # informational
    modules: list[str] = field(default_factory=list)
    linked_issues: list[int] = field(default_factory=list)
    first_time_author: bool = False


# ─── gh CLI wrappers with caching ─────────────────────────────────────────────


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / name


def _cache_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
    return age < CACHE_TTL


def gh_json(args: list[str], cache_name: str | None, use_cache: bool) -> list | dict:
    """Run `gh ... --json ...` and return parsed JSON, with on-disk caching."""
    if cache_name and use_cache:
        p = _cache_path(cache_name)
        if _cache_fresh(p):
            return json.loads(p.read_text())
    try:
        result = subprocess.run(
            ["gh"] + args, capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"gh error: {e.stderr}", file=sys.stderr)
        raise
    data = json.loads(result.stdout) if result.stdout.strip() else []
    if cache_name:
        _cache_path(cache_name).write_text(json.dumps(data))
    return data


def gh_text(args: list[str], cache_name: str | None, use_cache: bool) -> str:
    """Run `gh ...` and return raw stdout text, with on-disk caching."""
    if cache_name and use_cache:
        p = _cache_path(cache_name)
        if _cache_fresh(p):
            return p.read_text()
    try:
        result = subprocess.run(
            ["gh"] + args, capture_output=True, text=True, check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"gh error: {e.stderr}", file=sys.stderr)
        return ""
    if cache_name:
        _cache_path(cache_name).write_text(result.stdout)
    return result.stdout


def fetch_issues(use_cache: bool = True) -> list[Issue]:
    raw = gh_json(
        [
            "issue", "list", "--repo", REPO, "--state", "all",
            "--limit", "500",
            "--json", "number,title,state,labels,author,body,createdAt,closedAt",
        ],
        "issues.json", use_cache,
    )
    return [
        Issue(
            number=i["number"],
            title=i["title"] or "",
            state=i["state"],
            labels=[lbl["name"] for lbl in i.get("labels", [])],
            author=(i.get("author") or {}).get("login", "") or "—",
            body=i.get("body") or "",
            created_at=i["createdAt"],
            closed_at=i.get("closedAt"),
        )
        for i in raw
    ]


def fetch_prs(use_cache: bool = True) -> list[PR]:
    raw = gh_json(
        [
            "pr", "list", "--repo", REPO, "--state", "all",
            "--limit", "500",
            "--json", "number,title,state,labels,author,body,headRefName,"
                      "createdAt,mergedAt,closedAt,additions,deletions,files",
        ],
        "prs.json", use_cache,
    )
    return [
        PR(
            number=p["number"],
            title=p["title"] or "",
            state=p["state"],
            labels=[lbl["name"] for lbl in p.get("labels", [])],
            author=(p.get("author") or {}).get("login", "") or "—",
            body=p.get("body") or "",
            branch=p.get("headRefName", ""),
            created_at=p["createdAt"],
            merged_at=p.get("mergedAt"),
            closed_at=p.get("closedAt"),
            files=[f["path"] for f in p.get("files", [])],
            additions=p.get("additions", 0),
            deletions=p.get("deletions", 0),
        )
        for p in raw
    ]


def fetch_pr_diff(pr_number: int, use_cache: bool = True) -> str:
    """Fetch PR diff — cached per-PR."""
    return gh_text(
        ["pr", "diff", str(pr_number), "--repo", REPO],
        f"pr_{pr_number}_diff.txt",
        use_cache,
    )


def fetch_author_history(login: str, use_cache: bool = True) -> int:
    """Return number of merged PRs this author has in the repo."""
    if not login or login == "—":
        return 0
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", login)
    raw = gh_json(
        [
            "pr", "list", "--repo", REPO, "--state", "merged",
            "--author", login, "--limit", "50",
            "--json", "number",
        ],
        f"author_{safe}.json", use_cache,
    )
    return len(raw)


# ─── Analysis ─────────────────────────────────────────────────────────────────


FEATURE_TITLE_PREFIX = re.compile(
    r"^\s*(\[?RFC\]?|feat[:(]|feature request|feature proposal|"
    r"\[feature\]|\[integration idea\]|\[spec\]|\[question\]|"
    r"feature:|proposal:|idea:|discussion:|showcase:|example:|"
    r"clarification:|community feedback)",
    re.IGNORECASE,
)

# Phrases that describe a proposed fix / prevention, not an active bug
DEWEIGHT_PHRASES = [
    "prevent data loss", "to prevent", "avoid data loss", "avoid corruption",
    "harm structurally impossible", "no data loss", "backup before",
    "data-loss-prevention", "prevent crash", "avoid crash",
]


BUG_TITLE_PREFIX = re.compile(
    r"^\s*(\[?bug\]?[:\s]|fix[:(]|crash|broken|regression|"
    r"fails?[:\s]|error[:\s]|doesn't work|does not work|"
    r"【bug】)",
    re.IGNORECASE,
)


def classify_severity(issue: Issue) -> str:
    title_lower = issue.title.lower()
    body_lower = issue.body.lower()

    # Features/RFCs don't get severity bump from body keywords
    if "enhancement" in issue.labels:
        return "normal"
    if FEATURE_TITLE_PREFIX.match(issue.title):
        return "normal"

    # De-weight common "prevent X" phrasing
    for phrase in DEWEIGHT_PHRASES:
        body_lower = body_lower.replace(phrase, "")

    is_bug_signaled = (
        "bug" in issue.labels
        or bool(BUG_TITLE_PREFIX.match(issue.title))
    )

    # Title alone is strongest signal — always promotes to CRITICAL
    for pat in CRITICAL_KEYWORDS:
        if re.search(pat, title_lower, re.IGNORECASE):
            return "critical"

    # Body keyword only promotes if there's a bug signal elsewhere
    if is_bug_signaled:
        for pat in CRITICAL_KEYWORDS:
            if re.search(pat, body_lower, re.IGNORECASE):
                return "critical"

    # HIGH via title
    for pat in HIGH_KEYWORDS:
        if re.search(pat, title_lower, re.IGNORECASE):
            return "high"

    # HIGH via body requires bug signal
    if is_bug_signaled:
        for pat in HIGH_KEYWORDS:
            if re.search(pat, body_lower, re.IGNORECASE):
                return "high"

    return "normal"


def detect_noise(issue: Issue) -> tuple[bool, str]:
    title = issue.title.strip()
    body = issue.body.strip()
    substantive_title = bool(SUBSTANTIVE_TITLE_MARKERS.search(title))

    # Hard noise title patterns always win
    for pat in NOISE_TITLE_PATTERNS:
        if re.match(pat, title, re.IGNORECASE):
            return True, f"title matches noise pattern /{pat}/"

    # Very short title + very short body, and title has no bug/error signal
    if len(title) < 20 and len(body) < 40 and not substantive_title:
        return True, "very short title and body, no bug signal in title"

    # Thanks-only / greeting body (short and sweet)
    if len(body) < 200 and not substantive_title:
        for pat in NOISE_BODY_PATTERNS:
            if re.match(pat, body, re.IGNORECASE):
                return True, f"body matches noise pattern /{pat}/"

    # Body mostly emoji / non-ASCII punctuation (only when title is also unhelpful)
    if body and len(body) < 300 and not substantive_title:
        non_word = sum(1 for c in body if not c.isalnum() and not c.isspace())
        if non_word / max(len(body), 1) > 0.5:
            return True, "body is mostly symbols/emoji"

    return False, ""


def find_duplicates(issues: list[Issue]) -> list[tuple[int, int, float]]:
    """Flag near-duplicate OPEN issues by title similarity. Returns (a, b, ratio)."""
    opens = [i for i in issues if i.state == "OPEN"]
    dupes: list[tuple[int, int, float]] = []
    # Normalize titles for comparison
    normed = [(i, re.sub(r"[^a-z0-9 ]+", " ", i.title.lower())) for i in opens]
    for idx, (i1, t1) in enumerate(normed):
        for i2, t2 in normed[idx + 1:]:
            ratio = SequenceMatcher(None, t1, t2).ratio()
            if ratio > 0.85:
                dupes.append((i1.number, i2.number, ratio))
    return dupes


def cross_reference_modules(text: str, changed_files: list[str] | None = None) -> list[str]:
    """Match a blob of text (+ optional changed files) against mempalace modules."""
    hits: set[str] = set()
    lower = text.lower()
    for mod in MEMPALACE_MODULES:
        if mod in lower or mod[:-3] in re.findall(r"\b\w+\b", lower):
            hits.add(mod)
    if changed_files:
        for f in changed_files:
            # Match changed file against known module basenames
            base = Path(f).name
            if base in MEMPALACE_MODULES:
                hits.add(base)
    # Filter out false positives: bare module names that are common words
    COMMON_WORD_MODULES = {"version.py", "config.py"}  # too generic alone
    if len(hits) == 1 and next(iter(hits)) in COMMON_WORD_MODULES:
        # Only keep if file path explicitly matched
        if changed_files and any(Path(f).name in hits for f in changed_files):
            return sorted(hits)
        return []
    return sorted(hits)


def extract_linked_issues(pr: PR) -> list[int]:
    """Pull #NNN references out of a PR title/body."""
    text = f"{pr.title}\n{pr.body}"
    nums = re.findall(r"#(\d+)", text)
    return sorted({int(n) for n in nums})


def analyze_pr_suspicion(
    pr: PR, diff: str, author_merged_count: int
) -> tuple[list[str], list[str]]:
    """Return (hard_flags, context_notes).

    hard_flags: real red flags that warrant review.
    context_notes: informational annotations (first-time contributor, size).
    A PR is "flagged" only when it has at least one hard_flag.
    """
    hard_flags: list[str] = []
    context_notes: list[str] = []

    # First-time contributor → context only, not a flag by itself
    if author_merged_count == 0 and pr.state == "OPEN":
        context_notes.append("first-time contributor (no prior merged PRs)")
        pr.first_time_author = True

    # Sensitive paths → hard flag
    for f in pr.files:
        for pat, reason in SENSITIVE_PATHS:
            if re.match(pat, f):
                hard_flags.append(f"touches `{f}` — {reason}")
                break

    # Diff red flags → hard flag
    if diff:
        added_lines = [
            ln[1:] for ln in diff.splitlines()
            if ln.startswith("+") and not ln.startswith("+++")
        ]
        added_text = "\n".join(added_lines)
        for pat, reason, exclude_pat in DIFF_RED_FLAGS:
            for m in re.finditer(pat, added_text):
                snippet = m.group(0)[:70]
                if exclude_pat and re.search(exclude_pat, snippet):
                    continue
                hard_flags.append(f"diff contains {reason}: `{snippet}`")
                break  # one hit per pattern is enough

    # Size disproportion
    total_changes = pr.additions + pr.deletions
    if total_changes > 2000:
        hard_flags.append(f"very large diff: +{pr.additions}/-{pr.deletions}")
    elif total_changes > 500:
        context_notes.append(
            f"large-ish diff (+{pr.additions}/-{pr.deletions})"
        )

    if (pr.state == "OPEN" and total_changes > 300 and len(pr.body) < 100
            and not hard_flags):
        # Thin description on a decent-sized PR → context (not alarming alone)
        context_notes.append(
            f"thin description ({len(pr.body)} chars) for "
            f"+{pr.additions}/-{pr.deletions}"
        )

    return hard_flags, context_notes


# ─── Analysis pipeline ────────────────────────────────────────────────────────


def enrich_issues(issues: list[Issue]) -> list[Issue]:
    for i in issues:
        i.severity = classify_severity(i)
        i.is_noise, i.noise_reason = detect_noise(i)
        i.modules = cross_reference_modules(f"{i.title}\n{i.body}")
    return issues


def enrich_prs(
    prs: list[PR],
    use_cache: bool,
    scan_diffs: bool = True,
) -> list[PR]:
    author_cache: dict[str, int] = {}
    for pr in prs:
        if pr.author not in author_cache:
            author_cache[pr.author] = fetch_author_history(pr.author, use_cache)
        diff = ""
        # Only scan diffs for OPEN PRs (performance + relevance)
        if scan_diffs and pr.state == "OPEN":
            diff = fetch_pr_diff(pr.number, use_cache)
        pr.suspicious_flags, pr.context_notes = analyze_pr_suspicion(
            pr, diff, author_cache[pr.author]
        )
        pr.modules = cross_reference_modules(
            f"{pr.title}\n{pr.body}", pr.files
        )
        pr.linked_issues = extract_linked_issues(pr)
    return prs


# ─── Rendering ────────────────────────────────────────────────────────────────


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _two_weeks_ago() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=14)).date().isoformat()


def _label_str(labels: list[str]) -> str:
    return ", ".join(labels) if labels else "—"


def _module_str(modules: list[str], cap: int = 4) -> str:
    if not modules:
        return "—"
    if len(modules) <= cap:
        return ", ".join(modules)
    return ", ".join(modules[:cap]) + f", +{len(modules) - cap} more"


def _issue_row(i: Issue) -> str:
    labels = _label_str(i.labels)
    mods = _module_str(i.modules)
    return (
        f"| {i.number} | {i.title.replace('|', '\\|')} | {i.author} | "
        f"{i.created_at[:10]} | {labels} | {mods} |"
    )


def _pr_row(pr: PR) -> str:
    linked = ", ".join(f"#{n}" for n in pr.linked_issues) or "—"
    return (
        f"| #{pr.number} | `{pr.branch}` | {pr.title.replace('|', '\\|')} | "
        f"{linked} |"
    )


def render_markdown(
    issues: list[Issue], prs: list[PR], dupes: list[tuple[int, int, float]]
) -> str:
    open_issues = [i for i in issues if i.state == "OPEN"]
    closed_issues = [i for i in issues if i.state == "CLOSED"]
    open_prs = [p for p in prs if p.state == "OPEN"]
    merged_prs = [p for p in prs if p.state == "MERGED"]

    cutoff = _two_weeks_ago()
    recent_closed = [
        i for i in closed_issues if (i.closed_at or "") >= cutoff
    ]
    recent_merged = [
        p for p in merged_prs if (p.merged_at or "") >= cutoff
    ]

    critical = [i for i in open_issues if i.severity == "critical"]
    high = [i for i in open_issues if i.severity == "high"]
    bugs_labeled = [i for i in open_issues if "bug" in i.labels]
    bugs_unlabeled_defects = [
        i for i in open_issues
        if "bug" not in i.labels and i.severity in ("critical", "high")
        and not i.is_noise
    ]
    feats_labeled = [i for i in open_issues if "enhancement" in i.labels]
    noise = [i for i in open_issues if i.is_noise]
    suspicious_prs = [p for p in open_prs if p.suspicious_flags]

    lines: list[str] = []
    lines.append("# MemPalace Issue Tracker\n")
    lines.append(
        f"> Synced from [{REPO}](https://github.com/{REPO}/issues) "
        f"on {_today()}"
    )
    lines.append(
        f"> Total: **{len(open_issues)} open issues**, "
        f"**{len(open_prs)} open PRs**\n"
    )
    lines.append(
        "> Generated by `tools/sync_issues.py` — personal triage tool "
        "(not for upstream).\n"
    )

    # ─── CRITICAL ──────────────────────────────────────────────────
    lines.append("---\n")
    lines.append("## CRITICAL (heuristic)\n")
    lines.append(
        "Auto-classified by keyword match: crash / corruption / data-loss / "
        "security in title or body. Review and promote to hand-curated list as "
        "needed.\n"
    )
    lines.append("| # | Title | Author | Filed | Labels | Modules |")
    lines.append("|---|---|---|---|---|---|")
    for i in sorted(critical, key=lambda x: x.number, reverse=True):
        lines.append(_issue_row(i))
    lines.append("")

    # ─── HIGH ──────────────────────────────────────────────────────
    lines.append("## HIGH (heuristic)\n")
    lines.append(
        "Silent failures, memory exhaustion, race conditions, stale state.\n"
    )
    lines.append("| # | Title | Author | Filed | Labels | Modules |")
    lines.append("|---|---|---|---|---|---|")
    for i in sorted(high, key=lambda x: x.number, reverse=True):
        lines.append(_issue_row(i))
    lines.append("")

    # ─── Bugs (labeled) ────────────────────────────────────────────
    lines.append(f"## Bugs — labeled `bug` ({len(bugs_labeled)} open)\n")
    lines.append("| # | Title | Author | Filed | Severity | Modules |")
    lines.append("|---|---|---|---|---|---|")
    for i in sorted(bugs_labeled, key=lambda x: x.number, reverse=True):
        lines.append(
            f"| {i.number} | {i.title.replace('|', '\\|')} | {i.author} | "
            f"{i.created_at[:10]} | {i.severity} | {_module_str(i.modules)} |"
        )
    lines.append("")

    # ─── Bugs (unlabeled but clearly defects) ──────────────────────
    lines.append(
        f"## Bugs — unlabeled but severity ≥ high ({len(bugs_unlabeled_defects)})\n"
    )
    lines.append(
        "Unambiguous defects the heuristic flagged but upstream hasn't "
        "labeled. Candidates for `bug` label.\n"
    )
    lines.append("| # | Title | Filed | Severity | Modules |")
    lines.append("|---|---|---|---|---|")
    for i in sorted(bugs_unlabeled_defects, key=lambda x: x.number, reverse=True):
        lines.append(
            f"| {i.number} | {i.title.replace('|', '\\|')} | "
            f"{i.created_at[:10]} | {i.severity} | {_module_str(i.modules)} |"
        )
    lines.append("")

    # ─── Features ──────────────────────────────────────────────────
    lines.append(
        f"## Features — labeled `enhancement` ({len(feats_labeled)} open)\n"
    )
    lines.append("| # | Title | Author | Filed |")
    lines.append("|---|---|---|---|")
    for i in sorted(feats_labeled, key=lambda x: x.number, reverse=True):
        lines.append(
            f"| {i.number} | {i.title.replace('|', '\\|')} | "
            f"{i.author} | {i.created_at[:10]} |"
        )
    lines.append("")

    # ─── Noise ─────────────────────────────────────────────────────
    lines.append(f"## Low-signal / noise candidates ({len(noise)})\n")
    lines.append(
        "Auto-flagged as low-value. Review before closing — heuristic only.\n"
    )
    lines.append("| # | Title | Reason |")
    lines.append("|---|---|---|")
    for i in sorted(noise, key=lambda x: x.number, reverse=True):
        lines.append(
            f"| {i.number} | {i.title.replace('|', '\\|')} | {i.noise_reason} |"
        )
    lines.append("")

    # ─── Near-duplicate issues ─────────────────────────────────────
    if dupes:
        lines.append(f"## Near-duplicate open issues ({len(dupes)} pairs)\n")
        lines.append(
            "Pairs with title similarity > 0.85. Review for consolidation.\n"
        )
        lines.append("| # A | # B | Similarity |")
        lines.append("|---|---|---|")
        for a, b, r in sorted(dupes, key=lambda x: -x[2]):
            lines.append(f"| {a} | {b} | {r:.2f} |")
        lines.append("")

    # ─── Suspicious PRs ────────────────────────────────────────────
    lines.append(
        f"## PRs flagged for review ({len(suspicious_prs)})\n"
    )
    lines.append(
        "PRs matching one or more suspicion heuristics. Most flags are "
        "benign — review individually before acting. Flags are informational.\n"
    )
    for pr in sorted(suspicious_prs, key=lambda x: x.number, reverse=True):
        lines.append(
            f"- **#{pr.number}** [`{pr.branch}`] by @{pr.author} "
            f"(+{pr.additions}/-{pr.deletions}) — {pr.title}"
        )
        for flag in pr.suspicious_flags:
            lines.append(f"  - ! {flag}")
        for note in pr.context_notes:
            lines.append(f"  - · {note}")
    lines.append("")

    # ─── Recently merged ───────────────────────────────────────────
    lines.append(f"## Recently merged ({len(recent_merged)}, last 14 days)\n")
    lines.append("| # | Branch | Title | Merged | Modules |")
    lines.append("|---|---|---|---|---|")
    for pr in sorted(recent_merged, key=lambda x: x.merged_at or "", reverse=True):
        lines.append(
            f"| #{pr.number} | `{pr.branch}` | "
            f"{pr.title.replace('|', '\\|')} | "
            f"{(pr.merged_at or '')[:10]} | {_module_str(pr.modules)} |"
        )
    lines.append("")

    # ─── Recently closed issues ────────────────────────────────────
    lines.append(f"## Recently closed ({len(recent_closed)}, last 14 days)\n")
    lines.append("| # | Title | Labels | Closed |")
    lines.append("|---|---|---|---|")
    for i in sorted(recent_closed, key=lambda x: x.closed_at or "", reverse=True):
        lines.append(
            f"| {i.number} | {i.title.replace('|', '\\|')} | "
            f"{_label_str(i.labels)} | {(i.closed_at or '')[:10]} |"
        )
    lines.append("")

    # ─── Summary ───────────────────────────────────────────────────
    lines.append("## Summary\n")
    lines.append("| Category | Count |")
    lines.append("|---|---|")
    lines.append(f"| Open issues | {len(open_issues)} |")
    lines.append(f"|   of which CRITICAL (heuristic) | {len(critical)} |")
    lines.append(f"|   of which HIGH (heuristic) | {len(high)} |")
    lines.append(f"|   of which labeled `bug` | {len(bugs_labeled)} |")
    lines.append(f"|   of which labeled `enhancement` | {len(feats_labeled)} |")
    lines.append(f"|   of which noise candidates | {len(noise)} |")
    lines.append(f"| Open PRs | {len(open_prs)} |")
    lines.append(f"|   of which flagged for review | {len(suspicious_prs)} |")
    lines.append(f"| Merged (last 14d) | {len(recent_merged)} |")
    lines.append(f"| Closed issues (last 14d) | {len(recent_closed)} |")
    lines.append("")

    return "\n".join(lines)


# ─── Audit report modes ───────────────────────────────────────────────────────


def print_pr_audit(prs: list[PR]) -> None:
    flagged = sorted(
        [p for p in prs if p.state == "OPEN" and p.suspicious_flags],
        key=lambda x: x.number, reverse=True,
    )
    if not flagged:
        print("No open PRs flagged.")
        return
    print(f"\n{len(flagged)} open PRs flagged for review:\n")
    for pr in flagged:
        linked = ", ".join(f"#{n}" for n in pr.linked_issues) or "—"
        print(f"━━━ PR #{pr.number} [{pr.branch}] by @{pr.author} ━━━")
        print(f"  Title:   {pr.title}")
        print(f"  Size:    +{pr.additions}/-{pr.deletions} "
              f"across {len(pr.files)} files")
        print(f"  Linked:  {linked}")
        print(f"  Modules: {_module_str(pr.modules)}")
        print(f"  URL:     https://github.com/{REPO}/pull/{pr.number}")
        print("  Red flags:")
        for flag in pr.suspicious_flags:
            print(f"    ! {flag}")
        if pr.context_notes:
            print("  Context:")
            for note in pr.context_notes:
                print(f"    · {note}")
        print()


def print_noise_report(issues: list[Issue]) -> None:
    noise = sorted(
        [i for i in issues if i.state == "OPEN" and i.is_noise],
        key=lambda x: x.number, reverse=True,
    )
    if not noise:
        print("No open noise candidates.")
        return
    print(f"\n{len(noise)} open issues flagged as low-signal:\n")
    for i in noise:
        print(f"  #{i.number:<4} {i.title[:70]:<70} "
              f"[{i.noise_reason}]")
    print(f"\n  URLs: https://github.com/{REPO}/issues/<NUMBER>")


# ─── Delta ────────────────────────────────────────────────────────────────────


def diff_against_previous(new_md: str, path: Path) -> str:
    if not path.exists():
        return "  (no previous ISSUES.md — this is the first sync)"
    old = path.read_text()
    old_total = re.search(r"\*\*(\d+) open issues\*\*", old)
    new_total = re.search(r"\*\*(\d+) open issues\*\*", new_md)
    old_prs = re.search(r"\*\*(\d+) open PRs\*\*", old)
    new_prs = re.search(r"\*\*(\d+) open PRs\*\*", new_md)
    if not all([old_total, new_total, old_prs, new_prs]):
        return "  (counts not found in old file — cannot compute delta)"
    return (
        f"  issues: {old_total.group(1)} → {new_total.group(1)} "
        f"(Δ {int(new_total.group(1)) - int(old_total.group(1)):+d})\n"
        f"  PRs:    {old_prs.group(1)} → {new_prs.group(1)} "
        f"(Δ {int(new_prs.group(1)) - int(old_prs.group(1)):+d})"
    )


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Bypass on-disk cache, fetch fresh from GitHub",
    )
    parser.add_argument(
        "--skip-diffs", action="store_true",
        help="Skip PR diff scans (faster, but no diff-based red flags)",
    )
    parser.add_argument(
        "--audit-prs", action="store_true",
        help="Print suspicious-PR audit report; do not write ISSUES.md",
    )
    parser.add_argument(
        "--noise-report", action="store_true",
        help="Print noise candidate list; do not write ISSUES.md",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print summary of what would be written; don't touch ISSUES.md",
    )
    parser.add_argument(
        "--output", type=Path, default=OUTPUT,
        help=f"Output path (default: {OUTPUT})",
    )
    args = parser.parse_args()

    use_cache = not args.no_cache

    print(f"Fetching issues from {REPO}...", file=sys.stderr)
    issues = enrich_issues(fetch_issues(use_cache))

    print(f"Fetching PRs from {REPO}...", file=sys.stderr)
    prs = fetch_prs(use_cache)

    print(f"Analyzing {len(prs)} PRs "
          f"(diffs: {'skipped' if args.skip_diffs else 'on'})...",
          file=sys.stderr)
    prs = enrich_prs(prs, use_cache, scan_diffs=not args.skip_diffs)

    if args.audit_prs:
        print_pr_audit(prs)
        return 0

    if args.noise_report:
        print_noise_report(issues)
        return 0

    dupes = find_duplicates(issues)
    md = render_markdown(issues, prs, dupes)

    print("Delta vs previous ISSUES.md:", file=sys.stderr)
    print(diff_against_previous(md, args.output), file=sys.stderr)

    if args.dry_run:
        print(f"\n(dry-run) Would write {len(md)} bytes to {args.output}",
              file=sys.stderr)
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(md)
    print(f"Wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
