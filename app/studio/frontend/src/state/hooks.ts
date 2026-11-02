import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { newFolder, step, type Folder, type RunState, type StudioEvent } from "./fold";
import { clockOf, countAt, nextDecision, type Timed } from "./replay";

const FLUSH_MS = 200;
const TICK_MS = 100;

export interface EventFeed<E> {
  events: E[];
  done: boolean;
  error: string | null;
}

// A run's events: all at once for a recording, or streamed (server-sent events) while it runs.
export function useEvents<E>(root: string, path: string, live: boolean): EventFeed<E> {
  const [feed, setFeed] = useState<EventFeed<E>>({ events: [], done: false, error: null });
  useEffect(() => {
    setFeed({ events: [], done: false, error: null });
    if (!live) {
      let alive = true;
      api<E[]>("/api/run/events", { root, path }).then(
        (events) => alive && setFeed({ events, done: true, error: null }),
        (err: Error) => alive && setFeed({ events: [], done: true, error: err.message }),
      );
      return () => {
        alive = false;
      };
    }
    const buffer: E[] = [];
    let received = 0;
    let source: EventSource | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      if (!buffer.length) return;
      const fresh = buffer.splice(0);
      setFeed((f) => ({ ...f, events: [...f.events, ...fresh] }));
    };
    const open = () => {
      const params = new URLSearchParams({ root, path, after: String(received) });
      source = new EventSource(`/api/run/stream?${params}`);
      source.onmessage = (m) => {
        buffer.push(JSON.parse(m.data));
        received += 1;
      };
      source.addEventListener("end", () => {
        source?.close();
        closed = true;
        flush();
        setFeed((f) => ({ ...f, done: true }));
      });
      source.onerror = () => {
        source?.close();
        if (!closed) retry = setTimeout(open, 1000);
      };
    };
    open();
    const timer = setInterval(flush, FLUSH_MS);
    return () => {
      closed = true;
      source?.close();
      clearInterval(timer);
      if (retry) clearTimeout(retry);
    };
  }, [root, path, live]);
  return feed;
}

// The run state after the first `count` events, folded incrementally while count grows.
export function useFolded(events: StudioEvent[], count: number): RunState {
  const ref = useRef<{ folder: Folder; n: number; events: StudioEvent[] }>({ folder: newFolder(), n: 0, events });
  return useMemo(() => {
    let cur = ref.current;
    // a live feed grows by new arrays with the same first events
    const sameRun = cur.events === events || (cur.n <= events.length && cur.events[0] === events[0]);
    if (!sameRun || count < cur.n) cur = { folder: newFolder(), n: 0, events };
    for (let i = cur.n; i < Math.min(count, events.length); i++) step(cur.folder, events[i]);
    cur.n = Math.min(count, events.length);
    cur.events = events;
    ref.current = cur;
    // a new object each time, so components see the change
    return { ...cur.folder.state };
  }, [events, count]);
}

export interface Player {
  count: number;
  clock: number;
  playing: boolean;
  speed: number;
  setCount: (n: number) => void;
  setPlaying: (p: boolean) => void;
  setSpeed: (s: number) => void;
  stepOne: () => void;
  nextDecision: () => void;
}

// Replay controls: play at 1-50x the recorded pace, pause, step, scrub, jump to the next decision.
export function usePlayer(events: Timed[], initialSpeed = 10): Player {
  const [count, setCountRaw] = useState(0);
  const [clock, setClock] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(initialSpeed);
  const clockRef = useRef(0);
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      const end = events.length ? events[events.length - 1].t : 0;
      clockRef.current = Math.min(clockRef.current + (TICK_MS / 1000) * speed, end);
      setClock(clockRef.current);
      setCountRaw(countAt(events, clockRef.current));
      if (clockRef.current >= end) setPlaying(false);
    }, TICK_MS);
    return () => clearInterval(timer);
  }, [playing, speed, events]);
  const setCount = (n: number) => {
    const c = Math.max(0, Math.min(n, events.length));
    clockRef.current = clockOf(events, c);
    setClock(clockRef.current);
    setCountRaw(c);
  };
  return {
    count,
    clock,
    playing,
    speed,
    setCount,
    setPlaying,
    setSpeed,
    stepOne: () => setCount(count + 1),
    nextDecision: () => setCount(nextDecision(events, count)),
  };
}
