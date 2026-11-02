import {
  BaseEdge,
  Handle,
  Position,
  ReactFlow,
  getStraightPath,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import { roleOf, type AgentStats, type Message, type RunState } from "../state/fold";
import { seconds } from "./common";

const POS: Record<string, { x: number; y: number }> = {
  manager: { x: 245, y: 150 },
  explorer: { x: 20, y: 40 },
  auditor: { x: 20, y: 115 },
  investigator: { x: 20, y: 190 },
  planner: { x: 20, y: 265 },
  engineer: { x: 500, y: 30 },
  tester: { x: 500, y: 95 },
  validator: { x: 500, y: 160 },
  fixer: { x: 500, y: 225 },
  reporter: { x: 500, y: 290 },
  solo: { x: 245, y: 260 },
};
const GROUPS = [
  { id: "research", label: "Research squad", x: 8, y: 10, w: 182, h: 320 },
  { id: "development", label: "Development squad", x: 488, y: 0, w: 182, h: 350 },
];

type AgentData = { stats: AgentStats; active: boolean };
type GroupData = { label: string };

function AgentNode({ data }: NodeProps<Node<AgentData>>) {
  const s = data.stats;
  const many = s.instances.length > 1 ? ` ×${s.instances.length}` : "";
  return (
    <div className={`agent squad-${s.squad} ${data.active ? "active" : ""} ${s.llmOpen ? "thinking" : ""}`} data-agent={s.role}>
      <Handle type="target" position={Position.Left} className="hidden-handle" />
      <div className="agent-name">
        {s.role}
        {many}
        {s.llmOpen > 0 && <span className="spinner small" aria-label="waiting for the LLM" />}
      </div>
      <div className="agent-stats">
        <span title="tool steps">{s.steps} steps</span>
        <span title="LLM calls">{s.llmCalls} LLM</span>
        <span title="busy time">{seconds(s.seconds)}</span>
      </div>
      <Handle type="source" position={Position.Right} className="hidden-handle" />
    </div>
  );
}

function GroupNode({ data }: NodeProps<Node<GroupData>>) {
  return <div className="squad-label">{data.label}</div>;
}

function MessageEdge({ id, sourceX, sourceY, targetX, targetY, data }: EdgeProps<Edge<{ fresh: boolean }>>) {
  const [path] = getStraightPath({ sourceX, sourceY, targetX, targetY });
  return (
    <>
      <BaseEdge id={id} path={path} className={data?.fresh ? "msg-edge fresh" : "msg-edge"} />
      {data?.fresh && (
        <circle r="5" className="msg-dot">
          <animateMotion dur="0.9s" repeatCount="indefinite" path={path} />
        </circle>
      )}
    </>
  );
}

const nodeTypes = { agent: AgentNode, squad: GroupNode };
const edgeTypes = { message: MessageEdge };

function edgesFor(messages: Message[]): Edge[] {
  const edges: Edge[] = [];
  messages.forEach((m, i) => {
    const fresh = i === messages.length - 1;
    const from = roleOf(m.sender);
    for (const r of m.recipients) {
      const to = roleOf(r);
      if (!POS[from] || !POS[to] || from === to) continue;
      edges.push({
        id: `${m.eventId}-${to}`,
        source: from,
        target: to,
        type: "message",
        data: { fresh },
        label: fresh && to === roleOf(m.recipients[0]) ? m.type : undefined,
      });
    }
  });
  return edges;
}

export function AgentGraph({ state, recent = 3 }: { state: RunState; recent?: number }) {
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
  return (
    <div className="agent-graph" aria-label="Agent graph">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        fitViewOptions={{ padding: 0.08 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
      />
      {state.lastMessage && (
        <div className="graph-caption">
          <b>{state.lastMessage.sender}</b> → {state.lastMessage.recipients.join(", ")}: <i>{state.lastMessage.type}</i>
        </div>
      )}
    </div>
  );
}
