import type { NodeResult } from '../types';
import { useI18n } from '../lib/i18n';
import {
  DASH,
  formatCurrencyEur,
  formatNumber,
  pickArray,
  pickNumber,
} from '../lib/format';
import './ImpactDashboard.css';

interface ImpactDashboardProps {
  results: Record<string, NodeResult>;
}

interface MetricSpec {
  key: string;
  label: string;
  hint: string;
  tone: 'money' | 'ops' | 'customer';
  value: string;
  present: boolean;
}

export function ImpactDashboard({ results }: ImpactDashboardProps) {
  const { t, locale } = useI18n();
  const demand = results['demand_forecast']?.structured;
  const inventory = results['network_inventory']?.structured;
  const financial = results['financial_impact']?.structured;
  const store = results['store_impact']?.structured;
  const pricing = results['pricing_compliance']?.structured;
  const synthesis = results['impact_synthesis']?.structured;

  const revenueAtRisk = firstNumber(
    [financial, synthesis],
    ['revenueAtRiskEur', 'revenueAtRisk', 'totalRevenueAtRiskEur', 'estimatedRevenueAtRiskEur'],
  );
  const casesShort = firstNumber(
    [inventory, demand, synthesis],
    ['casesShort', 'shortfallCases', 'totalShortfallCases', 'weeklyShortfallCases', 'caseShortfall'],
  );
  const shelfAvailability = firstNumber(
    [store, inventory, synthesis],
    ['shelfAvailabilityPct', 'currentShelfAvailabilityPct', 'averageShelfAvailabilityPct', 'avgShelfAvailabilityPct'],
  );
  const storesAffected = firstCount(
    [store, inventory, synthesis],
    ['storesAffected', 'affectedStores', 'storeCountAffected', 'affectedStoreClusters'],
  );
  const penaltyExposure = firstNumber(
    [financial, pricing, synthesis],
    ['contractualPenaltyExposureEur', 'penaltyExposureEur', 'contractPenaltyExposureEur', 'estimatedPenaltyEur'],
  );
  const promotionExposure = firstNumber(
    [financial, pricing, synthesis],
    ['promotionExposureEur', 'promotionCancellationCostEur', 'promoExposureEur', 'printedLeafletExposureEur'],
  );

  const metrics: MetricSpec[] = [
    metric('revenue', 'Revenue at risk', 'financial_impact', 'money', formatCurrencyEur(revenueAtRisk), revenueAtRisk !== undefined),
    metric('cases', 'Cases short', 'network_inventory', 'ops', formatNumber(casesShort), casesShort !== undefined),
    metric('availability', 'Shelf availability', 'store_impact', 'customer', formatPercent(shelfAvailability, locale), shelfAvailability !== undefined),
    metric('stores', 'Stores affected', 'store_impact', 'customer', formatNumber(storesAffected), storesAffected !== undefined),
    metric('penalty', 'Penalty exposure', 'pricing_compliance', 'money', formatCurrencyEur(penaltyExposure), penaltyExposure !== undefined),
    metric('promotion', 'Promotion exposure', 'pricing_compliance', 'money', formatCurrencyEur(promotionExposure), promotionExposure !== undefined),
  ];

  const anyData = metrics.some((m) => m.present);

  return (
    <section className="card">
      <div className="card__head">
        <h2 className="card__title">{t('Business impact')}</h2>
        {!anyData ? <span className="chip">{t('awaiting assessment')}</span> : null}
      </div>
      <div className="card__body impact">
        <div className="impact__grid">
          {metrics.map((m) => (
            <div
              key={m.key}
              className={`impact__card impact__card--${m.tone} ${m.present ? '' : 'impact__card--empty'}`}
            >
              <span className="impact__label">{t(m.label)}</span>
              <span className="impact__value">{m.value}</span>
              <span className="impact__hint mono">{m.hint}</span>
            </div>
          ))}
        </div>
        {!anyData ? (
          <p className="impact__note">
            {t('Metrics populate as demand, inventory, finance, store and compliance agents report.')}
          </p>
        ) : null}
      </div>
    </section>
  );
}

function metric(
  key: string,
  label: string,
  hint: string,
  tone: MetricSpec['tone'],
  value: string,
  present: boolean,
): MetricSpec {
  return { key, label, hint, tone, value: present ? value : DASH, present };
}

function firstNumber(sources: Array<unknown>, keys: string[]): number | undefined {
  for (const source of sources) {
    const value = pickNumber(source, keys);
    if (value !== undefined) return value;
  }
  return undefined;
}

/** Counts accept either a number or an array of entities. */
function firstCount(sources: Array<unknown>, keys: string[]): number | undefined {
  for (const source of sources) {
    const arr = pickArray(source, keys);
    if (arr) return arr.length;
    const value = pickNumber(source, keys);
    if (value !== undefined) return value;
  }
  return undefined;
}

function formatPercent(value: number | undefined, locale: string): string {
  if (value === undefined) return DASH;
  return new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(value / 100);
}

export default ImpactDashboard;
