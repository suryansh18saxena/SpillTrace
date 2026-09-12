'use client';

import { useState, type CSSProperties } from 'react';
import {
  BAND_HIGH_MIN,
  BAND_MODERATE_MIN,
  BarList,
  ChartFrame,
  ColumnChart,
  SegmentBar,
  StatTile,
  type ColumnDatum,
} from '@/components/charts';
import { Notice, NoticeStack } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { PageHeader } from '@/components/layout/PageHeader';
import { Reveal } from '@/components/motion/Reveal';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import {
  IconCases,
  IconChart,
  IconDroplet,
  IconFilter,
  IconGauge,
  IconShield,
  IconTarget,
} from '@/components/ui/Icons';
import { LinkButton } from '@/components/ui/LinkButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { useCaseUniverse, UNIVERSE_CASE_LIMIT } from '@/lib/api/aggregate';
import type { DataProvenance } from '@/lib/api/types';
import { cx } from '@/lib/cx';
import { formatMmsi, formatPercent, formatScore, pluralize } from '@/lib/format';
import {
  allAttributions,
  allDetections,
  confidenceCounts,
  meanFactorScores,
  verificationCounts,
  vesselAppearances,
  weeklyBuckets,
  type TimeBucket,
} from '@/lib/insights';
import layout from '@/components/layout/layout.module.css';
import styles from './analytics.module.css';

// ------------------------------------------------------------------ scope

const DAY_MS = 86_400_000;
const WEEK_MS = 7 * DAY_MS;

type RangeKey = 'all' | '30d' | '90d';

interface RangeOption {
  key: RangeKey;
  label: string;
  /** Cases opened within this many days; `null` means every loaded case. */
  days: number | null;
  /** Weekly chart window; `null` sizes it to the data (12–52 weeks). */
  weeks: number | null;
}

const RANGES: readonly RangeOption[] = [
  { key: 'all', label: 'All time', days: null, weeks: null },
  { key: '30d', label: 'Last 30 days', days: 30, weeks: 5 },
  { key: '90d', label: 'Last 90 days', days: 90, weeks: 13 },
];

/** How wide the weekly charts are. "All time" reaches back to the oldest plotted event. */
function weeksFor(option: RangeOption, timestamps: readonly number[]): number {
  if (option.weeks !== null) return option.weeks;
  const valid = timestamps.filter(Number.isFinite);
  if (valid.length === 0) return 12;
  const span = Math.floor((Date.now() - Math.min(...valid)) / WEEK_MS) + 2;
  return Math.min(52, Math.max(12, span));
}

function plotted(buckets: readonly TimeBucket[]): number {
  return buckets.reduce((sum, bucket) => sum + bucket.value, 0);
}

// ------------------------------------------------------------ vocabulary

/**
 * Look-alike outcomes in the order the rules reach them. VERIFIED means the
 * slick passed the physical checks — it does not by itself establish that a
 * discharge happened, which the server's own notice (rendered below) says.
 */
const OUTCOMES: ReadonlyArray<{ key: string; label: string; meaning: string }> = [
  { key: 'VERIFIED', label: 'Verified', meaning: 'Passed the look-alike checks' },
  { key: 'UNCERTAIN', label: 'Uncertain', meaning: 'The checks could not decide' },
  { key: 'FALSE_POSITIVE', label: 'False positive', meaning: 'Set aside as a look-alike' },
  { key: 'REJECTED', label: 'Rejected', meaning: 'Set aside by the checks' },
  { key: 'NOT_CHECKED', label: 'Not yet checked', meaning: 'No verification recorded' },
];

const BANDS = [
  {
    key: 'LOW' as const,
    label: 'Low',
    color: 'var(--confidence-1)',
    range: `below ${BAND_MODERATE_MIN.toFixed(2)}`,
    meaning: 'A weak link. Corroboration is needed before the vessel is prioritised.',
  },
  {
    key: 'MODERATE' as const,
    label: 'Moderate',
    color: 'var(--confidence-2)',
    range: `${BAND_MODERATE_MIN.toFixed(2)} to below ${BAND_HIGH_MIN.toFixed(2)}`,
    meaning: 'Worth further enquiry, but it does not single the vessel out on its own.',
  },
  {
    key: 'HIGH' as const,
    label: 'High',
    color: 'var(--confidence-3)',
    range: `${BAND_HIGH_MIN.toFixed(2)} and above`,
    meaning: 'A strong lead to prioritise for enquiry — not a finding.',
  },
];

// ---------------------------------------------------------------- scoring

function median(values: readonly number[]): number | null {
  const sorted = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (sorted.length === 0) return null;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
}

/** Band index a score reaches on the server's own edges, before any cap. */
function bandFromScore(score: number): number {
  if (score >= BAND_HIGH_MIN) return 2;
  if (score >= BAND_MODERATE_MIN) return 1;
  return 0;
}

function bandRank(label: string): number {
  if (label === 'HIGH') return 2;
  if (label === 'MODERATE' || label === 'MEDIUM') return 1;
  return 0;
}

const BIN_COUNT = 10;

/**
 * Ten equal bins over the 0–1 score scale. The last bin is closed so a score
 * of exactly 1.00 is counted. Tick text is left empty on purpose: the band
 * ruler under the chart carries the scale, so a label centred on a bin can't
 * be misread as that bin's edge.
 */
function scoreHistogram(scores: readonly number[]): ColumnDatum[] {
  const bins: ColumnDatum[] = Array.from({ length: BIN_COUNT }, (_, index) => {
    const lo = (index / BIN_COUNT).toFixed(2);
    const hi = ((index + 1) / BIN_COUNT).toFixed(2);
    return {
      key: `bin-${index}`,
      label: '',
      detail: index === BIN_COUNT - 1 ? `Scores ${lo} to ${hi}` : `Scores ${lo} to under ${hi}`,
      value: 0,
    };
  });
  for (const score of scores) {
    if (!Number.isFinite(score)) continue;
    // The epsilon keeps 0.70 (stored as 0.6999…) in the 0.70 bin.
    const index = Math.min(BIN_COUNT - 1, Math.max(0, Math.floor(score * BIN_COUNT + 1e-9)));
    bins[index]!.value += 1;
  }
  return bins;
}

/** Which band(s) a histogram bin covers, for the table view. */
function binBands(index: number): string {
  const lo = index / BIN_COUNT;
  const hi = (index + 1) / BIN_COUNT;
  const names = BANDS.filter((band, i) => {
    const from = i === 0 ? 0 : i === 1 ? BAND_MODERATE_MIN : BAND_HIGH_MIN;
    const to = i === 0 ? BAND_MODERATE_MIN : i === 1 ? BAND_HIGH_MIN : 1.0001;
    return lo < to && hi > from;
  }).map((band) => band.key);
  return names.join(' / ');
}

// ------------------------------------------------------------- provenance

const PROVENANCE_ORDER = ['REAL', 'MIXED', 'SYNTHETIC'];

function provenanceTally(values: ReadonlyArray<DataProvenance | null | undefined>) {
  const counts = new Map<string, number>();
  for (const value of values) {
    const key = value ?? '';
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  const order = (key: string) => {
    if (!key) return PROVENANCE_ORDER.length + 1;
    const index = PROVENANCE_ORDER.indexOf(key);
    return index === -1 ? PROVENANCE_ORDER.length : index;
  };
  return [...counts.entries()]
    .map(([key, count]) => ({ key, count }))
    .sort((a, b) => order(a.key) - order(b.key));
}

// ------------------------------------------------------------ small parts

function SectionHead({
  id,
  index,
  title,
  description,
}: {
  id: string;
  index: string;
  title: string;
  description: string;
}) {
  return (
    <div className={styles.sectionHead}>
      <h2 className={styles.sectionTitle} id={id}>
        <span className={styles.sectionIndex}>{index}</span>
        {title}
      </h2>
      <p className={styles.sectionDescription}>{description}</p>
    </div>
  );
}

/**
 * The three evidence-strength bands laid under the histogram's baseline.
 *
 * Its side insets mirror ColumnChart's plot padding (32 px left, 8 px right),
 * so the 0.45 and 0.80 edges sit exactly where they cut through the bins. It
 * is decorative (`aria-hidden`): the same edges are stated in the caption and
 * in the table view.
 */
function BandRuler() {
  const zones = [
    { key: 'LOW', from: 0, to: BAND_MODERATE_MIN, tone: 1 },
    { key: 'MODERATE', from: BAND_MODERATE_MIN, to: BAND_HIGH_MIN, tone: 2 },
    { key: 'HIGH', from: BAND_HIGH_MIN, to: 1, tone: 3 },
  ];
  const edges = [0, BAND_MODERATE_MIN, BAND_HIGH_MIN, 1];
  return (
    <div className={styles.ruler} aria-hidden="true">
      <div className={styles.rulerZones}>
        {zones.map((zone) => (
          <span
            key={zone.key}
            className={styles.rulerZone}
            style={
              {
                flexBasis: `${(zone.to - zone.from) * 100}%`,
                '--zone-fill': `var(--confidence-${zone.tone}-subtle)`,
                '--zone-edge': `var(--confidence-${zone.tone})`,
                '--zone-text': `var(--confidence-${zone.tone}-text)`,
              } as CSSProperties
            }
          >
            {zone.key}
          </span>
        ))}
      </div>
      <div className={styles.rulerScale}>
        {edges.map((edge) => (
          <span key={edge} style={{ left: `${edge * 100}%` }}>
            {edge === 0 || edge === 1 ? String(edge) : edge.toFixed(2)}
          </span>
        ))}
      </div>
    </div>
  );
}

function ChartSkeleton({ height = '12rem' }: { height?: string }) {
  return <Skeleton height={height} radius="var(--radius-md)" />;
}

// ------------------------------------------------------------------- page

/**
 * Analytics — trends across the analyst's investigations.
 *
 * There is no analytics endpoint: every figure is derived in the browser from
 * the same per-case responses the case pages use (`useCaseUniverse`), and every
 * chart ships its numbers as a table. What the API does not record — model
 * accuracy over time — is stated as untracked, never drawn.
 */
export default function AnalyticsPage() {
  const [range, setRange] = useState<RangeKey>('all');
  const universe = useCaseUniverse({ attributions: true, detections: true, vessels: true });

  const option = RANGES.find((item) => item.key === range) ?? RANGES[0]!;
  const cutoff = option.days === null ? null : Date.now() - option.days * DAY_MS;
  const bundles =
    cutoff === null
      ? universe.bundles
      : universe.bundles.filter((bundle) => Date.parse(bundle.case.created_at) >= cutoff);
  const cases = bundles.map((bundle) => bundle.case);

  const pending = universe.isPending;
  const details = pending || universe.isLoadingDetails;

  // --------------------------------------------------------- detections
  const detections = allDetections(bundles);
  const verification = verificationCounts(detections);
  const setAside = (verification['FALSE_POSITIVE'] ?? 0) + (verification['REJECTED'] ?? 0);
  const checked = detections.length - (verification['NOT_CHECKED'] ?? 0);
  // A share of nothing is unknown, not 0 %.
  const setAsideShare = checked > 0 ? setAside / checked : null;
  const outcomeRows = [
    ...OUTCOMES,
    ...Object.keys(verification)
      .filter((key) => !OUTCOMES.some((outcome) => outcome.key === key))
      .map((key) => ({ key, label: key, meaning: 'Status reported by the server' })),
  ].filter((row) => row.key !== 'NOT_CHECKED' || (verification['NOT_CHECKED'] ?? 0) > 0);

  // ------------------------------------------------------- attributions
  const attributions = allAttributions(bundles);
  const scores = attributions.map((item) => item.final_score);
  const bands = confidenceCounts(attributions);
  const medianScore = median(scores);
  const highShare = attributions.length > 0 ? bands.HIGH / attributions.length : null;
  const casesWithCandidates = bundles.filter(
    (bundle) => (bundle.attributions?.items.length ?? 0) > 0,
  ).length;
  // Candidates whose score reaches a higher band than the one the server gave
  // them: the discrimination check caps the band, never the score.
  const capped = attributions.filter(
    (item) => bandFromScore(item.final_score) > bandRank(item.confidence_label),
  ).length;
  const histogram = scoreHistogram(scores);
  const factors = meanFactorScores(attributions);
  const factorCounts = new Map<string, number>();
  for (const item of attributions) {
    for (const factor of item.factors) {
      factorCounts.set(factor.key, (factorCounts.get(factor.key) ?? 0) + 1);
    }
  }
  const scoringVersions = [
    ...new Set(attributions.map((item) => item.scoring_version).filter(Boolean)),
  ];

  // ------------------------------------------------------------- weekly
  const caseTimes = cases.map((item) => Date.parse(item.created_at));
  const detectionTimes = detections.map((item) => Date.parse(item.detected_at));
  const weeks = weeksFor(option, [...caseTimes, ...detectionTimes]);
  const casesWeekly = weeklyBuckets(caseTimes, weeks);
  const detectionsWeekly = weeklyBuckets(detectionTimes, weeks);
  const casesOutside = caseTimes.length - plotted(casesWeekly);
  const detectionsOutside = detectionTimes.length - plotted(detectionsWeekly);
  const windowStart = casesWeekly[0]?.detail.replace(/^Week of /, '') ?? '';

  // ------------------------------------------------------------ vessels
  const appearances = vesselAppearances(bundles);
  const frequent = appearances
    .map((vessel) => ({
      vessel,
      cases: new Set(vessel.candidateIn.map((ref) => ref.caseId)).size,
    }))
    .filter((entry) => entry.cases > 0)
    .sort(
      (a, b) =>
        b.cases - a.cases ||
        (a.vessel.name ?? `${a.vessel.mmsi}`).localeCompare(b.vessel.name ?? `${b.vessel.mmsi}`),
    )
    .slice(0, 8);
  const repeatCandidates = appearances.filter(
    (vessel) => new Set(vessel.candidateIn.map((ref) => ref.caseId)).size > 1,
  ).length;

  // --------------------------------------------------------- provenance
  const provenanceRows = [
    {
      key: 'cases',
      label: 'Cases',
      tally: provenanceTally(cases.map((item) => item.data_provenance)),
    },
    {
      key: 'detections',
      label: 'Detections',
      tally: provenanceTally(detections.map((item) => item.data_provenance)),
    },
    {
      key: 'candidates',
      label: 'Ranked candidates',
      tally: provenanceTally(attributions.map((item) => item.data_provenance)),
    },
    {
      key: 'vessels',
      label: 'Distinct vessels',
      tally: provenanceTally(appearances.map((item) => item.provenance)),
    },
  ];
  // A case labelled REAL can still hold synthetic records (e.g. a synthetic AIS
  // adapter). Each record keeps its own label; this just says so up front.
  const realWithSynthetic = bundles.filter(
    (bundle) =>
      bundle.case.data_provenance === 'REAL' &&
      [
        ...(bundle.attributions?.items ?? []).map((item) => item.data_provenance),
        ...(bundle.detections?.items ?? []).map((item) => item.data_provenance),
        ...(bundle.vessels?.items ?? []).map((item) => item.data_provenance),
      ].some((value) => value === 'SYNTHETIC' || value === 'MIXED'),
  ).length;

  // ------------------------------------------------------------ notices
  const detectionNotices = bundles.map((bundle) => bundle.detections?.notice);
  const rankingNotices = bundles.flatMap((bundle) => [
    bundle.attributions?.disclaimer,
    bundle.attributions?.score_disclaimer,
    bundle.attributions?.proximity_disclaimer,
  ]);
  const vesselNotices = bundles.map((bundle) => bundle.vessels?.notice);
  const shortfalls = new Map<string, number>();
  for (const bundle of bundles) {
    const note = bundle.attributions?.shortfall_note?.trim();
    if (note) shortfalls.set(note, (shortfalls.get(note) ?? 0) + 1);
  }

  const hasCases = universe.cases.length > 0;
  const inScope = cases.length > 0;

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        eyebrow="Overview"
        title={
          <>
            Analytics <span className={cx('serif', styles.titleAccent)}>across every case</span>
          </>
        }
        subtitle="Detections, look-alike checks, evidence strength and investigative scores across your investigations. Every figure is computed from the cases themselves; nothing here is estimated."
      />

      {/* ------------------------------------------------------ scope */}
      <div className={styles.scopeSticky}>
        <div className={styles.scopeBar}>
          <div className={styles.scopeLead}>
            <span className={styles.scopeIcon} aria-hidden="true">
              <IconFilter size={14} />
            </span>
            <span className={styles.scopeLabel} id="analytics-range-label">
              Cases opened
            </span>
            <div className={styles.segmented} role="group" aria-labelledby="analytics-range-label">
              {RANGES.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  aria-pressed={range === item.key}
                  onClick={() => setRange(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
          <p className={styles.scopeSummary} aria-live="polite">
            {pending ? (
              'Loading cases…'
            ) : (
              <>
                <strong>{pluralize(cases.length, 'case')}</strong> in scope
                {option.days !== null ? ` of ${universe.cases.length} loaded` : ''} · every chart
                below uses this scope
              </>
            )}
          </p>
        </div>
      </div>

      {universe.truncated || universe.failedDetails > 0 ? (
        <div className={styles.coverage}>
          {universe.truncated ? (
            <p>
              Figures cover the {UNIVERSE_CASE_LIMIT} most recent of {universe.total} cases.
            </p>
          ) : null}
          {universe.failedDetails > 0 ? (
            <p>
              {pluralize(universe.failedDetails, 'per-case request')} could not be loaded; the
              figures below exclude {universe.failedDetails === 1 ? 'it' : 'them'}.
            </p>
          ) : null}
        </div>
      ) : null}

      {universe.isError ? <ErrorState error={universe.error} onRetry={universe.refetch} /> : null}

      {!pending && !universe.isError && !hasCases ? (
        <Card>
          <EmptyState
            icon={<IconChart size={18} />}
            title="Nothing to chart yet"
            description="Analytics are computed from your cases. Open an investigation and run its pipeline; the trends appear here as soon as it produces detections and candidates."
            action={
              <LinkButton href="/cases/new" variant="primary" size="sm">
                Create a case
              </LinkButton>
            }
          />
        </Card>
      ) : null}

      {!pending && hasCases && !inScope ? (
        <Card>
          <EmptyState
            icon={<IconFilter size={18} />}
            title={`No cases were opened in the ${option.label.toLowerCase()}`}
            description={`${pluralize(universe.cases.length, 'case')} ${universe.cases.length === 1 ? 'is' : 'are'} loaded, opened earlier than that. Widen the range to include ${universe.cases.length === 1 ? 'it' : 'them'}.`}
            action={
              <Button variant="secondary" size="sm" onClick={() => setRange('all')}>
                Show all time
              </Button>
            }
          />
        </Card>
      ) : null}

      {pending || inScope ? (
        <>
          {/* --------------------------------------------------- KPIs */}
          <Reveal className={styles.kpis} stagger={0.06} y={20}>
            <StatTile
              label="Investigations in range"
              value={pending ? undefined : cases.length}
              loading={pending}
              icon={<IconCases size={16} />}
              caption={
                option.days === null
                  ? 'Every loaded case, by the date it was opened'
                  : `Opened in the ${option.label.toLowerCase()}`
              }
              trend={pending ? undefined : casesWeekly.map((bucket) => bucket.value)}
              trendLabel={`Cases opened per week, last ${weeks} weeks`}
            />
            <StatTile
              label="Slicks detected"
              value={details ? undefined : detections.length}
              loading={details}
              icon={<IconDroplet size={16} />}
              tone="signal"
              caption={
                detections.length > 0
                  ? `${verification['VERIFIED'] ?? 0} passed the look-alike checks`
                  : 'No detections recorded in these cases'
              }
            />
            <StatTile
              label="Set aside as look-alikes"
              value={details ? undefined : setAside}
              loading={details}
              icon={<IconFilter size={16} />}
              tone="neutral"
              caption={
                setAsideShare === null
                  ? 'Share: — (no detections have been checked)'
                  : `${formatPercent(setAsideShare)} of ${pluralize(checked, 'checked detection')}`
              }
            />
            <StatTile
              label="Candidates ranked"
              value={details ? undefined : attributions.length}
              loading={details}
              icon={<IconTarget size={16} />}
              caption={
                attributions.length > 0
                  ? `Across ${pluralize(casesWithCandidates, 'case')}`
                  : 'No candidates ranked in these cases'
              }
            />
            <StatTile
              label="Median investigative score"
              value={details ? undefined : medianScore}
              decimals={2}
              loading={details}
              icon={<IconGauge size={16} />}
              tone="neutral"
              caption="0–1 scale; not a probability"
            />
            <StatTile
              label="Share in HIGH band"
              value={details ? undefined : highShare === null ? null : Math.round(highShare * 100)}
              suffix="%"
              loading={details}
              icon={<IconShield size={16} />}
              tone="signal"
              caption={
                highShare === null
                  ? 'No candidates to band yet'
                  : `${bands.HIGH} of ${attributions.length} candidates · leads, not findings`
              }
            />
          </Reveal>

          {/* ----------------------------------------------- throughput */}
          <section className={styles.section} aria-labelledby="analytics-throughput">
            <SectionHead
              id="analytics-throughput"
              index="01"
              title="Throughput"
              description={`Weekly counts over the last ${weeks} weeks, UTC. Empty weeks are shown, so a quiet period reads as quiet.`}
            />
            <div className={styles.grid}>
              <Reveal className={styles.cell}>
                <ChartFrame
                  className={styles.fill}
                  title="Cases opened per week"
                  subtitle="By the date each case was opened. Hover or focus a column for its count."
                  table={{
                    caption: 'Cases opened per week',
                    columns: ['Week', 'Cases opened'],
                    rows: casesWeekly.map((bucket) => [bucket.detail, bucket.value]),
                  }}
                  foot={
                    casesOutside > 0
                      ? `${pluralize(casesOutside, 'case')} opened before the week of ${windowStart} ${casesOutside === 1 ? 'is' : 'are'} outside this window.`
                      : undefined
                  }
                >
                  {pending ? (
                    <ChartSkeleton />
                  ) : (
                    <ColumnChart data={casesWeekly} label="Cases opened per week" unit="cases" />
                  )}
                </ChartFrame>
              </Reveal>

              <Reveal className={styles.cell}>
                <ChartFrame
                  className={styles.fill}
                  title="Slicks detected per week"
                  subtitle="By each detection's timestamp, which can be weeks earlier than the date its case was opened."
                  table={{
                    caption: 'Slicks detected per week',
                    columns: ['Week', 'Detections'],
                    rows: detectionsWeekly.map((bucket) => [bucket.detail, bucket.value]),
                  }}
                  foot={
                    detectionsOutside > 0
                      ? `${pluralize(detectionsOutside, 'detection')} from these cases ${detectionsOutside === 1 ? 'falls' : 'fall'} outside this ${weeks}-week window and ${detectionsOutside === 1 ? 'is' : 'are'} not plotted.`
                      : undefined
                  }
                >
                  {details ? (
                    <ChartSkeleton />
                  ) : detections.length === 0 ? (
                    <p className={styles.empty}>No slicks have been detected in these cases.</p>
                  ) : (
                    <ColumnChart
                      data={detectionsWeekly}
                      label="Slicks detected per week"
                      unit="detections"
                    />
                  )}
                </ChartFrame>
              </Reveal>
            </div>
          </section>

          {/* ---------------------------------------- look-alikes & bands */}
          <section className={styles.section} aria-labelledby="analytics-evidence">
            <SectionHead
              id="analytics-evidence"
              index="02"
              title="Look-alikes and evidence strength"
              description="What the physical rules concluded about each slick, and how strong the evidence is behind each ranked candidate."
            />
            <div className={styles.grid}>
              <Reveal className={styles.cell}>
                <ChartFrame
                  className={styles.fill}
                  title="Look-alike verification outcomes"
                  subtitle="Low wind, biogenic films and rain cells can mimic oil in SAR; these rules test for them."
                  table={{
                    caption: 'Detections by look-alike verification outcome',
                    columns: ['Outcome', 'Meaning', 'Detections'],
                    rows: outcomeRows.map((row) => [
                      row.label,
                      row.meaning,
                      verification[row.key] ?? 0,
                    ]),
                  }}
                  foot={
                    detections.length > 0
                      ? `Set aside = false positives + rejected: ${setAside} of ${pluralize(checked, 'checked detection')}${setAsideShare === null ? '' : ` (${formatPercent(setAsideShare)})`}.`
                      : undefined
                  }
                >
                  {details ? (
                    <ChartSkeleton height="9rem" />
                  ) : (
                    <BarList
                      label="Detections by verification outcome"
                      empty="No detections have been verified in these cases."
                      max={Math.max(1, detections.length)}
                      items={
                        detections.length === 0
                          ? []
                          : outcomeRows.map((row) => ({
                              key: row.key,
                              label: row.label,
                              value: verification[row.key] ?? 0,
                            }))
                      }
                    />
                  )}
                </ChartFrame>
              </Reveal>

              <Reveal className={styles.cell}>
                <ChartFrame
                  className={styles.fill}
                  title="Evidence strength across candidates"
                  subtitle="The server's band for every ranked candidate. A band describes the supporting evidence; it is not a likelihood of responsibility."
                  table={{
                    caption: 'Candidates by evidence-strength band',
                    columns: ['Band', 'Score range', 'Candidates', 'Share'],
                    rows: BANDS.map((band) => [
                      band.key,
                      band.range,
                      bands[band.key],
                      attributions.length
                        ? formatPercent(bands[band.key] / attributions.length)
                        : '—',
                    ]),
                  }}
                >
                  {details ? (
                    <ChartSkeleton height="9rem" />
                  ) : attributions.length === 0 ? (
                    <p className={styles.empty}>No candidates have been ranked in these cases.</p>
                  ) : (
                    <>
                      <SegmentBar
                        label="Candidates by evidence-strength band"
                        hideEmpty
                        segments={BANDS.map((band) => ({
                          key: band.key,
                          label: band.label,
                          value: bands[band.key],
                          color: band.color,
                        }))}
                      />
                      <ul className={styles.bandList} aria-label="What each band means">
                        {BANDS.map((band) => (
                          <li
                            key={band.key}
                            className={styles.band}
                            style={{ '--band-color': band.color } as CSSProperties}
                          >
                            <span className={styles.bandSwatch} aria-hidden="true" />
                            <span className={styles.bandName}>{band.key}</span>
                            <span className={styles.bandRange}>{band.range}</span>
                            <span className={styles.bandMeaning}>{band.meaning}</span>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                </ChartFrame>
              </Reveal>
            </div>
            <NoticeStack notices={detectionNotices} className={styles.notices} />
          </section>

          {/* ---------------------------------------------------- scores */}
          <section className={styles.section} aria-labelledby="analytics-scores">
            <SectionHead
              id="analytics-scores"
              index="03"
              title="Investigative scores"
              description="How the six-factor score is distributed across candidates, and which factors carry it. A score ranks leads for enquiry; it is not a probability."
            />
            <div className={styles.grid}>
              <Reveal className={styles.cell}>
                <ChartFrame
                  className={styles.fill}
                  title="Investigative-score distribution"
                  subtitle="Final score of every ranked candidate, in ten bins on the 0–1 scale. Hover or focus a column for its count."
                  table={{
                    caption: 'Candidates by investigative-score bin',
                    columns: ['Score range', 'Band(s) on the score scale', 'Candidates'],
                    rows: histogram.map((bin, index) => [
                      bin.detail ?? '',
                      binBands(index),
                      bin.value,
                    ]),
                  }}
                  foot={
                    <>
                      Band edges on the score scale: LOW below {BAND_MODERATE_MIN.toFixed(2)},
                      MODERATE {BAND_MODERATE_MIN.toFixed(2)} to below {BAND_HIGH_MIN.toFixed(2)},
                      HIGH {BAND_HIGH_MIN.toFixed(2)} and above; the 0.40–0.50 bin straddles the
                      first edge.
                      {capped > 0
                        ? ` ${pluralize(capped, 'candidate')} scored into a higher band than the one the server gave ${capped === 1 ? 'it' : 'them'}: the server lowers a band when its discrimination check fails (for example, when the origin region cannot separate the candidates). Scores are not changed.`
                        : ''}
                    </>
                  }
                >
                  {details ? (
                    <ChartSkeleton height="13rem" />
                  ) : attributions.length === 0 ? (
                    <p className={styles.empty}>No candidates have been ranked in these cases.</p>
                  ) : (
                    <div className={styles.histogram}>
                      <ColumnChart
                        data={histogram}
                        label="Candidates by investigative-score bin, 0 to 1"
                        unit={attributions.length === 1 ? 'candidate' : 'candidates'}
                        height={184}
                      />
                      <BandRuler />
                    </div>
                  )}
                </ChartFrame>
              </Reveal>

              <Reveal className={styles.cell}>
                <ChartFrame
                  className={styles.fill}
                  title="Mean factor scores"
                  subtitle="The average 0–1 score each factor gave the candidates, heaviest factor first. w is the factor's weight in the final score."
                  table={{
                    caption: 'Mean factor scores across candidates',
                    columns: ['Factor', 'Weight', 'Mean score', 'Mean contribution', 'Candidates'],
                    rows: factors.map((factor) => [
                      factor.label,
                      formatScore(factor.weight),
                      formatScore(factor.score),
                      formatScore(factor.contribution),
                      factorCounts.get(factor.key) ?? 0,
                    ]),
                  }}
                  foot={
                    factors.length > 0
                      ? `Weights are prototype engineering defaults until calibrated. A lower AIS-reliability mean reflects reporting gaps: a gap lowers confidence in a track, it is not evidence of wrongdoing.${scoringVersions.length > 1 ? ` These means pool candidates scored under ${scoringVersions.length} scoring versions (${scoringVersions.join(', ')}).` : scoringVersions.length === 1 ? ` Scoring version ${scoringVersions[0]}.` : ''}`
                      : undefined
                  }
                >
                  {details ? (
                    <ChartSkeleton height="13rem" />
                  ) : (
                    <BarList
                      label="Mean score per factor, 0 to 1"
                      empty="No candidates have been ranked in these cases."
                      max={1}
                      items={factors.map((factor) => ({
                        key: factor.key,
                        label: `${factor.label} (w ${formatScore(factor.weight)})`,
                        value: factor.score,
                        display: formatScore(factor.score),
                      }))}
                    />
                  )}
                </ChartFrame>
              </Reveal>
            </div>
            <NoticeStack notices={rankingNotices} className={styles.notices} />
            {shortfalls.size > 0 ? (
              <div className={styles.notices}>
                {[...shortfalls.entries()].map(([note, count]) => (
                  <Notice
                    key={note}
                    tone="info"
                    label={`Shortfall · ${pluralize(count, 'case')}`}
                    text={note}
                  />
                ))}
              </div>
            ) : null}
          </section>

          {/* ------------------------------------------ vessels & data */}
          <section className={styles.section} aria-labelledby="analytics-vessels">
            <SectionHead
              id="analytics-vessels"
              index="04"
              title="Vessels and provenance"
              description="Which vessels recur across investigations, and where every record on this page came from."
            />
            <div className={styles.grid}>
              <Reveal className={styles.cell}>
                <ChartFrame
                  className={styles.fill}
                  title="Vessels most often ranked as candidates"
                  subtitle={`Cases in which each vessel (grouped by MMSI) was ranked, top 8. Bar length is the share of the ${pluralize(casesWithCandidates, 'case')} that ranked any candidate.`}
                  table={{
                    caption: 'Vessels by number of cases in which they were ranked as a candidate',
                    columns: ['Vessel', 'MMSI', 'Provenance', 'Cases as candidate'],
                    rows: frequent.map(({ vessel, cases: count }) => [
                      vessel.name ?? 'Unnamed',
                      formatMmsi(vessel.mmsi),
                      vessel.provenance ?? 'Unlabelled',
                      count,
                    ]),
                  }}
                  foot={
                    // Mandatory and in the foot, so it stays visible in the table view too.
                    <>
                      <strong className={styles.caveatLead}>
                        Repeat appearances are history, not wrongdoing.
                      </strong>{' '}
                      A vessel on a regular route through a busy lane reappears as a candidate
                      simply because it is often there.
                      {details || frequent.length === 0
                        ? ''
                        : repeatCandidates > 0
                          ? ` ${pluralize(repeatCandidates, 'vessel')} ${repeatCandidates === 1 ? 'was' : 'were'} a candidate in more than one case.`
                          : ' No vessel was a candidate in more than one case.'}
                    </>
                  }
                >
                  {details ? (
                    <ChartSkeleton height="14rem" />
                  ) : (
                    <BarList
                      labelWidth="15rem"
                      label="Vessels by cases in which they were a candidate"
                      empty="No candidates have been ranked in these cases."
                      max={Math.max(1, casesWithCandidates)}
                      items={frequent.map(({ vessel, cases: count }) => ({
                        key: String(vessel.mmsi),
                        label: vessel.name ?? `MMSI ${formatMmsi(vessel.mmsi)}`,
                        value: count,
                        display: pluralize(count, 'case'),
                        href: `/vessels/${vessel.vesselId}`,
                      }))}
                    />
                  )}
                </ChartFrame>
              </Reveal>

              <div className={styles.stack}>
                <Reveal className={styles.cell}>
                  <Card
                    className={styles.fill}
                    title="Data provenance"
                    description="Every record keeps its own label. Provenance is shown as text, never by colour alone."
                  >
                    {details ? (
                      <ChartSkeleton height="9rem" />
                    ) : (
                      <>
                        <dl className={styles.provList}>
                          {provenanceRows.map((row) => {
                            const total = row.tally.reduce((sum, item) => sum + item.count, 0);
                            return (
                              <div key={row.key} className={styles.provRow}>
                                <dt className={styles.provLabel}>
                                  {row.label}
                                  <span className={styles.provTotal}>{total}</span>
                                </dt>
                                <dd className={styles.provValues}>
                                  {total === 0 ? (
                                    <span className={styles.provNone}>None in scope</span>
                                  ) : (
                                    row.tally.map((item) => (
                                      <span
                                        key={item.key || 'unlabelled'}
                                        className={styles.provItem}
                                      >
                                        {item.key ? (
                                          <ProvenanceBadge provenance={item.key} />
                                        ) : (
                                          <Badge tone="neutral">Unlabelled</Badge>
                                        )}
                                        <span className={styles.provCount}>{item.count}</span>
                                      </span>
                                    ))
                                  )}
                                </dd>
                              </div>
                            );
                          })}
                        </dl>
                        {realWithSynthetic > 0 ? (
                          <p className={styles.provNote}>
                            {pluralize(realWithSynthetic, 'case')} labelled REAL{' '}
                            {realWithSynthetic === 1 ? 'contains' : 'contain'} synthetic records
                            (candidates, detections or vessels). Read each record by its own label.
                          </p>
                        ) : null}
                      </>
                    )}
                  </Card>
                </Reveal>

                <Reveal className={styles.cell}>
                  <div className={styles.untracked}>
                    <div className={styles.untrackedHead}>
                      <h2 className={styles.untrackedTitle}>Model accuracy over time</h2>
                      <Badge tone="neutral">Not tracked</Badge>
                    </div>
                    <p>
                      The API keeps no time series of model evaluations: a registered model carries
                      at most one metrics snapshot per version, and often none. A trend here would
                      need evaluation runs stored with timestamps against a labelled reference set,
                      so none is drawn.
                    </p>
                    <LinkButton href="/ml-ops" variant="ghost" size="sm">
                      Registered models in ML Ops
                    </LinkButton>
                  </div>
                </Reveal>
              </div>
            </div>
            <NoticeStack notices={vesselNotices} className={styles.notices} />
          </section>
        </>
      ) : null}
    </main>
  );
}
