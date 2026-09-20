import french from '../../../../data/locales/fr.json';
import german from '../../../../data/locales/de.json';
import spanish from '../../../../data/locales/es.json';

export type Language = 'en' | 'fr' | 'de' | 'es';
export type MessageParams = Record<string, string | number>;
export const LOCALES: Record<Language, string> = {
  en: 'en-GB', fr: 'fr-FR', de: 'de-DE', es: 'es-ES',
};

const CATALOGS: Record<Language, Record<string, string>> = {
  en: {}, fr: french, de: german, es: spanish,
};
const MAX_TEXT = 12_000;
const MAX_BATCH = 24;
const MAX_BATCH_CHARS = 40_000;
const CACHE_LIMIT = 2_000;
const MAX_ATTEMPTS = 3;
const MAX_CONSECUTIVE_FAILURES = 3;
const TRANSLATION_ERROR = 'Translation unavailable. Showing original text.';
const APP_TITLE = 'Grocery Supply Disruption Response';
let activeLanguage: Language = 'en';

export function isLanguage(value: unknown): value is Language {
  return value === 'en' || value === 'fr' || value === 'de' || value === 'es';
}

export function readLanguagePreference(): Language {
  if (typeof document === 'undefined') return 'en';
  const value = document.cookie.match(/(?:^|;\s*)gsdr-language=(en|fr|de|es)(?:;|$)/)?.[1];
  return isLanguage(value) ? value : 'en';
}

export function applyLanguage(language: Language): void {
  activeLanguage = language;
  if (typeof document !== 'undefined') {
    document.documentElement.lang = language;
    document.title = catalogText(language, APP_TITLE) ?? APP_TITLE;
  }
}

export function getLocale(): string {
  return LOCALES[activeLanguage];
}

function catalogText(language: Language, source: string): string | undefined {
  const catalog = CATALOGS[language];
  return Object.prototype.hasOwnProperty.call(catalog, source) ? catalog[source] : undefined;
}

function isTechnicalValue(value: string): boolean {
  return !/\p{L}/u.test(value)
    || /^(?:https?:\/\/|\/api\/|[\w.+-]+@)/.test(value)
    || /^\d{4}-\d{2}-\d{2}(?:T|\b)/.test(value)
    || /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value)
    || /^[A-Z\d]+(?:[-_][A-Z\d]+)+$/.test(value)
    || /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(value);
}

function isIdentityField(key: string): boolean {
  return /^(?:id|ids|model|toolName|toolNames|partitionKey|approver)$/i.test(key)
    || /(?:Id|Ids|_id|_ids|Url|Urls|Uri|Sku|Skus)$/.test(key);
}

function fieldLabel(key: string): string {
  return key.replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .split(/[_\-\s]+/).filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}

export type TranslationResult = { translations: string[]; untranslated?: number[] };

export type TranslationTransport = (
  language: Language, texts: string[], signal: AbortSignal,
) => Promise<string[] | TranslationResult>;

async function translateBatch(
  language: Language, texts: string[], signal: AbortSignal,
): Promise<TranslationResult> {
  const response = await fetch('/api/translate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ language, texts }),
    signal,
  });
  if (!response.ok) throw new Error(`Translation request failed (HTTP ${response.status}).`);
  const body: unknown = await response.json();
  if (!body || typeof body !== 'object' || !('translations' in body)
    || !Array.isArray(body.translations)
    || body.translations.length !== texts.length
    || !body.translations.every((value): value is string =>
      typeof value === 'string' && value.trim().length > 0 && value.length <= MAX_TEXT * 4)) {
    throw new Error('Translation response has an invalid shape.');
  }
  const reported: unknown = 'untranslated' in body ? body.untranslated : undefined;
  const untranslated = Array.isArray(reported)
    ? reported.filter((index): index is number =>
      Number.isInteger(index) && index >= 0 && index < texts.length)
    : [];
  return { translations: body.translations, untranslated };
}

/** Keeps canonical run data untouched; only the rendered presentation is translated. */
export class TranslationStore {
  language: Language;
  error: string | null = null;
  private revision = 0;
  private listeners = new Set<() => void>();
  private cache = new Map<string, string>();
  private queue = new Set<string>();
  private failed = new Set<string>();
  private inFlight = new Set<string>();
  private attempts = new Map<string, number>();
  private consecutiveFailures = 0;
  private halted = false;
  private controller: AbortController | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private active = true;

  constructor(language: Language = 'en', private transport: TranslationTransport = translateBatch) {
    this.language = language;
    applyLanguage(language);
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = (): number => this.revision;

  get pending(): boolean {
    return this.queue.size > 0 || this.inFlight.size > 0;
  }

  private notify(): void {
    this.revision += 1;
    this.listeners.forEach((listener) => listener());
  }

  setLanguage = (language: Language): void => {
    if (language === this.language) return;
    this.pause();
    this.queue.clear();
    this.failed.clear();
    this.attempts.clear();
    this.consecutiveFailures = 0;
    this.halted = false;
    this.error = null;
    this.language = language;
    applyLanguage(language);
    if (typeof document !== 'undefined') {
      document.cookie = `gsdr-language=${language}; path=/; max-age=31536000; samesite=lax`;
    }
    this.resume();
    this.notify();
  };

  text = (source: string): string => {
    if (this.language === 'en' || !source.trim()) return source;
    const value = source.trim();
    const prefix = source.slice(0, source.indexOf(value));
    const suffix = source.slice(source.indexOf(value) + value.length);
    const known = catalogText(this.language, value);
    if (known !== undefined) return prefix + known + suffix;
    if (isTechnicalValue(value)) return source;
    if (value.length > MAX_TEXT) {
      const boundary = value.lastIndexOf(' ', MAX_TEXT);
      const split = boundary > 0 ? boundary : MAX_TEXT;
      return prefix + this.text(value.slice(0, split)) + this.text(value.slice(split)) + suffix;
    }
    const cacheKey = `${this.language}:${value}`;
    const cached = this.cache.get(cacheKey);
    if (cached !== undefined) {
      this.cache.delete(cacheKey);
      this.cache.set(cacheKey, cached);
      return prefix + cached + suffix;
    }
    if (this.halted) {
      // A confirmed outage stops automatic requests until the reader retries.
      this.failed.add(value);
      return source;
    }
    if (!this.failed.has(value) && !this.inFlight.has(value)) {
      this.queue.add(value);
      this.schedule();
    }
    return source;
  };

  t = (source: string, params?: MessageParams): string => {
    const translated = this.text(source);
    if (!params) return translated;
    return translated.replace(/\{(\w+)\}/g, (placeholder: string, key: string) => {
      const value = params[key];
      if (value === undefined) return placeholder;
      if (typeof value === 'number') return new Intl.NumberFormat(getLocale()).format(value);
      return catalogText(this.language, value) ?? value;
    });
  };

  json = (value: unknown): string => {
    let parsed = value;
    if (typeof value === 'string') {
      try {
        parsed = JSON.parse(value);
      } catch {
        return this.text(value);
      }
    }
    const localize = (item: unknown, key = ''): unknown => {
      if (isIdentityField(key)) return item;
      if (typeof item === 'string') return this.text(item);
      if (Array.isArray(item)) return item.map((child) => localize(child, key));
      if (item && typeof item === 'object') {
        const translated: Record<string, unknown> = Object.create(null);
        for (const [name, child] of Object.entries(item)) {
          let label = this.text(fieldLabel(name));
          if (Object.prototype.hasOwnProperty.call(translated, label)) label += ` (${name})`;
          translated[label] = localize(child, name);
        }
        return translated;
      }
      return item;
    };
    return JSON.stringify(this.language === 'en' ? parsed : localize(parsed), null, 2) ?? '';
  };

  retry = (): void => {
    for (const source of this.failed) {
      this.attempts.delete(source);
      this.queue.add(source);
    }
    this.failed.clear();
    this.consecutiveFailures = 0;
    this.halted = false;
    this.error = null;
    this.notify();
    this.schedule();
  };

  pause = (): void => {
    this.active = false;
    clearTimeout(this.timer);
    this.timer = undefined;
    this.controller?.abort();
    this.controller = null;
    for (const source of this.inFlight) this.queue.add(source);
    this.inFlight.clear();
  };

  resume = (): void => {
    this.active = true;
    this.schedule();
  };

  private schedule(): void {
    if (!this.active || this.timer !== undefined || this.controller || !this.queue.size) return;
    // Scheduling avoids updating React subscribers during a component's render.
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.flush();
    }, 30);
  }

  /** Retries a text in progressively smaller batches so one bad item cannot strand the rest. */
  private deferFailure(source: string): void {
    const attempts = (this.attempts.get(source) ?? 0) + 1;
    this.attempts.set(source, attempts);
    if (attempts >= MAX_ATTEMPTS) {
      this.failed.add(source);
      this.error = TRANSLATION_ERROR;
      return;
    }
    this.queue.add(source);
  }

  private async flush(): Promise<void> {
    if (!this.active || this.controller || !this.queue.size) return;
    const language = this.language;
    const first: string | undefined = this.queue.values().next().value;
    if (first === undefined) return;
    // A text that already failed is retried alone, isolating the item the provider rejects.
    const limit = (this.attempts.get(first) ?? 0) > 0 ? 1 : MAX_BATCH;
    const batch: string[] = [];
    let size = 0;
    for (const source of this.queue) {
      if (batch.length >= limit || size + source.length > MAX_BATCH_CHARS) break;
      batch.push(source);
      size += source.length;
    }
    batch.forEach((source) => {
      this.queue.delete(source);
      this.inFlight.add(source);
    });
    const controller = new AbortController();
    this.controller = controller;
    const timeout = setTimeout(() => controller.abort(), 65_000);
    this.notify();
    try {
      const result = await this.transport(language, batch, controller.signal);
      if (this.controller !== controller || this.language !== language) return;
      if (controller.signal.aborted) throw new Error('Translation request timed out.');
      const translations = Array.isArray(result) ? result : result.translations;
      const degraded = new Set(
        (Array.isArray(result) ? [] : result.untranslated ?? [])
          .map((index) => batch[index]).filter((source): source is string => source !== undefined),
      );
      if (translations.length !== batch.length || translations.some((text) => !text.trim())) {
        throw new Error('Translation response has an invalid shape.');
      }
      this.consecutiveFailures = 0;
      batch.forEach((source, index) => {
        const translation = translations[index];
        if (translation === undefined) return;
        if (degraded.has(source)) {
          // The provider could not translate this text; keep it retryable instead of caching English.
          this.deferFailure(source);
          return;
        }
        this.attempts.delete(source);
        this.cache.set(`${language}:${source}`, translation);
      });
      while (this.cache.size > CACHE_LIMIT) {
        const oldest = this.cache.keys().next().value;
        if (oldest !== undefined) this.cache.delete(oldest);
      }
    } catch (error) {
      if (this.controller !== controller || this.language !== language) return;
      this.consecutiveFailures += 1;
      batch.forEach((source) => this.deferFailure(source));
      if (this.consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
        // Sustained failures mean the service is down, so stop retrying until the reader asks.
        this.halted = true;
        this.queue.forEach((source) => this.failed.add(source));
        this.queue.clear();
        this.error = TRANSLATION_ERROR;
      }
      console.warn(error instanceof Error ? error.message : 'Translation request failed.');
    } finally {
      clearTimeout(timeout);
      if (this.controller === controller) {
        this.controller = null;
        this.inFlight.clear();
        this.notify();
        this.schedule();
      }
    }
  }
}
