'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { Map as MapLibreMap } from 'maplibre-gl';
import { API_BASE_URL, MAP_DEFAULT_CENTER, MAP_DEFAULT_ZOOM, MAP_STYLE_URL } from '@/lib/config';
import { getAccessToken } from '@/lib/auth/session';

export interface UseMapOptions {
  center?: [number, number];
  zoom?: number;
  /** Enable pan/zoom. Disabled maps are still keyboard-focusable for reading. */
  interactive?: boolean;
  /** Accessible name applied to the canvas container. */
  label?: string;
}

export interface UseMapResult {
  containerRef: (node: HTMLDivElement | null) => void;
  map: MapLibreMap | null;
  status: 'idle' | 'loading' | 'ready' | 'error';
  error: Error | null;
  /** Increments whenever the document theme changes, so paint can be re-derived. */
  themeVersion: number;
  retry: () => void;
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

/**
 * Creates and owns a MapLibre GL map.
 *
 * MapLibre is imported dynamically: the module touches `window` at import time,
 * and every page in this app is server-rendered first. The style is
 * `/map-style.json`, served by us — there is no tile provider, no API key and no
 * request that leaves our origin (AD-5, CON-004).
 */
export function useMap(options: UseMapOptions = {}): UseMapResult {
  const {
    center = MAP_DEFAULT_CENTER,
    zoom = MAP_DEFAULT_ZOOM,
    interactive = true,
    label,
  } = options;

  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [status, setStatus] = useState<UseMapResult['status']>('idle');
  const [error, setError] = useState<Error | null>(null);
  const [themeVersion, setThemeVersion] = useState(0);
  const [attempt, setAttempt] = useState(0);

  // Keep the initial view in a ref: changing the camera prop must not tear down
  // and rebuild the map, which would lose every layer and the analyst's pan.
  const initialView = useRef({ center, zoom });

  const containerRef = useCallback((node: HTMLDivElement | null) => {
    setContainer(node);
  }, []);

  const retry = useCallback(() => {
    setError(null);
    setStatus('idle');
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
        if (cancelled) return;

        instance = new maplibre.Map({
          container,
          style: MAP_STYLE_URL,
          center: initialView.current.center,
          zoom: initialView.current.zoom,
          interactive,
          attributionControl: false,
          // Nothing to fetch from a third party, so no cross-origin worker or
          // RTL text plugin is ever loaded.
          fadeDuration: 120,
          /**
           * The only absolute URL the map is ever allowed to fetch is our own
           * API — probability-raster tiles (API.md §7). Those endpoints are
           * authenticated, and MapLibre cannot otherwise attach a bearer token,
           * so it is attached here. Anything else (there is nothing else: the
           * style is a local file) is passed through untouched, and the CSP's
           * `connect-src` blocks it anyway.
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

        instance.addControl(
          new maplibre.NavigationControl({ visualizePitch: false, showCompass: false }),
          'top-right',
        );
        instance.addControl(
          new maplibre.ScaleControl({ maxWidth: 120, unit: 'metric' }),
          'bottom-right',
        );
        instance.addControl(
          new maplibre.AttributionControl({
            compact: true,
            customAttribution:
              'SPILLTRACE self-hosted basemap · no third-party tiles · data layers from the SPILLTRACE API',
          }),
          'bottom-right',
        );

        if (label) instance.getCanvas().setAttribute('aria-label', label);
        // The canvas is focusable so the map can be panned/zoomed from the
        // keyboard (MapLibre binds arrow keys and +/- once it has focus).
        instance.getCanvas().setAttribute('tabindex', '0');

        instance.on('load', () => {
          if (!cancelled) setStatus('ready');
        });
        instance.on('error', (event: { error?: Error }) => {
          // Style/source errors are reported but must not blank the map.
          if (event?.error) console.warn('[map]', event.error.message);
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
    const observer = new MutationObserver(() => setThemeVersion((value) => value + 1));
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

  return { containerRef, map, status, error, themeVersion, retry };
}
