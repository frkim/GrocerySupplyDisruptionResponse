import { useMemo, useState } from 'react';
import type { GraphNode, NodeResult, NodeState, ToolCall } from '../types';
import {
  DASH,
  HOSTING_LABEL,
  STATE_LABEL,
  formatDurationMs,
  formatNumber,
  humanise,
  prettyJson,
  truncate,
} from '../lib/format';
import './AgentDetailPanel.css';

interface AgentDetailPanelProps {
  node: GraphNode | null;
  state: NodeState;
  result: NodeResult | null;
  onClose: () => void;
}

export function AgentDetailPanel({ node, state, result, onClose }: AgentDetailPanelProps) {
  const [structuredOpen, setStructuredOpen] = useState(true);

  const structuredText = useMemo(
    () => (result?.structured ? prettyJson(result.structured) : ''),
    [result?.structured],
  );

  if (!node) {
    return (
      <section className="card">
        <div className="card__head">
          <h2 className="card__title">Agent detail</h2>
        </div>
        <div className="card__body">
          <p className="empty">Select a node in the graph to inspect its output.</p>
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
          <h2 className="card__title" id="agent-detail-title">Execution details</h2>
          <p className="detail__hint">Input, output, timing, and tool activity for this node.</p>
        </div>
        <div className="detail__head-actions">
          <span className={`detail__state detail__state--${state}`}>{STATE_LABEL[state]}</span>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close execution details" title="Close">
            ×
          </button>
        </div>
      </div>

      <div className="card__body detail__body">
        <div className="detail__id">
          <h3 className="detail__name">
            {result?.agentName || node.label || humanise(node.id)}
          </h3>
          <p className="detail__desc">{node.description ?? 'No description supplied.'}</p>
          <div className="detail__tags">
            <span className="chip chip--accent">{HOSTING_LABEL[hosting] ?? hosting}</span>
            <span className="chip">{humanise(node.group)}</span>
            <span className="chip mono">{node.id}</span>
          </div>
        </div>

        <div className="detail__metrics">
          <Metric label="Duration" value={formatDurationMs(result?.durationMs)} />
          <Metric label="Prompt tokens" value={formatNumber(result?.promptTokens)} />
          <Metric label="Completion tokens" value={formatNumber(result?.completionTokens)} />
          <Metric label="Total tokens" value={formatNumber(result?.totalTokens)} />
        </div>

        <div className="detail__block">
          <span className="detail__block-title">Input</span>
          <pre className="detail__json detail__json--input">{result?.input || DASH}</pre>
        </div>

        {result?.error ? (
          <div className="detail__error">
            <span className="detail__block-title">Error</span>
            <p>{result.error}</p>
          </div>
        ) : null}

        <div className="detail__block">
          <span className="detail__block-title">Output</span>
          {result?.narrative ? (
            <p className="detail__narrative">{result.narrative}</p>
          ) : (
            <p className="detail__placeholder">
              {state === 'pending'
                ? 'This agent has not run yet.'
                : state === 'running'
                  ? 'Agent is reasoning…'
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
            Structured output
            {hasStructured ? (
              <span className="detail__count">
                {Object.keys(result?.structured ?? {}).length} keys
              </span>
            ) : (
              <span className="detail__count">empty</span>
            )}
          </button>
          {structuredOpen && hasStructured ? (
            <pre className="detail__json">{structuredText}</pre>
          ) : null}
        </div>

        <div className="detail__block">
          <span className="detail__block-title">
            Tool calls
            <span className="detail__count">{toolCalls.length}</span>
          </span>
          {toolCalls.length === 0 ? (
            <p className="detail__placeholder">No tools were invoked.</p>
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
        <span className="detail__tool-name mono">{call.toolName ?? 'unnamed tool'}</span>
        <span className="detail__tool-time mono">{formatDurationMs(call.durationMs)}</span>
      </button>
      {open ? (
        <div className="detail__tool-body">
          <div className="detail__tool-field">
            <span className="detail__tool-label">Arguments</span>
            <pre className="detail__json detail__json--inline">
              {call.arguments ? truncate(String(call.arguments), 1200) : DASH}
            </pre>
          </div>
          <div className="detail__tool-field">
            <span className="detail__tool-label">Result</span>
            <pre className="detail__json detail__json--inline">
              {call.result ? truncate(String(call.result), 1600) : DASH}
            </pre>
          </div>
        </div>
      ) : null}
    </li>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail__metric">
      <span className="detail__metric-label">{label}</span>
      <span className="detail__metric-value mono">{value}</span>
    </div>
  );
}

export default AgentDetailPanel;
