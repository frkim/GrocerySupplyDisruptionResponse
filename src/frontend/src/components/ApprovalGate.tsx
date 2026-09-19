import { useEffect, useMemo, useState } from 'react';
import type { GateRecommendation, RunDecision, ScenarioOption } from '../types';
import { DASH, formatCurrencyEur } from '../lib/format';
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
          <h2 className="card__title">Executive decision</h2>
          <span className="gate__badge gate__badge--approved">Approved</span>
        </div>
        <div className="card__body gate__body">
          <div className="gate__resolved">
            <div>
              <span className="gate__label">Selected option</span>
              <strong className="gate__resolved-option">
                {decision.optionId ?? DASH}
                {optionTitle(options, decision.optionId) ? (
                  <span className="gate__resolved-title">
                    {optionTitle(options, decision.optionId)}
                  </span>
                ) : null}
              </strong>
            </div>
            <div>
              <span className="gate__label">Approver</span>
              <span className="gate__resolved-value">{decision.approver ?? DASH}</span>
            </div>
            {decision.notes ? (
              <div className="gate__resolved-notes">
                <span className="gate__label">Notes</span>
                <p>{String(decision.notes)}</p>
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
        <h2 className="card__title">Executive approval gate</h2>
        <span className="gate__badge gate__badge--awaiting">
          <span className="gate__badge-dot" aria-hidden="true" />
          Run paused — decision required
        </span>
      </div>

      <div className="card__body gate__body">
        <div className="gate__recommendation">
          <span className="gate__label">Agent recommendation</span>
          <div className="gate__rec-head">
            <span className="gate__rec-id">{recommendation?.optionId ?? DASH}</span>
            <strong className="gate__rec-title">
              {recommendedOption?.title ?? 'No recommendation supplied'}
            </strong>
            {recommendedOption?.costEur !== undefined ? (
              <span className="gate__rec-cost mono">
                {formatCurrencyEur(recommendedOption.costEur)}
              </span>
            ) : null}
          </div>
          <p className="gate__rationale">
            {recommendation?.rationale ?? 'The deliberation agent returned no rationale.'}
          </p>
        </div>

        <div className="gate__choices">
          <span className="gate__label">Select the option to authorise</span>
          <div className="gate__choice-row">
            {options.length === 0 ? (
              <span className="muted">No options available.</span>
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
                      {option.title ?? `Option ${option.optionId}`}
                    </span>
                    <span className="gate__choice-meta mono">
                      {formatCurrencyEur(option.costEur)}
                      {option.timeToImplementDays !== undefined
                        ? ` · ${option.timeToImplementDays} d`
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
            <span className="gate__label">Approver</span>
            <input
              type="text"
              value={approver}
              onChange={(event) => setApprover(event.target.value)}
              placeholder={DEFAULT_APPROVER}
            />
          </label>
          <label className="gate__field gate__field--wide">
            <span className="gate__label">Notes (optional)</span>
            <input
              type="text"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Conditions, caveats, or communication instructions"
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
              ? 'Submitting…'
              : `Authorise option ${selectedOptionId ?? ''}`.trim()}
          </button>
        </div>

        {error ? <p className="gate__error">{error}</p> : null}
      </div>
    </section>
  );
}

function optionTitle(options: ScenarioOption[], optionId: unknown): string | null {
  if (typeof optionId !== 'string') return null;
  return options.find((option) => option.optionId === optionId)?.title ?? null;
}

export default ApprovalGate;
