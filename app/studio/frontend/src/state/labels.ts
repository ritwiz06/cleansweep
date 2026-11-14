// How raw table data reads in the UI: column names and enum values in plain words, dates in a
// short form, numbers with separators. One map for every screen, so a header reads the same
// everywhere.

const HEADERS: Record<string, string> = {
  llm: "LLM",
  llm_requests: "LLM requests",
  llm_requests_mean: "LLM requests (mean)",
  llm_calls: "LLM calls",
  ci_low: "CI low",
  ci_high: "CI high",
  n: "n",
  ui: "UI",
  id: "ID",
  safe_score: "Safe score",
  item_id: "Item",
};

const WORDS: Record<string, string> = { llm: "LLM", ci: "CI", ui: "UI", api: "API", id: "ID", ok: "OK", pr: "PR" };

const SNAKE = /^[a-z][a-z0-9]*(_[a-z0-9]+)+$/;
const ISO = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$/;

// Whole values that read better than a plain swap of the version token.
const PHASE_VALUES: Record<string, string> = { "injected v3": "injection (Phase 3)", "real v3": "real projects (Phase 3)" };

// "v1 (static detectors)" -> "Phase 1 (static detectors)": the screens speak of phases, not
// versions. A token inside a name or path ("verifiers.v1", "results/summary/v2/") stays.
export function phaseWords(text: string): string {
  return PHASE_VALUES[text] ?? text.replace(/(?<![\w./-])v([123])(\.\d+)*(?![\w/-]|\.\w)/g, "Phase $1");
}

function words(text: string): string {
  return text
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => WORDS[w.toLowerCase()] ?? w)
    .join(" ");
}

// "safe_score" -> "Safe score", "lines removed (mean, 95% CI)" stays as it is but capitalized.
export function headerLabel(column: string): string {
  if (column in HEADERS) return HEADERS[column];
  const text = phaseWords(words(column));
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// "leftover_file" -> "leftover file"; anything that is not a plain snake_case word stays.
export function valueLabel(value: string): string {
  return SNAKE.test(value) ? words(value) : phaseWords(value);
}

export function isIsoDate(value: string): boolean {
  return ISO.test(value);
}

// "2026-11-01T10:05:00+00:00" -> "Nov 1, 10:05" (in the reader's time zone).
export function shortDate(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

// 50427 -> "50,427"; decimals keep up to three digits.
export function formatNumber(value: number, decimals?: number): string {
  if (decimals !== undefined) return value.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
  if (Number.isInteger(value)) return value.toLocaleString("en-US");
  return (Math.round(value * 1000) / 1000).toLocaleString("en-US", { maximumFractionDigits: 3 });
}

// The decimals a column of numbers is shown with: as many as its most precise value, at most
// three, so the column lines up.
export function columnDecimals(values: unknown[]): number {
  let most = 0;
  for (const v of values) {
    if (typeof v !== "number" || Number.isInteger(v)) continue;
    const digits = String(Math.round(v * 1000) / 1000).split(".")[1]?.length ?? 0;
    most = Math.max(most, digits);
  }
  return Math.min(most, 3);
}

// A cell reads as a number when it is one, or a number with an interval, ratio or unit.
const NUMERIC = /^[\s\d.,%+\-−/[\]()]+(\s?(s|min|%))?$/;

export function looksNumeric(value: unknown): boolean {
  if (typeof value === "number") return true;
  return typeof value === "string" && value.trim() !== "" && /\d/.test(value) && NUMERIC.test(value.trim());
}

// A column is right-aligned when most of its filled cells are numbers.
export function numericColumn(values: unknown[]): boolean {
  const filled = values.filter((v) => v !== null && v !== undefined && v !== "" && v !== "-");
  return filled.length > 0 && filled.filter(looksNumeric).length / filled.length >= 0.8;
}

// "llm_manager" -> "LLM Manager", "no_candidates" -> "no candidates".
export function ruleLabel(rule: string): string {
  return words(rule).replace(/\bmanager\b/, "Manager");
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n.toLocaleString("en-US")} ${n === 1 ? word : many}`;
}
