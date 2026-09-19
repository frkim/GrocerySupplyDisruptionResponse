export type Theme = 'light' | 'dark';

const COOKIE_NAME = 'sdr-theme';
const ONE_YEAR_SECONDS = 60 * 60 * 24 * 365;

export function readThemeCookie(): Theme | null {
  const match = document.cookie.match(/(?:^|;\s*)sdr-theme=(light|dark)\b/);
  return match ? (match[1] as Theme) : null;
}

export function writeThemeCookie(theme: Theme): void {
  document.cookie = `${COOKIE_NAME}=${theme}; path=/; max-age=${ONE_YEAR_SECONDS}; samesite=lax`;
}

export function resolveInitialTheme(): Theme {
  const stored = readThemeCookie();
  if (stored) return stored;
  const prefersLight =
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: light)').matches;
  return prefersLight ? 'light' : 'dark';
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme;
}
