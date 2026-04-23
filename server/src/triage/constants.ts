import { resolve } from "node:path";

export const REPO = "MemPalace/mempalace";

// Root of the mempalace-triage repo. The triage module lives at
// server/src/triage, so up three levels.
export const REPO_ROOT = resolve(import.meta.dir, "../../..");
export const CACHE_DIR = resolve(REPO_ROOT, ".cache");
export const DEFAULT_OUTPUT = resolve(REPO_ROOT, "ISSUES.md");
export const CACHE_TTL_MS = 6 * 60 * 60 * 1000; // 6h

// Modules we cross-reference against. Names match the upstream CLAUDE.md table.
export const MEMPALACE_MODULES = [
  "palace.py", "miner.py", "convo_miner.py", "searcher.py", "mcp_server.py",
  "config.py", "normalize.py", "dialect.py", "palace_graph.py", "hooks_cli.py",
  "version.py", "layers.py", "knowledge_graph.py", "cli.py",
  "split_mega_files.py", "entity_detector.py",
] as const;

// Bare module names without .py — used for word-boundary matching against text.
export const MODULE_BARE_NAMES = new Set(
  MEMPALACE_MODULES.filter((m) => m.endsWith(".py")).map((m) => m.slice(0, -3)),
);

// Modules whose bare name is a common English word — require a file-path
// confirmation before counting as a hit when they're the *only* match.
export const COMMON_WORD_MODULES = new Set(["version.py", "config.py"]);

// ─── Heuristic keyword banks ────────────────────────────────────────────────

// All patterns are stored as plain strings; callers wrap in `new RegExp(..., "i")`
// at match time so flags stay explicit at the call site.
export const CRITICAL_KEYWORDS: string[] = [
  // crashes / corruption / data loss
  "\\bsegfault\\b", "\\bEXC_BAD_ACCESS\\b", "\\bOOM\\b",
  "\\bdata loss\\b", "\\bdata gone\\b", "\\blost data\\b",
  "\\bcorrupt\\w*\\b", "\\bunrecoverable\\b", "\\bdestroy\\w*\\b",
  "\\bfills disk\\b", "\\bterabytes?\\b", "\\binfinite recursion\\b",
  // security
  "\\bmalicious\\b", "\\bexploit\\b", "\\bshell injection\\b",
  "\\bpath traversal\\b", "\\bapi key exposure\\b", "\\brce\\b",
  // catastrophic semantics
  "\\bsingle point of failure\\b", "\\bSPOF\\b",
  "\\bpalace data gone\\b", "\\bbreaks existing\\b",
  // release / packaging defects — added after #1093 slipped through classified
  // as "normal". These catch install-time regressions the runtime-symptom
  // vocabulary above misses.
  "\\brelease defect\\b", "\\bbroken install\\b",
  "\\bfresh install\\b.*\\bfail",
  "\\bentry point\\b.*\\bmissing\\b",
  "\\bpip install\\b.*\\bfail",
  "\\bcommand not found\\b", "\\bexecutable file not found\\b",
  "\\bv\\d+\\.\\d+\\.\\d+\\b.*\\brelease defect\\b",
];

export const HIGH_KEYWORDS: string[] = [
  "\\bsilent(ly)? (fail|skip|drop|truncate|return|ingest)\\w*\\b",
  "\\bmemory exhaustion\\b", "\\bdenial of service\\b", "\\bDoS\\b",
  "\\brace condition\\b", "\\brace on\\b",
  "\\bsurrogate error\\b", "\\bencoding (crash|error|failure)\\b",
  "\\bstale (cache|index|results)\\b",
  "\\bre-process\\w* every\\b",
  // Packaging / plugin manifest drift — flags issues that touch the release
  // surface (plugin.json, pyproject.toml) before they escalate to broken
  // installs. Paired with the CRITICAL additions so near-misses still surface.
  "\\bplugin\\.json\\b", "\\bpyproject\\.toml\\b",
  "\\bconsole script\\b", "\\bentry point\\b",
  "\\bpipx\\b", "\\buv compat\\w*\\b",
];

// RegExp objects (not strings) because one pattern needs the `u` flag to
// match Python's Unicode `\w` semantics — in Python `\W` excludes letters
// in any script (e.g. Chinese), in JS without `u` it excludes only ASCII.
export const NOISE_TITLE_PATTERNS: RegExp[] = [
  /^null$/i,
  /^TLDR$/i,
  /^new issue$/i,
  /^test$/i,
  /^asdf/i,
  /^hello,?( world)?[!?.]?$/i,
  /^(thank you|thanks|谢谢|merci|gracias|danke)[!.]?$/i,
  // Only punctuation / emoji. `\p{L}\p{N}_` = any Unicode letter/number + `_`
  // (Python's default `\w`). Requires the `u` flag.
  /^[^\p{L}\p{N}_]+$/iu,
];

export const NOISE_BODY_PATTERNS: RegExp[] = [
  /^(thank you|thanks|appreciate)/i,
  /^(hi|hello)[,!. ]/i,
  // Empty body alone is NOT noise — many real bugs have title-only reports.
];

// Title signals that override noise detection even if body is empty / short.
export const SUBSTANTIVE_TITLE_MARKERS = new RegExp(
  "\\b(bug|error|crash|fail|broken|segfault|hang|corrupt|data loss|" +
    "regression|cannot|can't|doesn't|does not|unable|timeout|exception|" +
    "v\\d+\\.\\d+|Python \\d|Windows|Linux|macOS|[a-z_]+\\.py|" +
    "[A-Z]{2,}[a-z]*Error)",
  "i",
);

export const FEATURE_TITLE_PREFIX = new RegExp(
  "^\\s*(\\[?RFC\\]?|feat[:(]|feature request|feature proposal|" +
    "\\[feature\\]|\\[integration idea\\]|\\[spec\\]|\\[question\\]|" +
    "feature:|proposal:|idea:|discussion:|showcase:|example:|" +
    "clarification:|community feedback)",
  "i",
);

// Phrases that describe a proposed fix / prevention, not an active bug.
export const DEWEIGHT_PHRASES: string[] = [
  "prevent data loss", "to prevent", "avoid data loss", "avoid corruption",
  "harm structurally impossible", "no data loss", "backup before",
  "data-loss-prevention", "prevent crash", "avoid crash",
];

export const BUG_TITLE_PREFIX = new RegExp(
  "^\\s*(\\[?bug\\]?[:\\s]|fix[:(]|crash|broken|regression|" +
    "fails?[:\\s]|error[:\\s]|doesn't work|does not work|" +
    "【bug】)",
  "i",
);

// ─── Suspicious PR indicators ───────────────────────────────────────────────

/**
 * Suspicion levels. Rule matches with different levels combine to give the
 * overall PR level (max wins). See {@link analyzePrSuspicion}.
 *
 * - `critical` — code in the diff matches something that actually executes
 *   arbitrary code or exfiltrates data (eval, shell pipes, netcat, etc).
 * - `high`     — the PR touches a trust boundary that runs on maintainer or
 *   end-user machines (CI workflows, hook scripts, pre-commit).
 * - `medium`   — supply-chain surface is changing (deps, lockfile, LICENSE,
 *   git config). Worth a conscious review, not inherently malicious.
 * - `low`      — size-based: diff too large to review casually.
 */
export type SuspicionLevel = "critical" | "high" | "medium" | "low" | "none";

export interface SensitivePathRule {
  pattern: string;
  reason: string;
  level: Exclude<SuspicionLevel, "critical" | "none">;
}

export const SENSITIVE_PATHS: SensitivePathRule[] = [
  // High — code that runs on maintainer or end-user machines without explicit consent.
  { pattern: "^\\.github/workflows/", reason: "modifies CI workflow", level: "high" },
  { pattern: "^\\.github/actions/", reason: "modifies CI action", level: "high" },
  {
    pattern: "^hooks/.*\\.(sh|py|bash|zsh|fish|ps1)$",
    reason: "changes hook scripts (user-facing exec)",
    level: "high",
  },
  { pattern: "^\\.pre-commit-config\\.yaml$", reason: "modifies pre-commit hooks", level: "high" },
  { pattern: "^conftest\\.py$", reason: "import-time test hook", level: "high" },

  // Medium — supply-chain / trust surface changes.
  { pattern: "^pyproject\\.toml$", reason: "changes dependencies / build config", level: "medium" },
  { pattern: "^setup\\.py$", reason: "changes install script", level: "medium" },
  { pattern: "^setup\\.cfg$", reason: "changes install config", level: "medium" },
  { pattern: "^uv\\.lock$", reason: "changes locked deps", level: "medium" },
  { pattern: "^LICENSE$", reason: "modifies LICENSE", level: "medium" },
  { pattern: "^\\.git(ignore|attributes)$", reason: "modifies git config", level: "medium" },
];

export interface DiffRedFlag {
  pattern: string;
  reason: string;
  excludeIf?: string;
  /** All current diff red flags are critical (actual code-execution / exfil). */
  level?: Extract<SuspicionLevel, "critical" | "high">;
}

// Patterns that scan a PR's *added* lines for dangerous content. `excludeIf`
// runs against the matched snippet to suppress common false positives.
export const DIFF_RED_FLAGS: DiffRedFlag[] = [
  { pattern: "(?<![.\\w])eval\\s*\\(", reason: "eval() call" },
  { pattern: "(?<![.\\w])exec\\s*\\(", reason: "exec() call" },
  { pattern: "\\b__import__\\s*\\(", reason: "dynamic __import__" },
  {
    pattern: "(?<![.\\w])compile\\s*\\(['\"]",
    reason: "builtin compile() on a string literal",
  },
  {
    pattern: "subprocess\\.[A-Za-z_]+\\([^)]*shell\\s*=\\s*True",
    reason: "subprocess shell=True",
  },
  { pattern: "\\bos\\.system\\s*\\(", reason: "os.system() call" },
  { pattern: "\\bos\\.popen\\s*\\(", reason: "os.popen() call" },
  { pattern: "curl\\s+[^|]*\\|\\s*(bash|sh|zsh)", reason: "curl pipe to shell" },
  { pattern: "wget\\s+[^|]*\\|\\s*(bash|sh|zsh)", reason: "wget pipe to shell" },
  { pattern: "[A-Za-z0-9+/]{160,}={0,2}", reason: "long base64-like string" },
  {
    pattern:
      "https?://(?!github\\.com|raw\\.githubusercontent\\.com|pypi\\.org|" +
      "files\\.pythonhosted\\.org|docs\\.python\\.org|python\\.org|" +
      "anthropic\\.com|openai\\.com|chatgpt\\.com|claude\\.com|claude\\.ai|" +
      "cursor\\.com|cursor\\.sh|openrouter\\.ai|huggingface\\.co|" +
      "chromadb|trychroma\\.com|" +
      "www\\.mempalace|mempalace\\.tech|mempalace\\.ai|" +
      "readthedocs\\.io|sentry\\.io|schema\\.org|w3\\.org|en\\.wikipedia\\.org|" +
      "microsoft\\.com|apple\\.com|jetbrains\\.com|mozilla\\.org|" +
      "ollama\\.com|ollama\\.ai|lancedb\\.com|qdrant\\.tech|tidbcloud\\.com|" +
      "example\\.com|localhost|127\\.0\\.0\\.1)" +
      "[A-Za-z0-9.-]+\\.[A-Za-z]{2,}",
    reason: "URL to unfamiliar domain",
  },
  {
    pattern: "\\bnc\\s+-e\\b|\\bnetcat\\b.*\\b-e\\b",
    reason: "netcat -e (reverse shell marker)",
  },
];
