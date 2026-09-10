'use client';

import { useParams, useSearchParams } from 'next/navigation';
import { Suspense, useMemo, useState } from 'react';
import type { FeatureCollection } from 'geojson';
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
import { useVessel, useVesselPositions, useVessels } from '@/lib/api/hooks';
import type { AisPosition, TrajectorySegment } from '@/lib/api/types';
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
  formatSpeedKn,
  truncateId,
} from '@/lib/format';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';

/** Positions the small map draws. The endpoint caps a page at 200 rows. */
const TRACK_LIMIT = 200;
const TABLE_PAGE = 25;

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
