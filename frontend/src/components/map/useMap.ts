'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { Map as MapLibreMap, StyleSpecification } from 'maplibre-gl';
import { API_BASE_URL, MAP_DEFAULT_CENTER, MAP_DEFAULT_ZOOM, MAP_STYLE_URL } from '@/lib/config';
import { getAccessToken } from '@/lib/auth/session';
import {
  applyBasemap,
  buildCompositeStyle,
  DEFAULT_BASEMAP,
  EXTERNAL_SOURCE_IDS,
  isBasemapId,
  referenceBasemapFor,
  type BasemapId,
} from '@/lib/map/basemaps';
import { readPreference, writePreference } from '@/lib/preferences';

export const PREF_BASEMAP = 'basemap';
export const PREF_BASEMAP_LABELS = 'basemap-labels';

export interface UseMapOptions {
  center?: [number, number];
  zoom?: number;
  /** Enable pan/zoom. Disabled maps are still keyboard-focusable for reading. */
  interactive?: boolean;
  /** Accessible name applied to the canvas container. */
  label?: string;
  /** Initial basemap; defaults to the analyst's saved preference, then Satellite. */
  basemap?: BasemapId;
  /** Start in globe projection (situational overview, landing hero). */
  globe?: boolean;
  /** Slowly rotate the globe until the user interacts. Off under reduced motion. */
  autoRotate?: boolean;
  /** Skip the persisted preference (e.g. the public landing globe). */
  persist?: boolean;
}

export interface UseMapResult {
  containerRef: (node: HTMLDivElement | null) => void;
  map: MapLibreMap | null;
  status: 'idle' | 'loading' | 'ready' | 'error';
  error: Error | null;
  /** Increments whenever the document theme changes, so paint can be re-derived. */
  themeVersion: number;
  theme: 'dark' | 'light';
  retry: () => void;
  basemap: BasemapId;
  setBasemap: (id: BasemapId) => void;
  labels: boolean;
  setLabels: (labels: boolean) => void;
  globe: boolean;
  setGlobe: (globe: boolean) => void;
  /** Non-null after imagery failed to load and the map fell back to Offline. */
  fallbackNotice: string | null;
}

/**
 * Reads a CSS design token so map paint follows the application theme.
 * `getComputedStyle` is the only way to get at a custom property from JS, and it
 * keeps the palette defined in exactly one place (`src/styles/tokens.css`).
 */
export function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined' || typeof document === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function currentTheme(): 'dark' | 'light' {
  if (typeof document === 'undefined') return 'dark';
  return document.documentElement.dataset['theme'] === 'light' ? 'light' : 'dark';
}

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function readBasemapPreference(): BasemapId | null {
  const stored = readPreference(PREF_BASEMAP);
  return isBasemapId(stored) ? stored : null;
}

const FALLBACK_NOTICE =
  'Imagery tiles could not be reached, so the map is showing the offline graticule. ' +
  'Evidence layers are unaffected.';

/**
 * Creates and owns a MapLibre GL map.
 *
 * MapLibre is imported dynamically: the module touches `window` at import time,
 * and every page in this app is server-rendered first. The style is composed at
 * runtime from our self-hosted `/map-style.json` (the offline graticule) plus
 * the public imagery basemaps in `lib/map/basemaps.ts`. The only request that
 * ever carries a credential is one aimed at our own API (probability tiles).
 */
export function useMap(options: UseMapOptions = {}): UseMapResult {
  const {
    center = MAP_DEFAULT_CENTER,
    zoom = MAP_DEFAULT_ZOOM,
    interactive = true,
    label,
    basemap: initialBasemap,
    globe: initialGlobe = false,
    autoRotate = false,
    persist = true,
  } = options;

  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [status, setStatus] = useState<UseMapResult['status']>('idle');
  const [error, setError] = useState<Error | null>(null);
  const [themeVersion, setThemeVersion] = useState(0);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [attempt, setAttempt] = useState(0);
  const [basemap, setBasemapState] = useState<BasemapId>(initialBasemap ?? DEFAULT_BASEMAP);
  const [labels, setLabelsState] = useState(true);
  const [globe, setGlobeState] = useState(initialGlobe);
  const [fallbackNotice, setFallbackNotice] = useState<string | null>(null);

  // Keep the initial view in a ref: changing the camera prop must not tear down
  // and rebuild the map, which would lose every layer and the analyst's pan.
  const initialView = useRef({ center, zoom });
  const userSetBasemap = useRef(Boolean(initialBasemap));

  // Preferences are read after mount so the server render never disagrees with
  // the first client render.
  useEffect(() => {
    setTheme(currentTheme());
    if (!persist || initialBasemap) return;
    const stored = readBasemapPreference();
    if (stored) {
      setBasemapState(stored);
      userSetBasemap.current = true;
    }
    const storedLabels = readPreference(PREF_BASEMAP_LABELS);
    if (storedLabels !== null) setLabelsState(storedLabels !== '0');
  }, [persist, initialBasemap]);

  const containerRef = useCallback((node: HTMLDivElement | null) => {
    setContainer(node);
  }, []);

  const retry = useCallback(() => {
    setError(null);
    setStatus('idle');
    setFallbackNotice(null);
    setAttempt((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!container) return;

    let cancelled = false;
    let instance: MapLibreMap | null = null;
    setStatus('loading');

    (async () => {
      try {
        const maplibre = await import('maplibre-gl');
        const response = await fetch(MAP_STYLE_URL);
        if (!response.ok) throw new Error(`The basemap style could not be loaded (${response.status}).`);
        const offline = (await response.json()) as StyleSpecification;
        if (cancelled) return;

        instance = new maplibre.Map({
          container,
          style: buildCompositeStyle(offline),
          center: initialView.current.center,
          zoom: initialView.current.zoom,
          interactive,
          attributionControl: false,
          fadeDuration: 160,
          maxPitch: 70,
          /**
           * Only our own API ever receives a credential: probability-raster
           * tiles (API.md §7) are authenticated, and MapLibre cannot otherwise
           * attach a bearer token. Every other URL — the public imagery tile
           * services declared in `lib/map/basemaps.ts` — passes through untouched
           * with no headers, and the CSP `connect-src` restricts which hosts
           * those can be.
           */
          transformRequest: (url: string) => {
            if (!url.startsWith(API_BASE_URL)) return { url };
            const token = getAccessToken();
            return {
              url,
              credentials: 'include' as const,
              ...(token ? { headers: { Authorization: `Bearer ${token}` } } : {}),
            };
          },
        });

        if (interactive) {
          instance.addControl(
            new maplibre.NavigationControl({ visualizePitch: true, showCompass: true }),
            'top-right',
          );
          instance.addControl(
            new maplibre.ScaleControl({ maxWidth: 120, unit: 'metric' }),
            'bottom-right',
          );
        }
        instance.addControl(
          new maplibre.AttributionControl({
            compact: true,
            customAttribution: 'Evidence layers · SPILLTRACE API',
          }),
          'bottom-right',
        );

        if (label) instance.getCanvas().setAttribute('aria-label', label);
        // The canvas is focusable so the map can be panned/zoomed from the
        // keyboard (MapLibre binds arrow keys and +/- once it has focus).
        instance.getCanvas().setAttribute('tabindex', '0');

        // Imagery reachability: a burst of tile errors with no successful tile
        // means the network (or an air-gapped demo room) cannot reach the
        // provider. Fall back to the offline graticule and say so.
        let tileErrors = 0;
        let tileSuccesses = 0;
        instance.on('error', (event: { error?: Error; sourceId?: string }) => {
          const sourceId = event?.sourceId;
          if (sourceId && EXTERNAL_SOURCE_IDS.includes(sourceId)) {
            tileErrors += 1;
            if (tileErrors >= 4 && tileSuccesses === 0 && !cancelled) {
              setFallbackNotice(FALLBACK_NOTICE);
              setBasemapState('offline');
            }
            return;
          }
          if (sourceId && sourceId.startsWith('st-src-')) {
            // Data-layer tiles (probability raster) may legitimately 404 before a
            // stage has produced them; one warning is enough.
            if (tileErrors === 0) console.warn('[map] data tile unavailable', event.error?.message);
            return;
          }
          // Style/source errors are reported but must not blank the map.
          if (event?.error) console.warn('[map]', event.error.message);
        });
        instance.on('data', (event: { sourceId?: string; tile?: unknown }) => {
          if (event.tile && event.sourceId && EXTERNAL_SOURCE_IDS.includes(event.sourceId)) {
            tileSuccesses += 1;
          }
        });

        instance.on('load', () => {
          if (!cancelled) setStatus('ready');
        });

        if (!cancelled) setMap(instance);
      } catch (cause) {
        if (cancelled) return;
        setStatus('error');
        setError(
          cause instanceof Error
            ? cause
            : new Error('The map could not be initialised in this browser.'),
        );
      }
    })();

    return () => {
      cancelled = true;
      instance?.remove();
      setMap(null);
      setStatus('idle');
    };
  }, [container, interactive, label, attempt]);

  // Keep the canvas sized to its container: the investigation layout resizes
  // when the side panel opens, and MapLibre does not observe that itself.
  useEffect(() => {
    if (!map || !container || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(container);
    return () => observer.disconnect();
  }, [map, container]);

  // Re-derive paint colours when the theme changes.
  useEffect(() => {
    if (typeof MutationObserver === 'undefined' || typeof document === 'undefined') return;
    const observer = new MutationObserver(() => {
      setTheme(currentTheme());
      setThemeVersion((value) => value + 1);
    });
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!map || status !== 'ready') return;
    const ocean = cssVar('--map-ocean', '#0a1622');
    const graticule = cssVar('--map-graticule', '#1b2c3d');
    try {
      if (map.getLayer('ocean')) map.setPaintProperty('ocean', 'background-color', ocean);
      if (map.getLayer('graticule-minor')) {
        map.setPaintProperty('graticule-minor', 'line-color', graticule);
      }
      if (map.getLayer('graticule-major')) {
        map.setPaintProperty('graticule-major', 'line-color', graticule);
      }
    } catch {
      // The style may not have finished swapping; the next theme change retries.
    }
  }, [map, status, themeVersion]);

  // A reference basemap made for the other theme swaps to its counterpart when
  // the theme flips; imagery and offline are theme-agnostic.
  useEffect(() => {
    if (basemap === 'dark' || basemap === 'light') {
      const suited = referenceBasemapFor(theme);
      if (suited !== basemap) setBasemapState(suited);
    }
  }, [theme, basemap]);

  useEffect(() => {
    if (!map || status !== 'ready') return;
    try {
      applyBasemap(map, { basemap, labels });
    } catch (cause) {
      console.warn('[map] could not switch basemap', cause);
    }
  }, [map, status, basemap, labels]);

  // Globe projection + atmosphere. Guarded: older MapLibre builds lack setProjection.
  useEffect(() => {
    if (!map || status !== 'ready') return;
    const instance = map as MapLibreMap & {
      setProjection?: (projection: { type: 'globe' | 'mercator' }) => void;
      setSky?: (sky: Record<string, unknown>) => void;
    };
    try {
      instance.setProjection?.({ type: globe ? 'globe' : 'mercator' });
      instance.setSky?.(
        globe
          ? {
              'sky-color': cssVar('--map-sky', '#0b1a2e'),
              'horizon-color': cssVar('--map-horizon', '#2b5c9e'),
              'fog-color': cssVar('--map-ocean', '#07121f'),
              'sky-horizon-blend': 0.6,
              'horizon-fog-blend': 0.8,
              'fog-ground-blend': 0.85,
              'atmosphere-blend': ['interpolate', ['linear'], ['zoom'], 0, 1, 6, 0.6, 9, 0],
            }
          : { 'atmosphere-blend': 0 },
      );
    } catch (cause) {
      console.warn('[map] projection not supported', cause);
    }
  }, [map, status, globe, themeVersion]);

  // Idle auto-rotation for the globe: stops on the first interaction, never runs
  // under reduced motion or in a hidden tab.
  useEffect(() => {
    if (!map || status !== 'ready' || !globe || !autoRotate || prefersReducedMotion()) return;
    let stopped = false;
    let frame = 0;
    let last = performance.now();
    const stop = () => {
      stopped = true;
    };
    const step = (now: number) => {
      if (stopped) return;
      if (!document.hidden) {
        const dt = Math.min(64, now - last);
        map.setCenter([map.getCenter().lng + dt * 0.004, map.getCenter().lat]);
      }
      last = now;
      frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    const events = ['mousedown', 'touchstart', 'wheel', 'dragstart', 'keydown'] as const;
    for (const name of events) map.on(name, stop);
    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
      for (const name of events) map.off(name, stop);
    };
  }, [map, status, globe, autoRotate]);

  const setBasemap = useCallback(
    (id: BasemapId) => {
      userSetBasemap.current = true;
      setFallbackNotice(null);
      setBasemapState(id);
      if (persist) writePreference(PREF_BASEMAP, id);
    },
    [persist],
  );

  const setLabels = useCallback(
    (value: boolean) => {
      setLabelsState(value);
      if (persist) writePreference(PREF_BASEMAP_LABELS, value ? '1' : '0');
    },
    [persist],
  );

  const setGlobe = useCallback((value: boolean) => setGlobeState(value), []);

  return {
    containerRef,
    map,
    status,
    error,
    themeVersion,
    theme,
    retry,
    basemap,
    setBasemap,
    labels,
    setLabels,
    globe,
    setGlobe,
    fallbackNotice,
  };
}
