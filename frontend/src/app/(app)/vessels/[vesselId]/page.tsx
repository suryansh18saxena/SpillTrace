'use client';

import Link from 'next/link';
import { useParams, useSearchParams } from 'next/navigation';
import { Suspense, useMemo, useState } from 'react';
import type { FeatureCollection } from 'geojson';
import { ConfidenceBadge } from '@/components/attribution/ConfidenceBadge';
import { CaseSubNav } from '@/components/common/CaseSubNav';
import { MetaList, Readout, ReadoutGrid } from '@/components/common/MetaList';
import { Notice } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { VesselEventTimeline } from '@/components/vessel/VesselEventTimeline';
import { PageHeader } from '@/components/layout/PageHeader';
import { MapView, type MapDataLayer } from '@/components/map/MapView';
import { styleForLayer } from '@/components/map/layerStyles';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { LinkButton } from '@/components/ui/LinkButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { Table, type Column } from '@/components/ui/Table';
import { UNIVERSE_CASE_LIMIT, useCaseUniverse } from '@/lib/api/aggregate';
import { useVessel, useVesselPositions, useVessels } from '@/lib/api/hooks';
import type { AisPosition, TrajectorySegment } from '@/lib/api/types';
import { cx } from '@/lib/cx';
import {
  EMPTY_VALUE,
  formatBearing,
  formatCoordinate,
  formatDateTime,
  formatDateTimeCompact,
  formatDuration,
  formatImo,
  formatInteger,
  formatMmsi,
  formatNumber,
  formatPercent,
  formatScore,
  formatSpeedKn,
  pluralize,
  truncateId,
} from '@/lib/format';
import { vesselAppearances } from '@/lib/insights';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';
import history from '../vessels.module.css';

/** Positions the small map draws. The endpoint caps a page at 200 rows. */
const TRACK_LIMIT = 200;
const TABLE_PAGE = 25;

/**
 * "History across your cases": every aggregated case this MMSI was observed
 * in, with its rank where one was assigned.
 *
 * Matched by MMSI, because that is the identifier a vessel keeps from case to
 * case. The list is a record of where the vessel has appeared, nothing more: a
 * vessel on a regular route through a busy lane reappears as a candidate simply
 * because it is often there, so repetition is never framed as a pattern
 * (CON-001).
 */
function VesselCaseHistory({ mmsi, currentCaseId }: { mmsi: number; currentCaseId?: string }) {
  const universe = useCaseUniverse({ vessels: true, attributions: true });
  const loading = universe.isPending || universe.isLoadingDetails;
  const entry = vesselAppearances(universe.bundles).find((item) => item.mmsi === mmsi);
  const bundles = new Map(universe.bundles.map((bundle) => [bundle.case.id, bundle]));
  const rankedCases = new Set(entry?.candidateIn.map((ranking) => ranking.caseId));
  // The rankings' own caveats, verbatim and de-duplicated, for every case whose
  // score is shown here.
  const disclaimers = Array.from(
    new Set(
      universe.bundles
        .filter((bundle) => rankedCases.has(bundle.case.id))
        .flatMap((bundle) => [
          bundle.attributions?.disclaimer,
          bundle.attributions?.score_disclaimer,
        ])
        .map((text) => text?.trim())
        .filter((text): text is string => Boolean(text)),
    ),
  );

  let body;
  if (universe.isError) {
    body = <ErrorState compact error={universe.error} onRetry={universe.refetch} />;
  } else if (!entry && loading) {
    body = (
      <div className={history.historySkeleton} aria-busy="true">
        <span className="sr-only">Loading case history</span>
        <Skeleton height="3rem" radius="var(--radius-md)" />
        <Skeleton height="3rem" radius="var(--radius-md)" />
      </div>
    );
  } else if (!entry) {
    body = (
      <EmptyState
        compact
        title="Not found in your recent cases"
        description={`This MMSI does not appear in the ${pluralize(universe.cases.length, 'case')} aggregated here. It may belong to a case outside the ${UNIVERSE_CASE_LIMIT} most recent, or a per-case request may have failed.`}
      />
    );
  } else {
    body = (
      <>
        <dl className={history.historyStats}>
          <div>
            <dt>Observed in</dt>
            <dd>{pluralize(entry.observedIn.length, 'case')}</dd>
          </div>
          <div>
            <dt>Candidate in</dt>
            <dd>{pluralize(entry.candidateIn.length, 'case')}</dd>
          </div>
        </dl>
        <ol className={history.historyList}>
          {entry.observedIn.map((ref) => {
            const bundle = bundles.get(ref.caseId);
            const ranking = entry.candidateIn
              .filter((item) => item.caseId === ref.caseId)
              .sort((a, b) => a.rank - b.rank)[0];
            const of = bundle?.attributions?.total;
            return (
              <li
                key={ref.caseId}
                className={cx(history.historyItem, ranking && history.historyItemRanked)}
              >
                <div className={history.historyHead}>
                  <Link href={`/cases/${ref.caseId}`} className={history.historyCase}>
                    {ref.caseTitle}
                  </Link>
                  <span className={styles.badgeRow}>
                    {ref.caseId === currentCaseId ? <Badge tone="neutral">This case</Badge> : null}
                    <ProvenanceBadge provenance={bundle?.case.data_provenance} />
                  </span>
                </div>
                <div className={history.historyOutcome}>
                  {ranking ? (
                    <>
                      <span className={history.historyFigure}>
                        <span className={history.historyFigureLabel}>Rank</span>#{ranking.rank}
                        {of ? ` of ${of}` : ''}
                      </span>
                      <span className={history.historyFigure}>
                        <span className={history.historyFigureLabel}>Score</span>
                        {formatScore(ranking.score)}
                      </span>
                      <ConfidenceBadge label={ranking.band} />
                    </>
                  ) : bundle?.attributions ? (
                    <span className={history.historyUnranked}>Observed, not ranked</span>
                  ) : (
                    // Unknown is not "not ranked": the ranking itself did not load.
                    <span className={history.historyUnranked}>Ranking not available</span>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
        <p className={history.historyCaveat}>
          Appearing as a candidate in several cases is history, not evidence of wrongdoing — a
          vessel on a regular route through a busy lane will reappear simply because it is often
          there.
        </p>
        {universe.truncated ? (
          <p className={history.coverageNote}>
            Covers the {UNIVERSE_CASE_LIMIT} most recent of {universe.total} cases.
          </p>
        ) : null}
        {universe.failedDetails > 0 ? (
          <p className={history.coverageNote}>
            {universe.failedDetails} per-case request{universe.failedDetails === 1 ? '' : 's'} could
            not be loaded; this history excludes them.
          </p>
        ) : null}
        {disclaimers.length > 0 ? (
          <div className={history.historyNotices}>
            {disclaimers.map((text, index) => (
              // One label for the group; every caveat still verbatim in its own notice.
              <Notice
                key={text}
                text={text}
                label={index === 0 ? 'About the rankings' : undefined}
              />
            ))}
          </div>
        ) : null}
      </>
    );
  }

  return (
    <Card
      title="History across your cases"
      description="Every case in which this MMSI was observed in AIS, and its rank wherever it was ranked as a candidate."
    >
      {body}
    </Card>
  );
}

function VesselDetail() {
  const params = useParams<{ vesselId: string }>();
  const vesselId = params?.vesselId;
  const searchParams = useSearchParams();
  // Optional: links from inside an investigation carry the case, which is where
  // the per-segment AIS quality metrics live.
  const caseId = searchParams?.get('case') ?? undefined;

  const [offset, setOffset] = useState(0);
  const [includeInvalid, setIncludeInvalid] = useState(true);

  const vesselQuery = useVessel(vesselId);
  const trackQuery = useVesselPositions(vesselId, { limit: TRACK_LIMIT, offset: 0 });
  const tableQuery = useVesselPositions(vesselId, {
    limit: TABLE_PAGE,
    offset,
    include_invalid: includeInvalid,
  });
  const caseVesselsQuery = useVessels(caseId);

  const vessel = vesselQuery.data;
  const ais = vessel?.ais ?? null;

  const segments = useMemo<TrajectorySegment[]>(() => {
    if (!caseId || !vesselId) return [];
    const match = caseVesselsQuery.data?.items.find((item) => item.id === vesselId);
    return match?.segments ?? [];
  }, [caseId, vesselId, caseVesselsQuery.data]);

  const trackPositions = useMemo(() => trackQuery.data?.items ?? [], [trackQuery.data]);

  const trackData = useMemo<FeatureCollection>(() => {
    const coordinates = trackPositions
      .filter((position) => position.is_valid !== false)
      .map((position) => position.position?.coordinates)
      .filter((pair): pair is number[] => Array.isArray(pair) && pair.length >= 2);
    if (coordinates.length < 2) return { type: 'FeatureCollection', features: [] };
    return {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: { vessel_id: vesselId ?? '' },
          geometry: { type: 'LineString', coordinates },
        },
      ],
    };
  }, [trackPositions, vesselId]);

  const pointData = useMemo<FeatureCollection>(
    () => ({
      type: 'FeatureCollection',
      features: trackPositions
        .filter((position) => position.position?.coordinates)
        .map((position) => ({
          type: 'Feature' as const,
          properties: {
            timestamp: position.timestamp,
            sog_knots: position.sog_knots,
          },
          geometry: position.position,
        })),
    }),
    [trackPositions],
  );

  const mapLayers = useMemo<MapDataLayer[]>(() => {
    const trackStyle = styleForLayer({ id: 'trajectories', type: 'geojson' });
    const pointStyle = styleForLayer({ id: 'vessels', type: 'geojson' });
    return [
      {
        id: 'trajectories',
        kind: 'line',
        colorVar: trackStyle.colorVar,
        colorFallback: trackStyle.fallback,
        visible: true,
        opacity: 1,
        lineWidth: 2,
        data: trackData,
      },
      {
        id: 'vessels',
        kind: 'point',
        colorVar: pointStyle.colorVar,
        colorFallback: pointStyle.fallback,
        visible: true,
        opacity: 0.9,
        circleRadius: 2.5,
        data: pointData,
      },
    ];
  }, [trackData, pointData]);

  const fitTo = useMemo(() => {
    const coordinates = trackPositions
      .map((position) => position.position?.coordinates)
      .filter((pair): pair is number[] => Array.isArray(pair) && pair.length >= 2);
    if (coordinates.length === 0) return null;
    let west = Infinity;
    let east = -Infinity;
    let south = Infinity;
    let north = -Infinity;
    for (const [lon, lat] of coordinates) {
      if (typeof lon !== 'number' || typeof lat !== 'number') continue;
      west = Math.min(west, lon);
      east = Math.max(east, lon);
      south = Math.min(south, lat);
      north = Math.max(north, lat);
    }
    if (!Number.isFinite(west)) return null;
    return [west, south, east, north] as [number, number, number, number];
  }, [trackPositions]);

  const positionColumns: Column<AisPosition>[] = [
    {
      key: 'timestamp',
      header: 'Time (UTC)',
      mono: true,
      width: '11rem',
      render: (row) => formatDateTimeCompact(row.timestamp),
    },
    {
      key: 'position',
      header: 'Position',
      mono: true,
      render: (row) =>
        row.position?.coordinates
          ? formatCoordinate(row.position.coordinates[0], row.position.coordinates[1])
          : EMPTY_VALUE,
    },
    {
      key: 'sog',
      header: 'Speed',
      numeric: true,
      mono: true,
      width: '6rem',
      render: (row) => formatSpeedKn(row.sog_knots),
    },
    {
      key: 'cog',
      header: 'Course',
      numeric: true,
      mono: true,
      width: '6rem',
      render: (row) => formatBearing(row.cog_deg),
    },
    {
      key: 'valid',
      header: 'Accepted',
      width: '9rem',
      render: (row) =>
        row.is_valid ? (
          <Badge tone="success">Accepted</Badge>
        ) : (
          <Badge
            tone="warning"
            title={row.rejection_reason ?? 'Rejected by the AIS cleaning stage.'}
          >
            Rejected
          </Badge>
        ),
    },
    {
      key: 'reason',
      header: 'Quality',
      render: (row) =>
        row.rejection_reason ?? (row.quality_flags?.length ? row.quality_flags.join(', ') : '—'),
    },
  ];

  const positions = tableQuery.data?.items ?? [];
  const total = tableQuery.data?.total ?? 0;
  const coverage = useMemo(() => {
    if (segments.length === 0) return null;
    const ratios = segments
      .map((segment) => segment.coverage_ratio)
      .filter((ratio): ratio is number => typeof ratio === 'number');
    if (ratios.length === 0) return null;
    return ratios.reduce((sum, ratio) => sum + ratio, 0) / ratios.length;
  }, [segments]);
  const gapCount = segments.reduce((sum, segment) => sum + segment.gap_count, 0);
  const longestGapMinutes = segments.reduce(
    (max, segment) => Math.max(max, segment.max_gap_minutes ?? 0),
    0,
  );

  if (vesselQuery.isError) {
    return (
      <main className={layout.content} id="main-content">
        <PageHeader title="Vessel" />
        <ErrorState
          error={vesselQuery.error}
          title={vesselQuery.error?.isNotFound ? 'Vessel not found' : undefined}
          description={
            vesselQuery.error?.isNotFound
              ? 'This vessel does not exist, or it belongs to a case you are not entitled to open.'
              : undefined
          }
          onRetry={() => void vesselQuery.refetch()}
          action={
            <LinkButton href="/cases" variant="ghost" size="sm">
              Back to cases
            </LinkButton>
          }
        />
      </main>
    );
  }

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        title={
          vessel?.name?.trim() || (vesselQuery.isPending ? 'Loading vessel…' : 'Unnamed vessel')
        }
        subtitle="Reported static data, AIS quality and the track this vessel broadcast inside the case window."
        actions={
          caseId ? (
            <LinkButton href={`/cases/${caseId}/ranking`} variant="secondary" size="md">
              Back to the ranking
            </LinkButton>
          ) : (
            <LinkButton href="/cases" variant="secondary" size="md">
              Back to cases
            </LinkButton>
          )
        }
      />
      {caseId ? <CaseSubNav caseId={caseId} /> : null}

      {vesselQuery.isPending ? (
        <div className={styles.detailStack} aria-busy="true">
          <span className="sr-only">Loading vessel</span>
          <Skeleton height="6rem" radius="var(--radius-lg)" />
          <Skeleton height="18rem" radius="var(--radius-lg)" />
        </div>
      ) : !vessel ? (
        <EmptyState title="No vessel" description="This vessel record is empty." />
      ) : (
        <div className={styles.detailStack}>
          <div className={styles.badgeRow}>
            <ProvenanceBadge provenance={vessel.data_provenance} />
            {vessel.ship_type_name ? <Badge tone="neutral">{vessel.ship_type_name}</Badge> : null}
            {vessel.flag_country ? <Badge tone="neutral">{vessel.flag_country}</Badge> : null}
          </div>

          <ReadoutGrid>
            <Readout
              label="Accepted positions"
              value={formatInteger(ais?.position_count ?? null)}
              caption="AIS reports that survived the cleaning stage."
            />
            <Readout
              label="Rejected positions"
              value={formatInteger(ais?.rejected_count ?? 0)}
              caption="Reports discarded as implausible. A rejection is a data-quality judgement, not a finding about the vessel."
            />
            <Readout
              label="Reporting coverage"
              value={coverage === null ? EMPTY_VALUE : formatPercent(coverage)}
              caption={
                caseId
                  ? 'Mean coverage across this vessel’s track segments in the case window.'
                  : 'Open this vessel from a case to see per-segment coverage.'
              }
            />
            <Readout
              label="Reporting gaps"
              value={segments.length === 0 ? EMPTY_VALUE : formatInteger(gapCount)}
              caption={
                longestGapMinutes > 0
                  ? `Longest ${formatDuration(longestGapMinutes * 60)}. A gap is not evidence of wrongdoing.`
                  : 'No gaps recorded inside the tracked segments.'
              }
            />
          </ReadoutGrid>

          <Notice text={vessel.notice} label="About AIS coverage" />

          <div className={styles.detailGrid}>
            <div className={styles.detailStack}>
              <Card
                title="Track"
                description={
                  trackQuery.data && trackQuery.data.total > TRACK_LIMIT
                    ? `Drawn from the first ${formatInteger(TRACK_LIMIT)} of ${formatInteger(trackQuery.data.total)} recorded positions.`
                    : 'Drawn from every accepted AIS position in the case window.'
                }
                flush
              >
                <div className={styles.detailMap}>
                  {trackQuery.isError ? (
                    <ErrorState
                      compact
                      error={trackQuery.error}
                      onRetry={() => void trackQuery.refetch()}
                      description="The track could not be loaded."
                    />
                  ) : (
                    <MapView
                      label={`AIS track for ${vessel.name ?? 'this vessel'}`}
                      layers={mapLayers}
                      fitTo={fitTo}
                      badges={<ProvenanceBadge provenance={vessel.data_provenance} />}
                      hint={
                        trackData.features.length === 0 && !trackQuery.isPending
                          ? 'No accepted positions to draw. The vessel may have been heard only once, or every report may have been rejected by the cleaning stage.'
                          : undefined
                      }
                    />
                  )}
                </div>
              </Card>

              <Card
                title="AIS positions"
                description="Individual reports, including the ones the cleaning stage rejected, so the filtering itself is auditable."
                actions={
                  <Button
                    size="sm"
                    variant="secondary"
                    aria-pressed={includeInvalid}
                    onClick={() => {
                      setIncludeInvalid((value) => !value);
                      setOffset(0);
                    }}
                  >
                    {includeInvalid ? 'Hide rejected' : 'Show rejected'}
                  </Button>
                }
                footer={
                  <div className={styles.pagination}>
                    <span className={styles.paginationStatus}>
                      {total === 0
                        ? 'No positions'
                        : `Showing ${formatInteger(offset + 1)}–${formatInteger(Math.min(offset + TABLE_PAGE, total))} of ${formatInteger(total)}`}
                    </span>
                    <div className={styles.paginationButtons}>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={offset === 0}
                        onClick={() => setOffset((value) => Math.max(0, value - TABLE_PAGE))}
                      >
                        Previous
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={offset + TABLE_PAGE >= total}
                        onClick={() => setOffset((value) => value + TABLE_PAGE)}
                      >
                        Next
                      </Button>
                    </div>
                  </div>
                }
                flush
              >
                <Table
                  caption={`AIS positions for ${vessel.name ?? 'this vessel'}`}
                  columns={positionColumns}
                  rows={positions}
                  getRowKey={(row, index) => `${row.timestamp}-${index}`}
                  loading={tableQuery.isPending}
                  error={
                    tableQuery.isError ? (
                      <ErrorState
                        compact
                        error={tableQuery.error}
                        onRetry={() => void tableQuery.refetch()}
                      />
                    ) : undefined
                  }
                  empty={
                    <EmptyState
                      compact
                      title="No positions"
                      description="No AIS position was recorded for this vessel inside the case window."
                    />
                  }
                />
              </Card>
            </div>

            <div className={styles.detailStack}>
              <Card
                title="Reported static data"
                description="Broadcast by the vessel itself. AIS static fields are self-reported and can be incomplete or wrong."
              >
                <MetaList
                  dense
                  entries={[
                    { key: 'mmsi', term: 'MMSI', mono: true, value: formatMmsi(vessel.mmsi) },
                    {
                      key: 'imo',
                      term: 'IMO',
                      mono: true,
                      value: vessel.imo === null ? 'Not broadcast' : formatImo(vessel.imo),
                    },
                    {
                      key: 'callsign',
                      term: 'Call sign',
                      mono: true,
                      value: vessel.callsign ?? EMPTY_VALUE,
                    },
                    {
                      key: 'type',
                      term: 'Ship type',
                      value: vessel.ship_type_name ?? EMPTY_VALUE,
                      hint:
                        vessel.ship_type === null || vessel.ship_type === undefined
                          ? undefined
                          : `AIS code ${vessel.ship_type}`,
                    },
                    { key: 'flag', term: 'Flag', value: vessel.flag_country ?? EMPTY_VALUE },
                    {
                      key: 'length',
                      term: 'Length',
                      mono: true,
                      value:
                        vessel.length_m === null || vessel.length_m === undefined
                          ? EMPTY_VALUE
                          : `${formatNumber(vessel.length_m, { maximumFractionDigits: 1 })} m`,
                    },
                    {
                      key: 'width',
                      term: 'Beam',
                      mono: true,
                      value:
                        vessel.width_m === null || vessel.width_m === undefined
                          ? EMPTY_VALUE
                          : `${formatNumber(vessel.width_m, { maximumFractionDigits: 1 })} m`,
                    },
                    {
                      key: 'draught',
                      term: 'Draught',
                      mono: true,
                      value:
                        vessel.draught_m === null || vessel.draught_m === undefined
                          ? EMPTY_VALUE
                          : `${formatNumber(vessel.draught_m, { maximumFractionDigits: 1 })} m`,
                    },
                    {
                      key: 'destination',
                      term: 'Destination',
                      value: vessel.destination ?? EMPTY_VALUE,
                      hint: 'Self-declared and frequently stale.',
                    },
                    {
                      key: 'completeness',
                      term: 'Static completeness',
                      mono: true,
                      value: formatPercent(vessel.static_completeness ?? null),
                      hint: 'Share of the static fields this vessel actually broadcast.',
                    },
                    {
                      key: 'id',
                      term: 'Vessel id',
                      mono: true,
                      value: <span title={vessel.id}>{truncateId(vessel.id, 8, 6)}</span>,
                    },
                  ]}
                />
              </Card>

              <VesselCaseHistory mmsi={vessel.mmsi} currentCaseId={caseId} />

              <Card
                title="AIS quality"
                description="What the cleaning stage saw, and what it discarded."
              >
                <MetaList
                  dense
                  entries={[
                    {
                      key: 'first',
                      term: 'First position',
                      mono: true,
                      value: formatDateTime(ais?.first_position ?? vessel.first_seen ?? null),
                    },
                    {
                      key: 'last',
                      term: 'Last position',
                      mono: true,
                      value: formatDateTime(ais?.last_position ?? vessel.last_seen ?? null),
                    },
                    {
                      key: 'accepted',
                      term: 'Accepted',
                      mono: true,
                      value: formatInteger(ais?.position_count ?? null),
                    },
                    {
                      key: 'rejected',
                      term: 'Rejected',
                      mono: true,
                      value: formatInteger(ais?.rejected_count ?? 0),
                    },
                    {
                      key: 'segments',
                      term: 'Track segments',
                      mono: true,
                      value: caseId ? formatInteger(segments.length) : 'Case context needed',
                    },
                    {
                      key: 'source',
                      term: 'Source',
                      mono: true,
                      value: vessel.source ?? EMPTY_VALUE,
                    },
                  ]}
                />
              </Card>

              <Card
                title="Event timeline"
                description="Every segment boundary and every reporting gap, in order."
              >
                {caseId && caseVesselsQuery.isPending ? (
                  <Skeleton height="8rem" radius="var(--radius-md)" />
                ) : (
                  <VesselEventTimeline
                    segments={segments}
                    firstSeen={vessel.first_seen ?? ais?.first_position ?? null}
                    lastSeen={vessel.last_seen ?? ais?.last_position ?? null}
                    gapNotice={vessel.notice ?? null}
                  />
                )}
                {!caseId ? (
                  <Notice
                    tone="info"
                    label="Limited timeline"
                    text="Per-segment coverage and gap metrics are computed per case. Open this vessel from an investigation to see them."
                  />
                ) : null}
              </Card>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}

/**
 * UI-008 — vessel details.
 *
 * The `Suspense` boundary is required: this screen reads the optional `?case=`
 * search parameter, and Next refuses to prerender a client component that calls
 * `useSearchParams` without one.
 */
export default function VesselDetailsPage() {
  return (
    <Suspense
      fallback={
        <main className={layout.content} id="main-content">
          <div className={styles.detailStack} aria-busy="true">
            <span className="sr-only">Loading vessel</span>
            <Skeleton height="6rem" radius="var(--radius-lg)" />
            <Skeleton height="18rem" radius="var(--radius-lg)" />
          </div>
        </main>
      }
    >
      <VesselDetail />
    </Suspense>
  );
}
