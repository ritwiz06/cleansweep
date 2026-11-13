import { createContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import type { Loaded, Table } from "../api";
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
export function Help({ text }: { text: string }) {
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
        className="help-button"
        aria-label="What am I looking at?"
        title="What am I looking at?"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen(!open)}
      >
        ?
      </button>
      {open && (
        <span id={id} className="help-pop" role="note">
          {text}
        </span>
      )}
    </span>
  );
}

// A screen's header: the title, one line on what the screen shows, and its actions.
export function PageHeader({
  title,
  description,
  help,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  help?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-head">
      <div className="page-head-text">
        <div className="page-title">
          <h2>{title}</h2>
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

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
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

function cell(value: unknown): ReactNode {
  if (value === null || value === undefined || value === "") return <span className="muted">-</span>;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return Number.isInteger(value) ? value : Math.round(value * 1000) / 1000;
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  // long cells are cut; the whole text is in the tooltip
  return text.length > CELL_CHARS ? <span title={text}>{text.slice(0, CELL_CHARS - 3)}...</span> : text;
}

// A results table (columns + rows); click a header to sort.
export function DataTable({
  table,
  filter,
  maxHeight = 420,
  label,
}: {
  table: Table | null | undefined;
  filter?: (row: unknown[]) => boolean;
  maxHeight?: number;
  label?: string;
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
                onClick={() => setSort((s) => ({ col: i, desc: s?.col === i ? !s.desc : false }))}
                aria-sort={sort?.col === i ? (sort.desc ? "descending" : "ascending") : "none"}
              >
                {c}
                {sort?.col === i ? (sort.desc ? " ▾" : " ▴") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>
              {row.map((v, c) => (
                // a long text gets a readable width instead of a column squeezed to a few words
                <td key={c} className={typeof v === "string" && v.length > 60 ? "wrap" : undefined}>
                  {cell(v)}
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
