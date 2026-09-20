import type { RunStatus } from '../types';
import { formatElapsed, formatNumber } from '../lib/format';
import { useI18n } from '../lib/i18n';
import { isLanguage } from '../lib/localization';
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
  const { language, setLanguage, t, pending, error, retry } = useI18n();
  const running = status === 'running' || status === 'awaiting';

  return (
    <header className="hdr">
      <div className="hdr__brand">
        <div className="hdr__mark" aria-hidden="true">
          <span />
        </div>
        <div className="hdr__names">
          <h1 className="hdr__product">{t('Grocery Supply Disruption Response')}</h1>
          <p className="hdr__sub">
            {t('Vivalis Retail Group · Agentic response console — nationwide egg shortage')}
            <span className={`hdr__conn hdr__conn--${connClass(backendOnline)}`}>
              {backendOnline === null
                ? t('checking backend')
                : backendOnline
                  ? t('backend online')
                  : t('backend offline')}
            </span>
          </p>
        </div>
      </div>

      <div className="hdr__meta">
        <span className="hdr__incident" title={t('Active incident')}>
          <span className="hdr__incident-dot" aria-hidden="true" />
          {incidentId ?? t('No active incident')}
        </span>

        <span className={`hdr__pill hdr__pill--${status}`}>
          <span className="hdr__pill-dot" aria-hidden="true" />
          {t(STATUS_TEXT[status])}
        </span>

        <div className="hdr__stat">
          <span className="hdr__stat-label">{t('Elapsed')}</span>
          <span className="hdr__stat-value mono">{formatElapsed(elapsedMs)}</span>
        </div>

        <div className="hdr__stat">
          <span className="hdr__stat-label">{t('Tokens')}</span>
          <span className="hdr__stat-value mono">{formatNumber(totalTokens)}</span>
        </div>

        <div className="hdr__stat">
          <span className="hdr__stat-label">{t('Agents')}</span>
          <span className="hdr__stat-value mono">
            {formatNumber(completedNodes)}/{formatNumber(totalNodes)}
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
          {running ? t('Running…') : t('Run demonstration')}
        </button>
        <button type="button" className="btn" onClick={onReset} disabled={status === 'idle'}>
          {t('Reset')}
        </button>
        <label className="hdr__language" title={t('Language')}>
          <LanguageFlag language={language} />
          <select
            aria-label={t('Language')}
            value={language}
            onChange={(event) => {
              const value = event.target.value;
              if (isLanguage(value)) setLanguage(value);
            }}
          >
            <option value="en">🇬🇧 EN — {t('English')}</option>
            <option value="fr">🇫🇷 FR — {t('French')}</option>
            <option value="de">🇩🇪 GER — {t('German')}</option>
            <option value="es">🇪🇸 ES — {t('Spanish')}</option>
          </select>
        </label>
        <ThemeToggle />
      </div>
      {error || pending ? (
        <div className="hdr__translation" role="status" aria-live="polite">
          {error ? t('Translation unavailable. Showing original text.') : t('Translating content…')}
          {error ? (
            <button type="button" className="btn" onClick={retry}>
              {t('Retry translation')}
            </button>
          ) : null}
        </div>
      ) : null}
    </header>
  );
}

function LanguageFlag({ language }: { language: 'en' | 'fr' | 'de' | 'es' }) {
  return (
    <svg className="hdr__flag" viewBox="0 0 30 20" aria-hidden="true" focusable="false">
      {language === 'en' ? (
        <>
          <path fill="#012169" d="M0 0h30v20H0z" />
          <path stroke="#fff" strokeWidth="5" d="m0 0 30 20M30 0 0 20" />
          <path stroke="#c8102e" strokeWidth="2" d="m0 0 30 20M30 0 0 20" />
          <path stroke="#fff" strokeWidth="7" d="M15 0v20M0 10h30" />
          <path stroke="#c8102e" strokeWidth="4" d="M15 0v20M0 10h30" />
        </>
      ) : language === 'fr' ? (
        <>
          <path fill="#fff" d="M0 0h30v20H0z" />
          <path fill="#002395" d="M0 0h10v20H0z" />
          <path fill="#ed2939" d="M20 0h10v20H20z" />
        </>
      ) : language === 'de' ? (
        <>
          <path fill="#ffce00" d="M0 0h30v20H0z" />
          <path fill="#d00" d="M0 0h30v13.33H0z" />
          <path fill="#000" d="M0 0h30v6.67H0z" />
        </>
      ) : (
        <>
          <path fill="#aa151b" d="M0 0h30v20H0z" />
          <path fill="#f1bf00" d="M0 5h30v10H0z" />
          <path fill="#aa151b" d="M8 8h4v5H8z" />
        </>
      )}
    </svg>
  );
}

function connClass(online: boolean | null): string {
  if (online === null) return 'unknown';
  return online ? 'ok' : 'bad';
}

export default Header;
