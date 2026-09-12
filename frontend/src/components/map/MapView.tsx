'use client';

import { createContext, useContext, useEffect, useRef, type ReactNode } from 'react';
import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent } from 'maplibre-gl';
import type { FeatureCollection } from 'geojson';
import { ErrorState } from '@/components/ui/ErrorState';
import { Spinner } from '@/components/ui/Spinner';
import { cx } from '@/lib/cx';
import type { BBox } from '@/lib/geo';
import { BasemapControl } from './BasemapControl';
import type { BasemapId } from '@/lib/map/basemaps';
import { cssVar, prefersReducedMotion, useMap } from './useMap';
import styles from './map.module.css';

export type MapLayerKind = 'polygon' | 'line' | 'point' | 'raster';

/** A MapLibre filter expression. Kept loose: MapLibre validates it at runtime. */
export type MapFilter = unknown[];

export interface MapDataLayer {
  id: string;
  kind: MapLayerKind;
  /** Vector payload. `null` means "known layer, nothing to draw yet". */
  data?: FeatureCollection | null;
  /** `{z}/{x}/{y}` templates for a raster layer. */
  tiles?: string[];
  /** Design-token name driving the layer colour, e.g. `--map-spill`. */
  colorVar: string;
  colorFallback: string;
  visible: boolean;
  /** 0..1. Applied to fill, line and circle alike so one slider governs a layer. */
  opacity?: number;
  /**
   * Feature property in `[0,1]` that graduates the fill across the 3-step
   * confidence ramp — used for the origin **probability region**, which is never
   * drawn as a single certain outline (CON-008).
   */
  graduatedBy?: string;
  /**
   * Invert the ramp for nested probability contours.
   *
   * The 90 % contour is the *largest* and least specific region; the 50 % contour
   * is the tightest. Drawing them with opacity inversely proportional to the
   * probability mass makes the nesting legible: the innermost, most concentrated
   * region reads strongest, exactly as the statistic means.
   */
  graduatedInverse?: boolean;
  filter?: MapFilter | null;
  /** Include this layer in hover tooltips and click-to-select. */
  selectable?: boolean;
  circleRadius?: number;
  lineWidth?: number;
}

export interface MapFeatureSelection {
  layerId: string;
  properties: Record<string, unknown>;
  lngLat: { lng: number; lat: number };
}

const MapContext = createContext<MapLibreMap | null>(null);

/** The live map instance, for controls rendered inside `<MapView>`. */
export function useMapInstance(): MapLibreMap | null {
  return useContext(MapContext);
}

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };

const sourceIdFor = (id: string) => `st-src-${id}`;
const layerIdsFor = (id: string, kind: MapLayerKind): string[] =>
  kind === 'polygon' ? [`st-${id}-fill`, `st-${id}-line`] : [`st-${id}`];

/** `st-origin_region-fill` → `origin_region`. */
function dataLayerIdFrom(styleLayerId: string): string {
  return styleLayerId.replace(/^st-/, '').replace(/-(fill|line)$/, '');
}

function removeLayerAndSource(map: MapLibreMap, layerIds: string[], sourceId: string): void {
  for (const layerId of layerIds) {
    if (map.getLayer(layerId)) map.removeLayer(layerId);
  }
  if (map.getSource(sourceId)) map.removeSource(sourceId);
}

/** Colour ramp expression for a probability-graduated fill. */
function graduatedColor(property: string, inverse: boolean): unknown {
  const low = cssVar('--confidence-1', '#7a8798');
  const mid = cssVar('--confidence-2', '#c08b34');
  const high = cssVar('--confidence-3', '#f0c04a');
  const stops = inverse ? [high, mid, low] : [low, mid, high];
  return [
    'interpolate',
    ['linear'],
    ['coalesce', ['to-number', ['get', property]], 0],
    0,
    stops[0],
    0.5,
    stops[1],
    1,
    stops[2],
  ];
}

/** Opacity expression that makes nested probability contours read as nested. */
function graduatedOpacity(property: string, opacity: number, inverse: boolean): unknown {
  const near = inverse ? 0.34 : 0.1;
  const far = inverse ? 0.08 : 0.34;
  return [
    'interpolate',
    ['linear'],
    ['coalesce', ['to-number', ['get', property]], 0.5],
    0.4,
    near * opacity,
    1,
    far * opacity,
  ];
}

function applyLayer(map: MapLibreMap, layer: MapDataLayer): void {
  const sourceId = sourceIdFor(layer.id);
  const color = cssVar(layer.colorVar, layer.colorFallback);
  const visibility = layer.visible ? 'visible' : 'none';
  const opacity = layer.opacity ?? 1;

  if (layer.kind === 'raster') {
    if (!layer.tiles || layer.tiles.length === 0) return;
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, { type: 'raster', tiles: layer.tiles, tileSize: 256 });
    }
    const layerId = `st-${layer.id}`;
    if (!map.getLayer(layerId)) {
      map.addLayer({
        id: layerId,
        type: 'raster',
        source: sourceId,
        paint: { 'raster-opacity': opacity, 'raster-resampling': 'linear' },
      });
    }
    map.setLayoutProperty(layerId, 'visibility', visibility);
    map.setPaintProperty(layerId, 'raster-opacity', opacity);
    return;
  }

  const data = layer.data ?? EMPTY;
  const existing = map.getSource(sourceId) as GeoJSONSource | undefined;
  if (existing) {
    existing.setData(data);
  } else {
    map.addSource(sourceId, { type: 'geojson', data });
  }

  const graduated = Boolean(layer.graduatedBy);
  const fillColor = layer.graduatedBy
    ? (graduatedColor(layer.graduatedBy, layer.graduatedInverse ?? false) as unknown as string)
    : color;
  const fillOpacity = layer.graduatedBy
    ? (graduatedOpacity(
        layer.graduatedBy,
        opacity,
        layer.graduatedInverse ?? false,
      ) as unknown as number)
    : 0.18 * opacity;

  // A filter is applied to every style layer this data layer owns, and cleared
  // (rather than left behind) when the caller stops filtering.
  const filter = (layer.filter ?? null) as never;
  const setFilter = (styleLayerId: string) => {
    if (layer.filter) map.setFilter(styleLayerId, filter);
    else map.setFilter(styleLayerId, null);
  };

  if (layer.kind === 'polygon') {
    const fillId = `st-${layer.id}-fill`;
    const lineId = `st-${layer.id}-line`;
    if (!map.getLayer(fillId)) {
      map.addLayer({
        id: fillId,
        type: 'fill',
        source: sourceId,
        paint: { 'fill-color': fillColor, 'fill-opacity': fillOpacity },
      });
    }
    if (!map.getLayer(lineId)) {
      map.addLayer({
        id: lineId,
        type: 'line',
        source: sourceId,
        paint: {
          'line-color': color,
          'line-width': layer.lineWidth ?? 1.6,
          'line-opacity': opacity,
        },
      });
    }
    map.setPaintProperty(fillId, 'fill-color', fillColor);
    map.setPaintProperty(fillId, 'fill-opacity', fillOpacity);
    map.setPaintProperty(lineId, 'line-color', graduated ? fillColor : color);
    map.setPaintProperty(lineId, 'line-opacity', opacity);
    map.setPaintProperty(lineId, 'line-width', layer.lineWidth ?? 1.6);
    map.setLayoutProperty(fillId, 'visibility', visibility);
    map.setLayoutProperty(lineId, 'visibility', visibility);
    setFilter(fillId);
    setFilter(lineId);
    return;
  }

  const layerId = `st-${layer.id}`;
  if (layer.kind === 'line') {
    if (!map.getLayer(layerId)) {
      map.addLayer({
        id: layerId,
        type: 'line',
        source: sourceId,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': color,
          'line-width': layer.lineWidth ?? 1.4,
          'line-opacity': 0.9 * opacity,
        },
      });
    }
    map.setPaintProperty(layerId, 'line-color', color);
    map.setPaintProperty(layerId, 'line-opacity', 0.9 * opacity);
    map.setPaintProperty(layerId, 'line-width', layer.lineWidth ?? 1.4);
  } else {
    if (!map.getLayer(layerId)) {
      map.addLayer({
        id: layerId,
        type: 'circle',
        source: sourceId,
        paint: {
          'circle-radius': layer.circleRadius ?? 4,
          'circle-color': color,
          'circle-stroke-width': 1,
          'circle-stroke-color': cssVar('--color-bg', '#0b0f14'),
          'circle-opacity': opacity,
          'circle-stroke-opacity': opacity,
        },
      });
    }
    map.setPaintProperty(layerId, 'circle-color', color);
    map.setPaintProperty(layerId, 'circle-radius', layer.circleRadius ?? 4);
    map.setPaintProperty(layerId, 'circle-opacity', opacity);
    map.setPaintProperty(layerId, 'circle-stroke-opacity', opacity);
  }
  map.setLayoutProperty(layerId, 'visibility', visibility);
  setFilter(layerId);
}

export interface MapViewProps {
  /** Accessible name for the map canvas. Required — a bare canvas is invisible. */
  label: string;
  layers?: readonly MapDataLayer[];
  /** Bounding box to fly to when it changes. */
  fitTo?: BBox | null;
  interactive?: boolean;
  /** Chips overlaid top-left, e.g. a SYNTHETIC provenance badge. */
  badges?: ReactNode;
  /** Short instruction overlaid bottom-left, e.g. how to draw an AOI. */
  hint?: ReactNode;
  /** Legend, timeline or other overlay rendered bottom-centre. */
  overlay?: ReactNode;
  /** Controls rendered inside the map context (they can call `useMapInstance`). */
  children?: ReactNode;
  /** Handed the instance once the style has loaded — for controls rendered outside. */
  onMapReady?: (map: MapLibreMap | null) => void;
  /** Fires on click over any `selectable` layer, and with `null` on empty water. */
  onFeatureSelect?: (selection: MapFeatureSelection | null) => void;
  /**
   * Hover text for a feature. Returning `null` suppresses the tooltip. Plain
   * text only: it is written with `textContent`, never `innerHTML`.
   */
  describeFeature?: (layerId: string, properties: Record<string, unknown>) => string | null;
  className?: string;
  style?: React.CSSProperties;
  /** Initial basemap (defaults to the analyst's saved choice, then Satellite). */
  basemap?: BasemapId;
  /** Show the basemap switcher. Default on for interactive maps. */
  basemapControl?: boolean;
  /** Offer the globe projection toggle in the switcher. */
  globeToggle?: boolean;
  /** Start in globe projection. */
  globe?: boolean;
  /** Rotate the globe slowly until the user interacts (reduced-motion safe). */
  autoRotate?: boolean;
  /** Tilt the camera when flying to `fitTo`, for a more cinematic reveal. */
  cinematic?: boolean;
}

/**
 * The MapLibre wrapper.
 *
 * Data layers are declared, not imperatively managed by callers: pass the array
 * and this component reconciles sources, style layers, filters, opacity and
 * visibility. That keeps every screen's map code to a list of layer descriptors,
 * and keeps the imperative MapLibre surface in exactly one file.
 */
export function MapView({
  label,
  layers = [],
  fitTo,
  interactive = true,
  badges,
  hint,
  overlay,
  children,
  onMapReady,
  onFeatureSelect,
  describeFeature,
  className,
  style,
  basemap: initialBasemap,
  basemapControl = interactive,
  globeToggle = false,
  globe: initialGlobe = false,
  autoRotate = false,
  cinematic = true,
}: MapViewProps) {
  const {
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
  } = useMap({
    interactive,
    label,
    basemap: initialBasemap,
    globe: initialGlobe,
    autoRotate,
  });
  const readoutRef = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const previousIds = useRef<Map<string, MapLayerKind>>(new Map());
  const selectableIds = useRef<string[]>([]);

  // Callbacks are held in refs so that a parent re-rendering with a new closure
  // does not tear down and re-register the map's event handlers on every frame.
  const describeRef = useRef(describeFeature);
  describeRef.current = describeFeature;
  const selectRef = useRef(onFeatureSelect);
  selectRef.current = onFeatureSelect;

  useEffect(() => {
    if (!map || status !== 'ready') return;

    const next = new Map<string, MapLayerKind>();
    const selectable: string[] = [];
    for (const layer of layers) {
      next.set(layer.id, layer.kind);
      try {
        applyLayer(map, layer);
        if (layer.selectable && layer.visible) {
          selectable.push(...layerIdsFor(layer.id, layer.kind).filter((id) => map.getLayer(id)));
        }
      } catch (cause) {
        console.warn(`[map] could not apply layer "${layer.id}"`, cause);
      }
    }
    // Lines and circles are easier to hit than a polygon fill, so they are
    // queried first when several layers overlap under the pointer.
    selectableIds.current = selectable.sort(
      (a, b) => Number(a.endsWith('-fill')) - Number(b.endsWith('-fill')),
    );

    for (const [id, kind] of previousIds.current) {
      if (next.has(id)) continue;
      try {
        removeLayerAndSource(map, layerIdsFor(id, kind), sourceIdFor(id));
      } catch {
        // The style may already have been torn down; nothing to clean up.
      }
    }
    previousIds.current = next;
  }, [map, status, layers, themeVersion]);

  useEffect(() => {
    onMapReady?.(status === 'ready' ? map : null);
  }, [map, status, onMapReady]);

  useEffect(() => {
    if (!map || status !== 'ready' || !fitTo) return;
    const reduced = prefersReducedMotion();
    map.fitBounds(
      [
        [fitTo[0], fitTo[1]],
        [fitTo[2], fitTo[3]],
      ],
      {
        padding: 64,
        maxZoom: 12,
        duration: reduced ? 0 : cinematic ? 1600 : 600,
        essential: true,
        ...(cinematic && !reduced ? { pitch: 32, bearing: -8, curve: 1.3 } : {}),
      },
    );
  }, [map, status, fitTo, cinematic]);

  // Coordinate readout and hover tooltip, written straight to the DOM: at 60
  // pointer events a second, routing this through React state would re-render
  // the whole investigation panel.
  useEffect(() => {
    if (!map || status !== 'ready') return;

    const hideTooltip = () => {
      const node = tooltipRef.current;
      if (!node) return;
      node.hidden = true;
      node.textContent = '';
    };

    const onMove = (event: MapMouseEvent) => {
      const readout = readoutRef.current;
      if (readout) {
        readout.textContent = `${event.lngLat.lat.toFixed(4)}°, ${event.lngLat.lng.toFixed(4)}°`;
      }

      const node = tooltipRef.current;
      const ids = selectableIds.current;
      if (!node || ids.length === 0) return;

      const hits = map.queryRenderedFeatures(event.point, { layers: ids });
      const hit = hits[0];
      const text = hit
        ? (describeRef.current?.(
            dataLayerIdFrom(hit.layer.id),
            (hit.properties ?? {}) as Record<string, unknown>,
          ) ?? null)
        : null;

      map.getCanvas().style.cursor = hit ? 'pointer' : '';
      if (!text) {
        hideTooltip();
        return;
      }
      node.hidden = false;
      node.textContent = text;
      // Offset so the label never sits under the pointer itself.
      node.style.transform = `translate(${event.point.x + 14}px, ${event.point.y + 14}px)`;
    };

    const onLeave = () => {
      if (readoutRef.current) readoutRef.current.textContent = '';
      map.getCanvas().style.cursor = '';
      hideTooltip();
    };

    const onClick = (event: MapMouseEvent) => {
      const handler = selectRef.current;
      if (!handler) return;
      const ids = selectableIds.current;
      const hits = ids.length ? map.queryRenderedFeatures(event.point, { layers: ids }) : [];
      const hit = hits[0];
      handler(
        hit
          ? {
              layerId: dataLayerIdFrom(hit.layer.id),
              properties: (hit.properties ?? {}) as Record<string, unknown>,
              lngLat: { lng: event.lngLat.lng, lat: event.lngLat.lat },
            }
          : null,
      );
    };

    map.on('mousemove', onMove);
    map.on('mouseout', onLeave);
    map.on('click', onClick);
    return () => {
      map.off('mousemove', onMove);
      map.off('mouseout', onLeave);
      map.off('click', onClick);
    };
  }, [map, status]);

  return (
    <MapContext.Provider value={map}>
      <div className={cx(styles.mapRoot, className)} style={style} data-testid="map-view">
        <div
          ref={containerRef}
          className={styles.mapCanvas}
          role="application"
          aria-label={label}
        />

        {badges ? <div className={styles.mapBadges}>{badges}</div> : null}
        {basemapControl && status === 'ready' ? (
          <BasemapControl
            basemap={basemap}
            onBasemapChange={setBasemap}
            labels={labels}
            onLabelsChange={setLabels}
            theme={theme}
            fallbackNotice={fallbackNotice}
            {...(globeToggle ? { globe, onGlobeChange: setGlobe } : {})}
          />
        ) : null}
        {hint ? <p className={styles.mapHint}>{hint}</p> : null}
        {overlay ? <div className={styles.mapOverlayBar}>{overlay}</div> : null}

        <div ref={tooltipRef} className={styles.mapTooltip} hidden aria-hidden="true" />
        <span
          ref={readoutRef}
          className={styles.mapReadout}
          aria-hidden="true"
          data-testid="map-readout"
        />

        {status === 'error' ? (
          <div className={styles.mapOverlay}>
            <div className={styles.mapOverlayCard}>
              <ErrorState
                title="The map could not start"
                description={
                  error?.message ??
                  'MapLibre GL needs WebGL. Enable hardware acceleration, or use a different browser, to see the map.'
                }
                onRetry={retry}
              />
            </div>
          </div>
        ) : null}

        {status !== 'ready' && status !== 'error' ? (
          <div className={styles.mapOverlay} aria-busy="true">
            <Spinner size="md" label="Loading map" />
          </div>
        ) : null}

        {children}
      </div>
    </MapContext.Provider>
  );
}
