import { useMemo } from 'react';
import type { GraphNode, NodeGroup, NodeResult, NodeState, OrchestrationGraph } from '../types';
import { HOSTING_LABEL, formatDurationMs } from '../lib/format';
import './AgentGraph.css';

const NODE_W = 172;
const NODE_H = 64;
const GAP_X = 42;
const GAP_Y = 46;
const PAD = 34;

const GROUP_COLOR: Record<string, string> = {
  detection: '#38bdf8',
  situational: '#818cf8',
  impact: '#f472b6',
  remediation: '#fbbf24',
  validation: '#22d3ee',
  decision: '#a78bfa',
  execution: '#34d399',
};

const GROUP_LABEL: Record<string, string> = {
  detection: 'Detection',
  situational: 'Situational awareness',
  impact: 'Business impact',
  remediation: 'Remediation',
  validation: 'Specialist validation',
  decision: 'Decision',
  execution: 'Execution',
};

const HOSTING_SHORT: Record<string, string> = {
  foundry: 'FDY',
  local: 'LCL',
  a2a: 'A2A',
  system: 'SYS',
};

interface AgentGraphProps {
  graph: OrchestrationGraph;
  states: Record<string, NodeState>;
  results: Record<string, NodeResult>;
  selectedId: string | null;
  onSelect: (nodeId: string) => void;
}

interface Placed extends GraphNode {
  x: number;
  y: number;
}

export function AgentGraph({
  graph,
  states,
  results,
  selectedId,
  onSelect,
}: AgentGraphProps) {
  const { placed, byId, width, height } = useMemo(() => layout(graph.nodes), [graph.nodes]);

  if (placed.length === 0) {
    return (
      <section className="card graph">
        <div className="card__head">
          <h2 className="card__title">Agent orchestration graph</h2>
        </div>
        <div className="card__body">
          <p className="empty">Topology unavailable.</p>
        </div>
      </section>
    );
  }

  const runningCount = placed.filter((n) => states[n.id] === 'running').length;

  return (
    <section className="card graph">
      <div className="card__head">
        <h2 className="card__title">Agent orchestration graph</h2>
        <div className="graph__head-meta">
          {runningCount > 1 ? (
            <span className="graph__parallel">
              <span className="graph__parallel-dot" aria-hidden="true" />
              {runningCount} agents running in parallel
            </span>
          ) : null}
          <span className="chip">{placed.length} nodes</span>
        </div>
      </div>

      <div className="card__body card__body--flush graph__canvas">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="graph__svg"
          role="img"
          aria-label="Multi-agent orchestration graph"
        >
          <defs>
            <marker
              id="arrow-idle"
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="7"
              markerHeight="7"
              orient="auto"
            >
              <path d="M0,0 L8,4 L0,8 z" fill="#2c3448" />
            </marker>
            <marker
              id="arrow-live"
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="7"
              markerHeight="7"
              orient="auto"
            >
              <path d="M0,0 L8,4 L0,8 z" fill="#38bdf8" />
            </marker>
          </defs>

          <g className="graph__edges">
            {graph.edges.map((edge, index) => {
              const from = byId.get(edge.from);
              const to = byId.get(edge.to);
              if (!from || !to) return null;

              const sourceState = states[edge.from] ?? 'pending';
              const targetState = states[edge.to] ?? 'pending';
              const live = sourceState === 'completed';
              const flowing =
                live && (targetState === 'running' || targetState === 'awaiting');

              return (
                <path
                  key={`${edge.from}->${edge.to}-${index}`}
                  d={edgePath(from, to)}
                  className={[
                    'graph__edge',
                    live ? 'graph__edge--live' : '',
                    flowing ? 'graph__edge--flowing' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  markerEnd={live ? 'url(#arrow-live)' : 'url(#arrow-idle)'}
                />
              );
            })}
          </g>

          <g className="graph__nodes">
            {placed.map((node) => {
              const state = states[node.id] ?? 'pending';
              const result = results[node.id];
              const selected = selectedId === node.id;
              const accent = groupColor(node.group);
              const lines = wrapLabel(node.label || node.id);

              return (
                <g
                  key={node.id}
                  className={[
                    'graph__node',
                    `graph__node--${state}`,
                    selected ? 'graph__node--selected' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  transform={`translate(${node.x}, ${node.y})`}
                  onClick={() => onSelect(node.id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onSelect(node.id);
                    }
                  }}
                  tabIndex={0}
                  role="button"
                  aria-label={`${node.label} — ${state}`}
                >
                  <rect
                    className="graph__node-halo"
                    x={-3}
                    y={-3}
                    width={NODE_W + 6}
                    height={NODE_H + 6}
                    rx={12}
                  />
                  <rect
                    className="graph__node-box"
                    width={NODE_W}
                    height={NODE_H}
                    rx={10}
                  />
                  <rect
                    className="graph__node-accent"
                    width={3}
                    height={NODE_H - 20}
                    x={0}
                    y={10}
                    rx={2}
                    fill={accent}
                  />

                  <text className="graph__node-label" x={13} y={lines.length > 1 ? 22 : 27}>
                    {lines[0]}
                  </text>
                  {lines[1] ? (
                    <text className="graph__node-label" x={13} y={36}>
                      {lines[1]}
                    </text>
                  ) : null}

                  <text className="graph__node-badge" x={13} y={NODE_H - 12}>
                    {HOSTING_SHORT[node.hostingMode] ?? 'AGT'}
                  </text>
                  <text className="graph__node-sub" x={46} y={NODE_H - 12}>
                    {state === 'completed' && result?.durationMs
                      ? formatDurationMs(result.durationMs)
                      : stateWord(state)}
                  </text>

                  <circle
                    className="graph__node-state"
                    cx={NODE_W - 15}
                    cy={NODE_H - 16}
                    r={5}
                  />
                  {state === 'running' || state === 'awaiting' ? (
                    <circle
                      className="graph__node-ping"
                      cx={NODE_W - 15}
                      cy={NODE_H - 16}
                      r={5}
                    />
                  ) : null}
                </g>
              );
            })}
          </g>
        </svg>
      </div>

      <div className="graph__legend">
        <div className="graph__legend-group">
          <span className="graph__legend-title">State</span>
          {(
            [
              ['pending', 'Pending'],
              ['running', 'Running'],
              ['completed', 'Completed'],
              ['awaiting', 'Awaiting'],
              ['failed', 'Failed'],
              ['skipped', 'Skipped'],
            ] as const
          ).map(([key, label]) => (
            <span key={key} className={`graph__legend-item graph__legend-item--${key}`}>
              <span className="graph__legend-dot" aria-hidden="true" />
              {label}
            </span>
          ))}
        </div>
        <div className="graph__legend-group">
          <span className="graph__legend-title">Hosting</span>
          {(['foundry', 'local', 'a2a', 'system'] as const).map((mode) => (
            <span key={mode} className="graph__legend-item">
              <span className="graph__legend-badge">{HOSTING_SHORT[mode]}</span>
              {HOSTING_LABEL[mode]}
            </span>
          ))}
        </div>
        <div className="graph__legend-group">
          <span className="graph__legend-title">Stage</span>
          {Object.keys(GROUP_LABEL).map((group) => (
            <span key={group} className="graph__legend-item">
              <span
                className="graph__legend-swatch"
                style={{ background: groupColor(group as NodeGroup) }}
                aria-hidden="true"
              />
              {GROUP_LABEL[group]}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

function groupColor(group: NodeGroup | string): string {
  return GROUP_COLOR[group] ?? '#64748b';
}

function stateWord(state: NodeState): string {
  switch (state) {
    case 'running':
      return 'running…';
    case 'awaiting':
      return 'awaiting';
    case 'failed':
      return 'failed';
    case 'skipped':
      return 'skipped';
    case 'completed':
      return 'done';
    default:
      return 'queued';
  }
}

function layout(nodes: GraphNode[]): {
  placed: Placed[];
  byId: Map<string, Placed>;
  width: number;
  height: number;
} {
  if (nodes.length === 0) {
    return { placed: [], byId: new Map(), width: 100, height: 100 };
  }

  const rows = nodes.map((n) => (Number.isFinite(n.row) ? n.row : 0));
  const cols = nodes.map((n) => (Number.isFinite(n.col) ? n.col : 0));
  const minRow = Math.min(...rows);
  const minCol = Math.min(...cols);
  const maxRow = Math.max(...rows);
  const maxCol = Math.max(...cols);

  const placed: Placed[] = nodes.map((node) => {
    const row = (Number.isFinite(node.row) ? node.row : 0) - minRow;
    const col = (Number.isFinite(node.col) ? node.col : 0) - minCol;
    return {
      ...node,
      x: PAD + col * (NODE_W + GAP_X),
      y: PAD + row * (NODE_H + GAP_Y),
    };
  });

  const byId = new Map<string, Placed>();
  for (const node of placed) byId.set(node.id, node);

  const width = PAD * 2 + (maxCol - minCol + 1) * NODE_W + (maxCol - minCol) * GAP_X;
  const height = PAD * 2 + (maxRow - minRow + 1) * NODE_H + (maxRow - minRow) * GAP_Y;

  return { placed, byId, width, height };
}

function edgePath(from: Placed, to: Placed): string {
  const gap = 6; // keeps the arrowhead clear of the target border
  const sameRow = from.y === to.y;

  if (sameRow) {
    const forward = to.x >= from.x;
    const sx = forward ? from.x + NODE_W : from.x;
    const tx = forward ? to.x - gap : to.x + NODE_W + gap;
    const y = from.y + NODE_H / 2;
    const bend = Math.max(24, Math.abs(tx - sx) / 2);
    const c1 = forward ? sx + bend : sx - bend;
    const c2 = forward ? tx - bend : tx + bend;
    return `M ${sx} ${y} C ${c1} ${y}, ${c2} ${y}, ${tx} ${y}`;
  }

  const downward = to.y > from.y;
  const sx = from.x + NODE_W / 2;
  const sy = downward ? from.y + NODE_H : from.y;
  const tx = to.x + NODE_W / 2;
  const ty = downward ? to.y - gap : to.y + NODE_H + gap;
  const span = Math.abs(ty - sy);
  const bend = Math.max(22, Math.min(span * 0.55, 70));
  const c1y = downward ? sy + bend : sy - bend;
  const c2y = downward ? ty - bend : ty + bend;

  return `M ${sx} ${sy} C ${sx} ${c1y}, ${tx} ${c2y}, ${tx} ${ty}`;
}

/** Split a node label onto at most two lines that fit inside the box. */
function wrapLabel(label: string, maxChars = 21): [string, string?] {
  if (label.length <= maxChars) return [label];

  const words = label.split(' ');
  let first = '';
  let index = 0;
  while (index < words.length) {
    const word = words[index] ?? '';
    const candidate = first ? `${first} ${word}` : word;
    if (candidate.length > maxChars && first) break;
    first = candidate;
    index += 1;
  }
  let second = words.slice(index).join(' ');
  if (!second) return [first];
  if (second.length > maxChars) second = `${second.slice(0, maxChars - 1)}…`;
  return [first, second];
}

export default AgentGraph;
