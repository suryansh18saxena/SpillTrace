/**
 * The scene's world model, in kilometres.
 *
 * x runs east, z runs south (three.js +z faces the default camera), y is up.
 * One unit is one kilometre, so drift displacements can use the run's real
 * wind and current values directly and the geometry stays honest to the case.
 *
 * Figures come from the seeded `kutch-01` run — see `../content.ts`.
 */

import { mulberry32 } from '../timeline';

/** Metres per degree at ~22.5 °N, for the HUD's coordinate readout. */
export const KM_PER_DEG_LON = 102.9;
export const KM_PER_DEG_LAT = 111.0;
export const AOI_CENTER_LON = 69.5;
export const AOI_CENTER_LAT = 22.5;

export function worldToLonLat(x: number, z: number): [lon: number, lat: number] {
  return [AOI_CENTER_LON + x / KM_PER_DEG_LON, AOI_CENTER_LAT - z / KM_PER_DEG_LAT];
}

/** 1.8° × 1.2° AOI ≈ 185 km × 133 km, centred on the slick. */
export const AOI = { minX: -92, maxX: 92, minZ: -66, maxZ: 66 };

/**
 * The detected slick: 85.3 km² at 7.6 : 1 elongation → semi-axes ≈ 21 × 2.8 km
 * (π · 21 · 2.8 ≈ 185 km² for the smooth ellipse; the shader's noisy boundary
 * and damping profile bring the visible dark core close to the run's area).
 */
export const SLICK = { center: [0, 0] as const, a: 21, b: 2.8, rot: -0.55 };

/** Mean fields from the run, converted to world axes (x = east, z = −north). */
export const WIND = { x: 4.26, z: -3.29 }; // 5.4 m/s
export const CURRENT = { x: 0.3, z: 0.075 }; // 0.31 m/s

export const DRIFT_HOURS = 18;
export const WIND_DRIFT_FACTOR = 0.03;
export const WIND_DRIFT_SIGMA = 0.01;
export const DIFFUSIVITY = 10; // m²/s

/** Where the ensemble mean lands after 18 h backwards: −(current + α·wind) · 3.6 · 18. */
export const ORIGIN_CENTER = (() => {
  const s = 3.6 * DRIFT_HOURS;
  return {
    x: -(CURRENT.x + WIND_DRIFT_FACTOR * WIND.x) * s,
    z: -(CURRENT.z + WIND_DRIFT_FACTOR * WIND.z) * s,
  };
})();

/** 522 km² outer contour → semi-axes 16.5 × 10.1 km; nested 75 % and 50 % inside. */
export const ORIGIN = { a: 16.5, b: 10.1, rot: 0.12, levels: [1, 0.72, 0.46] as const };

export interface VesselPath {
  key: string;
  /** Waypoints in km. */
  points: readonly (readonly [number, number])[];
  /** Path parameter (0 = T−18 h, 1 = acquisition) at each waypoint. */
  knots: readonly number[];
  /** Portions of the track with no AIS reports, as [from, to] in path parameter. */
  gaps?: readonly (readonly [number, number])[];
  /** Path parameter at closest approach, where the vessel holds during attribution. */
  holdAt: number;
}

const O = ORIGIN_CENTER;

/**
 * Tracks laid out so each vessel does what its record says: two pass through
 * the origin region inside the window, one passes through with a 14 h gap,
 * one skims 3.4 km outside, one crosses only after the window, one stays
 * 80 km east. Shapes are illustrative; the relations are the run's.
 */
export const VESSEL_PATHS: VesselPath[] = [
  {
    key: 'sagar',
    points: [
      [-98, 44],
      [O.x, O.z],
      [30, -22],
      [86, -54],
    ],
    knots: [0, 0.247, 0.62, 1],
    holdAt: 0.247,
  },
  {
    key: 'orchid',
    points: [
      [-62, -62],
      [O.x, O.z],
      [-12, 62],
    ],
    knots: [0, 0.33, 1],
    holdAt: 0.33,
  },
  {
    key: 'matsya',
    points: [
      [-40, 10],
      [O.x, O.z],
      [-6, -6],
      [20, 8],
      [46, 20],
    ],
    knots: [0, 0.011, 0.3, 0.7, 1],
    gaps: [[0.06, 0.84]],
    holdAt: 0.011,
  },
  {
    key: 'meridian',
    points: [
      [-90, -46],
      [O.x, O.z - ORIGIN.b - 3.35],
      [52, 22],
    ],
    knots: [0, 0.128, 1],
    holdAt: 0.128,
  },
  {
    key: 'straits',
    points: [
      [60, -122],
      [O.x, O.z],
    ],
    knots: [0, 1.083],
    holdAt: 0.55,
  },
  {
    key: 'halcyon',
    points: [
      [58, -64],
      [88, -18],
      [94, 42],
    ],
    knots: [0, 0.5, 1],
    holdAt: 0.5,
  },
];

/** Position along a path at parameter `u`, extrapolating linearly past the ends. */
export function pathPositionAt(path: VesselPath, u: number): [number, number] {
  const { points, knots } = path;
  const last = points.length - 1;
  if (u <= knots[0]!) return [points[0]![0], points[0]![1]];
  for (let i = 0; i < last; i += 1) {
    const k0 = knots[i]!;
    const k1 = knots[i + 1]!;
    if (u <= k1 || i === last - 1) {
      const t = (u - k0) / (k1 - k0);
      const p0 = points[i]!;
      const p1 = points[i + 1]!;
      return [p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t];
    }
  }
  return [points[last]![0], points[last]![1]];
}

/** Sample a path into `n` points between parameters `from` and `to`. */
export function samplePath(path: VesselPath, n = 64, from = 0, to = 1): [number, number, number][] {
  const out: [number, number, number][] = [];
  for (let i = 0; i < n; i += 1) {
    const u = from + ((to - from) * i) / (n - 1);
    const [x, z] = pathPositionAt(path, u);
    out.push([x, 0.25, z]);
  }
  return out;
}

/** Faint ambient traffic that never leaves the AOI — decoration, not data. */
export function ambientTracks(count: number, seed = 7): [number, number, number][][] {
  const rand = mulberry32(seed);
  const tracks: [number, number, number][][] = [];
  for (let i = 0; i < count; i += 1) {
    const edge = Math.floor(rand() * 4);
    const t0 = rand();
    const t1 = rand();
    const start: [number, number] =
      edge === 0
        ? [AOI.minX, AOI.minZ + (AOI.maxZ - AOI.minZ) * t0]
        : edge === 1
          ? [AOI.maxX, AOI.minZ + (AOI.maxZ - AOI.minZ) * t0]
          : edge === 2
            ? [AOI.minX + (AOI.maxX - AOI.minX) * t0, AOI.minZ]
            : [AOI.minX + (AOI.maxX - AOI.minX) * t0, AOI.maxZ];
    const end: [number, number] = [
      AOI.minX + (AOI.maxX - AOI.minX) * t1,
      AOI.minZ + (AOI.maxZ - AOI.minZ) * ((t0 + t1 * 0.6) % 1),
    ];
    const bend = (rand() - 0.5) * 30;
    const pts: [number, number, number][] = [];
    for (let k = 0; k < 24; k += 1) {
      const t = k / 23;
      const x = start[0] + (end[0] - start[0]) * t + Math.sin(t * Math.PI) * bend;
      const z = start[1] + (end[1] - start[1]) * t + Math.sin(t * Math.PI * 0.5) * bend * 0.4;
      pts.push([x, 0.18, z]);
    }
    tracks.push(pts);
  }
  return tracks;
}
