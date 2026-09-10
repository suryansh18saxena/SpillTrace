/**
 * Dependency-free geometry helpers for AOI drawing and validation (UI-003).
 *
 * The same rules the API enforces (API.md §4) are checked here first so the
 * analyst gets an immediate, specific message instead of a round-trip 422 — but
 * the server remains the authority, and a client that disagrees simply surfaces
 * the server's error.
 */

import type { Polygon } from 'geojson';
import { MAX_AOI_KM2, MAX_WINDOW_DAYS } from '@/lib/config';

export type LngLat = [number, number];

/** WGS84 semi-major axis, metres. */
const EARTH_RADIUS_M = 6_378_137;

const toRadians = (degrees: number): number => (degrees * Math.PI) / 180;

export function isValidLngLat(position: readonly number[] | undefined): position is LngLat {
  if (!position || position.length < 2) return false;
  const [lon, lat] = position;
  return (
    typeof lon === 'number' &&
    typeof lat === 'number' &&
    Number.isFinite(lon) &&
    Number.isFinite(lat) &&
    lon >= -180 &&
    lon <= 180 &&
    lat >= -90 &&
    lat <= 90
  );
}

/**
 * Geodesic area of a closed ring, in square metres.
 *
 * Chamberlain & Duquette's spherical-excess formula — the same one `@turf/area`
 * uses. Implemented here rather than pulled in as a dependency because it is
 * twenty lines and the alternative is a transitive dependency tree in a bundle
 * that must stay auditable (CON-004).
 */
export function ringAreaM2(ring: readonly (readonly number[])[]): number {
  const n = ring.length;
  if (n < 3) return 0;

  let total = 0;
  for (let i = 0; i < n; i += 1) {
    const lower = ring[i];
    const middle = ring[(i + 1) % n];
    const upper = ring[(i + 2) % n];
    if (!lower || !middle || !upper) continue;
    const lowerLon = lower[0] ?? 0;
    const upperLon = upper[0] ?? 0;
    const middleLat = middle[1] ?? 0;
    total += (toRadians(upperLon) - toRadians(lowerLon)) * Math.sin(toRadians(middleLat));
  }
  return Math.abs((total * EARTH_RADIUS_M * EARTH_RADIUS_M) / 2);
}

/** Geodesic area of a GeoJSON polygon (outer ring minus holes), in km². */
export function polygonAreaKm2(polygon: Polygon | null | undefined): number {
  if (!polygon || polygon.type !== 'Polygon' || !Array.isArray(polygon.coordinates)) return 0;
  const [outer, ...holes] = polygon.coordinates;
  if (!outer) return 0;
  let area = ringAreaM2(outer);
  for (const hole of holes) area -= ringAreaM2(hole);
  return Math.max(0, area) / 1_000_000;
}

/** Great-circle distance between two positions, in kilometres. */
export function haversineKm(a: LngLat, b: LngLat): number {
  const dLat = toRadians(b[1] - a[1]);
  const dLon = toRadians(b[0] - a[0]);
  const lat1 = toRadians(a[1]);
  const lat2 = toRadians(b[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.sin(dLon / 2) ** 2 * Math.cos(lat1) * Math.cos(lat2);
  return (2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h))) / 1000;
}

function orientation(p: LngLat, q: LngLat, r: LngLat): number {
  const value = (q[1] - p[1]) * (r[0] - q[0]) - (q[0] - p[0]) * (r[1] - q[1]);
  if (Math.abs(value) < 1e-12) return 0;
  return value > 0 ? 1 : 2;
}

function onSegment(p: LngLat, q: LngLat, r: LngLat): boolean {
  return (
    q[0] <= Math.max(p[0], r[0]) &&
    q[0] >= Math.min(p[0], r[0]) &&
    q[1] <= Math.max(p[1], r[1]) &&
    q[1] >= Math.min(p[1], r[1])
  );
}

/** Proper or improper intersection of segments `p1p2` and `q1q2`. */
export function segmentsIntersect(p1: LngLat, p2: LngLat, q1: LngLat, q2: LngLat): boolean {
  const o1 = orientation(p1, p2, q1);
  const o2 = orientation(p1, p2, q2);
  const o3 = orientation(q1, q2, p1);
  const o4 = orientation(q1, q2, p2);

  if (o1 !== o2 && o3 !== o4) return true;
  if (o1 === 0 && onSegment(p1, q1, p2)) return true;
  if (o2 === 0 && onSegment(p1, q2, p2)) return true;
  if (o3 === 0 && onSegment(q1, p1, q2)) return true;
  if (o4 === 0 && onSegment(q1, p2, q2)) return true;
  return false;
}

/**
 * True when a closed ring crosses itself (API.md §4 rejects self-intersecting
 * AOIs). O(n²), which is irrelevant for a hand-drawn polygon of a few vertices.
 */
export function ringSelfIntersects(ring: readonly LngLat[]): boolean {
  const points =
    ring.length > 1 && positionsEqual(ring[0], ring[ring.length - 1]) ? ring.slice(0, -1) : ring;
  const n = points.length;
  if (n < 4) return false;

  for (let i = 0; i < n; i += 1) {
    const a1 = points[i];
    const a2 = points[(i + 1) % n];
    if (!a1 || !a2) continue;
    for (let j = i + 1; j < n; j += 1) {
      // Skip the pair that shares a vertex, and the closing pair (0, n-1).
      if (j === i || (j + 1) % n === i || j === (i + 1) % n) continue;
      const b1 = points[j];
      const b2 = points[(j + 1) % n];
      if (!b1 || !b2) continue;
      if (segmentsIntersect(a1, a2, b1, b2)) return true;
    }
  }
  return false;
}

export function positionsEqual(
  a: readonly number[] | undefined,
  b: readonly number[] | undefined,
): boolean {
  if (!a || !b) return false;
  return Math.abs((a[0] ?? 0) - (b[0] ?? 0)) < 1e-9 && Math.abs((a[1] ?? 0) - (b[1] ?? 0)) < 1e-9;
}

/** Close a ring if the caller has not already repeated the first vertex. */
export function closeRing(ring: readonly LngLat[]): LngLat[] {
  const out = ring.map((p) => [p[0], p[1]] as LngLat);
  const first = out[0];
  const last = out[out.length - 1];
  if (first && last && !positionsEqual(first, last)) out.push([first[0], first[1]]);
  return out;
}

export function polygonFromVertices(vertices: readonly LngLat[]): Polygon {
  return { type: 'Polygon', coordinates: [closeRing(vertices)] };
}

/** Axis-aligned rectangle from two opposite corners. */
export function rectanglePolygon(a: LngLat, b: LngLat): Polygon {
  const west = Math.min(a[0], b[0]);
  const east = Math.max(a[0], b[0]);
  const south = Math.min(a[1], b[1]);
  const north = Math.max(a[1], b[1]);
  return {
    type: 'Polygon',
    coordinates: [
      [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
      ],
    ],
  };
}

export type BBox = [number, number, number, number];

export function polygonBbox(polygon: Polygon | null | undefined): BBox | null {
  const ring = polygon?.coordinates?.[0];
  if (!ring || ring.length === 0) return null;
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const position of ring) {
    const lon = position[0];
    const lat = position[1];
    if (typeof lon !== 'number' || typeof lat !== 'number') continue;
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  if (!Number.isFinite(west) || !Number.isFinite(south)) return null;
  return [west, south, east, north];
}

// ------------------------------------------------------------- AOI validation

export interface ValidationIssue {
  field: 'aoi' | 'start_time' | 'end_time' | 'title';
  message: string;
}

/** Mirrors the AOI rules in API.md §4. */
export function validateAoi(polygon: Polygon | null | undefined): ValidationIssue[] {
  if (!polygon) {
    return [{ field: 'aoi', message: 'Draw an area of interest on the map.' }];
  }

  const ring = polygon.coordinates?.[0];
  if (!ring || ring.length < 4) {
    return [{ field: 'aoi', message: 'An area of interest needs at least three corners.' }];
  }
  if (!ring.every(isValidLngLat)) {
    return [{ field: 'aoi', message: 'The area of interest contains an invalid coordinate.' }];
  }
  if (ringSelfIntersects(ring as LngLat[])) {
    return [
      {
        field: 'aoi',
        message: 'The area of interest crosses itself. Redraw it as a simple polygon.',
      },
    ];
  }

  const areaKm2 = polygonAreaKm2(polygon);
  if (areaKm2 <= 0) {
    return [{ field: 'aoi', message: 'The area of interest has no area.' }];
  }
  if (areaKm2 > MAX_AOI_KM2) {
    return [
      {
        field: 'aoi',
        message: `The area of interest is ${Math.round(areaKm2).toLocaleString('en-US')} km², above the ${MAX_AOI_KM2.toLocaleString('en-US')} km² limit. Draw a smaller area.`,
      },
    ];
  }
  return [];
}

/** Mirrors the time-window rules in API.md §4. */
export function validateTimeWindow(start: string, end: string): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  if (!start) issues.push({ field: 'start_time', message: 'Choose a start time.' });
  if (!end) issues.push({ field: 'end_time', message: 'Choose an end time.' });
  if (issues.length > 0) return issues;

  const startMs = Date.parse(start);
  const endMs = Date.parse(end);
  if (Number.isNaN(startMs)) {
    return [{ field: 'start_time', message: 'That start time is not a valid date and time.' }];
  }
  if (Number.isNaN(endMs)) {
    return [{ field: 'end_time', message: 'That end time is not a valid date and time.' }];
  }
  if (endMs <= startMs) {
    return [{ field: 'end_time', message: 'The end time must be after the start time.' }];
  }
  const days = (endMs - startMs) / 86_400_000;
  if (days > MAX_WINDOW_DAYS) {
    return [
      {
        field: 'end_time',
        message: `The time window is ${days.toFixed(1)} days, above the ${MAX_WINDOW_DAYS}-day limit.`,
      },
    ];
  }
  return [];
}

/** `datetime-local` gives `2026-08-01T00:00`; the API needs `…:00Z` (API.md §1). */
export function localInputToIso(value: string): string {
  if (!value) return '';
  return value.length === 16 ? `${value}:00Z` : `${value}Z`;
}

/** Inverse of `localInputToIso`, for pre-filling a `datetime-local` input. */
export function isoToLocalInput(value: string | null | undefined): string {
  if (!value) return '';
  return value.replace(/Z$/, '').slice(0, 16);
}
