import { SQUADS, roleOf } from "../state/fold";

// One stroke icon per agent role (24x24, currentColor); the role's name goes with it.
const PATHS: Record<string, string> = {
  manager: "M5 21V4h11l-2 4 2 4H5",
  explorer: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M15.5 8.5l-2 5-5 2 2-5z",
  auditor: "M9 4h6v3H9zM7 5.5H5V21h14V5.5h-2M8.5 12h7M8.5 16h4.5",
  investigator: "M10.5 4.5a6 6 0 1 0 0 12a6 6 0 1 0 0-12M15 15l5.5 5.5",
  planner: "M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2zM9 4v14M15 6v14",
  engineer: "M14.5 6.5a4 4 0 0 0-5.3 5.3L4 17l3 3 5.2-5.2a4 4 0 0 0 5.3-5.3l-2.4 2.4-2.6-.4-.4-2.6z",
  tester: "M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.7 3h10.6a2 2 0 0 0 1.7-3l-5-9V3M7.4 15h9.2",
  validator: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM8.5 12l2.5 2.5 4.5-5",
  fixer: "M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M12 8v8M8 12h8",
  reporter: "M7 3h7l4 4v14H7zM14 3v4h4M10 12h5M10 16h5",
  solo: "M12 4a4 4 0 1 0 0 8a4 4 0 1 0 0-8M4 21c1-4 4-6 8-6s7 2 8 6",
};

export function agentName(agent: string): string {
  const [role, instance] = agent.split("#");
  const name = role === "solo" ? "Single agent" : role.charAt(0).toUpperCase() + role.slice(1);
  if (!instance) return name;
  return /^\d+$/.test(instance) ? `${name} #${instance}` : `${name} (${instance})`;
}

export function AgentIcon({ agent, label }: { agent: string; label?: boolean }) {
  const role = roleOf(agent);
  const squad = SQUADS[role] === "single" ? "manager" : SQUADS[role] || "manager";
  return (
    <svg
      className={`agent-icon squad-${squad}`}
      viewBox="0 0 24 24"
      data-role={role}
      role={label ? "img" : undefined}
      aria-label={label ? agentName(agent) : undefined}
      aria-hidden={label ? undefined : true}
    >
      {label && <title>{agentName(agent)}</title>}
      <path d={PATHS[role] || PATHS.manager} />
    </svg>
  );
}

// An agent's icon with its name beside it.
export function AgentTag({ agent, short = false }: { agent: string; short?: boolean }) {
  const role = roleOf(agent);
  const squad = SQUADS[role] === "single" ? "manager" : SQUADS[role] || "manager";
  return (
    <span className={`agent-tag squad-${squad}`} data-agent={role}>
      <AgentIcon agent={agent} />
      <span className="agent-label">{short ? agentName(role) : agentName(agent)}</span>
    </span>
  );
}
