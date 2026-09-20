import type { GraphNode, NodeResult, NodeState } from '../types';
import { useI18n } from '../lib/i18n';
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
  const { t, text, locale } = useI18n();
  const price = (value: number) => new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
  const rows = nodes.map((node) => {
    const result = results[node.id];
    const promptTokens = result?.promptTokens ?? 0;
    const completionTokens = result?.completionTokens ?? 0;
    return {
      id: node.id,
      name: node.label || humanise(node.id),
      agentName: result?.agentName,
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
        <h2 className="card__title">{t('Governance & cost')}</h2>
        <span className="chip">{t('{count} agents', { count: formatNumber(rows.length) })}</span>
      </div>

      <div className="card__body card__body--flush gov__scroll">
        <table className="gov__table">
          <thead>
            <tr>
              <th scope="col">{t('Agent')}</th>
              <th scope="col">{t('Host')}</th>
              <th scope="col">{t('State')}</th>
              <th scope="col" className="gov__num">
                {t('Dur.')}
              </th>
              <th scope="col" className="gov__num">
                {t('Tokens')}
              </th>
              <th scope="col" className="gov__num">
                {t('Est. cost')}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className={`gov__row gov__row--${row.state}`}>
                <td>
                  <span className="gov__name" title={row.agentName}>{text(row.name)}</span>
                  <span className="gov__id mono">{row.id}</span>
                </td>
                <td>
                  <span className={`gov__host gov__host--${row.hosting}`}>
                    {t(HOSTING_LABEL[row.hosting] ?? row.hosting)}
                  </span>
                </td>
                <td>
                  <span className={`gov__state gov__state--${row.state}`}>
                    {t(COMPACT_STATE[row.state] ?? row.state)}
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
        <Total label="Completed" value={`${formatNumber(totals.completed)}/${formatNumber(rows.length)}`} />
        <Total label="Prompt" value={formatNumber(totals.prompt)} />
        <Total label="Completion" value={formatNumber(totals.completion)} />
        <Total label="Total tokens" value={formatNumber(totals.tokens)} />
        <Total label="Run time" value={formatDurationMs(totalDurationMs)} />
        <Total label="Est. cost" value={formatUsd(totals.cost)} accent />
      </div>

      <p className="gov__footnote">
        {t('Pricing (1M Tokens): Input {input} · Cached Input {cached} · Output {output}. Cost is an estimate only, computed at {input} per 1M prompt tokens and {output} per 1M completion tokens. Cached input is not currently reported separately by the runtime. It is not billing data.', {
          input: price(PROMPT_USD_PER_MILLION),
          cached: price(CACHED_PROMPT_USD_PER_MILLION),
          output: price(COMPLETION_USD_PER_MILLION),
        })}
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
  const { t } = useI18n();
  return (
    <div className={`gov__total ${accent ? 'gov__total--accent' : ''}`}>
      <span className="gov__total-label">{t(label)}</span>
      <span className="gov__total-value mono">{value}</span>
    </div>
  );
}

export default GovernancePanel;
