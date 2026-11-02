import { useCallback, useEffect, useState } from "react";

export interface RunRow {
  root: string;
  path: string;
  name: string;
  kind: "v1" | "v2" | "watch";
  mtime: number;
  target: string | null;
  mode: string | null;
  model: string | null;
  verdict: string | null;
  finished: boolean;
  live?: boolean;
}

export interface Table {
  columns: string[];
  rows: unknown[][];
}

export interface RunDetail extends RunRow {
  report: {
    repo_id: string;
    method: string;
    started_at: string;
    stats: Record<string, any>;
    items: {
      item_id: string;
      unit: string;
      category: string;
      lane: string;
      action: string;
      reason: string;
      evidence: string[];
      safe_score: number | null;
    }[];
    results: { item_id: string; status: string; notes: string; diff: string; tests: any }[];
    has_final_diff: boolean;
  } | null;
  docs: string[];
  has_cache: boolean;
  live: boolean;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const query = params
    ? "?" +
      new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, String(v)]),
      ).toString()
    : "";
  const response = await fetch(path + query);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail || detail;
    } catch {
      // not JSON
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(data.detail || response.statusText, response.status);
  return data as T;
}

export interface Loaded<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

// Fetch a JSON resource once per change of `key` (null: don't fetch).
export function useApi<T>(key: string | null, load: () => Promise<T>): Loaded<T> {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean }>({
    data: null,
    error: null,
    loading: key !== null,
  });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (key === null) return;
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    load().then(
      (data) => alive && setState({ data, error: null, loading: false }),
      (err: Error) => alive && setState({ data: null, error: err.message, loading: false }),
    );
    return () => {
      alive = false;
    };
    // `load` is recreated each render; `key` names what it loads
  }, [key, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, reload };
}

export function imageUrl(root: string, path: string): string {
  return `/api/image?${new URLSearchParams({ root, path })}`;
}

export function runHash(row: { root: string; path: string; kind?: string }, mode: "live" | "replay" = "replay"): string {
  return `#/${mode === "live" ? "run" : "replay"}?${new URLSearchParams({ root: row.root, path: row.path })}`;
}
