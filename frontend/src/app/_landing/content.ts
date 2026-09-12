/**
 * Every claim on the public landing page, in one place, with its source.
 *
 * Nothing here is an estimate or a projection. Demonstration figures describe the
 * seeded `kutch-01` case (seed 42, scoring `prd-j-v1`) on a clean database — see
 * `DEMO_CANDIDATES` for how they were cross-checked. If the scenario or the
 * scoring changes they must be re-checked: they are quoted, not computed,
 * because the landing page is public and cannot call the authenticated API.
 */

export interface Stage {
  job: string;
  name: string;
  text: string;
}

/**
 * The 13 pipeline stages, in the order the DAG actually executes them.
 *
 * `env.fetch` sits before `detect.verify`, which is *not* the order the problem
 * statement lists: verification needs the wind reading to apply its strongest
 * physical rule, so the dependency graph wins over the narrative order
 * (docs/DECISIONS.md AD-30).
 */
export const STAGES: Stage[] = [
  {
    job: 'scene.search',
    name: 'Find the radar scene',
    text: 'Search the Copernicus catalogue for Sentinel-1 SAR scenes covering the area and time window.',
  },
  {
    job: 'scene.download',
    name: 'Fetch the product',
    text: 'Pull the per-band Cloud-Optimised GeoTIFFs rather than the whole archive, and checksum them.',
  },
  {
    job: 'sar.preprocess',
    name: 'Prepare the imagery',
    text: 'Calibrate to dB, clip per scene, standardise, mask no-data and tile for the model.',
  },
  {
    job: 'ml.detect',
    name: 'Detect oil-like slicks',
    text: 'A U-Net produces a per-pixel oil probability field, blended across tile seams.',
  },
  {
    job: 'env.fetch',
    name: 'Load wind and current',
    text: 'Hourly Copernicus Marine surface current and 10 m wind for the event time and place.',
  },
  {
    job: 'detect.verify',
    name: 'Rule out look-alikes',
    text: 'Low wind, biogenic films and rain cells look identical on radar. Seven physical rules each report what they saw.',
  },
  {
    job: 'drift.hindcast',
    name: 'Run drift backwards',
    text: 'Thousands of particles integrated in reverse under wind and current, as a seeded ensemble.',
  },
  {
    job: 'ais.ingest',
    name: 'Pull AIS traffic',
    text: 'Vessel position and static messages for the origin bounding box and time window.',
  },
  {
    job: 'ais.clean',
    name: 'Clean the tracks',
    text: 'Duplicates, impossible jumps and bad timestamps are flagged — and kept, never deleted.',
  },
  {
    job: 'traj.build',
    name: 'Build trajectories',
    text: 'Time-ordered track segments per vessel, split on reporting gaps, with quality statistics.',
  },
  {
    job: 'correlate',
    name: 'Find candidates',
    text: 'Vessels compatible with the origin region in both space and time, each with a stated reason.',
  },
  {
    job: 'score',
    name: 'Score and rank',
    text: 'Six independent factors, weighted, explained one by one — and capped when they cannot separate.',
  },
  {
    job: 'report.build',
    name: 'Package the evidence',
    text: 'Every artifact, source, model version, seed and checksum, with the limitations stated up front.',
  },
];

/** Read from `docs/REQUIREMENTS.md` §7 — the nine constraints, faithfully. */
export const SAFEGUARDS = [
  {
    id: 'CON-001',
    title: 'The nearest vessel is not automatically responsible',
    body: 'When the evidence cannot separate candidates, every label is capped instead of naming a wall of suspects.',
  },
  {
    id: 'CON-002',
    title: 'An AIS gap is not proof of illegal activity',
    body: 'A gap lowers confidence in a track. It can never raise a vessel’s score.',
  },
  {
    id: 'CON-003',
    title: 'A score is not a legal probability',
    body: 'Weights are versioned prototype defaults, stored with every result, to be calibrated before any legal use.',
  },
  {
    id: 'CON-004',
    title: 'No provider key ever reaches the browser',
    body: 'Every credential stays server-side; the browser may only talk to SPILLTRACE’s own API.',
  },
  {
    id: 'CON-005',
    title: 'Heavy rasters stay out of the database',
    body: 'GeoTIFF and NetCDF live in object storage; PostgreSQL holds their checksums and metadata.',
  },
  {
    id: 'CON-006',
    title: 'Scoped, not a global surveillance system',
    body: 'An investigation starts from a case: one area of interest, one time window.',
  },
  {
    id: 'CON-007',
    title: 'Public AIS coverage is not complete',
    body: 'Absence of a vessel is not evidence of absence — coverage is recorded, not assumed.',
  },
  {
    id: 'CON-008',
    title: 'The origin is a region, never a coordinate',
    body: 'Nested 90 / 75 / 50 % probability contours with a stated confidence. No code path emits a point.',
  },
  {
    id: 'CON-009',
    title: 'Synthetic data can never pass as real',
    body: 'REAL / SYNTHETIC / MIXED provenance travels on every row, response and report.',
  },
];

export interface DemoCandidate {
  rank: number;
  name: string;
  score: number;
  meta: string;
  highlight?: boolean;
}

/**
 * The seeded demonstration case `kutch-01` (seed 42, scoring `prd-j-v1`) as it
 * runs on a clean database: 6 vessels seeded, 4 ranked, 2 excluded.
 *
 * Careful when re-reading these from a running system: AIS is queried by region
 * and time, so any *other* case covering the same window (a dev database with
 * a second Gulf of Kutch case, say) adds its vessels to this one's candidate
 * list and can change the ranks and trip the discrimination cap. The per-vessel
 * factor scores do not change, which is how these were cross-checked:
 * MATSYA VII = 0.35·0.960 + 0.20·1.000 + 0.15·1.000 + 0.10·0.587 + 0.10·0.990
 * + 0.10·0.448 = 0.8885.
 *
 * Rank 3 is the argument — a perfect time and trajectory match, ranked below two
 * others because a 14.1 h reporting gap lowers its AIS reliability to 0.448.
 * Names keep "(SYNTHETIC)" as everywhere (CON-009).
 */
export const DEMO_CANDIDATES: DemoCandidate[] = [
  {
    rank: 1,
    name: 'SAGAR PRABHA (SYNTHETIC)',
    score: 0.9546,
    meta: 'origin 0.960 · time 1.000 · AIS reliability 0.820',
  },
  {
    rank: 2,
    name: 'EASTERN ORCHID (SYNTHETIC)',
    score: 0.9274,
    meta: 'origin 0.960 · time 1.000 · AIS reliability 0.776',
  },
  {
    rank: 3,
    name: 'MATSYA VII (SYNTHETIC)',
    score: 0.8885,
    meta: '0.0 km from origin · perfect time & track · 14.1 h gap → AIS reliability 0.448',
    highlight: true,
  },
  {
    rank: 4,
    name: 'ATLANTIC MERIDIAN (SYNTHETIC)',
    score: 0.686,
    meta: 'origin 0.525 · trajectory 0.350 · AIS reliability 0.817',
  },
];

/** Verified counts. `tests` = 640 backend (pytest collection) + 154 frontend (vitest), 2026-09-11. */
export const PROOF = [
  { value: 13, label: 'pipeline stages', source: 'each a tracked, re-runnable job' },
  {
    value: 7,
    label: 'look-alike rules',
    source: 'wind, contrast, shape, elongation, power ratio, area, border',
  },
  {
    value: 6,
    label: 'explainable factors',
    source: 'weighted, stored and explained per candidate',
  },
  { value: 794, label: 'automated tests', source: '640 backend · 154 frontend' },
];

export const SOURCES = [
  'Sentinel-1 SAR',
  'Copernicus Data Space',
  'Copernicus Marine',
  'AISStream',
  'U-Net segmentation',
  'Reverse drift ensemble',
  'PostGIS',
  'MapLibre GL',
  'FastAPI',
  'PyTorch',
  'OpenDrift',
  'rasterio',
  'shapely 2',
  'Redis',
  'MinIO',
  'Next.js 15',
];

export const LOOKALIKE_RULES = [
  'Wind conditions',
  'Contrast',
  'Shape complexity',
  'Elongation',
  'Power ratio',
  'Area',
  'Border gradient',
];
