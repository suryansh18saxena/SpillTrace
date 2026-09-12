'use client';

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useMemo, type ReactNode } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';
import { ConfidenceBadge } from '@/components/attribution/ConfidenceBadge';
import { Disclaimer } from '@/components/attribution/Disclaimer';
import { BarList, SegmentBar } from '@/components/charts';
import { CaseStatusBadge } from '@/components/common/CaseStatusBadge';
import { MetaList, Readout, ReadoutGrid } from '@/components/common/MetaList';
import { Notice, NoticeStack } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { PageHeader } from '@/components/layout/PageHeader';
import { Reveal } from '@/components/motion/Reveal';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { IconArrowRight, IconCompare, IconPlus, IconShip } from '@/components/ui/Icons';
import { LinkButton } from '@/components/ui/LinkButton';
import { Select, type SelectOption } from '@/components/ui/Select';
import { Skeleton } from '@/components/ui/Skeleton';
import { Table, type Column } from '@/components/ui/Table';
import type { ApiError } from '@/lib/api/client';
import {
  useAttributions,
  useCase,
  useCases,
  useDetections,
  useDriftRuns,
  useVessels,
} from '@/lib/api/hooks';
import type {
  AttributionListResponse,
  Case,
  DetectionListResponse,
  DriftRun,
  DriftRunListResponse,
  VesselListResponse,
} from '@/lib/api/types';
import {
  formatAreaKm2,
  formatDateTimeCompact,
  formatDistanceKm,
  formatDuration,
  formatInteger,
  formatMmsi,
  formatOrdinal,
  formatScore,
  formatTimeRange,
  humanizeIdentifier,
  pluralize,
  truncateId,
} from '@/lib/format';
import {
  haversineKm,
  isValidLngLat,
  type LngLat,
  polygonAreaKm2,
  segmentsIntersect,
} from '@/lib/geo';
import {
  confidenceCounts,
  verificationCounts,
  vesselAppearances,
  type VesselAppearance,
} from '@/lib/insights';
import layout from '@/components/layout/layout.module.css';
import styles from './compare.module.css';

// ----------------------------------------------------------------- one side

type Letter = 'A' | 'B';

interface Side {
  letter: Letter;
  id: string | null;
  item: Case | undefined;
  caseQuery: UseQueryResult<Case, ApiError>;
  /** False for a DRAFT case: no pipeline has run, so nothing derived exists to fetch. */
  hasPipeline: boolean;
  detections: UseQueryResult<DetectionListResponse, ApiError>;
  driftRuns: UseQueryResult<DriftRunListResponse, ApiError>;
  attributions: UseQueryResult<AttributionListResponse, ApiError>;
  vessels: UseQueryResult<VesselListResponse, ApiError>;
}

/**
 * Everything one column needs. The queries share their keys with the case
 * pages, so a case the analyst has already opened costs nothing here.
 */
function useSide(letter: Letter, id: string | null, listed: Case | undefined): Side {
  const caseQuery = useCase(id ?? undefined);
  const item = caseQuery.data ?? listed;
  const hasPipeline = Boolean(item && item.status !== 'DRAFT');
  const pipelineId = hasPipeline ? item?.id : undefined;
  const detections = useDetections(pipelineId);
  const driftRuns = useDriftRuns(pipelineId);
  const attributions = useAttributions(pipelineId);
  const vessels = useVessels(pipelineId);
  return { letter, id, item, caseQuery, hasPipeline, detections, driftRuns, attributions, vessels };
}

// ----------------------------------------------------------------- geometry

/** The AOI's outer ring, without the repeated closing vertex. */
function outerRing(item: Case | undefined): LngLat[] {
  const ring = (item?.aoi?.coordinates?.[0] ?? []).filter(isValidLngLat);
  const first = ring[0];
  const last = ring[ring.length - 1];
  return ring.length > 1 && first && last && first[0] === last[0] && first[1] === last[1]
    ? ring.slice(0, -1)
    : ring;
}

/**
 * Area-weighted centroid of a ring in plain lon/lat.
 *
 * Planar is adequate at AOI scale (the API caps an AOI's area) and nothing
 * here spans the antimeridian; a degenerate ring falls back to its vertex mean.
 */
function ringCentroid(ring: readonly LngLat[]): LngLat | null {
  const n = ring.length;
  if (n === 0) return null;
  let twiceArea = 0;
  let cx = 0;
  let cy = 0;
  for (let i = 0; i < n; i += 1) {
    const p = ring[i]!;
    const q = ring[(i + 1) % n]!;
    const cross = p[0] * q[1] - q[0] * p[1];
    twiceArea += cross;
    cx += (p[0] + q[0]) * cross;
    cy += (p[1] + q[1]) * cross;
  }
  if (Math.abs(twiceArea) < 1e-12) {
    const sum = ring.reduce<LngLat>((acc, p) => [acc[0] + p[0], acc[1] + p[1]], [0, 0]);
    return [sum[0] / n, sum[1] / n];
  }
  return [cx / (3 * twiceArea), cy / (3 * twiceArea)];
}

/** Ray casting: is `point` inside the (implicitly closed) ring? */
function pointInRing(point: LngLat, ring: readonly LngLat[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const a = ring[i]!;
    const b = ring[j]!;
    const crosses =
      a[1] > point[1] !== b[1] > point[1] &&
      point[0] < ((b[0] - a[0]) * (point[1] - a[1])) / (b[1] - a[1]) + a[0];
    if (crosses) inside = !inside;
  }
  return inside;
}

/** Two simple polygons overlap if any edges cross, or one holds the other. */
function ringsOverlap(a: readonly LngLat[], b: readonly LngLat[]): boolean {
  for (let i = 0; i < a.length; i += 1) {
    const a1 = a[i]!;
    const a2 = a[(i + 1) % a.length]!;
    for (let j = 0; j < b.length; j += 1) {
      if (segmentsIntersect(a1, a2, b[j]!, b[(j + 1) % b.length]!)) return true;
    }
  }
  return pointInRing(a[0]!, b) || pointInRing(b[0]!, a);
}

function aoiAreaKm2(item: Case): number | null {
  if (typeof item.aoi_area_km2 === 'number') return item.aoi_area_km2;
  const area = polygonAreaKm2(item.aoi);
  return area > 0 ? area : null;
}

// --------------------------------------------------------------------- time

interface WindowRelation {
  overlapMs: number;
  gapMs: number;
  /** Which window opens first. */
  first: Letter;
}

function toMs(value: string | null | undefined): number {
  return value ? Date.parse(value) : Number.NaN;
}

function relateWindows(
  aStart: string | null | undefined,
  aEnd: string | null | undefined,
  bStart: string | null | undefined,
  bEnd: string | null | undefined,
): WindowRelation | null {
  const as = toMs(aStart);
  const ae = toMs(aEnd);
  const bs = toMs(bStart);
  const be = toMs(bEnd);
  if (![as, ae, bs, be].every(Number.isFinite)) return null;
  const overlap = Math.min(ae, be) - Math.max(as, bs);
  return {
    overlapMs: Math.max(0, overlap),
    gapMs: Math.max(0, -overlap),
    first: as <= bs ? 'A' : 'B',
  };
}

function describeRelation(
  relation: WindowRelation | null,
  noun: string,
): { label: string; value: string; caption: string } {
  if (!relation) {
    return {
      label: `${noun} windows`,
      value: '—',
      caption: 'Not recorded for both cases, so they cannot be compared.',
    };
  }
  if (relation.overlapMs > 0) {
    return {
      label: `${noun} windows overlap by`,
      value: formatDuration(relation.overlapMs / 1000),
      caption: 'Both windows cover this much of the same time.',
    };
  }
  const other: Letter = relation.first === 'A' ? 'B' : 'A';
  return {
    label: `Gap between ${noun.toLowerCase()} windows`,
    value: relation.gapMs === 0 ? 'None' : formatDuration(relation.gapMs / 1000),
    caption:
      relation.gapMs === 0
        ? `Case ${other}’s window opens as case ${relation.first}’s closes.`
        : `Case ${relation.first}’s window closes before case ${other}’s opens.`,
  };
}

/** The most recently created drift run — the one the case pages lead with. */
function latestRun(runs: readonly DriftRun[]): DriftRun | null {
  let best: DriftRun | null = null;
  for (const run of runs) {
    const at = Date.parse(run.created_at ?? '') || 0;
    if (!best || at > (Date.parse(best.created_at ?? '') || 0)) best = run;
  }
  return best;
}

// ------------------------------------------------------------------ helpers

function unique(texts: ReadonlyArray<string | null | undefined>): string[] {
  return Array.from(
    new Set(texts.map((text) => text?.trim()).filter((text): text is string => Boolean(text))),
  );
}

/**
 * Why a column is empty, in terms of where the case is in its pipeline — an
 * empty list on a running case means "not yet", not "none".
 */
function emptyNote(item: Case, produced: string, none: string): string {
  if (item.status === 'RUNNING' || item.status === 'QUEUED') {
    return `The pipeline is still running — no ${produced} recorded yet.`;
  }
  if (item.status === 'FAILED') {
    return `No ${produced} recorded; this case’s pipeline did not complete.`;
  }
  return none;
}

/** Loading, error and not-run states for one column's data, then the content. */
function gate<T>(
  side: Side,
  query: UseQueryResult<T, ApiError>,
  render: (data: T, item: Case) => ReactNode,
): ReactNode {
  if (!side.item) {
    return side.caseQuery.isError ? (
      <p className={styles.muted}>This case could not be loaded.</p>
    ) : (
      <Skeleton height="5rem" radius="var(--radius-md)" />
    );
  }
  if (!side.hasPipeline) {
    return (
      <p className={styles.muted}>
        No pipeline has run for this case yet, so it has produced nothing to compare.
      </p>
    );
  }
  if (query.isError) {
    return <ErrorState compact error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (query.data === undefined) return <Skeleton height="5rem" radius="var(--radius-md)" />;
  return render(query.data, side.item);
}

function IconSwap({ size = 16 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="m7 4-4 4 4 4" />
      <path d="M3 8h14" />
      <path d="m17 12 4 4-4 4" />
      <path d="M21 16H7" />
    </svg>
  );
}

// ----------------------------------------------------------- presentation

function Figure({
  label,
  value,
  caption,
}: {
  label: string;
  value: ReactNode;
  caption?: ReactNode;
}) {
  return (
    <div className={styles.figure}>
      <span className={styles.figureLabel}>{label}</span>
      <span className={styles.figureValue}>{value}</span>
      {caption ? <span className={styles.figureCaption}>{caption}</span> : null}
    </div>
  );
}

function Half({ side, children }: { side: Side; children: ReactNode }) {
  return (
    <div className={styles.half}>
      <h3 className={styles.halfLabel}>
        <span className={styles.letter} aria-hidden="true">
          {side.letter}
        </span>
        <span className="sr-only">Case {side.letter}: </span>
        <span className={styles.halfTitle}>{side.item?.title ?? `Case ${side.letter}`}</span>
      </h3>
      {children}
    </div>
  );
}

function CaseIdentity({ side }: { side: Side }) {
  const item = side.item;
  const synthetic = item?.data_provenance === 'SYNTHETIC';
  return (
    <section className={styles.identity} aria-label={`Case ${side.letter}`}>
      <div className={styles.identityTop}>
        <span className={styles.letterMark} aria-hidden="true">
          {side.letter}
        </span>
        <span className={styles.identityEyebrow}>Case {side.letter}</span>
        {item ? (
          <span className={styles.identityRef}>{item.case_ref ?? truncateId(item.id, 8, 4)}</span>
        ) : null}
      </div>

      {item ? (
        <>
          <h2 className={styles.identityTitle}>
            <Link href={`/cases/${item.id}`}>{item.title}</Link>
          </h2>
          <div className={styles.badgeRow}>
            <CaseStatusBadge status={item.status} />
            <ProvenanceBadge provenance={item.data_provenance} />
          </div>
          <MetaList
            dense
            entries={[
              {
                key: 'window',
                term: 'Time window',
                mono: true,
                value: formatTimeRange(item.start_time, item.end_time),
              },
              { key: 'area', term: 'AOI area', mono: true, value: formatAreaKm2(aoiAreaKm2(item)) },
              {
                key: 'created',
                term: 'Opened',
                mono: true,
                value: formatDateTimeCompact(item.created_at),
              },
            ]}
          />
          <Notice
            text={item.notice}
            tone={synthetic ? 'synthetic' : 'caution'}
            label={synthetic ? 'Synthetic data' : undefined}
          />
          <div className={styles.identityActions}>
            <LinkButton
              href={`/cases/${item.id}`}
              size="sm"
              variant="secondary"
              leadingIcon={<IconArrowRight size={14} />}
            >
              Open investigation
            </LinkButton>
          </div>
        </>
      ) : side.caseQuery.isError ? (
        <ErrorState
          compact
          error={side.caseQuery.error}
          title={side.caseQuery.error?.isNotFound ? 'Case not found' : undefined}
          description={
            side.caseQuery.error?.isNotFound
              ? 'This case does not exist, or it is not one you are entitled to open. Pick another above.'
              : undefined
          }
          onRetry={() => void side.caseQuery.refetch()}
        />
      ) : (
        <div className={styles.identitySkeleton} aria-busy="true">
          <span className="sr-only">Loading case {side.letter}</span>
          <Skeleton height="1.25rem" width="75%" />
          <Skeleton height="1rem" width="40%" />
          <Skeleton height="3rem" />
        </div>
      )}
    </section>
  );
}

/**
 * Both AOIs drawn to one scale, so "how far apart, how big, do they touch" is
 * read at a glance. A is solid and B dashed, each labelled with its letter:
 * the two are never told apart by colour alone.
 */
function AoiDiagram({
  ringA,
  ringB,
  centroidA,
  centroidB,
  label,
}: {
  ringA: readonly LngLat[];
  ringB: readonly LngLat[];
  centroidA: LngLat | null;
  centroidB: LngLat | null;
  label: string;
}) {
  const all = [...ringA, ...ringB];
  if (all.length === 0) return null;

  const W = 240;
  const H = 150;
  const PAD = 24;
  const west = Math.min(...all.map((p) => p[0]));
  const east = Math.max(...all.map((p) => p[0]));
  const south = Math.min(...all.map((p) => p[1]));
  const north = Math.max(...all.map((p) => p[1]));
  const kx = Math.cos((((south + north) / 2) * Math.PI) / 180);
  const width = Math.max((east - west) * kx, 1e-9);
  const height = Math.max(north - south, 1e-9);
  const scale = Math.min((W - 2 * PAD) / width, (H - 2 * PAD) / height);
  const ox = (W - width * scale) / 2;
  const oy = (H - height * scale) / 2;

  const project = (p: LngLat): [number, number] => [
    ox + (p[0] - west) * kx * scale,
    oy + (north - p[1]) * scale,
  ];
  const points = (ring: readonly LngLat[]) =>
    ring
      .map(project)
      .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
      .join(' ');

  const cA = centroidA ? project(centroidA) : null;
  const cB = centroidB ? project(centroidB) : null;

  // Put each letter on the corner of its own outline that faces away from the
  // other case, so the two labels never land on top of each other.
  const labelAt = (
    ring: readonly LngLat[],
    self: [number, number] | null,
    other: [number, number] | null,
    fallback: 1 | -1,
  ): { x: number; y: number; anchor: 'start' | 'end' } => {
    const projected = ring.map(project);
    const xs = projected.map((p) => p[0]);
    const ys = projected.map((p) => p[1]);
    const dx = self && other && self[0] !== other[0] ? Math.sign(self[0] - other[0]) : fallback;
    const dy = self && other && self[1] !== other[1] ? Math.sign(self[1] - other[1]) : fallback;
    const x = dx > 0 ? Math.max(...xs) + 5 : Math.min(...xs) - 5;
    const y = dy > 0 ? Math.max(...ys) + 12 : Math.min(...ys) - 5;
    return {
      x: Math.min(W - 6, Math.max(6, x)),
      y: Math.min(H - 5, Math.max(12, y)),
      anchor: dx > 0 ? 'start' : 'end',
    };
  };
  const labelA = ringA.length ? labelAt(ringA, cA, cB, -1) : null;
  const labelB = ringB.length ? labelAt(ringB, cB, cA, 1) : null;

  return (
    <svg className={styles.diagram} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
      <rect className={styles.diagramSea} x="0.5" y="0.5" width={W - 1} height={H - 1} rx="10" />
      {[0.25, 0.5, 0.75].map((f) => (
        <g key={f} className={styles.diagramGrid}>
          <line x1={W * f} y1="1" x2={W * f} y2={H - 1} />
          <line x1="1" y1={H * f} x2={W - 1} y2={H * f} />
        </g>
      ))}
      {cA && cB ? (
        <line className={styles.diagramLink} x1={cA[0]} y1={cA[1]} x2={cB[0]} y2={cB[1]} />
      ) : null}
      {ringB.length ? <polygon className={styles.diagramB} points={points(ringB)} /> : null}
      {ringA.length ? <polygon className={styles.diagramA} points={points(ringA)} /> : null}
      {cA ? <circle className={styles.diagramDot} cx={cA[0]} cy={cA[1]} r="2.5" /> : null}
      {cB ? <circle className={styles.diagramDot} cx={cB[0]} cy={cB[1]} r="2.5" /> : null}
      {labelA ? (
        <text className={styles.diagramLabel} x={labelA.x} y={labelA.y} textAnchor={labelA.anchor}>
          A
        </text>
      ) : null}
      {labelB ? (
        <text className={styles.diagramLabel} x={labelB.x} y={labelB.y} textAnchor={labelB.anchor}>
          B
        </text>
      ) : null}
    </svg>
  );
}

function Between({ a, b }: { a: Side; b: Side }) {
  if (!a.item || !b.item) return null;

  const ringA = outerRing(a.item);
  const ringB = outerRing(b.item);
  const centroidA = ringCentroid(ringA);
  const centroidB = ringCentroid(ringB);
  const distance = centroidA && centroidB ? haversineKm(centroidA, centroidB) : null;
  const overlap = ringA.length >= 3 && ringB.length >= 3 ? ringsOverlap(ringA, ringB) : null;

  const searched = describeRelation(
    relateWindows(a.item.start_time, a.item.end_time, b.item.start_time, b.item.end_time),
    'Search',
  );
  const runA = latestRun(a.driftRuns.data?.items ?? []);
  const runB = latestRun(b.driftRuns.data?.items ?? []);
  // Shown only when both cases have an inferred window — otherwise there is
  // nothing to relate, and a dash would add a row that says nothing.
  const inferred =
    runA?.inferred_start && runB?.inferred_start
      ? describeRelation(
          relateWindows(
            runA.inferred_start,
            runA.inferred_end,
            runB.inferred_start,
            runB.inferred_end,
          ),
          'Inferred discharge',
        )
      : null;

  const diagramLabel = [
    'The two areas of interest drawn to the same scale.',
    overlap === null ? null : overlap ? 'They overlap.' : 'They do not overlap.',
    distance === null ? null : `Their centres are ${formatDistanceKm(distance)} apart.`,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <section className={styles.between} aria-labelledby="compare-between">
      <div className={styles.betweenHead}>
        <p className="eyebrow">Between the two</p>
        <h2 id="compare-between" className={styles.betweenTitle}>
          Where and when the cases sit relative to each other
        </h2>
      </div>
      <div className={styles.betweenBody}>
        <figure className={styles.diagramFigure}>
          <AoiDiagram
            ringA={ringA}
            ringB={ringB}
            centroidA={centroidA}
            centroidB={centroidB}
            label={diagramLabel}
          />
          <figcaption className={styles.diagramCaption}>
            A solid, B dashed · the line joins the two centres
          </figcaption>
        </figure>
        <ReadoutGrid className={styles.betweenReadouts}>
          <Readout label={searched.label} value={searched.value} caption={searched.caption} />
          <Readout
            label="Between AOI centres"
            value={formatDistanceKm(distance)}
            caption="Great-circle distance between the centres of the two areas."
          />
          <Readout
            label="Areas of interest"
            value={overlap === null ? '—' : overlap ? 'Overlap' : 'Separate'}
            caption="Tested on the two AOI outlines as drawn."
          />
          {inferred ? (
            <Readout
              label={inferred.label}
              value={inferred.value}
              caption={`${inferred.caption} From each case’s latest drift run.`}
            />
          ) : null}
        </ReadoutGrid>
      </div>
      <p className={styles.betweenNote}>
        Nearness in space or time is context for the analyst. It does not show that two slicks share
        a source.
      </p>
    </section>
  );
}

// ------------------------------------------------------------- the sections

function DetectionsSection({ a, b }: { a: Side; b: Side }) {
  const outcomesA = verificationCounts(a.detections.data?.items ?? []);
  const outcomesB = verificationCounts(b.detections.data?.items ?? []);
  // One scale for both columns, so equal bars mean equal counts across cases.
  const max = Math.max(1, ...Object.values(outcomesA), ...Object.values(outcomesB));

  const half = (side: Side, outcomes: Record<string, number>) => (
    <Half side={side}>
      {gate(side, side.detections, (data, item) => {
        const items = data.items;
        if (items.length === 0) {
          return (
            <p className={styles.muted}>
              {emptyNote(item, 'slick', 'No slick was detected in this case’s scenes.')}
            </p>
          );
        }
        const total = items.reduce(
          (sum, detection) => sum + (Number.isFinite(detection.area_km2) ? detection.area_km2 : 0),
          0,
        );
        return (
          <>
            <div className={styles.figures}>
              <Figure label="Slicks detected" value={formatInteger(items.length)} />
              <Figure label="Total slick area" value={formatAreaKm2(total)} />
            </div>
            <div className={styles.block}>
              <p className={styles.blockLabel}>Look-alike verification</p>
              <BarList
                label={`Case ${side.letter} detections by verification outcome`}
                max={max}
                items={Object.entries(outcomes)
                  .filter(([, value]) => value > 0)
                  .map(([key, value]) => ({ key, label: humanizeIdentifier(key), value }))}
              />
            </div>
          </>
        );
      })}
    </Half>
  );

  return (
    <Card
      title="Detections"
      description="Oil-like features found in each case’s SAR scenes, and what the look-alike rules concluded about them."
    >
      <div className={styles.halves}>
        {half(a, outcomesA)}
        {half(b, outcomesB)}
      </div>
      <NoticeStack
        className={styles.sectionNotices}
        label="Detections"
        notices={[a.detections.data?.notice, b.detections.data?.notice]}
      />
    </Card>
  );
}

function DriftSection({ a, b }: { a: Side; b: Side }) {
  const half = (side: Side) => (
    <Half side={side}>
      {gate(side, side.driftRuns, (data, item) => {
        const run = latestRun(data.items);
        if (!run) {
          return (
            <p className={styles.muted}>
              {emptyNote(item, 'drift run', 'No drift run has been recorded for this case.')}
            </p>
          );
        }
        return (
          <>
            <div className={styles.figures}>
              <Figure
                label="Origin confidence"
                value={formatScore(run.origin_confidence)}
                caption="0–1 scale. Never combined with detection confidence."
              />
              <Figure
                label="Origin region area"
                value={formatAreaKm2(run.origin_area_km2 ?? null)}
              />
            </div>
            <MetaList
              dense
              entries={[
                {
                  key: 'window',
                  term: 'Inferred discharge window',
                  mono: true,
                  value: formatTimeRange(run.inferred_start, run.inferred_end),
                },
                { key: 'engine', term: 'Engine', mono: true, value: run.engine },
                data.items.length > 1 && {
                  key: 'runs',
                  term: 'Drift runs',
                  value: `Latest of ${data.items.length}`,
                },
              ]}
            />
          </>
        );
      })}
    </Half>
  );

  return (
    <Card
      title="Drift & origin"
      description="Reverse drift from each slick back to a region where a discharge was more likely — a region, never a point."
    >
      <div className={styles.halves}>
        {half(a)}
        {half(b)}
      </div>
      <NoticeStack
        className={styles.sectionNotices}
        label="Origin region"
        notices={[a.driftRuns.data?.notice, b.driftRuns.data?.notice]}
      />
    </Card>
  );
}

function CandidatesSection({ a, b }: { a: Side; b: Side }) {
  const half = (side: Side) => (
    <Half side={side}>
      {gate(side, side.attributions, (data, item) => {
        const ranked = [...data.items].sort((x, y) => x.rank - y.rank);
        if (ranked.length === 0) {
          return (
            <>
              <p className={styles.muted}>
                {emptyNote(item, 'candidate', 'No candidate vessels were ranked for this case.')}
              </p>
              <Notice text={data.shortfall_note} label="Fewer candidates than usual" tone="info" />
            </>
          );
        }
        const bands = confidenceCounts(ranked);
        const top = ranked.slice(0, 5);
        return (
          <>
            <div className={styles.figures}>
              <Figure label="Candidates ranked" value={formatInteger(ranked.length)} />
            </div>
            <div className={styles.block}>
              <p className={styles.blockLabel}>Evidence strength</p>
              <SegmentBar
                label={`Case ${side.letter} candidates by evidence-strength band`}
                segments={[
                  { key: 'LOW', label: 'Low', value: bands.LOW, color: 'var(--confidence-1)' },
                  {
                    key: 'MODERATE',
                    label: 'Moderate',
                    value: bands.MODERATE,
                    color: 'var(--confidence-2)',
                  },
                  { key: 'HIGH', label: 'High', value: bands.HIGH, color: 'var(--confidence-3)' },
                ]}
              />
            </div>
            <div className={styles.block}>
              <p className={styles.blockLabel}>
                {ranked.length > top.length ? `Top ${top.length} of ${ranked.length}` : 'Ranking'}
              </p>
              <ol className={styles.topList}>
                {top.map((attribution) => (
                  <li key={attribution.id} className={styles.topRow}>
                    <span className={styles.topRank} aria-hidden="true">
                      {attribution.rank}
                    </span>
                    <span className={styles.topIdentity}>
                      <Link
                        href={`/vessels/${attribution.vessel.id}?case=${item.id}`}
                        className={styles.topName}
                      >
                        <span className="sr-only">
                          {formatOrdinal(attribution.rank)} ranked candidate:{' '}
                        </span>
                        {attribution.vessel.name?.trim() || 'Unnamed vessel'}
                      </Link>
                      <span className={styles.topMeta}>
                        <span className={styles.mono}>
                          MMSI {formatMmsi(attribution.vessel.mmsi)}
                        </span>
                        <ConfidenceBadge label={attribution.confidence_label} />
                      </span>
                    </span>
                    <span className={styles.topScore}>
                      {formatScore(attribution.final_score)}
                      <span className={styles.topScoreCaption}>investigative score</span>
                    </span>
                  </li>
                ))}
              </ol>
            </div>
            {ranked.length > top.length ? (
              <div>
                <LinkButton
                  href={`/cases/${item.id}/ranking`}
                  size="sm"
                  variant="ghost"
                  leadingIcon={<IconArrowRight size={14} />}
                >
                  All {ranked.length} candidates
                </LinkButton>
              </div>
            ) : null}
            <Notice text={data.shortfall_note} label="Fewer candidates than usual" tone="info" />
          </>
        );
      })}
    </Half>
  );

  const disclaimers = unique([a.attributions.data?.disclaimer, b.attributions.data?.disclaimer]);

  return (
    <Card
      title="Candidate vessels"
      description="Vessels ranked for further enquiry in each case. A ranking prioritises enquiry; it never names a source."
    >
      <div className={styles.sectionLead}>
        {/* The server's text when it sent one; the component's own floor otherwise,
            so the scores below are never shown without it (CON-003). */}
        {(disclaimers.length ? disclaimers : [null]).map((text) => (
          <Disclaimer key={text ?? 'fallback'} text={text} />
        ))}
      </div>
      <div className={styles.halves}>
        {half(a)}
        {half(b)}
      </div>
      <div className={styles.sectionNotices}>
        {unique([a.attributions.data?.score_disclaimer, b.attributions.data?.score_disclaimer]).map(
          (text) => (
            <Notice key={text} text={text} label="What this score is" />
          ),
        )}
        {unique([
          a.attributions.data?.proximity_disclaimer,
          b.attributions.data?.proximity_disclaimer,
        ]).map((text) => (
          <Notice key={text} text={text} label="What proximity means" />
        ))}
      </div>
    </Card>
  );
}

function SharedVessels({ a, b }: { a: Side; b: Side }) {
  const caseA = a.item;
  const caseB = b.item;

  const shared = useMemo<VesselAppearance[]>(() => {
    if (!caseA || !caseB) return [];
    return vesselAppearances([
      { case: caseA, vessels: a.vessels.data, attributions: a.attributions.data },
      { case: caseB, vessels: b.vessels.data, attributions: b.attributions.data },
    ])
      .filter(
        (vessel) =>
          vessel.observedIn.some((ref) => ref.caseId === caseA.id) &&
          vessel.observedIn.some((ref) => ref.caseId === caseB.id),
      )
      .sort(
        (x, y) =>
          // Alphabetical on purpose: ordering by rank here would turn a list of
          // repeat sightings into a league table.
          (x.name ?? '￿').localeCompare(y.name ?? '￿') || x.mmsi - y.mmsi,
      );
  }, [caseA, caseB, a.vessels.data, a.attributions.data, b.vessels.data, b.attributions.data]);

  if (!caseA || !caseB) return null;

  const totalA = a.attributions.data?.items.length ?? 0;
  const totalB = b.attributions.data?.items.length ?? 0;
  const queries = [a.vessels, b.vessels, a.attributions, b.attributions];
  const blocked = !a.hasPipeline || !b.hasPipeline;
  const failed = queries.find((query) => query.isError);
  const loading = !blocked && queries.some((query) => query.data === undefined && !query.isError);
  const rankedInBoth = shared.filter(
    (vessel) =>
      vessel.candidateIn.some((ref) => ref.caseId === caseA.id) &&
      vessel.candidateIn.some((ref) => ref.caseId === caseB.id),
  ).length;

  const rankCell = (vessel: VesselAppearance, caseId: string, total: number) => {
    const entry = vessel.candidateIn.find((ref) => ref.caseId === caseId);
    if (!entry) return <span className={styles.muted}>Observed, not ranked</span>;
    return (
      <span className={styles.rankCell}>
        <span>
          Ranked {formatOrdinal(entry.rank)} of {total}
        </span>
        <ConfidenceBadge label={entry.band} />
      </span>
    );
  };

  const columns: Column<VesselAppearance>[] = [
    {
      key: 'vessel',
      header: 'Vessel',
      render: (vessel) => (
        <span className={styles.vesselCell}>
          <Link href={`/vessels/${vessel.vesselId}?case=${caseA.id}`} className={styles.vesselName}>
            {vessel.name?.trim() || 'Unnamed vessel'}
          </Link>
          <span className={styles.mono}>MMSI {formatMmsi(vessel.mmsi)}</span>
        </span>
      ),
    },
    {
      key: 'type',
      header: 'Type',
      width: '9rem',
      render: (vessel) => vessel.shipType ?? '—',
    },
    {
      key: 'a',
      header: 'In case A',
      width: '15rem',
      render: (vessel) => rankCell(vessel, caseA.id, totalA),
    },
    {
      key: 'b',
      header: 'In case B',
      width: '15rem',
      render: (vessel) => rankCell(vessel, caseB.id, totalB),
    },
  ];

  return (
    <Card
      title="Vessels seen in both"
      description="Vessels, grouped by MMSI, that appear in the AIS data of both cases — with each one’s rank wherever it was ranked as a candidate."
      flush
    >
      <div className={styles.sharedLead}>
        <Notice tone="info" label="Read this first">
          Appearing in both cases is history, not a pattern of wrongdoing. Busy shipping lanes
          produce repeat sightings: a vessel on a regular route will be seen again and again simply
          because it is often there.
        </Notice>
        {!blocked && !loading && !failed ? (
          <p className={styles.sharedSummary}>
            {shared.length === 0
              ? 'No vessel appears in both cases’ AIS data.'
              : `${pluralize(shared.length, 'vessel')} ${shared.length === 1 ? 'was' : 'were'} observed in both cases. ${
                  rankedInBoth === 0
                    ? 'None was ranked as a candidate in both.'
                    : `${formatInteger(rankedInBoth)} ${rankedInBoth === 1 ? 'was ranked as a candidate' : 'were ranked as candidates'} in both.`
                } Listed alphabetically.`}
          </p>
        ) : null}
      </div>

      {blocked ? (
        <EmptyState
          compact
          icon={<IconShip size={18} />}
          title="Needs AIS data from both cases"
          description="At least one of these cases has not run its pipeline, so there is no vessel list to match against."
        />
      ) : (
        <Table
          className={styles.sharedTable}
          caption="Vessels observed in both cases, with their candidate rank in each"
          columns={columns}
          rows={shared}
          getRowKey={(vessel) => String(vessel.mmsi)}
          loading={loading}
          skeletonRows={3}
          error={
            failed ? (
              <ErrorState compact error={failed.error} onRetry={() => void failed.refetch()} />
            ) : null
          }
          empty={
            <EmptyState
              compact
              icon={<IconShip size={18} />}
              title="No vessel appears in both"
              description="Neither case’s AIS data shares an MMSI with the other. Public AIS coverage is incomplete, so this does not mean no vessel was present in both — only that none was received in both."
            />
          }
        />
      )}

      <div className={styles.sharedFoot}>
        <NoticeStack
          label="AIS coverage"
          notices={[a.vessels.data?.notice, b.vessels.data?.notice]}
        />
        {shared.some((vessel) => vessel.candidateIn.length > 0) ? (
          <Disclaimer
            text={a.attributions.data?.disclaimer ?? b.attributions.data?.disclaimer ?? null}
          />
        ) : null}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------- page

function CompareFrame({ children }: { children: ReactNode }) {
  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        eyebrow="Investigations"
        title="Compare cases"
        subtitle="Two investigations side by side — what each produced, how they sit in space and time, and which vessels appear in both."
      />
      {children}
    </main>
  );
}

function CompareSkeleton() {
  return (
    <div className={styles.skeletonStack} aria-busy="true">
      <span className="sr-only">Loading the comparison</span>
      <Skeleton height="5rem" radius="var(--radius-lg)" />
      <div className={styles.pair}>
        <Skeleton height="14rem" radius="var(--radius-lg)" />
        <Skeleton height="14rem" radius="var(--radius-lg)" />
      </div>
      <Skeleton height="12rem" radius="var(--radius-lg)" />
    </div>
  );
}

function optionFor(item: Case): SelectOption {
  return { value: item.id, label: `${item.title} · ${item.case_ref ?? truncateId(item.id, 8, 4)}` };
}

function CompareInner() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const casesQuery = useCases({ limit: 100 });

  // Newest first, whatever order the API used: "the two most recent" is the default pair.
  const listed = useMemo(
    () =>
      [...(casesQuery.data?.items ?? [])].sort(
        (x, y) => (Date.parse(y.created_at) || 0) - (Date.parse(x.created_at) || 0),
      ),
    [casesQuery.data],
  );

  const paramA = searchParams.get('a');
  const paramB = searchParams.get('b');
  const idA = paramA || listed.find((item) => item.id !== paramB)?.id || null;
  const idB =
    (paramB && paramB !== idA ? paramB : null) ||
    listed.find((item) => item.id !== idA)?.id ||
    null;

  const a = useSide(
    'A',
    idA,
    listed.find((item) => item.id === idA),
  );
  const b = useSide(
    'B',
    idB,
    listed.find((item) => item.id === idB),
  );

  // The URL is the state: a comparison can be bookmarked or sent to a colleague.
  const setPair = (nextA: string | null, nextB: string | null) => {
    const params = new URLSearchParams(searchParams.toString());
    if (nextA) params.set('a', nextA);
    else params.delete('a');
    if (nextB) params.set('b', nextB);
    else params.delete('b');
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  };

  if (casesQuery.isError) {
    return (
      <CompareFrame>
        <ErrorState error={casesQuery.error} onRetry={() => void casesQuery.refetch()} />
      </CompareFrame>
    );
  }

  if (casesQuery.isPending) {
    return (
      <CompareFrame>
        <CompareSkeleton />
      </CompareFrame>
    );
  }

  if (!idA || !idB) {
    return (
      <CompareFrame>
        <EmptyState
          icon={<IconCompare size={18} />}
          title="A comparison needs two cases"
          description={
            listed.length === 1
              ? 'There is one case so far. Open a second investigation and the two can be compared here, side by side.'
              : 'There are no cases yet. Open two investigations to compare what each one produced.'
          }
          action={
            <LinkButton
              href="/cases/new"
              variant="primary"
              size="sm"
              leadingIcon={<IconPlus size={14} />}
            >
              New case
            </LinkButton>
          }
        />
      </CompareFrame>
    );
  }

  // A case reached by link can be older than the first 100; keep it pickable.
  const optionsFor = (side: Side, otherId: string | null): SelectOption[] => {
    const base = listed.map(optionFor);
    const extra =
      side.item && !listed.some((item) => item.id === side.item?.id) ? [optionFor(side.item)] : [];
    return [...extra, ...base].map((option) => ({ ...option, disabled: option.value === otherId }));
  };

  return (
    <CompareFrame>
      <div className={styles.pickers} role="group" aria-label="Choose the two cases to compare">
        <Select
          label="Case A"
          options={optionsFor(a, idB)}
          value={idA}
          onChange={(event) => setPair(event.target.value, idB)}
        />
        <Button
          variant="secondary"
          iconOnly
          aria-label="Swap case A and case B"
          title="Swap A and B"
          className={styles.swap}
          onClick={() => setPair(idB, idA)}
        >
          <IconSwap size={16} />
        </Button>
        <Select
          label="Case B"
          options={optionsFor(b, idA)}
          value={idB}
          onChange={(event) => setPair(idA, event.target.value)}
        />
      </div>

      <div className={styles.pair}>
        <CaseIdentity side={a} />
        <CaseIdentity side={b} />
      </div>

      <Reveal>
        <Between a={a} b={b} />
      </Reveal>

      <div className={styles.sections}>
        <Reveal>
          <DetectionsSection a={a} b={b} />
        </Reveal>
        <Reveal>
          <DriftSection a={a} b={b} />
        </Reveal>
        <Reveal>
          <CandidatesSection a={a} b={b} />
        </Reveal>
        <Reveal>
          <SharedVessels a={a} b={b} />
        </Reveal>
      </div>
    </CompareFrame>
  );
}

/**
 * Compare two cases (`/compare?a=<id>&b=<id>`).
 *
 * `useSearchParams` makes this page client-rendered below the nearest Suspense
 * boundary; without one, the production build refuses to prerender the route.
 */
export default function ComparePage() {
  return (
    <Suspense
      fallback={
        <CompareFrame>
          <CompareSkeleton />
        </CompareFrame>
      }
    >
      <CompareInner />
    </Suspense>
  );
}
