/**
 * Browser-visible configuration.
 *
 * Everything in here is inlined into the client bundle at build time, so it must
 * never contain a credential (CON-004). The browser calls our own API and the
 * public, unauthenticated basemap tile services listed in `lib/map/basemaps.ts`;
 * every third-party provider key stays server-side (AD-5, amended 2026-09-12).
 */

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '');
}

/**
 * Resolve the API origin from the build-time setting.
 *
 * - Unset: local development, where the API runs on its own port.
 * - An origin (`https://api.example.org`): the API lives on another host.
 * - Empty string: **same origin**. A reverse proxy serves `/api/*` beside the app,
 *   so the bundle is not tied to any host name. The production image is built this
 *   way, which is what lets one image move between an IP, a domain and HTTPS without
 *   a rebuild. In the browser that resolves to the page's own origin; during the
 *   server render there is no page, so API URLs stay path-relative there.
 */
export function resolveApiBaseUrl(
  configured: string | undefined,
  pageOrigin: string | undefined,
): string {
  if (configured === undefined) return 'http://localhost:8000';
  const trimmed = trimTrailingSlash(configured.trim());
  if (trimmed) return trimmed;
  return pageOrigin ? trimTrailingSlash(pageOrigin) : '';
}

/** Origin of the SPILLTRACE API — our own FastAPI service, never a third party. */
export const API_BASE_URL = resolveApiBaseUrl(
  process.env.NEXT_PUBLIC_API_BASE_URL,
  typeof window !== 'undefined' ? window.location.origin : undefined,
);

/** API.md §1 — every versioned endpoint lives under this prefix. */
export const API_PREFIX = '/api/v1';

export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME ?? 'SPILLTRACE';

export const APP_TAGLINE = 'Maritime oil-spill investigative attribution';

/**
 * The self-hosted offline basemap (graticule only, see public/map-style.json).
 * `lib/map/basemaps.ts` composes the public imagery basemaps on top of it at
 * runtime; choosing "Offline" in the map restores zero-external-request mode.
 */
export const MAP_STYLE_URL = '/map-style.json';

/** Default map view: the Arabian Sea / Gulf of Kutch area used by the demo scenario. */
export const MAP_DEFAULT_CENTER: [number, number] = [69.6, 22.6];
export const MAP_DEFAULT_ZOOM = 6;

export const DEFAULT_PAGE_SIZE = 25;
export const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

/** Mirrors the server-side `SPILLTRACE_MAX_AOI_KM2` default (API.md §4). */
export const MAX_AOI_KM2 = 250_000;

/** API.md §4 — the case time window may not exceed 30 days. */
export const MAX_WINDOW_DAYS = 30;

/** Default per-request timeout for the API client, in milliseconds. */
export const REQUEST_TIMEOUT_MS = 30_000;

/**
 * Uploading a scene is not a form submission: the server decodes, reprojects and
 * stores tens of megabytes of raster before it answers, so the ordinary request
 * timeout would abort a request that is working perfectly well.
 */
export const SCENE_UPLOAD_TIMEOUT_MS = 300_000;

/**
 * The standing product-level disclaimer (CON-001, CON-003, CON-008, MVP-11).
 *
 * Attribution responses carry their own `disclaimer` from the server and that one
 * always wins; this constant is the floor, shown wherever scores or candidate
 * vessels are surfaced before a server-provided disclaimer is available.
 */
export const INVESTIGATIVE_DISCLAIMER =
  'Investigative/probabilistic evidence — not automatic legal proof. Scores rank candidate ' +
  'vessels for further investigation and never establish responsibility.';
