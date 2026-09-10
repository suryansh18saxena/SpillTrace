'use client';

import { useParams } from 'next/navigation';
import { useCallback, useMemo, useState } from 'react';
import { CaseStatusBadge } from '@/components/common/CaseStatusBadge';
import { MetaList } from '@/components/common/MetaList';
import { Notice, NoticeStack } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { CandidateRanking } from '@/components/attribution/CandidateRanking';
import { JobProgress } from '@/components/jobs/JobProgress';
import { StreamStatus } from '@/components/jobs/StreamStatus';
import { LayerPanel, type LayerPanelItem } from '@/components/map/LayerPanel';
import { Legend, type LegendItem } from '@/components/map/Legend';
import { Timeline, type TimelineMarker, type TimelineSpan } from '@/components/map/Timeline';
import { SELECTABLE_LAYERS, styleForLayer } from '@/components/map/layerStyles';
import {
  MapView,
  type MapDataLayer,
  type MapFeatureSelection,
  type MapFilter,
} from '@/components/map/MapView';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { LinkButton } from '@/components/ui/LinkButton';
import { Select } from '@/components/ui/Select';
import { Skeleton } from '@/components/ui/Skeleton';
import { TabPanel, Tabs } from '@/components/ui/Tabs';
import { useToast } from '@/components/ui/Toast';
import { IconDroplet, IconReport, IconShip, IconTarget, IconWind } from '@/components/ui/Icons';
import {
  useAttributions,
  useCancelJob,
  useCase,
  useDetections,
  useDriftRuns,
  useJobs,
  useLayerDataSet,
  useLayerManifest,
  useRetryJob,
  useStartPipeline,
  useVessels,
} from '@/lib/api/hooks';
import { useJobStream } from '@/lib/api/useJobStream';
import type { ParticleProperties, PipelineMode } from '@/lib/api/types';
import { API_BASE_URL } from '@/lib/config';
import { cx } from '@/lib/cx';
import {
  formatAreaKm2,
  formatDateTimeCompact,
  formatDistanceKm,
  formatPercent,
  formatScore,
  formatSpeedKn,
  formatTimeRange,
  humanizeIdentifier,
  truncateId,
} from '@/lib/format';
import { polygonBbox } from '@/lib/geo';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';

const PIPELINE_MODES = [
  { value: 'DEMO', label: 'DEMO — deterministic synthetic data' },
  { value: 'REAL', label: 'REAL — configured external providers' },
];

interface LayerOverride {
  visible?: boolean;
  opacity?: number;
}

function asNumber(value: unknown): number | null {
  const parsed = typeof value === 'string' ? Number(value) : value;
  return typeof parsed === 'number' && Number.isFinite(parsed) ? parsed : null;
}

function asText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

/**
 * Hover text for a map feature.
 *
 * Plain text on purpose — `MapView` writes it with `textContent`, so a property
 * value that happens to contain markup can never become markup. Every line says
 * what the number is, never what it proves.
 */
function describeFeature(layerId: string, properties: Record<string, unknown>): string | null {
  switch (layerId) {
    case 'spill': {
      const area = asNumber(properties['area_km2']);
      const confidence = asNumber(properties['detection_confidence']);
      const status = asText(properties['verification_status']);
      return [
        'Detected slick',
        area === null ? null : `area ${formatAreaKm2(area)}`,
        confidence === null ? null : `detection confidence ${formatScore(confidence)}`,
        status ? `look-alike check: ${humanizeIdentifier(status)}` : null,
      ]
        .filter(Boolean)
        .join('\n');
    }
    case 'origin_region': {
      const label = asText(properties['label']) ?? 'Origin probability region';
      const area = asNumber(properties['area_km2']);
      return [
        label,
        area === null ? null : `area ${formatAreaKm2(area)}`,
        'A probability region, not a discharge coordinate.',
      ]
        .filter(Boolean)
        .join('\n');
    }
    case 'vessels': {
      const name = asText(properties['name']) ?? 'Unnamed vessel';
      const mmsi = properties['mmsi'];
      const sog = asNumber(properties['sog_knots']);
      const at = asText(properties['timestamp']);
      return [
        name,
        mmsi === undefined || mmsi === null ? null : `MMSI ${String(mmsi)}`,
        sog === null ? null : `speed ${formatSpeedKn(sog)}`,
        at ? `last report ${formatDateTimeCompact(at)}` : null,
      ]
        .filter(Boolean)
        .join('\n');
    }
    case 'trajectories': {
      const name = asText(properties['name']) ?? 'Unnamed vessel';
      const gaps = asNumber(properties['gap_count']);
      const coverage = asNumber(properties['coverage_ratio']);
      const distance = asNumber(properties['distance_km']);
      return [
        `${name} — AIS track`,
        distance === null ? null : `distance ${formatDistanceKm(distance)}`,
        coverage === null ? null : `coverage ${formatPercent(coverage)}`,
        gaps === null ? null : `${gaps} reporting gap${gaps === 1 ? '' : 's'}`,
      ]
        .filter(Boolean)
        .join('\n');
    }
    case 'scene_footprint': {
      const product = asText(properties['product_id']);
      const at = asText(properties['acquisition_time']);
      return ['SAR scene footprint', product, at ? `acquired ${formatDateTimeCompact(at)}` : null]
        .filter(Boolean)
        .join('\n');
    }
    case 'aoi':
      return asText(properties['title']) ?? 'Area of interest';
    default:
      return null;
  }
}

/** UI-004 — the investigation map, its layer switchboard and its timeline. */
export default function InvestigationPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = params?.caseId;
  const { toast } = useToast();

  const [tab, setTab] = useState('layers');
  const [overrides, setOverrides] = useState<Record<string, LayerOverride>>({});
  const [runDialogOpen, setRunDialogOpen] = useState(false);
  const [mode, setMode] = useState<PipelineMode>('DEMO');
  const [cursor, setCursor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [selection, setSelection] = useState<MapFeatureSelection | null>(null);

  const caseQuery = useCase(caseId);
  const manifestQuery = useLayerManifest(caseId);
  const detectionsQuery = useDetections(caseId);
  const driftRunsQuery = useDriftRuns(caseId);
  const vesselsQuery = useVessels(caseId);
  const attributionsQuery = useAttributions(caseId);

  const caseData = caseQuery.data;

  /*
   * Stream only while there is something to stream.
   *
   * Each open SSE connection holds a database session and a Redis subscription
   * on the server for as long as it lives, so leaving one open on a settled case
   * — in every tab, for every analyst — is a real cost for no information. A
   * COMPLETED case therefore streams nothing and polls nothing; the moment a
   * pipeline is queued the case status flips and the stream opens, with the
   * bounded job poll covering that gap.
   */
  const pipelineRunning = caseData?.status === 'QUEUED' || caseData?.status === 'RUNNING';
  const stream = useJobStream(caseId, { enabled: Boolean(caseId) && pipelineRunning });
  const jobsQuery = useJobs(caseId, { limit: 50 }, { poll: stream.shouldPoll });

  const startPipeline = useStartPipeline(caseId ?? '');
  const cancelJob = useCancelJob(caseId);
  const retryJob = useRetryJob(caseId);

  const manifestLayers = useMemo(() => manifestQuery.data?.layers ?? [], [manifestQuery.data]);

  // A layer is on unless the analyst turned it off, or the manifest says it
  // starts hidden. Tracking only the exceptions keeps this stable as the
  // manifest grows between pipeline stages.
  const isVisible = useCallback(
    (layerId: string): boolean => {
      const descriptor = manifestLayers.find((item) => item.id === layerId);
      if (descriptor?.available === false) return false;
      const override = overrides[layerId]?.visible;
      if (override !== undefined) return override;
      return descriptor?.visible ?? true;
    },
    [manifestLayers, overrides],
  );

  const opacityFor = useCallback(
    (layerId: string): number => {
      const override = overrides[layerId]?.opacity;
      if (override !== undefined) return override;
      const descriptor = manifestLayers.find((item) => item.id === layerId);
      return (descriptor ? styleForLayer(descriptor).opacity : undefined) ?? 1;
    },
    [manifestLayers, overrides],
  );

  const layerResults = useLayerDataSet(caseId, manifestLayers, isVisible);

  // ------------------------------------------------------------ time filters

  const particleIndex = manifestLayers.findIndex((layer) => layer.id === 'drift_particles');
  const particleData = particleIndex >= 0 ? layerResults[particleIndex]?.data : undefined;

  /** Simulation step indices with the wall-clock time each one represents. */
  const particleSteps = useMemo(() => {
    const byStep = new Map<number, number>();
    for (const feature of particleData?.features ?? []) {
      const props = feature.properties as unknown as ParticleProperties | null;
      if (!props) continue;
      const at = Date.parse(props.timestamp);
      if (!Number.isFinite(at)) continue;
      const existing = byStep.get(props.step_index);
      if (existing === undefined || at < existing) byStep.set(props.step_index, at);
    }
    return [...byStep.entries()]
      .map(([step, time]) => ({ step, time }))
      .sort((a, b) => a.time - b.time);
  }, [particleData]);

  const activeStep = useMemo(() => {
    if (cursor === null || particleSteps.length === 0) return null;
    let best = particleSteps[0]!;
    for (const candidate of particleSteps) {
      if (Math.abs(candidate.time - cursor) < Math.abs(best.time - cursor)) best = candidate;
    }
    return best.step;
  }, [cursor, particleSteps]);

  const vessels = useMemo(() => vesselsQuery.data?.items ?? [], [vesselsQuery.data]);

  /** Vessels whose AIS reporting covers the scrubbed instant. */
  const vesselIdsAtCursor = useMemo(() => {
    if (cursor === null) return null;
    return vessels
      .filter((vessel) => {
        const from = vessel.first_seen ? Date.parse(vessel.first_seen) : Number.NEGATIVE_INFINITY;
        const to = vessel.last_seen ? Date.parse(vessel.last_seen) : Number.POSITIVE_INFINITY;
        return cursor >= from && cursor <= to;
      })
      .map((vessel) => vessel.id);
  }, [cursor, vessels]);

  const cursorIso = cursor === null ? null : new Date(cursor).toISOString().replace(/\.\d+Z$/, 'Z');

  const filterFor = useCallback(
    (layerId: string): MapFilter | null => {
      if (cursor === null) return null;
      if (layerId === 'drift_particles') {
        return activeStep === null ? null : ['==', ['get', 'step_index'], activeStep];
      }
      if (layerId === 'trajectories' && cursorIso) {
        return [
          'all',
          ['<=', ['get', 'time_start'], cursorIso],
          ['>=', ['get', 'time_end'], cursorIso],
        ];
      }
      if (layerId === 'vessels' && vesselIdsAtCursor) {
        return ['in', ['get', 'vessel_id'], ['literal', vesselIdsAtCursor]];
      }
      return null;
    },
    [cursor, cursorIso, activeStep, vesselIdsAtCursor],
  );

  // Rebuilding the descriptor array on every render would make MapLibre re-parse
  // every GeoJSON payload, so it is keyed on what actually changes.
  const layerSignature = [
    manifestLayers
      .map(
        (layer, index) =>
          `${layer.id}:${isVisible(layer.id) ? 1 : 0}:${opacityFor(layer.id)}:${layerResults[index]?.dataUpdatedAt ?? 0}`,
      )
      .join('|'),
    cursorIso ?? 'all',
    activeStep ?? 'all',
    vesselIdsAtCursor?.join(',') ?? 'all',
  ].join('#');

  const mapLayers = useMemo<MapDataLayer[]>(() => {
    return manifestLayers.map((layer, index) => {
      const style = styleForLayer(layer);
      const result = layerResults[index];
      return {
        id: layer.id,
        kind: style.kind,
        colorVar: style.colorVar,
        colorFallback: style.fallback,
        visible: isVisible(layer.id),
        opacity: opacityFor(layer.id),
        selectable: SELECTABLE_LAYERS.has(layer.id),
        filter: filterFor(layer.id),
        ...(style.graduatedBy ? { graduatedBy: style.graduatedBy } : {}),
        ...(style.graduatedInverse ? { graduatedInverse: true } : {}),
        ...(style.circleRadius ? { circleRadius: style.circleRadius } : {}),
        ...(style.lineWidth ? { lineWidth: style.lineWidth } : {}),
        // Manifest URLs are API-relative; the tiles must be resolved against the
        // API origin (never `window.location`, which is also undefined during
        // the server render of this route).
        ...(style.kind === 'raster'
          ? { tiles: [layer.url.startsWith('http') ? layer.url : `${API_BASE_URL}${layer.url}`] }
          : { data: result?.data ?? null }),
      };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layerSignature]);

  // Not memoised: this is a handful of objects, and it has to track
  // `isFetching`, which changes without the layer payload changing.
  const panelItems: LayerPanelItem[] = manifestLayers.map((layer, index) => {
    const style = styleForLayer(layer);
    const result = layerResults[index];
    const isRaster = style.kind === 'raster';
    const count = result?.data?.features?.length ?? layer.feature_count ?? null;
    return {
      id: layer.id,
      title: layer.title,
      colorVar: style.colorVar,
      colorFallback: style.fallback,
      visible: isVisible(layer.id),
      opacity: opacityFor(layer.id),
      loading: !isRaster && Boolean(result?.isFetching),
      featureCount: isRaster ? null : count,
      notice: layer.notice ?? null,
      disabledReason:
        layer.available === false
          ? 'not produced yet'
          : !isRaster && result?.isError
            ? 'unavailable'
            : count === 0
              ? 'no features'
              : null,
    };
  });

  const legendItems: LegendItem[] = manifestLayers
    .filter((layer) => isVisible(layer.id))
    .map((layer) => {
      const style = styleForLayer(layer);
      return {
        id: layer.id,
        title: layer.title,
        colorVar: style.colorVar,
        colorFallback: style.fallback,
        shape: style.kind,
        description: style.legend ?? null,
      };
    });

  const fitTo = useMemo(() => polygonBbox(caseData?.aoi ?? null), [caseData?.aoi]);
  const jobs = jobsQuery.data?.items ?? [];
  const attributions = attributionsQuery.data?.items ?? [];
  const detections = useMemo(() => detectionsQuery.data?.items ?? [], [detectionsQuery.data]);
  const driftRuns = driftRunsQuery.data?.items ?? [];
  const activeJobs = jobs.filter(
    (job) => job.status === 'QUEUED' || job.status === 'RUNNING',
  ).length;

  const spillId = detections[0]?.id;
  const driftRun = driftRuns[0];

  const timelineSpans = useMemo<TimelineSpan[]>(() => {
    const spans: TimelineSpan[] = [];
    if (driftRun?.inferred_start && driftRun.inferred_end) {
      spans.push({
        id: 'inferred-window',
        label: 'Inferred discharge window',
        start: driftRun.inferred_start,
        end: driftRun.inferred_end,
        kind: 'window',
      });
    }
    const firsts = vessels
      .map((vessel) => (vessel.first_seen ? Date.parse(vessel.first_seen) : NaN))
      .filter(Number.isFinite);
    const lasts = vessels
      .map((vessel) => (vessel.last_seen ? Date.parse(vessel.last_seen) : NaN))
      .filter(Number.isFinite);
    if (firsts.length > 0 && lasts.length > 0) {
      spans.push({
        id: 'ais-coverage',
        label: `AIS coverage (${vessels.length} vessels)`,
        start: new Date(Math.min(...firsts)).toISOString(),
        end: new Date(Math.max(...lasts)).toISOString(),
        kind: 'coverage',
      });
    }
    return spans;
  }, [driftRun, vessels]);

  const timelineMarkers = useMemo<TimelineMarker[]>(
    () =>
      detections
        .filter((detection) => Boolean(detection.detected_at))
        .map((detection) => ({
          id: detection.id,
          label: 'Scene acquisition',
          time: detection.detected_at,
        })),
    [detections],
  );

  if (caseQuery.isError) {
    return (
      <main className={layout.content} id="main-content">
        <ErrorState
          error={caseQuery.error}
          title={caseQuery.error?.isNotFound ? 'Case not found' : undefined}
          description={
            caseQuery.error?.isNotFound
              ? 'This case does not exist, or it is not one you are entitled to open.'
              : undefined
          }
          onRetry={() => void caseQuery.refetch()}
          action={
            <LinkButton href="/cases" variant="ghost" size="sm">
              Back to cases
            </LinkButton>
          }
        />
      </main>
    );
  }

  const handleRunPipeline = () => {
    setRunDialogOpen(false);
    startPipeline.mutate(
      { mode },
      {
        onSuccess: (result) => {
          toast({
            tone: 'success',
            title: 'Pipeline started',
            description: `${result.jobs.length} stages queued in ${mode} mode.`,
          });
          setTab('pipeline');
        },
        onError: (error) => {
          toast({
            tone: 'error',
            title: 'Could not start the pipeline',
            description: error.message,
          });
        },
      },
    );
  };

  const selectionEntries = selection
    ? Object.entries(selection.properties)
        .filter(([, value]) => value !== null && value !== undefined && value !== '')
        .slice(0, 10)
    : [];
  const selectedVesselId =
    selection && (selection.layerId === 'vessels' || selection.layerId === 'trajectories')
      ? asText(selection.properties['vessel_id'])
      : null;

  return (
    <main className={cx(layout.content, layout.contentFlush)} id="main-content">
      <div className={styles.investigation}>
        <div className={styles.investigationMap}>
          <MapView
            label={`Investigation map${caseData ? ` for ${caseData.title}` : ''}`}
            layers={mapLayers}
            fitTo={fitTo}
            describeFeature={describeFeature}
            onFeatureSelect={setSelection}
            badges={
              caseData ? (
                <>
                  <ProvenanceBadge provenance={caseData.data_provenance} />
                  {activeJobs > 0 ? <Badge tone="accent">{activeJobs} stages running</Badge> : null}
                  {cursor !== null ? (
                    <Badge tone="info">Filtered to {formatDateTimeCompact(cursor)}</Badge>
                  ) : null}
                </>
              ) : null
            }
            hint={
              manifestLayers.length === 0 && !manifestQuery.isPending
                ? 'No data layers yet — the basemap shows the graticule only. Run the pipeline to produce the scene footprint, detection, origin region and vessel tracks.'
                : undefined
            }
            overlay={
              <>
                <Legend
                  items={legendItems}
                  note={
                    legendItems.some((item) => item.id === 'origin_region')
                      ? (driftRunsQuery.data?.notice ?? null)
                      : null
                  }
                />
                {caseData ? (
                  <Timeline
                    start={caseData.start_time}
                    end={caseData.end_time}
                    value={cursor}
                    onChange={setCursor}
                    playing={playing}
                    onTogglePlay={() => setPlaying((value) => !value)}
                    spans={timelineSpans}
                    markers={timelineMarkers}
                  />
                ) : null}
              </>
            }
          />
        </div>

        <aside className={styles.investigationPanel} aria-label="Case details and controls">
          <section className={styles.panelSection}>
            {caseQuery.isPending ? (
              <div className={styles.caseSummary} aria-busy="true">
                <Skeleton height="1.25rem" width="70%" />
                <Skeleton height="0.75rem" width="45%" />
                <Skeleton height="3rem" />
              </div>
            ) : caseData ? (
              <div className={styles.caseSummary}>
                <h1 className={styles.caseTitle}>{caseData.title}</h1>
                <div className={styles.badgeRow}>
                  <CaseStatusBadge status={caseData.status} />
                  <ProvenanceBadge provenance={caseData.data_provenance} />
                  {caseData.case_ref ? <Badge tone="neutral">{caseData.case_ref}</Badge> : null}
                </div>
                {caseData.description ? (
                  <p className={styles.metaValue}>{caseData.description}</p>
                ) : null}

                <MetaList
                  dense
                  entries={[
                    {
                      key: 'window',
                      term: 'Time window',
                      mono: true,
                      value: formatTimeRange(caseData.start_time, caseData.end_time),
                    },
                    {
                      key: 'area',
                      term: 'AOI area',
                      mono: true,
                      value: formatAreaKm2(caseData.aoi_area_km2 ?? null),
                    },
                    {
                      key: 'created',
                      term: 'Created',
                      mono: true,
                      value: formatDateTimeCompact(caseData.created_at),
                    },
                    {
                      key: 'id',
                      term: 'Case id',
                      mono: true,
                      value: <span title={caseData.id}>{truncateId(caseData.id, 10, 6)}</span>,
                    },
                  ]}
                />

                <Notice
                  text={caseData.notice}
                  tone={caseData.data_provenance === 'SYNTHETIC' ? 'synthetic' : 'caution'}
                  label={caseData.data_provenance === 'SYNTHETIC' ? 'Synthetic data' : undefined}
                />

                <div className={styles.subNav}>
                  <LinkButton
                    href={`/cases/${caseData.id}/spill`}
                    size="sm"
                    variant="secondary"
                    leadingIcon={<IconDroplet size={14} />}
                  >
                    Spill details
                  </LinkButton>
                  <LinkButton
                    href={`/cases/${caseData.id}/drift`}
                    size="sm"
                    variant="secondary"
                    leadingIcon={<IconWind size={14} />}
                  >
                    Drift &amp; origin
                  </LinkButton>
                  <LinkButton
                    href={`/cases/${caseData.id}/ranking`}
                    size="sm"
                    variant="secondary"
                    leadingIcon={<IconTarget size={14} />}
                  >
                    Ranking
                  </LinkButton>
                  <LinkButton
                    href={`/cases/${caseData.id}/report`}
                    size="sm"
                    variant="secondary"
                    leadingIcon={<IconReport size={14} />}
                  >
                    Report
                  </LinkButton>
                </div>

                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => setRunDialogOpen(true)}
                  loading={startPipeline.isPending}
                  loadingLabel="Starting pipeline"
                  disabled={caseData.status === 'ARCHIVED'}
                >
                  Run pipeline
                </Button>
              </div>
            ) : null}
          </section>

          {selection ? (
            <section className={styles.panelSection} aria-label="Selected map feature">
              <p className={styles.panelHeading}>
                Selected — {humanizeIdentifier(selection.layerId)}
              </p>
              <MetaList
                dense
                entries={selectionEntries.map(([key, value]) => ({
                  key,
                  term: humanizeIdentifier(key),
                  mono: true,
                  value: String(value),
                }))}
              />
              <div className={styles.subNav}>
                {selectedVesselId ? (
                  <LinkButton
                    href={`/vessels/${selectedVesselId}?case=${caseId}`}
                    size="sm"
                    variant="secondary"
                    leadingIcon={<IconShip size={14} />}
                  >
                    Open vessel
                  </LinkButton>
                ) : null}
                {selection.layerId === 'spill' && caseId ? (
                  <LinkButton href={`/cases/${caseId}/spill`} size="sm" variant="secondary">
                    Open detection
                  </LinkButton>
                ) : null}
                {selection.layerId === 'origin_region' && caseId ? (
                  <LinkButton href={`/cases/${caseId}/drift`} size="sm" variant="secondary">
                    Open drift run
                  </LinkButton>
                ) : null}
                <Button size="sm" variant="ghost" onClick={() => setSelection(null)}>
                  Clear selection
                </Button>
              </div>
            </section>
          ) : null}

          <section className={styles.panelSection}>
            <Tabs
              label="Investigation sections"
              value={tab}
              onChange={setTab}
              items={[
                { id: 'layers', label: 'Layers', count: manifestLayers.length },
                { id: 'pipeline', label: 'Pipeline', count: jobs.length },
                { id: 'candidates', label: 'Candidates', count: attributions.length },
              ]}
            />

            <TabPanel id="layers" active={tab === 'layers'}>
              <LayerPanel
                items={panelItems}
                loading={manifestQuery.isPending}
                error={manifestQuery.isError ? manifestQuery.error : undefined}
                onRetry={() => void manifestQuery.refetch()}
                onToggle={(id, visible) =>
                  setOverrides((current) => ({
                    ...current,
                    [id]: { ...current[id], visible },
                  }))
                }
                onOpacityChange={(id, opacity) =>
                  setOverrides((current) => ({
                    ...current,
                    [id]: { ...current[id], opacity },
                  }))
                }
              />
              <NoticeStack
                className={styles.panelNotices}
                notices={[
                  detectionsQuery.data?.notice,
                  vesselsQuery.data?.notice,
                  driftRunsQuery.data?.notice,
                ]}
              />
            </TabPanel>

            <TabPanel id="pipeline" active={tab === 'pipeline'}>
              <StreamStatus state={stream} />
              {jobsQuery.isError ? (
                <ErrorState
                  compact
                  error={jobsQuery.error}
                  onRetry={() => void jobsQuery.refetch()}
                />
              ) : jobsQuery.isPending ? (
                <div className={styles.jobsScroll} aria-busy="true">
                  <span className="sr-only">Loading pipeline stages</span>
                  <Skeleton height="4.5rem" radius="var(--radius-md)" />
                  <Skeleton height="4.5rem" radius="var(--radius-md)" />
                </div>
              ) : jobs.length === 0 ? (
                <EmptyState
                  compact
                  title="Pipeline not started"
                  description="No stage has run for this case yet. Running the pipeline queues scene search, detection, drift, AIS, correlation, scoring and the evidence report as tracked jobs."
                  action={
                    <Button variant="primary" size="sm" onClick={() => setRunDialogOpen(true)}>
                      Run pipeline
                    </Button>
                  }
                />
              ) : (
                <div className={styles.jobsScroll}>
                  {jobs.map((job) => (
                    <JobProgress
                      key={job.id}
                      job={job}
                      busy={cancelJob.isPending || retryJob.isPending}
                      onCancel={(jobId) => cancelJob.mutate(jobId)}
                      onRetry={(jobId) => retryJob.mutate(jobId)}
                    />
                  ))}
                </div>
              )}
            </TabPanel>

            <TabPanel id="candidates" active={tab === 'candidates'}>
              <CandidateRanking
                attributions={attributions}
                shortfallNote={attributionsQuery.data?.shortfall_note ?? null}
                disclaimer={attributionsQuery.data?.disclaimer ?? null}
                scoreDisclaimer={attributionsQuery.data?.score_disclaimer ?? null}
                proximityDisclaimer={attributionsQuery.data?.proximity_disclaimer ?? null}
                loading={attributionsQuery.isPending}
                error={attributionsQuery.isError ? attributionsQuery.error : undefined}
                onRetry={() => void attributionsQuery.refetch()}
              />
              {caseId ? (
                <div className={styles.subNav}>
                  <LinkButton href={`/cases/${caseId}/ranking`} size="sm" variant="secondary">
                    Open the full ranking
                  </LinkButton>
                </div>
              ) : null}
            </TabPanel>
          </section>

          {spillId ? (
            <section className={styles.panelSection}>
              <p className={styles.panelHeading}>Detection</p>
              <MetaList
                dense
                entries={[
                  {
                    key: 'detected',
                    term: 'Acquired',
                    mono: true,
                    value: formatDateTimeCompact(detections[0]?.detected_at),
                  },
                  {
                    key: 'area',
                    term: 'Slick area',
                    mono: true,
                    value: formatAreaKm2(detections[0]?.area_km2 ?? null),
                  },
                ]}
              />
            </section>
          ) : null}
        </aside>
      </div>

      <Dialog
        open={runDialogOpen}
        onClose={() => setRunDialogOpen(false)}
        title="Run the investigation pipeline"
        description="Every stage runs as a tracked job. You can cancel or retry any stage while it runs."
        footer={
          <>
            <Button variant="ghost" onClick={() => setRunDialogOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleRunPipeline} loading={startPipeline.isPending}>
              Start {mode} run
            </Button>
          </>
        }
      >
        <Select
          label="Mode"
          options={PIPELINE_MODES}
          value={mode}
          onChange={(event) => setMode(event.target.value as PipelineMode)}
          hint={
            mode === 'DEMO'
              ? 'Deterministic synthetic inputs. Every artifact produced is labelled SYNTHETIC and can never be mistaken for a real observation.'
              : 'Uses whichever provider each adapter is configured with. A provider that is unavailable produces a FAILED stage with a stated reason, never a silent fallback.'
          }
        />
      </Dialog>
    </main>
  );
}
