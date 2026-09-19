import type { ScenarioOption, ScenarioScores } from '../types';
import { DASH, formatCurrencyEur } from '../lib/format';
import './ScenarioComparison.css';

interface ScenarioComparisonProps {
  options: ScenarioOption[];
  recommendedId: string | null;
  selectedId: string | null;
  onSelect?: (optionId: string) => void;
}

const SCORE_DIMENSIONS: Array<{ key: keyof ScenarioScores; label: string }> = [
  { key: 'financial', label: 'Financial' },
  { key: 'operational', label: 'Operational' },
  { key: 'customer', label: 'Customer' },
  { key: 'compliance', label: 'Compliance' },
  { key: 'sustainability', label: 'Sustainability' },
];

export function ScenarioComparison({
  options,
  recommendedId,
  selectedId,
  onSelect,
}: ScenarioComparisonProps) {
  if (options.length === 0) return null;

  const maxScore = Math.max(
    10,
    ...options.flatMap((option) =>
      SCORE_DIMENSIONS.map(({ key }) => numberOr(option.scores?.[key], 0)),
    ),
  );

  return (
    <section className="card">
      <div className="card__head">
        <h2 className="card__title">Mitigation scenarios</h2>
        <span className="chip">{options.length} options evaluated</span>
      </div>

      <div className="card__body scen">
        <div className="scen__grid">
          {options.map((option) => {
            const recommended = option.optionId === recommendedId;
            const selected = option.optionId === selectedId;

            return (
              <article
                key={option.optionId}
                className={[
                  'scen__card',
                  recommended ? 'scen__card--recommended' : '',
                  selected ? 'scen__card--selected' : '',
                  onSelect ? 'scen__card--clickable' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={onSelect ? () => onSelect(option.optionId) : undefined}
              >
                <header className="scen__head">
                  <span className="scen__id">{option.optionId}</span>
                  <h3 className="scen__title">{option.title ?? `Option ${option.optionId}`}</h3>
                  {recommended ? <span className="scen__flag">Recommended</span> : null}
                </header>

                <p className="scen__desc">{option.description ?? DASH}</p>

                <div className="scen__facts">
                  <Fact label="Cost" value={formatCurrencyEur(option.costEur)} />
                  <Fact
                    label="Time to implement"
                    value={
                      option.timeToImplementDays !== undefined
                        ? `${option.timeToImplementDays} d`
                        : DASH
                    }
                  />
                  <Fact
                    label="Risk"
                    value={option.riskLevel ?? DASH}
                    tone={riskTone(option.riskLevel)}
                  />
                  <Fact
                    label="Primary lever"
                    value={formatLever(option.leverPrimary)}
                  />
                  <Fact
                    label="Shelf recovery"
                    value={
                      option.shelfAvailabilityRecoveryPct !== undefined
                        ? `${option.shelfAvailabilityRecoveryPct.toFixed(0)}%`
                        : DASH
                    }
                  />
                  <Fact
                    label="Total score"
                    value={
                      option.totalScore !== undefined ? option.totalScore.toFixed(1) : DASH
                    }
                    strong
                  />
                </div>

                <div className="scen__scores">
                  {SCORE_DIMENSIONS.map(({ key, label }) => {
                    const raw = option.scores?.[key];
                    const value = numberOr(raw, 0);
                    const pct = maxScore > 0 ? Math.min(100, (value / maxScore) * 100) : 0;
                    return (
                      <div key={String(key)} className="scen__score">
                        <span className="scen__score-label">{label}</span>
                        <span className="scen__score-track">
                          <span
                            className="scen__score-fill"
                            style={{ width: `${raw === undefined ? 0 : pct}%` }}
                          />
                        </span>
                        <span className="scen__score-value mono">
                          {raw === undefined ? DASH : value.toFixed(1)}
                        </span>
                      </div>
                    );
                  })}
                </div>

                <div className="scen__foot">
                  <div className="scen__foot-item">
                    <span className="scen__foot-label">Customer impact</span>
                    <span className="scen__foot-value">{option.customerImpact ?? DASH}</span>
                  </div>
                  <div className="scen__foot-item">
                    <span className="scen__foot-label">Expected outcome</span>
                    <span className="scen__foot-value">{option.expectedOutcome ?? DASH}</span>
                  </div>
                  <ListFact label="Key actions" items={option.keyActions} />
                  <ListFact label="Dependencies" items={option.dependencies} />
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

function Fact({
  label,
  value,
  tone,
  strong,
}: {
  label: string;
  value: string;
  tone?: string;
  strong?: boolean;
}) {
  return (
    <div className="scen__fact">
      <span className="scen__fact-label">{label}</span>
      <span
        className={[
          'scen__fact-value',
          strong ? 'scen__fact-value--strong' : '',
          tone ? `scen__fact-value--${tone}` : '',
        ]
          .filter(Boolean)
          .join(' ')}
      >
        {value}
      </span>
    </div>
  );
}

function riskTone(risk: string | undefined): string | undefined {
  if (!risk) return undefined;
  const normalised = risk.toLowerCase();
  if (normalised.includes('high') || normalised.includes('critical')) return 'bad';
  if (normalised.includes('medium') || normalised.includes('moderate')) return 'warn';
  if (normalised.includes('low')) return 'ok';
  return undefined;
}

function formatLever(lever: string | undefined): string {
  if (!lever) return DASH;
  return lever
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function ListFact({ label, items }: { label: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="scen__foot-item">
      <span className="scen__foot-label">{label}</span>
      <ul className="scen__list">
        {items.slice(0, 3).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function numberOr(value: number | undefined, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

export default ScenarioComparison;
