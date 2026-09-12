/**
 * Pure derivations shared by the overview screens.
 *
 * Everything here is computed from API responses already in memory — no
 * estimate, projection or placeholder number is ever produced. Where a value
 * cannot be computed (no data yet), functions return `null` so the UI can say
 * "unknown" instead of printing a zero that would be a false statement.
 */

import type { CaseBundle } from '@/lib/api/aggregate';
import type {
  Attribution,
  AttributionFactor,
  Case,
  ConfidenceLabel,
  SpillDetection,
  Vessel,
} from '@/lib/api/types';
import { formatOrdinal, formatScore } from '@/lib/format';

// ------------------------------------------------------------------ statuses

export const CASE_STATUS_ORDER = ['DRAFT', 'QUEUED', 'RUNNING', 'COMPLETED', 'FAILED', 'ARCHIVED'];

export function caseStatusCounts(cases: readonly Case[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of cases) counts[item.status] = (counts[item.status] ?? 0) + 1;
  return counts;
}

// ------------------------------------------------------------ time buckets

export interface TimeBucket {
  key: string;
  start: number;
  label: string;
  detail: string;
  value: number;
}

const DAY = 86_400_000;

function startOfWeekUtc(ms: number): number {
  const d = new Date(ms);
  const day = (d.getUTCDay() + 6) % 7; // Monday = 0
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - day);
}

/**
 * Counts per ISO week (UTC) over a fixed window ending this week, empty weeks
 * included — so a quiet period reads as quiet rather than disappearing, and a
 * single event is shown in context instead of as a lone bar.
 */
export function weeklyBuckets(timestamps: readonly number[], maxWeeks = 12): TimeBucket[] {
  const valid = timestamps.filter(Number.isFinite);
  const now = startOfWeekUtc(Date.now());
  const start = now - (maxWeeks - 1) * 7 * DAY;
  const buckets: TimeBucket[] = [];
  for (let t = start; t <= now; t += 7 * DAY) {
    const date = new Date(t);
    buckets.push({
      key: String(t),
      start: t,
      label: date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' }),
      detail: `Week of ${date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })}`,
      value: 0,
    });
  }
  for (const ts of valid) {
    const week = startOfWeekUtc(ts);
    const bucket = buckets.find((b) => b.start === week);
    if (bucket) bucket.value += 1;
  }
  return buckets;
}

// -------------------------------------------------------------- attributions

export interface CaseAttribution extends Attribution {
  caseId: string;
  caseTitle: string;
}

export function allAttributions(bundles: readonly CaseBundle[]): CaseAttribution[] {
  return bundles.flatMap((bundle) =>
    (bundle.attributions?.items ?? []).map((item) => ({
      ...item,
      caseId: bundle.case.id,
      caseTitle: bundle.case.title,
    })),
  );
}

export function confidenceCounts(items: readonly { confidence_label: ConfidenceLabel }[]) {
  const counts = { LOW: 0, MODERATE: 0, HIGH: 0 };
  for (const item of items) {
    if (item.confidence_label === 'HIGH') counts.HIGH += 1;
    else if (item.confidence_label === 'MODERATE' || item.confidence_label === 'MEDIUM')
      counts.MODERATE += 1;
    else counts.LOW += 1;
  }
  return counts;
}

/** Mean of each factor's normalised score across candidates, in weight order. */
export function meanFactorScores(items: readonly Attribution[]): AttributionFactor[] {
  const byKey = new Map<string, { factor: AttributionFactor; sum: number; n: number }>();
  for (const item of items) {
    for (const factor of item.factors) {
      const entry = byKey.get(factor.key) ?? { factor, sum: 0, n: 0 };
      entry.sum += factor.score;
      entry.n += 1;
      byKey.set(factor.key, entry);
    }
  }
  return [...byKey.values()]
    .map(({ factor, sum, n }) => ({
      ...factor,
      score: sum / n,
      contribution: (sum / n) * factor.weight,
    }))
    .sort((a, b) => b.weight - a.weight);
}

// ---------------------------------------------------------------- detections

export interface CaseDetection extends SpillDetection {
  caseId: string;
  caseTitle: string;
}

export function allDetections(bundles: readonly CaseBundle[]): CaseDetection[] {
  return bundles.flatMap((bundle) =>
    (bundle.detections?.items ?? []).map((item) => ({
      ...item,
      caseId: bundle.case.id,
      caseTitle: bundle.case.title,
    })),
  );
}

export function verificationCounts(detections: readonly SpillDetection[]) {
  const counts: Record<string, number> = {
    VERIFIED: 0,
    UNCERTAIN: 0,
    FALSE_POSITIVE: 0,
    REJECTED: 0,
    NOT_CHECKED: 0,
  };
  for (const detection of detections) {
    const status = detection.verification?.status ?? 'NOT_CHECKED';
    counts[status] = (counts[status] ?? 0) + 1;
  }
  return counts;
}

// ------------------------------------------------------ vessels across cases

export interface VesselAppearance {
  mmsi: number;
  name: string | null;
  /** A vessel id to link to (the most recent case's row). */
  vesselId: string;
  flag: string | null;
  shipType: string | null;
  /**
   * The provenance to display. When the same MMSI arrives with different
   * provenances across cases (say, one REAL and one SYNTHETIC case), it is
   * `MIXED` — never whichever happened to be seen first (CON-009).
   */
  provenance: string | undefined;
  /** Every distinct provenance this vessel's rows carried. */
  provenances: string[];
  /** Cases in which the vessel was observed in AIS. */
  observedIn: Array<{ caseId: string; caseTitle: string }>;
  /** Cases in which the vessel was ranked as a candidate, with its rank. */
  candidateIn: Array<{
    caseId: string;
    caseTitle: string;
    rank: number;
    score: number;
    band: ConfidenceLabel;
  }>;
  lastSeen: string | null;
}

/**
 * Groups vessels by MMSI across every aggregated case.
 *
 * "Candidate in N cases" is a statement about history, never a pattern of
 * guilt: a vessel on a regular route through a busy lane will reappear as a
 * candidate simply because it is often there.
 */
export function vesselAppearances(bundles: readonly CaseBundle[]): VesselAppearance[] {
  const byMmsi = new Map<number, VesselAppearance>();

  const ensure = (vessel: Pick<Vessel, 'id' | 'mmsi'> & Partial<Omit<Vessel, 'id' | 'mmsi'>>) => {
    let entry = byMmsi.get(vessel.mmsi);
    if (!entry) {
      entry = {
        mmsi: vessel.mmsi,
        name: vessel.name ?? null,
        vesselId: vessel.id,
        flag: vessel.flag_country ?? null,
        shipType: vessel.ship_type_name ?? null,
        provenance: vessel.data_provenance,
        provenances: [],
        observedIn: [],
        candidateIn: [],
        lastSeen: vessel.last_seen ?? null,
      };
      byMmsi.set(vessel.mmsi, entry);
    }
    if (vessel.data_provenance && !entry.provenances.includes(vessel.data_provenance)) {
      entry.provenances.push(vessel.data_provenance);
      entry.provenance = entry.provenances.length > 1 ? 'MIXED' : vessel.data_provenance;
    }
    if (!entry.name && vessel.name) entry.name = vessel.name;
    if (!entry.flag && vessel.flag_country) entry.flag = vessel.flag_country;
    if (!entry.shipType && vessel.ship_type_name) entry.shipType = vessel.ship_type_name;
    if (vessel.last_seen && (!entry.lastSeen || vessel.last_seen > entry.lastSeen)) {
      entry.lastSeen = vessel.last_seen;
    }
    return entry;
  };

  for (const bundle of bundles) {
    const ref = { caseId: bundle.case.id, caseTitle: bundle.case.title };
    for (const vessel of bundle.vessels?.items ?? []) {
      const entry = ensure(vessel);
      if (!entry.observedIn.some((c) => c.caseId === ref.caseId)) entry.observedIn.push(ref);
    }
    for (const attribution of bundle.attributions?.items ?? []) {
      const entry = ensure({ ...attribution.vessel, data_provenance: attribution.data_provenance });
      entry.candidateIn.push({
        ...ref,
        rank: attribution.rank,
        score: attribution.final_score,
        band: attribution.confidence_label,
      });
      if (!entry.observedIn.some((c) => c.caseId === ref.caseId)) entry.observedIn.push(ref);
    }
  }

  return [...byMmsi.values()];
}

// ---------------------------------------------------- plain-language summary

const BAND_MEANING: Record<string, string> = {
  HIGH: 'A HIGH band marks a strong lead to prioritise for further enquiry. It is not a finding, and it does not say what happened.',
  MODERATE:
    'A MODERATE band means the evidence is worth further enquiry, but it does not single this vessel out on its own.',
  MEDIUM:
    'A MODERATE band means the evidence is worth further enquiry, but it does not single this vessel out on its own.',
  LOW: 'A LOW band means the link is weak; corroborating evidence would be needed before this vessel is prioritised.',
};

const FACTOR_CONTEXT: Record<string, string> = {
  ais_reliability:
    'This factor falls when a track has reporting gaps or sparse positions. A gap in AIS reporting lowers confidence in the track; it is not evidence of wrongdoing.',
  origin_proximity:
    'Proximity to the origin probability region is one factor among six; being close does not by itself indicate involvement.',
  time_match:
    'This factor measures how well the vessel’s presence overlaps the inferred discharge window.',
  trajectory_match: 'This factor measures how well the track passes through the origin region.',
  heading_match: 'This factor compares the vessel’s heading with the drift-implied direction.',
  speed_match: 'This factor checks that the vessel’s speed is plausible for the observed slick.',
};

function lower(label: string): string {
  return label.charAt(0).toLowerCase() + label.slice(1);
}

/**
 * A plain-language reading of one candidate's score, built by fixed rules from
 * the factor data the server returned — not by a language model, and never
 * adding a fact the data does not contain.
 *
 * Vocabulary is the product's: "candidate", "investigative score", "lead",
 * "enquiry". It deliberately never describes a vessel as more than a candidate
 * (CON-001), never calls the score a probability (CON-003) and frames AIS gaps
 * as reduced confidence, not suspicion (CON-002).
 */
export function plainLanguageSummary(
  attribution: Attribution,
  all: readonly Attribution[],
): string[] {
  const name = attribution.vessel.name?.trim() || 'This unnamed vessel';
  const sentences: string[] = [];
  const band =
    attribution.confidence_label === 'MEDIUM' ? 'MODERATE' : attribution.confidence_label;

  sentences.push(
    `${name} is ranked ${formatOrdinal(attribution.rank)} of ${all.length} candidate vessel${all.length === 1 ? '' : 's'}, with an investigative score of ${formatScore(attribution.final_score)} — in the ${band} evidence-strength band.`,
  );

  // A score in a higher range than its label means the engine capped the band
  // (it could not separate the candidates). Say so, instead of leaving the
  // reader to wonder why 0.89 is "only" MODERATE.
  const rangeOf = (score: number) => (score >= 0.8 ? 2 : score >= 0.45 ? 1 : 0);
  const labelRank = band === 'HIGH' ? 2 : band === 'MODERATE' ? 1 : 0;
  if (rangeOf(attribution.final_score) > labelRank) {
    sentences.push(
      `The score alone would reach the ${rangeOf(attribution.final_score) === 2 ? 'HIGH' : 'MODERATE'} range, but the evidence band is capped at ${band}: the evidence does not separate this vessel from the other leading candidates, so the system does not single any one of them out.`,
    );
  }

  const byContribution = [...attribution.factors].sort((a, b) => b.contribution - a.contribution);
  const [first, second] = byContribution;
  if (first && second) {
    sentences.push(
      `Most of that score comes from ${lower(first.label)} (${formatScore(first.contribution)} of a possible ${formatScore(first.weight)}) and ${lower(second.label)} (${formatScore(second.contribution)} of ${formatScore(second.weight)}).`,
    );
  }

  const byShortfall = [...attribution.factors].sort(
    (a, b) => b.weight - b.contribution - (a.weight - a.contribution),
  );
  const gap = byShortfall[0];
  if (gap && gap.weight - gap.contribution >= 0.01) {
    sentences.push(
      `The largest shortfall is ${lower(gap.label)}, which delivered ${formatScore(gap.contribution)} of a possible ${formatScore(gap.weight)}.${FACTOR_CONTEXT[gap.key] ? ` ${FACTOR_CONTEXT[gap.key]}` : ''}`,
    );
  } else {
    sentences.push('Every factor delivered close to its full weight.');
  }

  const ordered = [...all].sort((a, b) => a.rank - b.rank);
  const index = ordered.findIndex((item) => item.id === attribution.id);
  const neighbour = ordered[index + 1] ?? ordered[index - 1];
  if (neighbour && Math.abs(neighbour.final_score - attribution.final_score) < 0.02) {
    sentences.push(
      `Its score is within ${formatScore(Math.abs(neighbour.final_score - attribution.final_score) || 0.01)} of the ${formatOrdinal(neighbour.rank)}-ranked candidate, so the order between the two is not meaningful on its own.`,
    );
  }

  sentences.push(BAND_MEANING[attribution.confidence_label] ?? BAND_MEANING['LOW']!);
  return sentences;
}
