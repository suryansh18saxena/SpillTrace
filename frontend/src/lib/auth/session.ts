/**
 * Client-side session handling (UI-001, NFR-007, decision A-05).
 *
 * ## Storage model — read this before changing anything here
 *
 * - The **access token lives in a module-scoped variable only**. It is never
 *   written to `localStorage`, `sessionStorage`, a cookie readable by script, or
 *   the URL. A token in `localStorage` is readable by any successful XSS and
 *   survives the tab; a token in a closure dies with the page.
 * - The **refresh token is never seen by JavaScript at all**. The server sets it
 *   as an httpOnly, SameSite cookie on `POST /auth/login`; the browser replays it
 *   automatically on `POST /auth/refresh` because we send `credentials:
 *   'include'`. That is why a page reload can recover a session without us ever
 *   persisting anything ourselves.
 * - Consequently a hard reload starts with no access token and MUST call
 *   `bootstrapSession()`, which performs exactly one silent refresh.
 *
 * `eslint.config.mjs` forbids `localStorage`/`sessionStorage` globals in
 * application code so this cannot be quietly undone.
 */

import { API_BASE_URL, API_PREFIX } from '@/lib/config';
import type { LoginResponse, User } from '@/lib/api/types';

export interface SessionState {
  status: 'unknown' | 'authenticated' | 'anonymous';
  user: User | null;
}

type Listener = (state: SessionState) => void;

let accessToken: string | null = null;
/** Epoch milliseconds at which the current access token expires. */
let accessTokenExpiresAt: number | null = null;
let currentUser: User | null = null;
let status: SessionState['status'] = 'unknown';

const listeners = new Set<Listener>();

/** Refresh is single-flight: N concurrent 401s must produce exactly one refresh. */
let inFlightRefresh: Promise<boolean> | null = null;

function snapshot(): SessionState {
  return { status, user: currentUser };
}

let cachedSnapshot: SessionState = snapshot();

function emit(): void {
  cachedSnapshot = snapshot();
  for (const listener of listeners) listener(cachedSnapshot);
}

/** Subscribe to session changes. Returns an unsubscribe function. */
export function subscribeToSession(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * Stable snapshot for `useSyncExternalStore` — it must return an identical
 * reference until something actually changes, or React will loop forever.
 */
export function getSessionSnapshot(): SessionState {
  return cachedSnapshot;
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function getCurrentUser(): User | null {
  return currentUser;
}

/** True when the token exists and has more than `skewMs` of life left. */
export function hasFreshAccessToken(skewMs = 5_000): boolean {
  if (!accessToken) return false;
  if (accessTokenExpiresAt === null) return true;
  return accessTokenExpiresAt - skewMs > Date.now();
}

export function setSession(payload: LoginResponse): void {
  accessToken = payload.access_token;
  accessTokenExpiresAt =
    typeof payload.expires_in === 'number' && Number.isFinite(payload.expires_in)
      ? Date.now() + payload.expires_in * 1000
      : null;
  currentUser = payload.user ?? null;
  status = 'authenticated';
  emit();
}

export function setCurrentUser(user: User | null): void {
  currentUser = user;
  if (user && accessToken) status = 'authenticated';
  emit();
}

export function clearSession(): void {
  accessToken = null;
  accessTokenExpiresAt = null;
  currentUser = null;
  status = 'anonymous';
  emit();
}

/** Reset to the pre-bootstrap state. Test helper; not used by the application. */
export function resetSessionForTests(): void {
  accessToken = null;
  accessTokenExpiresAt = null;
  currentUser = null;
  status = 'unknown';
  inFlightRefresh = null;
  emit();
}

async function performRefresh(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}${API_PREFIX}/auth/refresh`, {
      method: 'POST',
      // Sends the httpOnly refresh cookie. This is the only reason the refresh
      // token never has to be handled by JavaScript.
      credentials: 'include',
      headers: { Accept: 'application/json' },
    });

    if (!response.ok) {
      clearSession();
      return false;
    }

    const payload = (await response.json()) as Partial<LoginResponse>;
    if (!payload || typeof payload.access_token !== 'string') {
      clearSession();
      return false;
    }

    accessToken = payload.access_token;
    accessTokenExpiresAt =
      typeof payload.expires_in === 'number' && Number.isFinite(payload.expires_in)
        ? Date.now() + payload.expires_in * 1000
        : null;
    if (payload.user) currentUser = payload.user;
    status = 'authenticated';
    emit();
    return true;
  } catch {
    // Network failure: do not destroy a session we cannot prove is invalid, but
    // report failure so the caller surfaces a real error instead of a redirect.
    return false;
  }
}

/**
 * Refresh the access token. Concurrent callers share one network request.
 * Resolves `true` when a usable access token is now available.
 */
export function refreshSession(): Promise<boolean> {
  if (inFlightRefresh) return inFlightRefresh;
  inFlightRefresh = performRefresh().finally(() => {
    inFlightRefresh = null;
  });
  return inFlightRefresh;
}

/**
 * Called once when the authenticated shell mounts. Attempts a silent refresh so
 * that a page reload does not log the analyst out; marks the session anonymous
 * when there is no valid refresh cookie.
 */
export async function bootstrapSession(): Promise<SessionState> {
  if (status !== 'unknown') return snapshot();
  const ok = await refreshSession();
  if (!ok && status === 'unknown') {
    status = 'anonymous';
    emit();
  }
  return snapshot();
}
