import type { DisruptionSignal } from '../types';
import { DASH, formatNumber } from '../lib/format';
import './IncidentPanel.css';

interface IncidentPanelProps {
  signal: DisruptionSignal | null;
}

export function IncidentPanel({ signal }: IncidentPanelProps) {
  if (!signal) {
    return (
      <section className="card">
        <div className="card__head">
          <h2 className="card__title">Disruption signal</h2>
        </div>
        <div className="card__body">
          <p className="empty">No signal received.</p>
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
      ? `${signal.depletionDaysMin}–${signal.depletionDaysMax} days`
      : signal.depletionDaysMin !== undefined
        ? `${signal.depletionDaysMin}+ days`
        : DASH;

  return (
    <section className="card">
      <div className="card__head">
        <h2 className="card__title">Disruption signal</h2>
        <span className="chip">{signal.source ?? 'unknown source'}</span>
      </div>

      <div className="card__body inc">
        <div className="inc__headline">
          <span className="inc__label">Product at risk</span>
          <strong className="inc__product">
            {signal.productName ?? signal.productId ?? DASH}
          </strong>
          <span className="inc__id mono">{signal.productId ?? DASH}</span>
        </div>

        <div className="inc__grid">
          <Field label="Category" value={signal.category ?? DASH} />
          <Field label="Supplier" value={signal.supplierId ?? DASH} mono />
          <Field label="Days to depletion" value={depletionWindow} emphasis />
          <Field
            label="Supply shortfall"
            value={formatPercent(signal.supplyShortfallPct)}
            emphasis
          />
          <Field
            label="Demand surge"
            value={formatPercent(signal.demandSurgePct)}
            emphasis
          />
          <Field label="SKUs at risk" value={skus.length ? String(skus.length) : DASH} emphasis />
          <Field
            label="Detected"
            value={signal.detectedAt ? formatDetected(signal.detectedAt) : DASH}
          />
        </div>

        <div className="inc__confidence">
          <div className="inc__confidence-head">
            <span className="inc__label">Signal confidence</span>
            <span className="inc__confidence-value mono">
              {confidencePct === null ? DASH : `${confidencePct}%`}
            </span>
          </div>
          <div
            className="inc__bar"
            role="meter"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={confidencePct ?? 0}
            aria-label="Signal confidence"
          >
            <div
              className={`inc__bar-fill inc__bar-fill--${confidenceTone(confidence)}`}
              style={{ width: `${confidencePct ?? 0}%` }}
            />
          </div>
        </div>

        <ChipRow title="Affected regions" items={regions} tone="accent" />
        <ChipRow title="Affected DCs" items={warehouses} />
        <ChipRow title="Impacted SKUs" items={skus} max={10} />
        <div className="inc__root-cause">
          <span className="inc__label">Root cause</span>
          <p>{signal.rootCause || DASH}</p>
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
  return (
    <div className="inc__field">
      <span className="inc__label">{label}</span>
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
}: {
  title: string;
  items: string[];
  tone?: 'accent';
  max?: number;
}) {
  const shown = items.slice(0, max);
  const overflow = items.length - shown.length;

  return (
    <div className="inc__chips">
      <span className="inc__label">{title}</span>
      <div className="inc__chips-row">
        {shown.length === 0 ? (
          <span className="inc__value muted">{DASH}</span>
        ) : (
          shown.map((item) => (
            <span
              key={item}
              className={tone === 'accent' ? 'chip chip--accent' : 'chip'}
            >
              {item}
            </span>
          ))
        )}
        {overflow > 0 ? <span className="chip">+{overflow} more</span> : null}
      </div>
    </div>
  );
}

function clamp01(value: number): number {
  const scaled = value > 1 ? value / 100 : value;
  return Math.min(1, Math.max(0, scaled));
}

function formatPercent(value: number | undefined): string {
  if (value === undefined) return DASH;
  return `${formatNumber(value)}%`;
}

function confidenceTone(confidence: number | null): string {
  if (confidence === null) return 'idle';
  if (confidence >= 0.8) return 'bad';
  if (confidence >= 0.5) return 'warn';
  return 'ok';
}

function formatDetected(raw: string): string {
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default IncidentPanel;
