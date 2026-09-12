/**
 * Display preferences that survive a reload.
 *
 * Same contract as the theme preference in `theme.ts`: these are **display**
 * choices (is the sidebar collapsed, has the tour been seen, when were the
 * notifications last read) — never a credential and never session state. The
 * session lives only in memory; see `src/lib/auth/session.ts`.
 *
 * Every accessor tolerates storage being unavailable (private mode, blocked
 * site data): the UI then simply forgets between reloads.
 */

const PREFIX = 'spilltrace:pref:';

export const PREF_SIDEBAR_COLLAPSED = 'sidebar-collapsed';
// Bumped to v2 when the tour was rewritten to explain the product rather than
// the navigation — everyone should see the new first two steps once.
export const PREF_TOUR_DONE = 'tour-done-v2';
export const PREF_NOTIFICATIONS_SEEN = 'notifications-seen-at';

export function readPreference(key: string): string | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage.getItem(PREFIX + key);
  } catch {
    return null;
  }
}

export function writePreference(key: string, value: string): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(PREFIX + key, value);
  } catch {
    // Preference simply does not persist; the UI still works.
  }
}

export function readBooleanPreference(key: string): boolean {
  return readPreference(key) === '1';
}

export function writeBooleanPreference(key: string, value: boolean): void {
  writePreference(key, value ? '1' : '0');
}

/** Custom DOM event that asks the shell to (re)start the onboarding tour. */
export const START_TOUR_EVENT = 'spilltrace:start-tour';

export function requestTour(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(START_TOUR_EVENT));
}

/** Custom DOM event that opens the command palette from anywhere. */
export const OPEN_PALETTE_EVENT = 'spilltrace:open-palette';

export function requestPalette(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(OPEN_PALETTE_EVENT));
}
