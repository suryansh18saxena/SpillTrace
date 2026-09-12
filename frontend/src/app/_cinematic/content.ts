/**
 * Every figure on the cinematic landing page, with its source.
 *
 * All numbers are quoted from one run of the seeded demonstration case
 * `kutch-01` (seed 42, scoring `prd-j-v1`) on a clean database — the same
 * run `_landing/content.ts` documents. Nothing here is an estimate: if the
 * scenario or the scoring changes, these must be re-read from the API.
 *
 * Every vessel name carries "(SYNTHETIC)" and the scene is labelled as a
 * demonstration throughout (CON-009).
 */

import { DEMO_CANDIDATES, SAFEGUARDS } from '../_landing/content';

export { DEMO_CANDIDATES, SAFEGUARDS };

export const CASE = {
  ref: 'ST-2026-0001',
  scenario: 'kutch-01',
  seed: 42,
  region: 'Gulf of Kutch — Arabian Sea',
  acquisition: '2026-08-14 01:12 UTC',
  sensor: 'Sentinel-1 IW GRD',
  /** AOI bbox from the scenario: 68.6–70.4 °E, 21.9–23.1 °N. */
  aoi: 'AOI 68.6°E – 70.4°E · 21.9°N – 23.1°N',
  provenance: 'SYNTHETIC',
};

export const DETECTION = {
  areaKm2: 85.3,
  perimeterKm: 90.3,
  maxProbability: 0.999,
  meanProbability: 0.71,
  threshold: 0.5,
  contrastDb: -13.2,
  elongation: 7.6,
  complexity: 2.76,
  verification: 'VERIFIED',
  verificationConfidence: 0.907,
  windMs: 5.4,
  rulesPassed: 7,
  rulesTotal: 7,
};

export const ENVIRONMENT = {
  windMs: 5.4,
  currentMs: 0.31,
  source: 'Copernicus Marine (synthetic twin)',
};

export const DRIFT = {
  engine: 'analytical Lagrangian',
  mode: 'BACKWARD',
  particles: 6000,
  ensembles: 6,
  hours: 18,
  stepSeconds: 900,
  windDriftFactor: 0.03,
  windDriftSigma: 0.01,
  diffusivity: 10,
  originAreaKm2: 522.3,
  originConfidence: 0.633,
  windowStart: '13 Aug 08:57 UTC',
  windowEnd: '13 Aug 13:42 UTC',
};

export interface VesselRecord {
  key: string;
  name: string;
  mmsi: number;
  type: string;
  flag: string;
  lengthM: number;
  /** Rank in the seeded run, or `null` when correctly excluded. */
  rank: number | null;
  score: number | null;
  band: 'HIGH' | 'MODERATE' | 'LOW' | null;
  closestKm: number | null;
  closestAt: string | null;
  note: string;
}

/** The six seeded vessels, in the order the scene draws them. */
export const VESSELS: VesselRecord[] = [
  {
    key: 'sagar',
    name: 'SAGAR PRABHA (SYNTHETIC)',
    mmsi: 419008412,
    type: 'Tanker',
    flag: 'India',
    lengthM: 183,
    rank: 1,
    score: 0.9546,
    band: 'HIGH',
    closestKm: 0.0,
    closestAt: '13 Aug 11:39 UTC',
    note: 'Inside the origin region during the inferred window; continuous AIS.',
  },
  {
    key: 'orchid',
    name: 'EASTERN ORCHID (SYNTHETIC)',
    mmsi: 477203900,
    type: 'Cargo',
    flag: 'Hong Kong',
    lengthM: 229,
    rank: 2,
    score: 0.9274,
    band: 'HIGH',
    closestKm: 0.0,
    closestAt: '13 Aug 13:09 UTC',
    note: 'Inside the origin region during the inferred window.',
  },
  {
    key: 'matsya',
    name: 'MATSYA VII (SYNTHETIC)',
    mmsi: 419002315,
    type: 'Fishing',
    flag: 'India',
    lengthM: 24,
    rank: 3,
    score: 0.8885,
    band: 'HIGH',
    closestKm: 0.0,
    closestAt: '13 Aug 07:24 UTC',
    note: 'Perfect time and track match — ranked third because a 14.1 h reporting gap lowers AIS reliability to 0.448.',
  },
  {
    key: 'meridian',
    name: 'ATLANTIC MERIDIAN (SYNTHETIC)',
    mmsi: 636019284,
    type: 'Tanker',
    flag: 'Liberia',
    lengthM: 250,
    rank: 4,
    score: 0.686,
    band: 'MODERATE',
    closestKm: 3.35,
    closestAt: '13 Aug 09:30 UTC',
    note: 'Passes 3.4 km outside the origin region.',
  },
  {
    key: 'straits',
    name: 'STRAITS VOYAGER (SYNTHETIC)',
    mmsi: 563145700,
    type: 'Tanker',
    flag: 'Singapore',
    lengthM: 176,
    rank: null,
    score: null,
    band: null,
    closestKm: null,
    closestAt: null,
    note: 'Crosses the region — 13 hours outside the inferred window. Excluded.',
  },
  {
    key: 'halcyon',
    name: 'PACIFIC HALCYON (SYNTHETIC)',
    mmsi: 538008122,
    type: 'Cargo',
    flag: 'Marshall Islands',
    lengthM: 199,
    rank: null,
    score: null,
    band: null,
    closestKm: null,
    closestAt: null,
    note: 'Transits about 80 km east of the region. Excluded.',
  },
];

export const CANDIDATES = VESSELS.filter((v) => v.rank !== null).sort(
  (a, b) => (a.rank ?? 0) - (b.rank ?? 0),
);

export interface Factor {
  key: string;
  label: string;
  plain: string;
  weight: number;
  /** MATSYA VII's factor score in the seeded run (cross-checked in _landing/content.ts). */
  value: number;
}

/**
 * The six scoring factors with their versioned weights, and MATSYA VII's
 * values — the candidate whose breakdown makes the point: a perfect time and
 * track match still ranks third, because the one factor it fails is the one
 * that measures what the system could not see.
 *
 * 0.35·0.960 + 0.20·1.000 + 0.15·1.000 + 0.10·0.587 + 0.10·0.990 + 0.10·0.448 = 0.8885
 */
export const FACTORS: Factor[] = [
  { key: 'origin', label: 'Origin proximity', plain: 'Spatial fit', weight: 0.35, value: 0.96 },
  { key: 'time', label: 'Time match', plain: 'Temporal fit', weight: 0.2, value: 1.0 },
  { key: 'traj', label: 'Trajectory match', plain: 'Track fit', weight: 0.15, value: 1.0 },
  {
    key: 'heading',
    label: 'Heading match',
    plain: 'Drift compatibility',
    weight: 0.1,
    value: 0.587,
  },
  { key: 'speed', label: 'Speed match', plain: 'Vessel behaviour', weight: 0.1, value: 0.99 },
  { key: 'ais', label: 'AIS reliability', plain: 'Data quality', weight: 0.1, value: 0.448 },
];

export const EXPLAINED_VESSEL = VESSELS[2]!;
export const EXPLAINED_TOTAL = 0.8885;

export const TECH_LABELS = ['SAR', 'AIS', 'DRIFT', 'TRAJECTORY', 'ATTRIBUTION'] as const;

export const HERO = {
  title: 'SPILLTRACE',
  line1: 'Trace the spill.',
  line2: 'Find the source.',
  lede: 'AI-powered maritime intelligence for detecting, reconstructing and attributing oil spills from satellite and vessel data.',
  primary: 'Start investigation',
  secondary: 'Explore how it works',
};

export const FINAL = {
  line1: 'Trace the spill.',
  line2: 'Find the source.',
  lede: 'Open a case and watch the whole chain run on the seeded demonstration — no accounts, no keys. Every result it produces is labelled SYNTHETIC.',
  primary: 'Start an investigation',
  secondary: 'View system architecture',
};

export const DISCLAIMER =
  'Investigative, probabilistic evidence — never automatic legal proof. Nearest is not a verdict. An AIS gap is not evidence of wrongdoing. A score of 0.95 is not a 95 % probability.';
