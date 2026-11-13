import {
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useInternalNode,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type InternalNode,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useContext, useEffect, useMemo, useRef, type RefObject } from "react";
import { agentName, roleOf, type AgentStats, type Message, type RunState } from "../state/fold";
import { AgentIcon, AgentTag } from "./AgentIcon";
import { ANIMATE, Presenting, seconds } from "./common";

// A compact layout (about 790 by 330 units), so the graph can be zoomed up to fill a wide box.
const POS: Record<string, { x: number; y: number }> = {
  manager: { x: 300, y: 140 },
  explorer: { x: 20, y: 34 },
  auditor: { x: 20, y: 102 },
  investigator: { x: 20, y: 170 },
  planner: { x: 20, y: 238 },
  engineer: { x: 578, y: 30 },
  tester: { x: 578, y: 90 },
  validator: { x: 578, y: 150 },
  fixer: { x: 578, y: 210 },
  reporter: { x: 578, y: 270 },
  solo: { x: 300, y: 236 },
};
const GROUPS = [
  { id: "research", label: "Research squad", x: 4, y: 0, w: 226, h: 304 },
  { id: "development", label: "Development squad", x: 562, y: 0, w: 226, h: 332 },
];
const FIT = { padding: 0.05 };

type AgentData = { stats: AgentStats; active: boolean };
type GroupData = { label: string };

function AgentNode({ data }: NodeProps<Node<AgentData>>) {
  const s = data.stats;
  const many = s.instances.length > 1 ? ` ×${s.instances.length}` : "";
  return (
    <div className={`agent squad-${s.squad} ${data.active ? "active" : ""}`} data-agent={s.role}>
      <Handle type="target" position={Position.Left} className="hidden-handle" />
      <div className="agent-name">
        <AgentIcon agent={s.role} />
        <span className="agent-role">
          {s.role}
          {many}
        </span>
        {s.llmOpen > 0 && <span className="spinner small" aria-label="waiting for the LLM" />}
        {data.active && <span className="agent-now">at work</span>}
      </div>
      <div className="agent-stats">
        <span title="tool steps">{s.steps} steps</span>
        <span title="LLM calls">{s.llmCalls} LLM</span>
        <span title={`busy time: ${seconds(s.seconds)}`}>{s.seconds < 60 ? seconds(s.seconds) : `${Math.round(s.seconds / 60)} min`}</span>
      </div>
      <Handle type="source" position={Position.Right} className="hidden-handle" />
    </div>
  );
}

function GroupNode({ data }: NodeProps<Node<GroupData>>) {
  return <div className="squad-label">{data.label}</div>;
}

// Where the line from this node's centre to the other node's centre leaves this node's box.
function borderPoint(node: InternalNode, other: InternalNode) {
  const w = (node.measured.width ?? 0) / 2;
  const h = (node.measured.height ?? 0) / 2;
  const cx = node.internals.positionAbsolute.x + w;
  const cy = node.internals.positionAbsolute.y + h;
  const ox = other.internals.positionAbsolute.x + (other.measured.width ?? 0) / 2;
  const oy = other.internals.positionAbsolute.y + (other.measured.height ?? 0) / 2;
  const dx = ox - cx;
  const dy = oy - cy;
  if (!w || !h || (!dx && !dy)) return { x: cx, y: cy };
  const scale = 1 / Math.max(Math.abs(dx) / w, Math.abs(dy) / h);
  return { x: cx + dx * scale, y: cy + dy * scale };
}

// A message: a line from the sender's border to the recipient's, ending in an arrow. The newest
// one is highlighted, labelled with its type, and a dot travels along it.
// The path between two agents and where its label goes. Neighbours in one squad get a curve out
// to the squad's outer side, long enough to read as an arrow; others a straight line with the
// label just above its middle, beside the line rather than on it.
function edgeGeometry(from: InternalNode, to: InternalNode) {
  const box = (n: InternalNode) => {
    const { x, y } = n.internals.positionAbsolute;
    const w = n.measured.width ?? 0;
    const h = n.measured.height ?? 0;
    return { x, y, w, h, cx: x + w / 2, cy: y + h / 2 };
  };
  const f = box(from);
  const t = box(to);
  if (Math.abs(f.cx - t.cx) < 40) {
    const left = f.cx < 400;
    const ax = left ? f.x : f.x + f.w;
    const bx = left ? t.x : t.x + t.w;
    const out = left ? -44 : 44;
    return {
      path: `M ${ax},${f.cy} C ${ax + out},${f.cy} ${bx + out},${t.cy} ${bx},${t.cy}`,
      label: { x: ax + out * 0.8, y: (f.cy + t.cy) / 2 },
    };
  }
  const a = borderPoint(from, to);
  const b = borderPoint(to, from);
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  // the normal that points up, 16 units off the line
  const flip = dx >= 0 ? 1 : -1;
  return {
    path: `M ${a.x},${a.y} L ${b.x},${b.y}`,
    label: { x: (a.x + b.x) / 2 + (dy / len) * 16 * flip, y: (a.y + b.y) / 2 - (dx / len) * 16 * flip },
  };
}

function MessageEdge({ id, source, target, markerEnd, data }: EdgeProps<Edge<{ fresh: boolean; label?: string }>>) {
  const from = useInternalNode(source);
  const to = useInternalNode(target);
  if (!from || !to) return null;
  const { path, label } = edgeGeometry(from, to);
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} className={data?.fresh ? "msg-edge fresh" : "msg-edge"} />
      {data?.fresh && ANIMATE && (
        <g className="msg-dot">
          <circle r="11" className="msg-halo">
            <animateMotion dur="1.2s" repeatCount="indefinite" path={path} />
          </circle>
          <circle r="6">
            <animateMotion dur="1.2s" repeatCount="indefinite" path={path} />
          </circle>
        </g>
      )}
      {data?.label && (
        <EdgeLabelRenderer>
          <div className="msg-label" style={{ transform: `translate(-50%, -50%) translate(${label.x}px, ${label.y}px)` }}>
            {data.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

const nodeTypes = { agent: AgentNode, squad: GroupNode };
const edgeTypes = { message: MessageEdge };

// The recent messages as edges, newest first; two agents get one edge, the newest message's, so
// an older reply never adds a second arrowhead to the same line.
function edgesFor(messages: Message[]): Edge[] {
  const edges: Edge[] = [];
  const pairs = new Set<string>();
  [...messages].reverse().forEach((m, i) => {
    const fresh = i === 0;
    const from = roleOf(m.sender);
    for (const r of m.recipients) {
      const to = roleOf(r);
      const pair = [from, to].sort().join("|");
      if (!POS[from] || !POS[to] || from === to || pairs.has(pair)) continue;
      pairs.add(pair);
      edges.push({
        id: `${m.eventId}-${to}`,
        source: from,
        target: to,
        type: "message",
        markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18, color: fresh ? "var(--accent)" : "var(--neutral-mark)" },
        data: { fresh, label: fresh && to === roleOf(m.recipients[0]) ? m.type.replace(/_/g, " ") : undefined },
      });
    }
  });
  return edges;
}

// Keeps the whole team in view when the graph's box changes size (a tab, presentation mode).
function useFitOnResize(box: RefObject<HTMLDivElement | null>) {
  const flow = useReactFlow();
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => flow.fitView(FIT));
    observer.observe(el);
    return () => observer.disconnect();
  }, [flow]);
}

function Graph({ state, recent }: { state: RunState; recent: number }) {
  // the library is MIT licensed; its credit stays on screen except on a projector
  const presenting = useContext(Presenting);
  const box = useRef<HTMLDivElement>(null);
  useFitOnResize(box);
  const lastIds = state.messages.slice(-recent).map((m) => m.eventId).join(",");
  const nodes = useMemo<Node[]>(
    () => [
      ...GROUPS.map((g) => ({
        id: `group-${g.id}`,
        type: "squad",
        position: { x: g.x, y: g.y },
        data: { label: g.label },
        style: { width: g.w, height: g.h },
        className: `squad-box squad-${g.id}`,
        selectable: false,
        draggable: false,
        zIndex: -1,
      })),
      // the single-agent ablation's one agent appears only in its own runs
      ...Object.entries(POS)
        .filter(([role]) => role !== "solo" || state.agents.solo?.lastT != null)
        .map(([role, position]) => ({
          id: role,
          type: "agent",
          position,
          data: { stats: state.agents[role], active: state.active === role && !state.finished },
          draggable: false,
        })),
    ],
    // the stats objects are updated in place, so redraw on every new event
    [state.count, state.agents, state.active, state.finished],
  );
  const edges = useMemo(() => edgesFor(state.messages.slice(-recent)), [lastIds, recent]);
  const last = state.lastMessage;
  return (
    <div className="agent-graph" aria-label="Agent graph">
      <div className="agent-flow" ref={box}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          fitViewOptions={FIT}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          panOnDrag={false}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
          preventScrolling={false}
          proOptions={{ hideAttribution: presenting }}
        />
      </div>
      <div className="graph-caption" aria-live="polite">
        {last ? (
          <>
            <span className="graph-caption-label">Latest message</span>
            <AgentTag agent={last.sender} />
            <span className="arrow" aria-label="to">
              →
            </span>
            {last.recipients.map((r, i) => (
              <span key={r} className="recipient">
                <AgentTag agent={r} />
                {i < last.recipients.length - 1 && ","}
              </span>
            ))}
            <span className="msg-type">{last.type.replace(/_/g, " ")}</span>
          </>
        ) : (
          <span className="muted">No messages yet: the Manager sends the first one when the run starts.</span>
        )}
        {state.active && !state.finished && (
          <span className="graph-active">
            at work: <b>{agentName(state.active)}</b>
          </span>
        )}
      </div>
    </div>
  );
}

export function AgentGraph({ state, recent = 3 }: { state: RunState; recent?: number }) {
  return (
    <ReactFlowProvider>
      <Graph state={state} recent={recent} />
    </ReactFlowProvider>
  );
}
