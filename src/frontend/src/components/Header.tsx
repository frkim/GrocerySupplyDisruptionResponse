import type { RunStatus } from '../types';
import { formatElapsed, formatNumber } from '../lib/format';
import ThemeToggle from './ThemeToggle';
import './Header.css';

interface HeaderProps {
  incidentId: string | null;
  runId: string | null;
  status: RunStatus;
  elapsedMs: number;
  totalTokens: number;
  completedNodes: number;
  totalNodes: number;
  backendOnline: boolean | null;
  onRun: () => void;
  onReset: () => void;
}

const STATUS_TEXT: Record<RunStatus, string> = {
  idle: 'Standing by',
  running: 'Run in progress',
  awaiting: 'Awaiting approval',
  completed: 'Run complete',
  failed: 'Run failed',
};

export function Header({
  incidentId,
  runId,
  status,
  elapsedMs,
  totalTokens,
  completedNodes,
  totalNodes,
  backendOnline,
  onRun,
  onReset,
}: HeaderProps) {
  const running = status === 'running' || status === 'awaiting';

  return (
    <header className="hdr">
      <div className="hdr__brand">
        <div className="hdr__mark" aria-hidden="true">
          <span />
        </div>
        <div className="hdr__names">
          <h1 className="hdr__product">Grocery Supply Disruption Response</h1>
          <p className="hdr__sub">
            Vivalis Retail Group · Agentic response console — nationwide egg shortage
            <span className={`hdr__conn hdr__conn--${connClass(backendOnline)}`}>
              {backendOnline === null
                ? 'checking backend'
                : backendOnline
                  ? 'backend online'
                  : 'backend offline'}
            </span>
          </p>
        </div>
      </div>

      <div className="hdr__meta">
        <span className="hdr__incident" title="Active incident">
          <span className="hdr__incident-dot" aria-hidden="true" />
          {incidentId ?? 'No active incident'}
        </span>

        <span className={`hdr__pill hdr__pill--${status}`}>
          <span className="hdr__pill-dot" aria-hidden="true" />
          {STATUS_TEXT[status]}
        </span>

        <div className="hdr__stat">
          <span className="hdr__stat-label">Elapsed</span>
          <span className="hdr__stat-value mono">{formatElapsed(elapsedMs)}</span>
        </div>

        <div className="hdr__stat">
          <span className="hdr__stat-label">Tokens</span>
          <span className="hdr__stat-value mono">{formatNumber(totalTokens)}</span>
        </div>

        <div className="hdr__stat">
          <span className="hdr__stat-label">Agents</span>
          <span className="hdr__stat-value mono">
            {completedNodes}/{totalNodes}
          </span>
        </div>
      </div>

      <div className="hdr__actions">
        {runId ? <span className="hdr__runid mono">{runId}</span> : null}
        <button
          type="button"
          className="btn btn--primary"
          onClick={onRun}
          disabled={running}
        >
          {running ? 'Running…' : 'Run demonstration'}
        </button>
        <button type="button" className="btn" onClick={onReset} disabled={status === 'idle'}>
          Reset
        </button>
        <ThemeToggle />
      </div>
    </header>
  );
}

function connClass(online: boolean | null): string {
  if (online === null) return 'unknown';
  return online ? 'ok' : 'bad';
}

export default Header;
