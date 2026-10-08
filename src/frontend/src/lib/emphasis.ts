/**
 * Splits agent narrative text into plain and emphasised segments so the most decision-critical
 * facts (money, percentages, quantities, options, urgency and decision words) render in bold.
 * Explicit Markdown `**bold**` markers from live model output take precedence over heuristics.
 * Works on already translated text, so patterns cover English, French, German and Spanish.
 */
export type EmphasisSegment = { text: string; strong: boolean };

const NUM = String.raw`\d{1,3}(?:[ \u00a0\u202f,.]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?`;
const NOT_WORD_AFTER = String.raw`(?![\p{L}\p{N}])`;
const NOT_WORD_BEFORE = String.raw`(?<![\p{L}\p{N}])`;

/** Case-insensitive on the first letter only, so the overall pattern can stay case-sensitive. */
const word = (value: string): string =>
  `[${value.charAt(0).toUpperCase()}${value.charAt(0).toLowerCase()}]${value.slice(1)}`;

const UNITS = [
  'cases', 'case', 'caisses', 'caisse', 'cartons', 'carton', 'Kisten', 'Kiste', 'Kartons', 'Karton', 'cajas', 'caja',
  'days', 'day', 'jours', 'jour', 'Tagen', 'Tage', 'Tag', 'días', 'día', 'dias', 'dia',
  'hours', 'hour', 'heures', 'heure', 'Stunden', 'Stunde', 'horas', 'hora',
  'weeks', 'week', 'semaines', 'semaine', 'Wochen', 'Woche', 'semanas', 'semana',
  'points', 'point', 'Punkte', 'puntos', 'punto',
];

const KEYWORDS = [
  // Severity and urgency.
  'critical', 'critique', 'kritisch', 'kritische', 'crítica', 'crítico',
  'urgent', 'urgente', 'dringend',
  'immediately', 'immédiatement', 'sofort', 'inmediatamente',
  'twenty-four hours', 'vingt-quatre heures', 'vierundzwanzig Stunden', 'veinticuatro horas',
  'forty-eight hours', 'quarante-huit heures', 'achtundvierzig Stunden', 'cuarenta y ocho horas',
  // Decisions and blockers.
  'approved', 'approuvée', 'approuvé', 'genehmigt', 'aprobada', 'aprobado',
  'rejected', 'rejetée', 'rejeté', 'abgelehnt', 'rechazada', 'rechazado',
  'blocked', 'bloquée', 'bloqué', 'blockiert', 'bloqueada', 'bloqueado',
  'no single lever', 'aucun levier', 'kein einzelner Hebel', 'ninguna palanca',
];

const byLength = (a: string, b: string): number => b.length - a.length;
const escape = (value: string): string => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const MONEY = String.raw`(?:EUR|€)[ \u00a0\u202f]?(?:${NUM})(?:[ \u00a0\u202f]?(?:millions?|Mio\.?|M|k))?${NOT_WORD_AFTER}`
  + String.raw`|(?:${NUM})[ \u00a0\u202f]?(?:EUR|€)`;
const PERCENT = String.raw`[+\-−]?(?:${NUM})[ \u00a0\u202f]?%`;
const QUANTITY = String.raw`(?:${NUM})[ \u00a0\u202f](?:${[...UNITS].sort(byLength).map(escape).join('|')})${NOT_WORD_AFTER}`;
const OPTION = String.raw`(?:${['options', 'option', 'opciones', 'opción', 'Optionen'].map(word).join('|')})[ \u00a0\u202f][A-H]${NOT_WORD_AFTER}`;
const KEYWORD = String.raw`(?:${[...KEYWORDS].sort(byLength).map((k) => word(escape(k))).join('|')})${NOT_WORD_AFTER}`;

const HEURISTIC = new RegExp(
  `${NOT_WORD_BEFORE}(?:${MONEY}|${PERCENT}|${QUANTITY}|${OPTION}|${KEYWORD})`,
  'gu',
);
const MARKDOWN_BOLD = /\*\*(?=\S)([\s\S]*?\S)\*\*/g;

function push(segments: EmphasisSegment[], text: string, strong: boolean): void {
  if (!text) return;
  const last = segments[segments.length - 1];
  if (last && last.strong === strong) last.text += text;
  else segments.push({ text, strong });
}

function split(source: string, pattern: RegExp, group: number): EmphasisSegment[] {
  const segments: EmphasisSegment[] = [];
  let cursor = 0;
  pattern.lastIndex = 0;
  for (const match of source.matchAll(pattern)) {
    const index = match.index ?? 0;
    push(segments, source.slice(cursor, index), false);
    push(segments, match[group] ?? match[0], true);
    cursor = index + match[0].length;
  }
  push(segments, source.slice(cursor), false);
  return segments;
}

export function emphasize(source: string | null | undefined): EmphasisSegment[] {
  if (!source) return [];
  MARKDOWN_BOLD.lastIndex = 0;
  if (MARKDOWN_BOLD.test(source)) return split(source, MARKDOWN_BOLD, 1);
  return split(source, HEURISTIC, 0);
}
