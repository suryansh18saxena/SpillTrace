/**
 * The published, citable text shared by the public transparency page and the
 * analyst's guide (`/help`).
 *
 * Everything here is QUOTED from a source of truth in the repository rather than
 * paraphrased, and each block names its source. Two pages quoting one module
 * means the public account and the analyst's account cannot drift apart. If a
 * source changes, change it here — and never soften a quote to make it read
 * better: the point of these strings is that they say exactly what the system
 * says about itself.
 *
 * Nothing in this file is a measurement. There are no counts, rates or results
 * here — only rules, weights and wording — so neither page needs the API.
 */

// ---------------------------------------------------------------- safeguards

export interface Safeguard {
  id: string;
  /** Verbatim from docs/REQUIREMENTS.md §7 (PRD Part K). Do not edit. */
  rule: string;
  /** A plain-language gloss for a non-specialist reader. */
  plain: string;
  /**
   * How the rule is actually held — from REQUIREMENTS.md §7 "Enforcement",
   * docs/FINAL_AUDIT.md "Things we said we would not do", docs/SECURITY.md,
   * docs/AIS_PIPELINE.md and the scoring/drift/provenance modules named inline.
   */
  enforcement: string;
}

/**
 * CON-001…CON-009. The `rule` strings are the requirement register's own words.
 * CON-001 and CON-003 therefore contain "responsible" and "88% legal
 * probability" — inside the negations that forbid them. That is deliberate:
 * a constraint quoted "nicely" is no longer the constraint.
 */
export const SAFEGUARDS: readonly Safeguard[] = [
  {
    id: 'CON-001',
    rule: 'We will not say the nearest vessel is automatically responsible.',
    plain: 'Being closest to where the oil came from is never treated as being its source.',
    enforcement:
      'Built into the arithmetic: with no time overlap a candidate’s score cannot exceed 0.79, just under the 0.80 HIGH edge. When the evidence cannot tell candidates apart, every label is capped at MODERATE with a note saying why. Every candidate list carries the proximity notice, and generated text is checked against a list of forbidden phrases by test.',
  },
  {
    id: 'CON-002',
    rule: 'We will not treat an AIS gap as proof of illegal activity.',
    plain:
      'A vessel that stopped reporting its position has not, for that reason, done anything wrong.',
    enforcement:
      'A reporting gap lowers the AIS-reliability factor, which can only reduce a candidate’s score. Only a gap of 12 hours or more, starting over 50 nautical miles from shore where reception is adequate, may be surfaced at all — and the AIS-gap notice is attached wherever a gap is shown.',
  },
  {
    id: 'CON-003',
    rule: 'We will not call an 88% score an 88% legal probability unless scientifically calibrated.',
    plain: 'A score ranks leads on a 0–1 scale. It is not the chance that anything happened.',
    enforcement:
      'Scores are shown as 0–1 with two decimals, never as a percentage. Every score carries the score notice, and the exact weights are stored with each result under a scoring version so the number is always attributable to a model.',
  },
  {
    id: 'CON-004',
    rule: 'We will not expose AIS/API keys in the frontend.',
    plain: 'The credentials used to fetch satellite, ocean and vessel data never reach a browser.',
    enforcement:
      'The browser talks only to the SPILLTRACE API. A content-security policy pins where the page may connect, and a build check (make audit-secrets) scans the source and the built client bundle for credential-shaped names.',
  },
  {
    id: 'CON-005',
    rule: 'We will not store huge GeoTIFF/NetCDF files directly inside PostgreSQL.',
    plain:
      'Large imagery and model files live in object storage; the database keeps references to them.',
    enforcement:
      'Rasters, NetCDF fields and reports are written to S3-compatible object storage. PostgreSQL holds only metadata, the storage address and a SHA-256 checksum. Held by schema review.',
  },
  {
    id: 'CON-006',
    rule: 'We will not start by building a huge global real-time system.',
    plain: 'Each investigation is bounded to one area of sea and one window of time.',
    enforcement:
      'Every case is an area of interest pinned to a time window, validated and size-capped at the edge. Imagery, ocean data and vessel positions are fetched for that area and window only.',
  },
  {
    id: 'CON-007',
    rule: 'We will not claim public AIS coverage is complete for every Indian-water scenario.',
    plain: '“No vessel was seen” is not the same as “no vessel was there”.',
    enforcement:
      'Every AIS-derived view carries the coverage notice, and the observed reception density is recorded per case so an analyst can tell an empty sea from a blind spot.',
  },
  {
    id: 'CON-008',
    rule: 'Origin region is a probability region, never presented as an exact discharge coordinate.',
    plain:
      'The system points to an area, with the uncertainty drawn in — never to a spot on the map.',
    enforcement:
      'The drift stage outputs nested 50%, 75% and 90% contours built from back-tracked particle density; no code path emits a discharge point, and the origin-region notice travels with every region.',
  },
  {
    id: 'CON-009',
    rule: 'Synthetic/demo data is always visibly labelled and never presented as a real-world observation.',
    plain: 'Anything generated for testing or demonstration says so, everywhere it appears.',
    enforcement:
      'Every artifact carries a provenance field — REAL, SYNTHETIC or MIXED. Synthetic vessel names end in “(SYNTHETIC)”, the label is shown beside every artifact, and the synthetic notice leads the evidence report’s limitations.',
  },
];

// ------------------------------------------------------------------- scoring

/** `SCORING_VERSION` in backend/src/spilltrace/core/scoring/model.py (SCORE-008). */
export const SCORING_VERSION = 'prd-j-v1';

export interface ScoreFactor {
  key: string;
  /** `FACTOR_LABELS` in core/scoring/model.py. */
  label: string;
  /** `ScoringWeights` defaults in core/scoring/model.py — PRD Part J. */
  weight: number;
  /** "PRD meaning" column of REQUIREMENTS.md §6 (SCORE-001…006). */
  meaning: string;
}

/** In PRD order, heaviest first — the order the product renders them. */
export const SCORE_FACTORS: readonly ScoreFactor[] = [
  {
    key: 'origin_proximity',
    label: 'Origin proximity',
    weight: 0.35,
    meaning: 'The vessel was close to the high-probability origin area.',
  },
  {
    key: 'time_match',
    label: 'Time match',
    weight: 0.2,
    meaning: 'The vessel was there during the inferred discharge window.',
  },
  {
    key: 'trajectory_match',
    label: 'Trajectory match',
    weight: 0.15,
    meaning: 'The vessel’s path is consistent with entering or leaving the origin.',
  },
  {
    key: 'heading_match',
    label: 'Heading match',
    weight: 0.1,
    meaning: 'Its direction is compatible with the movement of the event.',
  },
  {
    key: 'speed_match',
    label: 'Speed match',
    weight: 0.1,
    meaning: 'Its speed is plausible for the event.',
  },
  {
    key: 'ais_reliability',
    label: 'AIS reliability',
    weight: 0.1,
    meaning: 'How complete and clean its AIS history is. Gaps lower confidence.',
  },
];

/**
 * Band edges — `CONFIDENCE_MODERATE_MIN` / `CONFIDENCE_HIGH_MIN` in
 * core/scoring/model.py, the same numbers `ScoreMeter` draws. Re-declared
 * rather than imported from ScoreMeter because that is a client module: a
 * server component importing a constant from it would receive a client
 * reference, not the number.
 */
export const BAND_MODERATE_MIN = 0.45;
export const BAND_HIGH_MIN = 0.8;

export type Band = 'LOW' | 'MODERATE' | 'HIGH';

/** Half-open, non-overlapping and exhaustive — `confidence_label()` in model.py. */
export function bandFor(score: number): Band {
  const value = Math.max(0, Math.min(1, score));
  if (value >= BAND_HIGH_MIN) return 'HIGH';
  if (value >= BAND_MODERATE_MIN) return 'MODERATE';
  return 'LOW';
}

/** Verbatim from `DESCRIPTION` in components/attribution/ConfidenceBadge.tsx. */
export const BAND_MEANINGS: Record<Band, string> = {
  LOW: 'Weak investigative signal — this candidate needs corroborating evidence.',
  MODERATE: 'Moderate investigative signal — worth further enquiry.',
  HIGH: 'Strong investigative signal — prioritise for further enquiry. Not proof of responsibility.',
};

/**
 * The most a candidate with `time_match = 0` can score, from the arithmetic in
 * core/scoring/model.py (`CONFIDENCE_HIGH_MIN` docstring):
 * 0.35 + 0.15 + 0.10 × 0.90 + 0.10 + 0.10 = 0.79 — the 0.90 being the
 * deliberate cap on the heading factor. It sits just below the HIGH edge.
 */
export const NO_TIME_OVERLAP_CEILING = 0.79;

/** PRD Part J, quoted verbatim in REQUIREMENTS.md §6. */
export const PRD_CALIBRATION_QUOTE =
  'Initial weights are engineering defaults for the prototype, not scientifically validated legal probabilities. They must be calibrated on labelled/validated cases.';

// ------------------------------------------------------ mandated disclaimers

/**
 * Verbatim from backend/src/spilltrace/core/disclaimers.py. The server attaches
 * these to live responses; they are reproduced here so a reader can see the
 * exact wording before meeting it on a result.
 */
export const DISCLAIMERS = {
  attribution:
    'Attribution is investigative/probabilistic evidence and is not automatic legal proof.',
  score:
    'This score combines six weighted evidence factors using prototype engineering weights. It is not a calibrated legal probability and must not be read as one.',
  originRegion:
    'The origin region is a probability region derived from reverse drift simulation. It indicates where a discharge was more likely to have occurred; it is not an exact discharge coordinate.',
  aisGap:
    'A gap in AIS reporting is not evidence of wrongdoing. Gaps are commonly caused by satellite revisit intervals, terrestrial receiver coverage, signal interference in busy waters, and equipment faults.',
  proximity:
    'Proximity to the origin region does not by itself indicate responsibility. Candidates are ranked to prioritise further investigation, not to assign blame.',
  aisCoverage:
    'AIS coverage is not complete. Vessels may be absent from this dataset because they were outside receiver coverage, because their transmissions collided with others, or because they do not carry AIS. Absence of a vessel is not evidence of absence.',
  detection:
    'Automated detection identifies oil-like surface features in SAR imagery. Dark features may also be produced by low wind, biogenic films, rain cells and other natural phenomena; see the look-alike verification result.',
  synthetic:
    'SYNTHETIC DEMONSTRATION DATA — generated deterministically by SPILLTRACE for development and demonstration. It does not represent any real vessel, spill, satellite observation or environmental measurement.',
} as const;

/** `REPORT_LIMITATIONS` in disclaimers.py — in its order (AC-12). */
export const REPORT_LIMITATIONS: readonly string[] = [
  DISCLAIMERS.attribution,
  DISCLAIMERS.score,
  DISCLAIMERS.originRegion,
  DISCLAIMERS.aisGap,
  DISCLAIMERS.proximity,
  DISCLAIMERS.aisCoverage,
  DISCLAIMERS.detection,
];

/**
 * The attribution the Copernicus Marine licence requires (docs/DECISIONS.md
 * AD-17; `ATTRIBUTION` in adapters/environmental/cmems.py). Must appear
 * wherever Copernicus Marine data is credited.
 */
export const CMEMS_ATTRIBUTION = 'Generated using E.U. Copernicus Marine Service Information';
