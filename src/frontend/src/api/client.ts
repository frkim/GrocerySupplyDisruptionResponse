import type { GovernanceResponse, ScenarioResponse } from '../types';

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, {
    headers: { Accept: 'application/json' },
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) {
    throw new Error(`${url} responded ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export function fetchHealth(signal?: AbortSignal): Promise<{ status?: string }> {
  return getJson<{ status?: string }>('/api/health', signal);
}

export function fetchScenario(signal?: AbortSignal): Promise<ScenarioResponse> {
  return getJson<ScenarioResponse>('/api/scenario', signal);
}

export function fetchGovernance(signal?: AbortSignal): Promise<GovernanceResponse> {
  return getJson<GovernanceResponse>('/api/governance', signal);
}

export interface DecisionPayload {
  optionId: string;
  approver: string;
  notes: string;
}

export async function submitDecision(
  runId: string,
  payload: DecisionPayload,
): Promise<unknown> {
  const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    let detail = '';
    try {
      detail = (await response.text()).slice(0, 240);
    } catch {
      /* ignore */
    }
    throw new Error(
      `Decision rejected: ${response.status} ${response.statusText}${detail ? ` — ${detail}` : ''}`,
    );
  }
  try {
    return await response.json();
  } catch {
    return null;
  }
}
