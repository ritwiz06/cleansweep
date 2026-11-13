import { createContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import type { Loaded, Table } from "../api";
import { columnDecimals, formatNumber, headerLabel, isIsoDate, numericColumn, shortDate, valueLabel } from "../state/labels";
import { StateChip, stateOf } from "./states";

// charts skip their entry animation when the reader asks for reduced motion (and the
// screenshots show finished charts)
export const ANIMATE =
  typeof window === "undefined" || !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

// True in presentation mode: no sidebar, large type, taller charts.
export const Presenting = createContext(false);

export function Loading({ what = "Loading" }: { what?: string }) {
  return (
    <div className="state loading" role="status">
      <span className="spinner" aria-hidden /> <span className="state-text">{what}...</span>
    </div>
  );
}

export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return (
    <div className="state error" role="alert">
      <span className="state-text">
        <strong>Could not load:</strong> {error}
      </span>
      {retry && (
        <button type="button" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}

// What an empty state offers to do next: a link (href) or a button (onClick).
export interface Action {
  label: string;
  href?: string;
  onClick?: () => void;
}

export function ActionButton({ action, primary = false }: { action: Action; primary?: boolean }) {
  if (action.href) {
    return (
      <a className={primary ? "button primary" : "button"} href={action.href}>
        {action.label}
      </a>
    );
  }
  return (
    <button type="button" className={primary ? "primary" : undefined} onClick={action.onClick}>
      {action.label}
    </button>
  );
}

export function Empty({ children, action }: { children: ReactNode; action?: Action }) {
  return (
    <div className="state empty">
      <span className="state-text">{children}</span>
      {action && <ActionButton action={action} />}
    </div>
  );
}

// Loading, error and empty states around a loaded resource.
export function Async<T>({
  res,
  what,
  empty,
  emptyAction,
  children,
}: {
  res: Loaded<T>;
  what?: string;
  empty?: (data: T) => ReactNode | null;
  emptyAction?: Action;
  children: (data: T) => ReactNode;
}) {
  if (res.loading && res.data === null) return <Loading what={what} />;
  if (res.error) return <ErrorBox error={res.error} retry={res.reload} />;
  if (res.data === null) return null;
  const blank = empty?.(res.data);
  return <>{blank ? <Empty action={emptyAction}>{blank}</Empty> : children(res.data)}</>;
}

// "What am I looking at?": one line about the screen, opened by the button beside the title.
// Escape or a click elsewhere closes it.
export function Help({
  text,
  children,
  label = "What am I looking at?",
  face = "?",
}: {
  text?: string;
  children?: ReactNode;
  label?: string;
  face?: string;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      box.current?.querySelector("button")?.focus();
    };
    const onDown = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);
  return (
    <span className="help" ref={box}>
      <button
        type="button"
        className={face === "?" ? "help-button" : "help-button wide"}
        aria-label={face === "?" ? label : undefined}
        title={label}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen(!open)}
      >
        {face}
      </button>
      {open && (
        <span id={id} className="help-pop" role="note">
          {children ?? text}
        </span>
      )}
    </span>
  );
}

// A screen's header: the title, one line on what the screen shows, and its actions.
export function PageHeader({
  title,
  titleTip,
  status,
  description,
  help,
  actions,
}: {
  title: ReactNode;
  titleTip?: string;
  status?: ReactNode;
  description?: ReactNode;
  help?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="page-head-text">
        <div className="page-title">
          <h2 title={titleTip}>{title}</h2>
          {status}
          {help && <Help text={help} />}
        </div>
        {description && <p className="page-desc">{description}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

// `scroll`: the card scrolls inside a fixed height, so it takes the focus for keyboard scrolling.
export function Card({
  title,
  actions,
  children,
  className = "",
  scroll = false,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  scroll?: boolean;
}) {
  return (
    <section className={`card ${className}`} tabIndex={scroll ? 0 : undefined}>
      {(title || actions) && (
        <header className="card-head">
          {title && <h3>{title}</h3>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      <div className="card-body">{children}</div>
    </section>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge tone-${tone}`}>{children}</span>;
}

export const STATUS_TONE: Record<string, string> = {
  kept: "good",
  repaired: "info",
  rolled_back: "bad",
  "rolled back": "bad",
  reverted: "bad",
  skipped: "neutral",
  failed: "bad",
  failing: "bad",
  done: "good",
  running: "warn",
  "in progress": "warn",
  stopped: "neutral",
  safe: "good",
  suggest: "warn",
  drop: "neutral",
  dropped: "neutral",
  accept: "good",
  reject: "bad",
  unsure: "warn",
  clean: "info",
  wait: "neutral",
  "everything runs": "good",
  "nothing applied": "neutral",
};

export function Status({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">-</span>;
  const state = stateOf(value);
  if (state) return <StateChip state={state} label={value.replace(/_/g, " ")} />;
  return <Badge tone={STATUS_TONE[value] || "neutral"}>{value.replace(/_/g, " ")}</Badge>;
}

export interface StatItem {
  label: string;
  value: ReactNode;
  hint?: string;
  lead?: boolean; // the screen's lead number: larger, two columns wide
  share?: number; // 0..1: a bar under the value
  tone?: string;
  aside?: ReactNode; // beside the value (a verdict chip)
}

// One row of numbers, the same on every screen: columns of one width, the value on top
// (tabular), a bar track under every value (filled for a share of a budget, so the values line
// up), and a short sentence-case label below.
export function StatsRow({ items, label }: { items: StatItem[]; label?: string }) {
  return (
    <div className="stats-row" role="group" aria-label={label}>
      {items.map((s) => (
        <div key={s.label} className={s.lead ? "stat lead" : "stat"} title={s.hint}>
          <div className="stat-top">
            <span className="stat-value">{s.value}</span>
            {s.aside}
          </div>
          {s.share !== undefined ? (
            <div className="bar" role="meter" aria-label={s.label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(s.share * 100)}>
              <div className={`fill tone-${s.tone || "good"}`} style={{ width: `${Math.min(s.share, 1) * 100}%` }} />
            </div>
          ) : (
            <div className="bar track" aria-hidden />
          )}
          <div className="stat-label">{s.label}</div>
        </div>
      ))}
    </div>
  );
}

export function Tabs<K extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { key: K; label: ReactNode }[];
  value: K;
  onChange: (key: K) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.key}
          role="tab"
          aria-selected={t.key === value}
          className={t.key === value ? "tab active" : "tab"}
          onClick={() => onChange(t.key)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

const CELL_CHARS = 160;
// columns whose values are outcomes, shown as chips
const STATUS_COLUMNS = new Set(["status", "result", "outcome", "verdict", "decision", "llm_decision"]);

function cell(value: unknown, column: string, decimals: number, rename?: (v: string) => string): ReactNode {
  if (value === null || value === undefined || value === "") return <span className="muted">-</span>;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return formatNumber(value, Number.isInteger(value) && decimals === 0 ? undefined : decimals);
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  if (rename) return rename(text);
  if (STATUS_COLUMNS.has(column)) return <Status value={text} />;
  if (isIsoDate(text)) return <span title={text}>{shortDate(text)}</span>;
  // long cells are cut; the whole text is in the tooltip
  if (text.length > CELL_CHARS) return <span title={text}>{text.slice(0, CELL_CHARS - 3)}...</span>;
  return valueLabel(text);
}

function cellClass(value: unknown, numeric: boolean): string | undefined {
  if (numeric) return "num";
  if (typeof value !== "string") return undefined;
  // a long text gets a readable width; a name or path never breaks
  if (value.length > 60) return "wrap";
  return /\s/.test(value) ? undefined : "ident";
}

// A results table (columns + rows): plain-word headers, numbers right-aligned with separators and
// one number of decimals per column, outcomes as chips; click a header to sort. `names` renames
// the values of a column (methods).
export function DataTable({
  table,
  filter,
  maxHeight = 420,
  label,
  names,
}: {
  table: Table | null | undefined;
  filter?: (row: unknown[]) => boolean;
  maxHeight?: number;
  label?: string;
  names?: Record<string, (value: string) => string>;
}) {
  const [sort, setSort] = useState<{ col: number; desc: boolean } | null>(null);
  const rows = useMemo(() => {
    if (!table) return [];
    const kept = filter ? table.rows.filter(filter) : [...table.rows];
    if (sort) {
      kept.sort((a, b) => {
        const x = a[sort.col] as number | string;
        const y = b[sort.col] as number | string;
        const order = x === y ? 0 : x === null ? 1 : y === null ? -1 : x < y ? -1 : 1;
        return sort.desc ? -order : order;
      });
    }
    return kept;
  }, [table, filter, sort]);
  const numeric = useMemo(() => (table ? table.columns.map((_, i) => numericColumn(table.rows.map((r) => r[i]))) : []), [table]);
  const decimals = useMemo(() => (table ? table.columns.map((_, i) => columnDecimals(table.rows.map((r) => r[i]))) : []), [table]);
  if (!table) return <Empty>No table yet.</Empty>;
  if (!table.rows.length) return <Empty>The table is empty.</Empty>;
  return (
    <div className="table-wrap" style={{ maxHeight }} tabIndex={0}>
      <table className="data" aria-label={label}>
        <thead>
          <tr>
            {table.columns.map((c, i) => (
              <th
                key={c}
                className={numeric[i] ? "num" : undefined}
                onClick={() => setSort((s) => ({ col: i, desc: s?.col === i ? !s.desc : false }))}
                aria-sort={sort?.col === i ? (sort.desc ? "descending" : "ascending") : "none"}
              >
                {headerLabel(c)}
                {sort?.col === i ? (sort.desc ? " ▾" : " ▴") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              {row.map((v, c) => (
                <td key={c} className={cellClass(v, numeric[c])}>
                  {cell(v, table.columns[c], decimals[c], names?.[table.columns[c]])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function seconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  if (value < 60) return `${value.toFixed(value < 10 ? 1 : 0)} s`;
  const total = Math.round(value); // 119.6 s is 2 min 0 s, not 1 min 60 s
  const m = Math.floor(total / 60);
  return `${m} min ${total - m * 60} s`;
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `${Math.round(value * 100)}%`;
}

export function Drawer({ title, onClose, children }: { title: ReactNode; onClose: () => void; children: ReactNode }) {
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, []);
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : "details"} onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <h3>{title}</h3>
          <button ref={close} className="icon" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}
