import { useEffect, useMemo, useState } from 'react';
import type { GateRecommendation, RunDecision, ScenarioOption } from '../types';
import { DASH, formatCurrencyEur } from '../lib/format';
import { useI18n } from '../lib/i18n';
import './ApprovalGate.css';

interface ApprovalGateProps {
  runId: string | null;
  options: ScenarioOption[];
  recommendation: GateRecommendation | null;
  decision: RunDecision | null;
  submitting: boolean;
  error: string | null;
  selectedOptionId: string | null;
  onSelectOption: (optionId: string) => void;
  onSubmit: (payload: { optionId: string; approver: string; notes: string }) => void;
}

const DEFAULT_APPROVER = 'Chief Supply Chain Officer';

export function ApprovalGate({
  runId,
  options,
  recommendation,
  decision,
  submitting,
  error,
  selectedOptionId,
  onSelectOption,
  onSubmit,
}: ApprovalGateProps) {
  const { t, text, locale } = useI18n();
  const [approver, setApprover] = useState(DEFAULT_APPROVER);
  const [notes, setNotes] = useState('');

  const recommendedOption = useMemo(
    () => options.find((option) => option.optionId === recommendation?.optionId) ?? null,
    [options, recommendation?.optionId],
  );

  useEffect(() => {
    if (!selectedOptionId && recommendation?.optionId) {
      onSelectOption(recommendation.optionId);
    }
  }, [recommendation?.optionId, selectedOptionId, onSelectOption]);

  if (decision) {
    return (
      <section className="card gate gate--resolved">
        <div className="card__head">
          <h2 className="card__title">{t('Executive decision')}</h2>
          <span className="gate__badge gate__badge--approved">{t('Approved')}</span>
        </div>
        <div className="card__body gate__body">
          <div className="gate__resolved">
            <div>
              <span className="gate__label">{t('Selected option')}</span>
              <strong className="gate__resolved-option">
                {decision.optionId ?? DASH}
                {optionTitle(options, decision.optionId) ? (
                  <span className="gate__resolved-title">
                    {text(optionTitle(options, decision.optionId) ?? '')}
                  </span>
                ) : null}
              </strong>
            </div>
            <div>
              <span className="gate__label">{t('Approver')}</span>
              <span className="gate__resolved-value">
                {decision.approver === DEFAULT_APPROVER ? t(DEFAULT_APPROVER) : decision.approver ?? DASH}
              </span>
            </div>
            {decision.notes ? (
              <div className="gate__resolved-notes">
                <span className="gate__label">{t('Notes')}</span>
                <p>{text(String(decision.notes))}</p>
              </div>
            ) : null}
          </div>
        </div>
      </section>
    );
  }

  const canSubmit = Boolean(runId && selectedOptionId && approver.trim() && !submitting);

  return (
    <section className="card gate gate--awaiting">
      <div className="card__head">
        <h2 className="card__title">{t('Executive approval gate')}</h2>
        <span className="gate__badge gate__badge--awaiting">
          <span className="gate__badge-dot" aria-hidden="true" />
          {t('Run paused — decision required')}
        </span>
      </div>

      <div className="card__body gate__body">
        <div className="gate__recommendation">
          <span className="gate__label">{t('Agent recommendation')}</span>
          <div className="gate__rec-head">
            <span className="gate__rec-id">{recommendation?.optionId ?? DASH}</span>
            <strong className="gate__rec-title">
              {recommendedOption?.title ? text(recommendedOption.title) : t('No recommendation supplied')}
            </strong>
            {recommendedOption?.costEur !== undefined ? (
              <span className="gate__rec-cost mono">
                {formatCurrencyEur(recommendedOption.costEur)}
              </span>
            ) : null}
          </div>
          <p className="gate__rationale">
            {recommendation?.rationale ? text(recommendation.rationale) : t('The deliberation agent returned no rationale.')}
          </p>
        </div>

        <div className="gate__choices">
          <span className="gate__label">{t('Select the option to authorise')}</span>
          <div className="gate__choice-row">
            {options.length === 0 ? (
              <span className="muted">{t('No options available.')}</span>
            ) : (
              options.map((option) => {
                const active = option.optionId === selectedOptionId;
                const recommended = option.optionId === recommendation?.optionId;
                return (
                  <button
                    key={option.optionId}
                    type="button"
                    className={[
                      'gate__choice',
                      active ? 'gate__choice--active' : '',
                      recommended ? 'gate__choice--recommended' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    onClick={() => onSelectOption(option.optionId)}
                    aria-pressed={active}
                  >
                    <span className="gate__choice-id">{option.optionId}</span>
                    <span className="gate__choice-title">
                      {option.title ? text(option.title) : t('Option {id}', { id: option.optionId })}
                    </span>
                    <span className="gate__choice-meta mono">
                      {formatCurrencyEur(option.costEur)}
                      {option.timeToImplementDays !== undefined
                        ? ` · ${t('{count} d', { count: option.timeToImplementDays.toLocaleString(locale) })}`
                        : ''}
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </div>

        <div className="gate__form">
          <label className="gate__field">
            <span className="gate__label">{t('Approver')}</span>
            <input
              type="text"
              value={approver === DEFAULT_APPROVER ? t(DEFAULT_APPROVER) : approver}
              onChange={(event) => setApprover(event.target.value)}
              placeholder={t(DEFAULT_APPROVER)}
            />
          </label>
          <label className="gate__field gate__field--wide">
            <span className="gate__label">{t('Notes (optional)')}</span>
            <input
              type="text"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder={t('Conditions, caveats, or communication instructions')}
            />
          </label>
          <button
            type="button"
            className="btn btn--gate gate__submit"
            disabled={!canSubmit}
            onClick={() =>
              selectedOptionId &&
              onSubmit({
                optionId: selectedOptionId,
                approver: approver.trim() || DEFAULT_APPROVER,
                notes: notes.trim(),
              })
            }
          >
            {submitting
              ? t('Submitting…')
              : t('Authorise option {id}', { id: selectedOptionId ?? '' }).trim()}
          </button>
        </div>

        {error ? <p className="gate__error">{text(error)}</p> : null}
      </div>
    </section>
  );
}

function optionTitle(options: ScenarioOption[], optionId: unknown): string | null {
  if (typeof optionId !== 'string') return null;
  return options.find((option) => option.optionId === optionId)?.title ?? null;
}

export default ApprovalGate;
