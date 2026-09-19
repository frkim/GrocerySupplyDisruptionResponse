import type { GraphNode, NodeResult, NodeState } from '../types';
import {
  COMPLETION_USD_PER_MILLION,
  CACHED_PROMPT_USD_PER_MILLION,
  DASH,
  HOSTING_LABEL,
  PROMPT_USD_PER_MILLION,
  estimateCostUsd,
  formatDurationMs,
  formatNumber,
  formatUsd,
  humanise,
} from '../lib/format';
import './GovernancePanel.css';

/** Shorter than the global labels so the narrow table column never overflows. */
const COMPACT_STATE: Record<NodeState, string> = {
  pending: 'Pending',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  skipped: 'Skipped',
  awaiting: 'Awaiting',
};

interface GovernancePanelProps {
  nodes: GraphNode[];
  states: Record<string, NodeState>;
  results: Record<string, NodeResult>;
  totalDurationMs: number;
}

export function GovernancePanel({
  nodes,
  states,
  results,
  totalDurationMs,
}: GovernancePanelProps) {
  const rows = nodes.map((node) => {
    const result = results[node.id];
    const promptTokens = result?.promptTokens ?? 0;
    const completionTokens = result?.completionTokens ?? 0;
    return {
      id: node.id,
      name: result?.agentName || node.label || humanise(node.id),
      hosting: result?.hostingMode ?? node.hostingMode,
      state: states[node.id] ?? 'pending',
      durationMs: result?.durationMs,
      promptTokens,
      completionTokens,
      totalTokens: result?.totalTokens ?? promptTokens + completionTokens,
      costUsd: estimateCostUsd(promptTokens, completionTokens),
    };
  });

  const totals = rows.reduce(
    (acc, row) => ({
      prompt: acc.prompt + row.promptTokens,
      completion: acc.completion + row.completionTokens,
      tokens: acc.tokens + row.totalTokens,
      cost: acc.cost + row.costUsd,
      completed: acc.completed + (row.state === 'completed' ? 1 : 0),
    }),
    { prompt: 0, completion: 0, tokens: 0, cost: 0, completed: 0 },
  );

  return (
    <section className="card gov">
      <div className="card__head">
        <h2 className="card__title">Governance &amp; cost</h2>
        <span className="chip">{rows.length} agents</span>
      </div>

      <div className="card__body card__body--flush gov__scroll">
        <table className="gov__table">
          <thead>
            <tr>
              <th scope="col">Agent</th>
              <th scope="col">Host</th>
              <th scope="col">State</th>
              <th scope="col" className="gov__num">
                Dur.
              </th>
              <th scope="col" className="gov__num">
                Tokens
              </th>
              <th scope="col" className="gov__num">
                Est. cost
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className={`gov__row gov__row--${row.state}`}>
                <td>
                  <span className="gov__name">{row.name}</span>
                  <span className="gov__id mono">{row.id}</span>
                </td>
                <td>
                  <span className={`gov__host gov__host--${row.hosting}`}>
                    {HOSTING_LABEL[row.hosting] ?? row.hosting}
                  </span>
                </td>
                <td>
                  <span className={`gov__state gov__state--${row.state}`}>
                    {COMPACT_STATE[row.state] ?? row.state}
                  </span>
                </td>
                <td className="gov__num mono">
                  {row.durationMs ? formatDurationMs(row.durationMs) : DASH}
                </td>
                <td className="gov__num mono">
                  {row.totalTokens ? formatNumber(row.totalTokens) : DASH}
                </td>
                <td className="gov__num mono">
                  {row.totalTokens ? formatUsd(row.costUsd) : DASH}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="gov__totals">
        <Total label="Completed" value={`${totals.completed}/${rows.length}`} />
        <Total label="Prompt" value={formatNumber(totals.prompt)} />
        <Total label="Completion" value={formatNumber(totals.completion)} />
        <Total label="Total tokens" value={formatNumber(totals.tokens)} />
        <Total label="Run time" value={formatDurationMs(totalDurationMs)} />
        <Total label="Est. cost" value={formatUsd(totals.cost)} accent />
      </div>

      <p className="gov__footnote">
        Pricing (1M Tokens): Input ${PROMPT_USD_PER_MILLION.toFixed(2)} · Cached Input $
        {CACHED_PROMPT_USD_PER_MILLION.toFixed(2)} · Output $
        {COMPLETION_USD_PER_MILLION.toFixed(2)}. Cost is an estimate only, computed at $
        {PROMPT_USD_PER_MILLION.toFixed(2)} per 1M prompt tokens and $
        {COMPLETION_USD_PER_MILLION.toFixed(2)} per 1M completion tokens. Cached input is not
        currently reported separately by the runtime. It is not billing data.
      </p>
    </section>
  );
}

function Total({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className={`gov__total ${accent ? 'gov__total--accent' : ''}`}>
      <span className="gov__total-label">{label}</span>
      <span className="gov__total-value mono">{value}</span>
    </div>
  );
}

export default GovernancePanel;
