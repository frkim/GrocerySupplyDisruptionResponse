import type { DisruptionSignal } from '../types';
import { DASH, formatNumber } from '../lib/format';
import { useI18n } from '../lib/i18n';
import './IncidentPanel.css';

interface IncidentPanelProps {
  signal: DisruptionSignal | null;
}

export function IncidentPanel({ signal }: IncidentPanelProps) {
  const { t, text, locale } = useI18n();
  const percent = (value: number | undefined) => value === undefined
    ? DASH
    : new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 1 }).format(value / 100);
  if (!signal) {
    return (
      <section className="card">
        <div className="card__head">
          <h2 className="card__title">{t('Disruption signal')}</h2>
        </div>
        <div className="card__body">
          <p className="empty">{t('No signal received.')}</p>
        </div>
      </section>
    );
  }

  const confidence =
    typeof signal.confidence === 'number' ? clamp01(signal.confidence) : null;
  const confidencePct = confidence === null ? null : Math.round(confidence * 100);

  const skus = signal.impactedSkus ?? [];
  const regions = signal.affectedRegions ?? [];
  const warehouses = signal.affectedWarehouses ?? [];

  const depletionWindow =
    signal.depletionDaysMin !== undefined && signal.depletionDaysMax !== undefined
      ? t('{min}–{max} days', { min: signal.depletionDaysMin.toLocaleString(locale), max: signal.depletionDaysMax.toLocaleString(locale) })
      : signal.depletionDaysMin !== undefined
        ? t('{count}+ days', { count: signal.depletionDaysMin.toLocaleString(locale) })
        : DASH;

  return (
    <section className="card">
      <div className="card__head">
        <h2 className="card__title">{t('Disruption signal')}</h2>
        <span className="chip">{signal.source ? text(signal.source) : t('unknown source')}</span>
      </div>

      <div className="card__body inc">
        <div className="inc__headline">
          <span className="inc__label">{t('Product at risk')}</span>
          <strong className="inc__product">
            {signal.productName ? text(signal.productName) : signal.productId ?? DASH}
          </strong>
          <span className="inc__id mono">{signal.productId ?? DASH}</span>
        </div>

        <div className="inc__grid">
          <Field label="Category" value={signal.category ? text(signal.category) : DASH} />
          <Field label="Supplier" value={signal.supplierId ?? DASH} mono />
          <Field label="Days to depletion" value={depletionWindow} emphasis />
          <Field
            label="Supply shortfall"
            value={percent(signal.supplyShortfallPct)}
            emphasis
          />
          <Field
            label="Demand surge"
            value={percent(signal.demandSurgePct)}
            emphasis
          />
          <Field label="SKUs at risk" value={skus.length ? formatNumber(skus.length) : DASH} emphasis />
          <Field
            label="Detected"
            value={signal.detectedAt ? formatDetected(signal.detectedAt, locale) : DASH}
          />
        </div>

        <div className="inc__confidence">
          <div className="inc__confidence-head">
            <span className="inc__label">{t('Signal confidence')}</span>
            <span className="inc__confidence-value mono">
              {confidencePct === null ? DASH : percent(confidencePct)}
            </span>
          </div>
          <div
            className="inc__bar"
            role="meter"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={confidencePct ?? 0}
            aria-label={t('Signal confidence')}
          >
            <div
              className={`inc__bar-fill inc__bar-fill--${confidenceTone(confidence)}`}
              style={{ width: `${confidencePct ?? 0}%` }}
            />
          </div>
        </div>

        <ChipRow title="Affected regions" items={regions} tone="accent" translate />
        <ChipRow title="Affected DCs" items={warehouses} />
        <ChipRow title="Impacted SKUs" items={skus} max={10} />
        <div className="inc__root-cause">
          <span className="inc__label">{t('Root cause')}</span>
          <p>{signal.rootCause ? text(signal.rootCause) : DASH}</p>
        </div>
      </div>
    </section>
  );
}

function Field({
  label,
  value,
  mono,
  emphasis,
}: {
  label: string;
  value: string;
  mono?: boolean;
  emphasis?: boolean;
}) {
  const { t } = useI18n();
  return (
    <div className="inc__field">
      <span className="inc__label">{t(label)}</span>
      <span
        className={[
          'inc__value',
          mono ? 'mono' : '',
          emphasis ? 'inc__value--em' : '',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        {value}
      </span>
    </div>
  );
}

function ChipRow({
  title,
  items,
  tone,
  max = 24,
  translate = false,
}: {
  title: string;
  items: string[];
  tone?: 'accent';
  max?: number;
  translate?: boolean;
}) {
  const { t, text } = useI18n();
  const shown = items.slice(0, max);
  const overflow = items.length - shown.length;

  return (
    <div className="inc__chips">
      <span className="inc__label">{t(title)}</span>
      <div className="inc__chips-row">
        {shown.length === 0 ? (
          <span className="inc__value muted">{DASH}</span>
        ) : (
          shown.map((item) => (
            <span
              key={item}
              className={tone === 'accent' ? 'chip chip--accent' : 'chip'}
            >
              {translate ? text(item) : item}
            </span>
          ))
        )}
        {overflow > 0 ? <span className="chip">{t('+{count} more', { count: formatNumber(overflow) })}</span> : null}
      </div>
    </div>
  );
}

function clamp01(value: number): number {
  const scaled = value > 1 ? value / 100 : value;
  return Math.min(1, Math.max(0, scaled));
}

function confidenceTone(confidence: number | null): string {
  if (confidence === null) return 'idle';
  if (confidence >= 0.8) return 'bad';
  if (confidence >= 0.5) return 'warn';
  return 'ok';
}

function formatDetected(raw: string, locale: string): string {
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toLocaleString(locale, {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default IncidentPanel;
