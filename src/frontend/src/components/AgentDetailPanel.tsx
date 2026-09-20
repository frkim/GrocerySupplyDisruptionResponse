import { useState } from 'react';
import type { GraphNode, NodeResult, NodeState, ToolCall } from '../types';
import { useI18n } from '../lib/i18n';
import {
  DASH,
  HOSTING_LABEL,
  STATE_LABEL,
  formatDurationMs,
  formatNumber,
  humanise,
} from '../lib/format';
import './AgentDetailPanel.css';

interface AgentDetailPanelProps {
  node: GraphNode | null;
  state: NodeState;
  result: NodeResult | null;
  onClose: () => void;
}

export function AgentDetailPanel({ node, state, result, onClose }: AgentDetailPanelProps) {
  const { t, text, json } = useI18n();
  const [structuredOpen, setStructuredOpen] = useState(true);
  const structuredText = result?.structured ? json(result.structured) : '';

  if (!node) {
    return (
      <section className="card">
        <div className="card__head">
          <h2 className="card__title">{t('Agent detail')}</h2>
        </div>
        <div className="card__body">
          <p className="empty">{t('Select a node in the graph to inspect its output.')}</p>
        </div>
      </section>
    );
  }

  const hosting = result?.hostingMode ?? node.hostingMode;
  const toolCalls = result?.toolCalls ?? [];
  const hasStructured = Boolean(result?.structured && Object.keys(result.structured).length > 0);

  return (
    <div className="detail-modal" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section className="card detail detail-modal__dialog" role="dialog" aria-modal="true" aria-labelledby="agent-detail-title">
      <div className="card__head">
        <div>
          <h2 className="card__title" id="agent-detail-title">{t('Execution details')}</h2>
          <p className="detail__hint">{t('Input, output, timing, and tool activity for this node.')}</p>
        </div>
        <div className="detail__head-actions">
          <span className={`detail__state detail__state--${state}`}>{t(STATE_LABEL[state])}</span>
          <button type="button" className="icon-button" onClick={onClose} aria-label={t('Close execution details')} title={t('Close')}>
            ×
          </button>
        </div>
      </div>

      <div className="card__body detail__body">
        <div className="detail__id">
          <h3 className="detail__name">
            {text(node.label || humanise(node.id))}
          </h3>
          <p className="detail__desc">{node.description ? text(node.description) : t('No description supplied.')}</p>
          <div className="detail__tags">
            <span className="chip chip--accent">{t(HOSTING_LABEL[hosting] ?? hosting)}</span>
            <span className="chip">{text(humanise(node.group))}</span>
            <span className="chip mono">{node.id}</span>
            {result?.agentName ? <span className="chip mono">{result.agentName}</span> : null}
          </div>
        </div>

        <div className="detail__metrics">
          <Metric label="Duration" value={formatDurationMs(result?.durationMs)} />
          <Metric label="Prompt tokens" value={formatNumber(result?.promptTokens)} />
          <Metric label="Completion tokens" value={formatNumber(result?.completionTokens)} />
          <Metric label="Total tokens" value={formatNumber(result?.totalTokens)} />
        </div>

        <div className="detail__block">
          <span className="detail__block-title">{t('Input')}</span>
          <pre className="detail__json detail__json--input">{result?.input ? json(result.input) : DASH}</pre>
        </div>

        {result?.error ? (
          <div className="detail__error">
            <span className="detail__block-title">{t('Error')}</span>
            <p>{text(result.error)}</p>
          </div>
        ) : null}

        <section className="detail__output" aria-labelledby="agent-output-title">
          <div className="detail__block">
            <h3 className="detail__block-title" id="agent-output-title">{t('Output')}</h3>
            {result?.narrative ? (
              <p className="detail__narrative">{text(result.narrative)}</p>
            ) : (
              <p className="detail__placeholder">
                {state === 'pending'
                  ? t('This agent has not run yet.')
                  : state === 'running'
                    ? t('Agent is reasoning…')
                    : DASH}
              </p>
            )}
          </div>

          <div className="detail__block">
            <button
              type="button"
              className="detail__toggle"
              onClick={() => setStructuredOpen((open) => !open)}
              aria-expanded={structuredOpen}
              disabled={!hasStructured}
            >
              <span className={`detail__caret ${structuredOpen ? 'detail__caret--open' : ''}`}>
                ▸
              </span>
              {t('Structured output')}
              {hasStructured ? (
                <span className="detail__count">
                  {t('{count} keys', { count: formatNumber(Object.keys(result?.structured ?? {}).length) })}
                </span>
              ) : (
                <span className="detail__count">{t('empty')}</span>
              )}
            </button>
            {structuredOpen && hasStructured ? (
              <pre className="detail__json">{structuredText}</pre>
            ) : null}
          </div>
        </section>

        <div className="detail__block">
          <span className="detail__block-title">
            {t('Tool calls')}
            <span className="detail__count">{formatNumber(toolCalls.length)}</span>
          </span>
          {toolCalls.length === 0 ? (
            <p className="detail__placeholder">{t('No tools were invoked.')}</p>
          ) : (
            <ul className="detail__tools">
              {toolCalls.map((call, index) => (
                <ToolCallRow key={`${call.toolName ?? 'tool'}-${index}`} call={call} />
              ))}
            </ul>
          )}
        </div>
      </div>
      </section>
    </div>
  );
}

function ToolCallRow({ call }: { call: ToolCall }) {
  const { t, json } = useI18n();
  const [open, setOpen] = useState(false);

  return (
    <li className="detail__tool">
      <button
        type="button"
        className="detail__tool-head"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className={`detail__caret ${open ? 'detail__caret--open' : ''}`}>▸</span>
        <span className="detail__tool-name mono">{call.toolName ?? t('unnamed tool')}</span>
        <span className="detail__tool-time mono">{formatDurationMs(call.durationMs)}</span>
      </button>
      {open ? (
        <div className="detail__tool-body">
          <div className="detail__tool-field">
            <span className="detail__tool-label">{t('Arguments')}</span>
            <pre className="detail__json detail__json--inline">
              {call.arguments ? json(call.arguments) : DASH}
            </pre>
          </div>
          <div className="detail__tool-field">
            <span className="detail__tool-label">{t('Result')}</span>
            <pre className="detail__json detail__json--inline">
              {call.result ? json(call.result) : DASH}
            </pre>
          </div>
        </div>
      ) : null}
    </li>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  const { t } = useI18n();
  return (
    <div className="detail__metric">
      <span className="detail__metric-label">{t(label)}</span>
      <span className="detail__metric-value mono">{value}</span>
    </div>
  );
}

export default AgentDetailPanel;
