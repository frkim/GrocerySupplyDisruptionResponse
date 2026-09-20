import type { HostingMode, NodeState } from '../types';
import { getLocale } from './localization';

/** Read the first present key from an object, tolerating camelCase/snake_case drift. */
export function pick(source: unknown, keys: string[]): unknown {
  if (!source || typeof source !== 'object') return undefined;
  const record = source as Record<string, unknown>;
  for (const key of keys) {
    const value = record[key];
    if (value !== undefined && value !== null && value !== '') return value;
  }
  return undefined;
}

export function pickNumber(source: unknown, keys: string[]): number | undefined {
  const value = pick(source, keys);
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value.replace(/[^0-9.\-]/g, ''));
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
}

export function pickString(source: unknown, keys: string[]): string | undefined {
  const value = pick(source, keys);
  if (typeof value === 'string') return value;
  if (typeof value === 'number') return String(value);
  return undefined;
}

export function pickArray(source: unknown, keys: string[]): unknown[] | undefined {
  const value = pick(source, keys);
  return Array.isArray(value) ? value : undefined;
}

export const DASH = '—';

export function formatCurrencyEur(value: number | undefined): string {
  if (value === undefined) return DASH;
  return new Intl.NumberFormat(getLocale(), {
    style: 'currency',
    currency: 'EUR',
    notation: Math.abs(value) >= 1000 ? 'compact' : 'standard',
    maximumFractionDigits: Math.abs(value) >= 1_000_000 ? 2 : 0,
  }).format(value);
}

export function formatNumber(value: number | undefined): string {
  if (value === undefined) return DASH;
  return new Intl.NumberFormat(getLocale()).format(Math.round(value));
}

export function formatTokens(value: number | undefined): string {
  if (value === undefined) return DASH;
  return new Intl.NumberFormat(getLocale(), {
    notation: value >= 1000 ? 'compact' : 'standard', maximumFractionDigits: 1,
  }).format(value);
}

export function formatDurationMs(value: number | undefined): string {
  if (value === undefined) return DASH;
  if (value < 1000) return `${formatNumber(value)} ms`;
  return `${new Intl.NumberFormat(getLocale(), {
    minimumFractionDigits: 1, maximumFractionDigits: 1,
  }).format(value / 1000)} s`;
}

export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

export function formatClock(at: number): string {
  const date = new Date(at);
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((part) => String(part).padStart(2, '0'))
    .join(':');
}

/** GPT-4o pricing used purely for the governance estimate, per 1M tokens. */
export const PROMPT_USD_PER_MILLION = 0.75;
export const CACHED_PROMPT_USD_PER_MILLION = 0.08;
export const COMPLETION_USD_PER_MILLION = 4.5;

export function estimateCostUsd(promptTokens = 0, completionTokens = 0): number {
  return (
    (promptTokens / 1_000_000) * PROMPT_USD_PER_MILLION +
    (completionTokens / 1_000_000) * COMPLETION_USD_PER_MILLION
  );
}

export function formatUsd(value: number): string {
  const digits = value >= 1 ? 2 : value >= 0.01 ? 3 : 4;
  return new Intl.NumberFormat(getLocale(), {
    style: 'currency', currency: 'USD',
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  }).format(value);
}

export const HOSTING_LABEL: Record<HostingMode, string> = {
  foundry: 'Foundry',
  local: 'Local',
  a2a: 'A2A',
  system: 'System',
};

export const STATE_LABEL: Record<NodeState, string> = {
  pending: 'Pending',
  running: 'Running',
  completed: 'Completed',
  failed: 'Failed',
  skipped: 'Skipped',
  awaiting: 'Awaiting decision',
};

export function humanise(id: string): string {
  return id
    .split(/[_\-\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** Compact a possibly-large JSON string for single-line display. */
export function truncate(value: string, max = 320): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max)}…`;
}
