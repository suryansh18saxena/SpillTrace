'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent } from 'maplibre-gl';
import type { Feature, FeatureCollection, Polygon } from 'geojson';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { IconDraw, IconClose, IconUndo } from '@/components/ui/Icons';
import { formatAreaKm2 } from '@/lib/format';
import {
  polygonAreaKm2,
  polygonBbox,
  polygonFromVertices,
  rectanglePolygon,
  ringSelfIntersects,
  type LngLat,
} from '@/lib/geo';
import { cssVar } from './useMap';
import styles from './map.module.css';

type DrawMode = 'idle' | 'polygon' | 'rectangle';

const DRAFT_SOURCE = 'st-aoi-draft';
const DRAFT_FILL = 'st-aoi-draft-fill';
const DRAFT_LINE = 'st-aoi-draft-line';
const DRAFT_POINTS = 'st-aoi-draft-points';

/** Pixels within which a click counts as "the same point". */
const SNAP_PX = 10;

const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };

function draftCollection(vertices: readonly LngLat[], hover: LngLat | null): FeatureCollection {
  const path = hover ? [...vertices, hover] : [...vertices];
  const features: Feature[] = [];

  if (path.length >= 2) {
    features.push({
      type: 'Feature',
      properties: { kind: 'path' },
      geometry: { type: 'LineString', coordinates: path.map((p) => [p[0], p[1]]) },
    });
  }
  if (path.length >= 3) {
    features.push({
      type: 'Feature',
      properties: { kind: 'preview' },
      geometry: polygonFromVertices(path),
    });
  }
  for (const [index, vertex] of vertices.entries()) {
    features.push({
      type: 'Feature',
      properties: { kind: 'vertex', index },
      geometry: { type: 'Point', coordinates: [vertex[0], vertex[1]] },
    });
  }
  return { type: 'FeatureCollection', features };
}

function ensureDraftLayers(map: MapLibreMap): void {
  const accent = cssVar('--map-aoi', '#4f8ff7');
  if (!map.getSource(DRAFT_SOURCE)) {
    map.addSource(DRAFT_SOURCE, { type: 'geojson', data: EMPTY });
  }
  if (!map.getLayer(DRAFT_FILL)) {
    map.addLayer({
      id: DRAFT_FILL,
      type: 'fill',
      source: DRAFT_SOURCE,
      filter: ['==', ['get', 'kind'], 'preview'],
      paint: { 'fill-color': accent, 'fill-opacity': 0.12 },
    });
  }
  if (!map.getLayer(DRAFT_LINE)) {
    map.addLayer({
      id: DRAFT_LINE,
      type: 'line',
      source: DRAFT_SOURCE,
      filter: ['==', ['get', 'kind'], 'path'],
      paint: { 'line-color': accent, 'line-width': 1.6, 'line-dasharray': [2, 1.5] },
    });
  }
  if (!map.getLayer(DRAFT_POINTS)) {
    map.addLayer({
      id: DRAFT_POINTS,
      type: 'circle',
      source: DRAFT_SOURCE,
      filter: ['==', ['get', 'kind'], 'vertex'],
      paint: {
        'circle-radius': 4,
        'circle-color': cssVar('--color-bg', '#0b0f14'),
        'circle-stroke-width': 2,
        'circle-stroke-color': accent,
      },
    });
  }
}

function removeDraftLayers(map: MapLibreMap): void {
  for (const id of [DRAFT_FILL, DRAFT_LINE, DRAFT_POINTS]) {
    if (map.getLayer(id)) map.removeLayer(id);
  }
  if (map.getSource(DRAFT_SOURCE)) map.removeSource(DRAFT_SOURCE);
}

export interface DrawAoiControlProps {
  map: MapLibreMap | null;
  value: Polygon | null;
  onChange: (polygon: Polygon | null) => void;
  disabled?: boolean;
  /** Validation message for the numeric bounds fields. */
  error?: string | null;
}

/**
 * AOI drawing, implemented from scratch on raw MapLibre events (UI-003).
 *
 * No draw plugin: `@mapbox/mapbox-gl-draw` is not MapLibre-native and every
 * MapLibre fork of it adds an unaudited dependency to a bundle we have promised
 * to keep free of third-party surface (CON-004).
 *
 * Two pointer gestures, and — importantly — a **complete keyboard path**. A map
 * drawing tool that only responds to a mouse is inaccessible by construction, so
 * the numeric bounds fields below the toolbar are a first-class way to define an
 * AOI, not a fallback: type four numbers, press Apply.
 */
export function DrawAoiControl({
  map,
  value,
  onChange,
  disabled = false,
  error,
}: DrawAoiControlProps) {
  const [mode, setMode] = useState<DrawMode>('idle');
  const [vertices, setVertices] = useState<LngLat[]>([]);
  const [hover, setHover] = useState<LngLat | null>(null);
  const [bounds, setBounds] = useState({ west: '', south: '', east: '', north: '' });
  const [boundsError, setBoundsError] = useState<string | null>(null);

  const areaKm2 = useMemo(() => polygonAreaKm2(value), [value]);
  const bbox = useMemo(() => polygonBbox(value), [value]);

  // Mirror the committed AOI into the numeric fields so the two ways of
  // defining an area always agree.
  useEffect(() => {
    if (!bbox) return;
    setBounds({
      west: bbox[0].toFixed(4),
      south: bbox[1].toFixed(4),
      east: bbox[2].toFixed(4),
      north: bbox[3].toFixed(4),
    });
  }, [bbox]);

  const stopDrawing = useCallback(() => {
    setMode('idle');
    setVertices([]);
    setHover(null);
  }, []);

  const commit = useCallback(
    (polygon: Polygon) => {
      onChange(polygon);
      stopDrawing();
    },
    [onChange, stopDrawing],
  );

  const finishPolygon = useCallback(
    (points: readonly LngLat[]) => {
      if (points.length < 3) return;
      commit(polygonFromVertices(points));
    },
    [commit],
  );

  // ------------------------------------------------------------- draft layers
  useEffect(() => {
    if (!map) return;
    try {
      ensureDraftLayers(map);
    } catch {
      return;
    }
    return () => {
      try {
        removeDraftLayers(map);
      } catch {
        // Map already torn down.
      }
    };
  }, [map]);

  useEffect(() => {
    if (!map) return;
    const source = map.getSource(DRAFT_SOURCE) as GeoJSONSource | undefined;
    if (!source) return;
    source.setData(mode === 'idle' ? EMPTY : draftCollection(vertices, hover));
  }, [map, mode, vertices, hover]);

  // ----------------------------------------------------------- pointer events
  useEffect(() => {
    if (!map || mode === 'idle' || disabled) return;

    const canvas = map.getCanvas();
    const previousCursor = canvas.style.cursor;
    canvas.style.cursor = 'crosshair';
    map.doubleClickZoom.disable();

    const near = (a: LngLat, b: LngLat): boolean => {
      const pa = map.project(a);
      const pb = map.project(b);
      return Math.hypot(pa.x - pb.x, pa.y - pb.y) <= SNAP_PX;
    };

    const handleClick = (event: MapMouseEvent) => {
      const point: LngLat = [event.lngLat.lng, event.lngLat.lat];

      if (mode === 'rectangle') {
        const anchor = vertices[0];
        if (!anchor) {
          setVertices([point]);
          return;
        }
        commit(rectanglePolygon(anchor, point));
        return;
      }

      const first = vertices[0];
      const last = vertices[vertices.length - 1];
      // Click the first vertex to close the ring.
      if (first && vertices.length >= 3 && near(point, first)) {
        finishPolygon(vertices);
        return;
      }
      // Swallow the repeat click that a double-click generates.
      if (last && near(point, last)) return;
      setVertices((current) => [...current, point]);
    };

    const handleMove = (event: MapMouseEvent) => {
      setHover([event.lngLat.lng, event.lngLat.lat]);
    };

    const handleDoubleClick = (event: MapMouseEvent) => {
      event.preventDefault();
      if (mode === 'polygon') finishPolygon(vertices);
    };

    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        stopDrawing();
      } else if (event.key === 'Enter') {
        event.preventDefault();
        if (mode === 'polygon') finishPolygon(vertices);
      } else if (event.key === 'Backspace') {
        event.preventDefault();
        setVertices((current) => current.slice(0, -1));
      }
    };

    map.on('click', handleClick);
    map.on('mousemove', handleMove);
    map.on('dblclick', handleDoubleClick);
    window.addEventListener('keydown', handleKey);

    return () => {
      map.off('click', handleClick);
      map.off('mousemove', handleMove);
      map.off('dblclick', handleDoubleClick);
      window.removeEventListener('keydown', handleKey);
      canvas.style.cursor = previousCursor;
      map.doubleClickZoom.enable();
    };
  }, [map, mode, vertices, disabled, commit, finishPolygon, stopDrawing]);

  // ------------------------------------------------------------ numeric entry
  const applyBounds = useCallback(() => {
    const west = Number.parseFloat(bounds.west);
    const south = Number.parseFloat(bounds.south);
    const east = Number.parseFloat(bounds.east);
    const north = Number.parseFloat(bounds.north);

    if ([west, south, east, north].some((n) => !Number.isFinite(n))) {
      setBoundsError('Enter all four bounds as decimal degrees.');
      return;
    }
    if (west < -180 || east > 180 || south < -90 || north > 90) {
      setBoundsError('Longitude must be between −180 and 180, latitude between −90 and 90.');
      return;
    }
    if (west === east || south === north) {
      setBoundsError('West/east and south/north must differ, or the area has no extent.');
      return;
    }
    setBoundsError(null);
    stopDrawing();
    onChange(rectanglePolygon([west, south], [east, north]));
  }, [bounds, onChange, stopDrawing]);

  const drawing = mode !== 'idle';
  const vertexCount = vertices.length;
  const selfIntersects = value
    ? ringSelfIntersects((value.coordinates[0] ?? []) as LngLat[])
    : false;

  const status = (() => {
    if (disabled) return 'Drawing is unavailable while the case is being created.';
    if (mode === 'rectangle') {
      return vertexCount === 0
        ? 'Click the first corner of the rectangle.'
        : 'Click the opposite corner to finish. Escape cancels.';
    }
    if (mode === 'polygon') {
      if (vertexCount < 3) {
        return `Click to add corners (${vertexCount} so far). At least three are needed.`;
      }
      return `${vertexCount} corners. Double-click, press Enter, or click the first corner to close. Backspace removes the last corner.`;
    }
    if (value) return 'Area of interest set. Redraw or edit the bounds below to change it.';
    return 'Choose a drawing tool, or type the bounds below.';
  })();

  return (
    <div className={styles.drawRoot}>
      <div className={styles.drawToolbar}>
        <div className={styles.drawToolbarGroup}>
          <Button
            variant={mode === 'rectangle' ? 'primary' : 'secondary'}
            size="sm"
            disabled={disabled || !map}
            aria-pressed={mode === 'rectangle'}
            onClick={() => {
              setVertices([]);
              setHover(null);
              setMode((current) => (current === 'rectangle' ? 'idle' : 'rectangle'));
            }}
            leadingIcon={<IconDraw size={14} />}
          >
            Rectangle
          </Button>
          <Button
            variant={mode === 'polygon' ? 'primary' : 'secondary'}
            size="sm"
            disabled={disabled || !map}
            aria-pressed={mode === 'polygon'}
            onClick={() => {
              setVertices([]);
              setHover(null);
              setMode((current) => (current === 'polygon' ? 'idle' : 'polygon'));
            }}
            leadingIcon={<IconDraw size={14} />}
          >
            Polygon
          </Button>
        </div>

        <Button
          variant="ghost"
          size="sm"
          disabled={!drawing || vertexCount === 0}
          onClick={() => setVertices((current) => current.slice(0, -1))}
          leadingIcon={<IconUndo size={14} />}
        >
          Undo corner
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={mode !== 'polygon' || vertexCount < 3}
          onClick={() => finishPolygon(vertices)}
        >
          Finish shape
        </Button>
        <Button
          variant="ghost"
          size="sm"
          disabled={disabled || (!value && !drawing)}
          onClick={() => {
            stopDrawing();
            onChange(null);
          }}
          leadingIcon={<IconClose size={14} />}
        >
          Clear
        </Button>
      </div>

      <p className={styles.drawStatus} role="status" aria-live="polite">
        {status}
      </p>

      {value ? (
        <div className={styles.drawSummary}>
          <div className={styles.drawSummaryItem}>
            <span className={styles.drawSummaryLabel}>Area</span>
            <span className={styles.drawSummaryValue}>{formatAreaKm2(areaKm2)}</span>
          </div>
          <div className={styles.drawSummaryItem}>
            <span className={styles.drawSummaryLabel}>Corners</span>
            <span className={styles.drawSummaryValue}>
              {Math.max(0, (value.coordinates[0]?.length ?? 1) - 1)}
            </span>
          </div>
          <div className={styles.drawSummaryItem}>
            <span className={styles.drawSummaryLabel}>Geometry</span>
            <span className={styles.drawSummaryValue}>
              {selfIntersects ? 'self-intersecting' : 'simple polygon'}
            </span>
          </div>
        </div>
      ) : null}

      <fieldset>
        <legend className={styles.drawSummaryLabel}>
          Bounds (decimal degrees, WGS 84) — keyboard entry
        </legend>
        <div className={styles.boundsGrid}>
          <Input
            label="West"
            type="number"
            step="0.0001"
            min={-180}
            max={180}
            inputMode="decimal"
            mono
            disabled={disabled}
            value={bounds.west}
            onChange={(event) => setBounds((b) => ({ ...b, west: event.target.value }))}
          />
          <Input
            label="South"
            type="number"
            step="0.0001"
            min={-90}
            max={90}
            inputMode="decimal"
            mono
            disabled={disabled}
            value={bounds.south}
            onChange={(event) => setBounds((b) => ({ ...b, south: event.target.value }))}
          />
          <Input
            label="East"
            type="number"
            step="0.0001"
            min={-180}
            max={180}
            inputMode="decimal"
            mono
            disabled={disabled}
            value={bounds.east}
            onChange={(event) => setBounds((b) => ({ ...b, east: event.target.value }))}
          />
          <Input
            label="North"
            type="number"
            step="0.0001"
            min={-90}
            max={90}
            inputMode="decimal"
            mono
            disabled={disabled}
            value={bounds.north}
            onChange={(event) => setBounds((b) => ({ ...b, north: event.target.value }))}
          />
        </div>
        <div className={styles.boundsFooter}>
          <Button variant="secondary" size="sm" onClick={applyBounds} disabled={disabled}>
            Apply bounds
          </Button>
          {boundsError || error ? (
            <span role="alert" style={{ color: 'var(--color-danger)', fontSize: 'var(--text-xs)' }}>
              {boundsError ?? error}
            </span>
          ) : null}
        </div>
      </fieldset>
    </div>
  );
}
