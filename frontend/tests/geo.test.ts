import { describe, expect, it } from 'vitest';
import type { Polygon } from 'geojson';
import {
  closeRing,
  haversineKm,
  isoToLocalInput,
  localInputToIso,
  polygonAreaKm2,
  polygonBbox,
  rectanglePolygon,
  ringSelfIntersects,
  validateAoi,
  validateTimeWindow,
  type LngLat,
} from '@/lib/geo';
import { MAX_WINDOW_DAYS } from '@/lib/config';

/** The AOI from the worked example in docs/API.md §4. */
const KUTCH_AOI: Polygon = {
  type: 'Polygon',
  coordinates: [
    [
      [68.9, 22.3],
      [70.4, 22.3],
      [70.4, 23.2],
      [68.9, 23.2],
      [68.9, 22.3],
    ],
  ],
};

describe('geodesic area', () => {
  it('computes a plausible area for the documented Gulf of Kutch AOI', () => {
    const area = polygonAreaKm2(KUTCH_AOI);
    // ~1.5° x 0.9° at 22–23°N is roughly 15,400 km².
    expect(area).toBeGreaterThan(14_000);
    expect(area).toBeLessThan(17_000);
  });

  it('is independent of winding order', () => {
    const reversed: Polygon = {
      type: 'Polygon',
      coordinates: [[...(KUTCH_AOI.coordinates[0] ?? [])].reverse()],
    };
    expect(polygonAreaKm2(reversed)).toBeCloseTo(polygonAreaKm2(KUTCH_AOI), 3);
  });

  it('returns zero for degenerate input', () => {
    expect(polygonAreaKm2(null)).toBe(0);
    expect(polygonAreaKm2({ type: 'Polygon', coordinates: [[]] })).toBe(0);
  });
});

describe('haversine', () => {
  it('measures one degree of latitude as about 111 km', () => {
    expect(haversineKm([0, 0], [0, 1])).toBeCloseTo(111.3, 0);
  });
});

describe('ring helpers', () => {
  it('closes an open ring', () => {
    const open: LngLat[] = [
      [0, 0],
      [1, 0],
      [1, 1],
    ];
    const closed = closeRing(open);
    expect(closed).toHaveLength(4);
    expect(closed[closed.length - 1]).toEqual([0, 0]);
  });

  it('accepts a simple polygon', () => {
    expect(ringSelfIntersects(KUTCH_AOI.coordinates[0] as LngLat[])).toBe(false);
  });

  it('detects a bow-tie', () => {
    const bowtie: LngLat[] = [
      [0, 0],
      [2, 2],
      [2, 0],
      [0, 2],
      [0, 0],
    ];
    expect(ringSelfIntersects(bowtie)).toBe(true);
  });

  it('builds an axis-aligned rectangle from any two corners', () => {
    const fromNe = rectanglePolygon([70.4, 23.2], [68.9, 22.3]);
    expect(polygonBbox(fromNe)).toEqual([68.9, 22.3, 70.4, 23.2]);
    expect(fromNe.coordinates[0]).toHaveLength(5);
  });
});

describe('AOI validation (API.md §4)', () => {
  it('accepts the documented AOI', () => {
    expect(validateAoi(KUTCH_AOI)).toEqual([]);
  });

  it('requires an AOI at all', () => {
    expect(validateAoi(null)[0]?.message).toMatch(/draw an area of interest/i);
  });

  it('rejects a ring with fewer than three corners', () => {
    const tooFew: Polygon = {
      type: 'Polygon',
      coordinates: [
        [
          [0, 0],
          [1, 1],
          [0, 0],
        ],
      ],
    };
    expect(validateAoi(tooFew)[0]?.message).toMatch(/at least three corners/i);
  });

  it('rejects a self-intersecting polygon', () => {
    const bowtie: Polygon = {
      type: 'Polygon',
      coordinates: [
        [
          [0, 0],
          [2, 2],
          [2, 0],
          [0, 2],
          [0, 0],
        ],
      ],
    };
    expect(validateAoi(bowtie)[0]?.message).toMatch(/crosses itself/i);
  });

  it('rejects an AOI above the configured area limit', () => {
    const huge = rectanglePolygon([-60, -20], [60, 20]);
    const issues = validateAoi(huge);
    expect(issues[0]?.field).toBe('aoi');
    expect(issues[0]?.message).toMatch(/above the .* km² limit/i);
  });

  it('rejects an out-of-range coordinate', () => {
    const bad: Polygon = {
      type: 'Polygon',
      coordinates: [
        [
          [0, 0],
          [200, 0],
          [200, 10],
          [0, 10],
          [0, 0],
        ],
      ],
    };
    expect(validateAoi(bad)[0]?.message).toMatch(/invalid coordinate/i);
  });
});

describe('time-window validation (API.md §4)', () => {
  it('accepts a two-day window', () => {
    expect(validateTimeWindow('2026-08-01T00:00:00Z', '2026-08-03T00:00:00Z')).toEqual([]);
  });

  it('requires both ends', () => {
    expect(validateTimeWindow('', '')).toHaveLength(2);
  });

  it('requires the end to be after the start', () => {
    const issues = validateTimeWindow('2026-08-03T00:00:00Z', '2026-08-01T00:00:00Z');
    expect(issues[0]?.field).toBe('end_time');
    expect(issues[0]?.message).toMatch(/after the start time/i);
  });

  it(`rejects a window longer than ${MAX_WINDOW_DAYS} days`, () => {
    const issues = validateTimeWindow('2026-08-01T00:00:00Z', '2026-09-15T00:00:00Z');
    expect(issues[0]?.message).toMatch(/above the 30-day limit/i);
  });
});

describe('datetime-local round trip', () => {
  it('adds seconds and the Z suffix the API requires', () => {
    expect(localInputToIso('2026-08-01T00:00')).toBe('2026-08-01T00:00:00Z');
    expect(localInputToIso('')).toBe('');
  });

  it('strips them again for the input element', () => {
    expect(isoToLocalInput('2026-08-01T00:00:00Z')).toBe('2026-08-01T00:00');
    expect(isoToLocalInput(null)).toBe('');
  });
});
