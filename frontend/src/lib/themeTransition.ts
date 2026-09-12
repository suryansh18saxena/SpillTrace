import { applyTheme, storeTheme, type Theme } from '@/lib/theme';

/** The theme currently stamped on <html>. */
export function currentTheme(): Theme {
  if (typeof document === 'undefined') return 'dark';
  return document.documentElement.dataset['theme'] === 'light' ? 'light' : 'dark';
}

interface ViewTransitionLike {
  ready: Promise<void>;
}

type DocumentWithTransitions = Document & {
  startViewTransition?: (update: () => void) => ViewTransitionLike;
};

/**
 * Switch theme with a circular reveal that grows from `origin` (the toggle).
 *
 * Uses the View Transitions API where it exists; everywhere else, and under
 * reduced motion, the theme simply switches. The preference is stored either
 * way — it is a display preference, not session state.
 */
export function setThemeWithTransition(next: Theme, origin?: { x: number; y: number }): void {
  const doc = document as DocumentWithTransitions;
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? true;

  const commit = () => {
    applyTheme(next);
    storeTheme(next);
  };

  if (!doc.startViewTransition || reduced) {
    commit();
    return;
  }

  const x = origin?.x ?? window.innerWidth - 80;
  const y = origin?.y ?? 32;
  const radius = Math.hypot(
    Math.max(x, window.innerWidth - x),
    Math.max(y, window.innerHeight - y),
  );

  const transition = doc.startViewTransition(commit);
  transition.ready
    .then(() => {
      document.documentElement.animate(
        { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
        {
          duration: 620,
          easing: 'cubic-bezier(0.16, 1, 0.3, 1)',
          pseudoElement: '::view-transition-new(root)',
        },
      );
    })
    .catch(() => {
      // The transition was skipped (e.g. tab hidden); the theme is applied anyway.
    });
}

export function toggleThemeWithTransition(origin?: { x: number; y: number }): Theme {
  const next: Theme = currentTheme() === 'light' ? 'dark' : 'light';
  setThemeWithTransition(next, origin);
  return next;
}
