/**
 * Theme preference.
 *
 * Dark is the default because the product is an operations tool and the map is
 * the hero on every investigation screen; light exists for daylight use and for
 * printing an evidence report.
 *
 * The preference is stored in `window.localStorage`. That is a **display**
 * preference, not a credential and not session state — nothing in
 * `src/lib/auth/session.ts` is ever persisted (see the note there).
 */

export type Theme = 'dark' | 'light';

export const THEME_STORAGE_KEY = 'spilltrace:theme';

export function isTheme(value: unknown): value is Theme {
  return value === 'dark' || value === 'light';
}

export function readStoredTheme(): Theme | null {
  if (typeof window === 'undefined') return null;
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(stored) ? stored : null;
  } catch {
    // Private mode / blocked site data: fall back to the system preference.
    return null;
  }
}

export function systemTheme(): Theme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'dark';
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function applyTheme(theme: Theme): void {
  if (typeof document === 'undefined') return;
  document.documentElement.dataset['theme'] = theme;
}

export function storeTheme(theme: Theme): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Preference simply does not persist; the UI still works.
  }
}

/**
 * Runs synchronously in <head> before first paint so the page never flashes the
 * wrong theme. Kept to one statement and no dependencies for exactly that reason.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem('${THEME_STORAGE_KEY}');if(t!=='light'&&t!=='dark'){t=window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark';}document.documentElement.dataset.theme=t;}catch(e){document.documentElement.dataset.theme='dark';}})();`;
