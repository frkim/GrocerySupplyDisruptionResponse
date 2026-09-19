import { useEffect, useState } from 'react';
import { applyTheme, resolveInitialTheme, writeThemeCookie, type Theme } from '../lib/theme';
import './ThemeToggle.css';

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(resolveInitialTheme);

  useEffect(() => {
    applyTheme(theme);
    writeThemeCookie(theme);
  }, [theme]);

  const next: Theme = theme === 'dark' ? 'light' : 'dark';
  const label = `Switch to ${next} theme`;

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => setTheme(next)}
      title={label}
      aria-label={label}
    >
      {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="12" cy="12" r="4.2" />
      <path
        strokeLinecap="round"
        d="M12 2.6v2.1M12 19.3v2.1M2.6 12h2.1M19.3 12h2.1M5.4 5.4l1.5 1.5M17.1 17.1l1.5 1.5M18.6 5.4l-1.5 1.5M6.9 17.1l-1.5 1.5"
      />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M20.4 14.2A8.4 8.4 0 1 1 9.8 3.6a6.6 6.6 0 0 0 10.6 10.6Z"
      />
    </svg>
  );
}

export default ThemeToggle;
