'use client';

import Link from 'next/link';
import { useCallback, useMemo, useState } from 'react';
import type { Feature, FeatureCollection, Point, Polygon } from 'geojson';
import { Disclaimer } from '@/components/attribution/Disclaimer';
import { CaseStatusBadge } from '@/components/common/CaseStatusBadge';
import { MetaList } from '@/components/common/MetaList';
import { Notice, NoticeStack } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { Legend, type LegendItem } from '@/components/map/Legend';
import { MapView, type MapDataLayer, type MapFeatureSelection } from '@/components/map/MapView';
import { ScreenGuide } from '@/components/explain/ScreenGuide';
import { Reveal } from '@/components/motion/Reveal';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import {
  IconArrowRight,
  IconArrowUpRight,
  IconClose,
  IconGlobe,
  IconTarget,
} from '@/components/ui/Icons';
import { LinkButton } from '@/components/ui/LinkButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { type CaseBundle, UNIVERSE_CASE_LIMIT, useCaseUniverse } from '@/lib/api/aggregate';
import { useCase } from '@/lib/api/hooks';
import type { Case } from '@/lib/api/types';
import { cx } from '@/lib/cx';
import {
  formatAreaKm2,
  formatDateTimeCompact,
  formatRelativeTime,
  formatScore,
  formatTimeRange,
  humanizeIdentifier,
  pluralize,
  truncateId,
} from '@/lib/format';
import { type BBox, polygonAreaKm2, polygonBbox } from '@/lib/geo';
import layout from '@/components/layout/layout.module.css';
import styles from './map.module.css';

// ------------------------------------------------------------------ constants

const AOI_LAYER = 'case_aoi';
const SELECTED_LAYER = 'case_aoi_selected';
const SLICK_LAYER = 'slick_centres';

const AOI_FALLBACK = '#4f8dff';
const SPILL_FALLBACK = '#f2c24c';

interface StatusFilter {
  id: string;
  label: string;
  /** `null` matches every status. */
  statuses: readonly string[] | null;
}

/**
 * "Running" includes QUEUED: from the analyst's side both mean "the chain is
 * working on it", and the overview screens count them together.
 */
const FILTERS: readonly StatusFilter[] = [
  { id: 'ALL', label: 'All', statuses: null },
  { id: 'RUNNING', label: 'Running', statuses: ['RUNNING', 'QUEUED'] },
  { id: 'COMPLETED', label: 'Completed', statuses: ['COMPLETED'] },
  { id: 'FAILED', label: 'Failed', statuses: ['FAILED'] },
  { id: 'DRAFT', label: 'Draft', statuses: ['DRAFT'] },
];

const DEFAULT_FILTER = FILTERS[0]!;

function matches(filter: StatusFilter, status: string): boolean {
  return filter.statuses === null || filter.statuses.includes(status);
}

/** Red appears only for a failed pipeline — a system state, never a finding. */
const STATUS_TONE: Record<string, string> = {
  RUNNING: 'var(--color-accent)',
  QUEUED: 'var(--color-accent)',
  COMPLETED: 'var(--color-success)',
  FAILED: 'var(--color-danger)',
};

const LEGEND_ITEMS: LegendItem[] = [
  {
    id: AOI_LAYER,
    title: 'Case area of interest',
    colorVar: '--map-aoi',
    colorFallback: AOI_FALLBACK,
    shape: 'polygon',
    description: 'Where, and over which time window, a case searched for slicks.',
  },
  {
    id: SLICK_LAYER,
    title: 'Slick centre',
    colorVar: '--map-spill',
    colorFallback: SPILL_FALLBACK,
    shape: 'point',
    description: 'The centre of a detected slick. It is not where the oil came from.',
  },
];

/** CON-008, stated where the symbol is explained rather than left to inference. */
const CENTRE_NOTE =
  'A slick marker sits at the centre of the detected slick — it is not where the oil came from. An origin is a probability region from reverse drift, shown on each case’s own map.';

const EMPTY_POLYGONS: FeatureCollection<Polygon> = { type: 'FeatureCollection', features: [] };

// -------------------------------------------------------------------- helpers

function asNumber(value: unknown): number | null {
  const parsed = typeof value === 'string' ? Number(value) : value;
  return typeof parsed === 'number' && Number.isFinite(parsed) ? parsed : null;
}

function asText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function aoiAreaKm2(item: Case): number | null {
  // The server's own figure is preferred; the geodesic estimate is computed
  // from the same polygon, so it is a measurement, not a placeholder.
  if (typeof item.aoi_area_km2 === 'number') return item.aoi_area_km2;
  const area = polygonAreaKm2(item.aoi);
  return area > 0 ? area : null;
}

function unionBbox(boxes: ReadonlyArray<BBox | null>): BBox | null {
  let out: BBox | null = null;
  for (const box of boxes) {
    if (!box) continue;
    out = out
      ? [
          Math.min(out[0], box[0]),
          Math.min(out[1], box[1]),
          Math.max(out[2], box[2]),
          Math.max(out[3], box[3]),
        ]
      : [...box];
  }
  return out;
}

interface MapModel {
  aois: FeatureCollection<Polygon>;
  slicks: FeatureCollection<Point>;
  /** Detections recorded for the cases on screen. */
  slickCount: number;
  /** Detections with no centroid — counted, but there is nowhere to draw them. */
  unplaced: number;
  bbox: BBox | null;
}

/**
 * GeoJSON for the cases on screen.
 *
 * Properties are flat primitives on purpose: MapLibre serialises nested
 * objects to strings, and `describeFeature` reads them back as plain values.
 */
function buildModel(bundles: readonly CaseBundle[]): MapModel {
  const aois: Feature<Polygon>[] = [];
  const slicks: Feature<Point>[] = [];
  let slickCount = 0;
  let unplaced = 0;

  for (const bundle of bundles) {
    const item = bundle.case;
    if (item.aoi?.type === 'Polygon') {
      aois.push({
        type: 'Feature',
        geometry: item.aoi,
        properties: {
          case_id: item.id,
          title: item.title,
          status: item.status,
          provenance: item.data_provenance ?? '',
          start_time: item.start_time,
          end_time: item.end_time,
        },
      });
    }
    for (const detection of bundle.detections?.items ?? []) {
      slickCount += 1;
      if (!detection.centroid) {
        unplaced += 1;
        continue;
      }
      slicks.push({
        type: 'Feature',
        geometry: detection.centroid,
        properties: {
          case_id: item.id,
          case_title: item.title,
          detection_id: detection.id,
          area_km2: detection.area_km2,
          detection_confidence: detection.detection_confidence,
          verification_status: detection.verification?.status ?? '',
          detected_at: detection.detected_at,
          provenance: detection.data_provenance ?? item.data_provenance ?? '',
        },
      });
    }
  }

  return {
    aois: { type: 'FeatureCollection', features: aois },
    slicks: { type: 'FeatureCollection', features: slicks },
    slickCount,
    unplaced,
    bbox: unionBbox(bundles.map((bundle) => polygonBbox(bundle.case.aoi))),
  };
}

/**
 * Hover text. Plain text only (`MapView` writes it with `textContent`), and
 * every line says what a value is — never what it proves.
 */
function describeFeature(layerId: string, properties: Record<string, unknown>): string | null {
  if (layerId === AOI_LAYER) {
    const status = asText(properties['status']);
    const provenance = asText(properties['provenance']);
    const window = formatTimeRange(
      asText(properties['start_time']),
      asText(properties['end_time']),
    );
    return [
      asText(properties['title']) ?? 'Case area of interest',
      [status ? humanizeIdentifier(status) : null, provenance].filter(Boolean).join(' · ') || null,
      `Searched ${window}`,
      'Area of interest — where the case looked, not a slick.',
    ]
      .filter(Boolean)
      .join('\n');
  }
  if (layerId === SLICK_LAYER) {
    const area = asNumber(properties['area_km2']);
    const confidence = asNumber(properties['detection_confidence']);
    const status = asText(properties['verification_status']);
    const provenance = asText(properties['provenance']);
    return [
      'Detected slick — centre',
      asText(properties['case_title']),
      area === null ? null : `area ${formatAreaKm2(area)}`,
      confidence === null ? null : `detection confidence ${formatScore(confidence)} (0–1)`,
      status ? `look-alike check: ${humanizeIdentifier(status)}` : 'look-alike check: not recorded',
      provenance === 'SYNTHETIC' ? 'SYNTHETIC data' : null,
      'The centre of the slick, not its origin.',
    ]
      .filter(Boolean)
      .join('\n');
  }
  return null;
}

// ----------------------------------------------------------------- AOI glyph

/**
 * The case's own AOI outline as a thumbnail, drawn from its polygon.
 *
 * An equirectangular projection scaled by cos(latitude) keeps the shape honest
 * at these small extents; the outline is the real one, never a stock icon.
 */
function AoiGlyph({ polygon }: { polygon: Polygon | null | undefined }) {
  const ring = (polygon?.coordinates?.[0] ?? []).filter(
    (p): p is [number, number] =>
      typeof p[0] === 'number' && typeof p[1] === 'number' && Number.isFinite(p[0] + p[1]),
  );
  const box = polygonBbox(polygon ?? null);
  if (ring.length < 3 || !box) return <IconTarget size={16} />;

  const kx = Math.cos((((box[1] + box[3]) / 2) * Math.PI) / 180);
  const width = Math.max((box[2] - box[0]) * kx, 1e-9);
  const height = Math.max(box[3] - box[1], 1e-9);
  const scale = 16 / Math.max(width, height);
  const offsetX = (24 - width * scale) / 2;
  const offsetY = (24 - height * scale) / 2;
  const points = ring
    .map(([lon, lat]) => {
      const x = offsetX + (lon - box[0]) * kx * scale;
      const y = offsetY + (box[3] - lat) * scale;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');

  return (
    <svg viewBox="0 0 24 24" width={24} height={24} aria-hidden="true" focusable="false">
      <polygon points={points} />
    </svg>
  );
}

// ---------------------------------------------------------------------- page

interface Selection {
  caseId: string;
  /** Set when the analyst picked a slick marker rather than the case area. */
  detectionId: string | null;
}

/** UI — the situational map: every case area and detected slick on one chart. */
export default function SituationalMapPage() {
  const universe = useCaseUniverse({ detections: true, attributions: true });
  const [filterId, setFilterId] = useState(DEFAULT_FILTER.id);
  const [selection, setSelection] = useState<Selection | null>(null);
  /**
   * An explicit camera request (zoom to one case, or fit all). A fresh array
   * each time, because `MapView` flies whenever `fitTo` changes identity — so
   * asking twice for the same area still re-centres after the analyst panned.
   */
  const [requestedView, setRequestedView] = useState<BBox | null>(null);

  const filter = FILTERS.find((item) => item.id === filterId) ?? DEFAULT_FILTER;
  const bundles = universe.bundles;
  const shown = bundles.filter((bundle) => matches(filter, bundle.case.status));

  // The universe hands back new bundle objects on every render; the GeoJSON is
  // keyed on what actually changes so MapLibre does not re-parse it each time.
  const signature = shown
    .map((bundle) =>
      [
        bundle.case.id,
        bundle.case.status,
        bundle.case.title,
        bundle.case.updated_at ?? '',
        bundle.case.data_provenance ?? '',
        bundle.detections
          ? bundle.detections.items
              .map((d) => `${d.id}:${d.verification?.status ?? ''}:${d.area_km2}`)
              .join(',')
          : 'pending',
      ].join('~'),
    )
    .join('|');

  const model = useMemo(
    () => buildModel(shown),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signature],
  );

  const byId = new Map(shown.map((bundle) => [bundle.case.id, bundle]));
  // A selection that the status filter hides is dropped rather than left
  // pointing at a case that is no longer on the map.
  const selectedBundle = selection ? byId.get(selection.caseId) : undefined;
  const selectedCase = selectedBundle?.case ?? null;
  const selectedDetection =
    selection?.detectionId && selectedBundle
      ? (selectedBundle.detections?.items.find((d) => d.id === selection.detectionId) ?? null)
      : null;
  // The list response carries neither the case's `notice` (e.g. the SYNTHETIC
  // demonstration warning) nor the server's AOI area, so the selection card
  // reads the case detail — the same query, and cache entry, as the case page.
  const selectedDetailQuery = useCase(selectedCase?.id);
  const selectedDetail =
    selectedDetailQuery.data && selectedDetailQuery.data.id === selectedCase?.id
      ? selectedDetailQuery.data
      : null;

  const selectedFc = useMemo<FeatureCollection<Polygon>>(
    () =>
      selectedCase?.aoi?.type === 'Polygon'
        ? {
            type: 'FeatureCollection',
            features: [{ type: 'Feature', geometry: selectedCase.aoi, properties: {} }],
          }
        : EMPTY_POLYGONS,
    [selectedCase],
  );

  const mapLayers = useMemo<MapDataLayer[]>(
    () => [
      {
        id: AOI_LAYER,
        kind: 'polygon',
        colorVar: '--map-aoi',
        colorFallback: AOI_FALLBACK,
        visible: true,
        // Light: case areas often coincide, and stacked fills would bury the
        // basemap and the slick markers under a solid block of colour. The
        // selected area is redrawn at full strength on top.
        opacity: 0.45,
        selectable: true,
        data: model.aois,
      },
      {
        // The selected area, drawn again with a heavier outline — same hue, so
        // emphasis never introduces a colour with a meaning of its own.
        id: SELECTED_LAYER,
        kind: 'polygon',
        colorVar: '--map-aoi',
        colorFallback: AOI_FALLBACK,
        visible: Boolean(selectedCase),
        opacity: 1,
        lineWidth: 3,
        data: selectedFc,
      },
      {
        id: SLICK_LAYER,
        kind: 'point',
        colorVar: '--map-spill',
        colorFallback: SPILL_FALLBACK,
        visible: true,
        opacity: 1,
        circleRadius: 6,
        selectable: true,
        data: model.slicks,
      },
    ],
    [model, selectedCase, selectedFc],
  );

  // Fit to everything on screen unless the analyst asked for something else.
  // Keyed on the numbers so a refetch with unchanged geometry never re-flies.
  const allKey = model.bbox ? model.bbox.join(',') : '';
  const allBbox = useMemo<BBox | null>(
    () => (allKey ? (allKey.split(',').map(Number) as BBox) : null),
    [allKey],
  );
  const fitTo = requestedView ?? allBbox;

  const handleFeatureSelect = useCallback((hit: MapFeatureSelection | null) => {
    if (!hit) {
      setSelection(null);
      return;
    }
    const caseId = asText(hit.properties['case_id']);
    if (!caseId) return;
    setSelection({
      caseId,
      detectionId: hit.layerId === SLICK_LAYER ? asText(hit.properties['detection_id']) : null,
    });
  }, []);

  const zoomTo = (item: Case) => {
    const box = polygonBbox(item.aoi);
    if (box) setRequestedView(box);
  };

  const focusCase = (item: Case) => {
    setSelection({ caseId: item.id, detectionId: null });
    zoomTo(item);
  };

  const fitAll = () => setRequestedView(model.bbox ? [...model.bbox] : null);

  const chooseFilter = (next: StatusFilter) => {
    setFilterId(next.id);
    // Re-frame on the new set of areas instead of holding a stale zoom.
    setRequestedView(null);
  };

  const anySynthetic = shown.some((bundle) => bundle.case.data_provenance === 'SYNTHETIC');
  const noCases = !universe.isPending && !universe.isError && universe.cases.length === 0;
  const filteredEmpty = !universe.isPending && !noCases && shown.length === 0;

  const detectionNotices = shown.map((bundle) => bundle.detections?.notice);
  const attributionDisclaimers = shown
    .filter((bundle) => (bundle.attributions?.items.length ?? 0) > 0)
    .map((bundle) => bundle.attributions?.disclaimer);
  const uniqueDisclaimers = Array.from(
    new Set(attributionDisclaimers.map((text) => text?.trim()).filter(Boolean)),
  ) as string[];

  return (
    <main className={cx(layout.content, layout.contentFlush)} id="main-content">
      <div className={styles.stage}>
        <div className={styles.mapArea}>
          <div className={styles.mapFrame}>
            <MapView
              label="Situational map of every case area of interest and detected slick"
              layers={mapLayers}
              fitTo={fitTo}
              describeFeature={describeFeature}
              onFeatureSelect={handleFeatureSelect}
              badges={
                <>
                  <Badge tone="neutral">
                    {universe.isPending
                      ? 'Loading cases…'
                      : `${pluralize(shown.length, 'case')} shown`}
                  </Badge>
                  {universe.isPending ? null : (
                    <Badge tone="neutral">
                      {universe.isLoadingDetails
                        ? 'Counting slicks…'
                        : pluralize(model.slickCount, 'slick')}
                    </Badge>
                  )}
                  {anySynthetic ? <Badge tone="synthetic">Includes SYNTHETIC data</Badge> : null}
                </>
              }
              hint={
                noCases
                  ? 'No cases yet. A case pins an area of interest to a time window; once one exists, its area appears here along with any slick it detects.'
                  : filteredEmpty
                    ? `No ${filter.label.toLowerCase()} cases right now. Choose another status to bring areas back onto the map.`
                    : undefined
              }
              globeToggle
              autoRotate
            />
          </div>
        </div>

        <aside className={styles.panel} aria-label="Cases on the map">
          <header className={styles.panelHead} data-page-header="">
            <p className="eyebrow">Operations centre</p>
            <h1 className={styles.title}>Situational map</h1>
            <p className={styles.lede}>
              Every case area and every detected slick on one chart of the sea. Select an area, a
              marker or a row to see what that case has produced so far.
            </p>
          </header>

          <ScreenGuide />

          <section className={styles.panelSection} aria-label="Filter and legend">
            <div className={styles.chips} role="group" aria-label="Filter cases by status">
              {FILTERS.map((item) => {
                const count = universe.isPending
                  ? null
                  : bundles.filter((bundle) => matches(item, bundle.case.status)).length;
                return (
                  <button
                    key={item.id}
                    type="button"
                    className={styles.chip}
                    aria-pressed={item.id === filter.id}
                    onClick={() => chooseFilter(item)}
                  >
                    {item.label}
                    <span className={styles.chipCount}>{count === null ? '…' : count}</span>
                  </button>
                );
              })}
            </div>
            {universe.isPending ? null : (
              <Legend items={LEGEND_ITEMS} note={CENTRE_NOTE} className={styles.legendBox} />
            )}
          </section>

          {selectedCase ? (
            <section
              className={styles.selection}
              aria-labelledby="map-selection-title"
              key={`${selectedCase.id}:${selectedDetection?.id ?? ''}`}
            >
              <div className={styles.selectionTop}>
                <p className={styles.sectionHeading}>
                  {selectedDetection ? 'Selected slick' : 'Selected case'}
                </p>
                <Button
                  size="sm"
                  variant="ghost"
                  iconOnly
                  aria-label="Clear selection"
                  onClick={() => setSelection(null)}
                >
                  <IconClose size={14} />
                </Button>
              </div>
              <h2 id="map-selection-title" className={styles.selectionTitle}>
                {selectedCase.title}
              </h2>
              <div className={styles.badgeRow}>
                <CaseStatusBadge status={selectedCase.status} />
                <ProvenanceBadge provenance={selectedCase.data_provenance} />
                <Badge tone="neutral">
                  {selectedCase.case_ref ?? truncateId(selectedCase.id, 8, 4)}
                </Badge>
              </div>
              <MetaList
                dense
                entries={[
                  {
                    key: 'window',
                    term: 'Time window',
                    mono: true,
                    value: formatTimeRange(selectedCase.start_time, selectedCase.end_time),
                  },
                  {
                    key: 'area',
                    term: 'AOI area',
                    mono: true,
                    value: formatAreaKm2(aoiAreaKm2(selectedDetail ?? selectedCase)),
                  },
                  {
                    key: 'slicks',
                    term: 'Slicks',
                    mono: true,
                    value: selectedBundle?.detections
                      ? selectedBundle.detections.items.length
                      : '—',
                  },
                  {
                    key: 'candidates',
                    term: 'Candidates',
                    mono: true,
                    value: selectedBundle?.attributions
                      ? selectedBundle.attributions.items.length
                      : '—',
                  },
                ]}
              />
              {selectedDetection ? (
                <div className={styles.slickBlock}>
                  <MetaList
                    dense
                    entries={[
                      {
                        key: 'slick-area',
                        term: 'Slick area',
                        mono: true,
                        value: formatAreaKm2(selectedDetection.area_km2),
                      },
                      {
                        key: 'confidence',
                        term: 'Detection confidence',
                        mono: true,
                        value: formatScore(selectedDetection.detection_confidence),
                        hint: 'On a 0–1 scale.',
                      },
                      {
                        key: 'verification',
                        term: 'Look-alike check',
                        value: selectedDetection.verification?.status
                          ? humanizeIdentifier(selectedDetection.verification.status)
                          : 'Not recorded',
                      },
                      {
                        key: 'acquired',
                        term: 'Acquired',
                        mono: true,
                        value: formatDateTimeCompact(selectedDetection.detected_at),
                      },
                    ]}
                  />
                  <p className={styles.slickNote}>
                    {/* The detection carries its own provenance, which need not match the case's. */}
                    <ProvenanceBadge provenance={selectedDetection.data_provenance} />
                    <span>The marker is this slick’s centre, not its origin.</span>
                  </p>
                </div>
              ) : null}
              <Notice
                text={selectedDetail?.notice ?? selectedCase.notice}
                tone={selectedCase.data_provenance === 'SYNTHETIC' ? 'synthetic' : 'caution'}
                label={selectedCase.data_provenance === 'SYNTHETIC' ? 'Synthetic data' : undefined}
              />
              <div className={styles.selectionActions}>
                <LinkButton
                  href={`/cases/${selectedCase.id}`}
                  variant="primary"
                  size="sm"
                  leadingIcon={<IconArrowRight size={14} />}
                >
                  Open investigation
                </LinkButton>
                <Button size="sm" variant="secondary" onClick={() => zoomTo(selectedCase)}>
                  Zoom to area
                </Button>
              </div>
            </section>
          ) : null}

          <section className={styles.panelSection} aria-labelledby="map-case-list">
            <div className={styles.listHead}>
              <h2 id="map-case-list" className={styles.sectionHeading}>
                {filter.id === 'ALL' ? 'Cases' : `${filter.label} cases`}
                {universe.isPending ? null : (
                  <span className={styles.headCount}>{shown.length}</span>
                )}
              </h2>
              {shown.length > 0 ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={fitAll}
                  leadingIcon={<IconGlobe size={14} />}
                >
                  Fit all
                </Button>
              ) : null}
            </div>

            {universe.isError ? (
              <ErrorState compact error={universe.error} onRetry={universe.refetch} />
            ) : universe.isPending ? (
              <div className={styles.caseList} aria-busy="true">
                <span className="sr-only">Loading cases</span>
                <Skeleton height="4.75rem" radius="var(--radius-md)" />
                <Skeleton height="4.75rem" radius="var(--radius-md)" />
                <Skeleton height="4.75rem" radius="var(--radius-md)" />
              </div>
            ) : noCases ? (
              <EmptyState
                compact
                icon={<IconGlobe size={18} />}
                title="Nothing on the map yet"
                description="A case pins an area of interest to a time window. Create one and its area appears here."
                action={
                  <LinkButton href="/cases/new" variant="primary" size="sm">
                    New case
                  </LinkButton>
                }
              />
            ) : shown.length === 0 ? (
              <p className={styles.fineprint}>No case is {filter.label.toLowerCase()} right now.</p>
            ) : (
              // Keyed on the filter so the rows stagger in again when it changes.
              <Reveal
                as="ul"
                key={filter.id}
                className={styles.caseList}
                stagger={0.05}
                y={12}
                immediate
              >
                {shown.map((bundle) => {
                  const item = bundle.case;
                  const isSelected = selectedCase?.id === item.id;
                  const live = item.status === 'RUNNING' || item.status === 'QUEUED';
                  return (
                    <li key={item.id} className={cx(styles.row, isSelected && styles.rowSelected)}>
                      <button
                        type="button"
                        className={styles.rowMain}
                        aria-pressed={isSelected}
                        onClick={() => focusCase(item)}
                      >
                        <span
                          className={styles.glyph}
                          style={
                            { '--status-tone': STATUS_TONE[item.status] } as React.CSSProperties
                          }
                          aria-hidden="true"
                        >
                          <AoiGlyph polygon={item.aoi} />
                          <span className={cx(styles.statusDot, live && styles.statusDotLive)} />
                        </span>
                        <span className={styles.rowText}>
                          <span className={styles.rowTitle}>{item.title}</span>
                          <span className={styles.rowMeta}>
                            <CaseStatusBadge status={item.status} />
                            <ProvenanceBadge provenance={item.data_provenance} />
                            <span className={styles.mono}>
                              {formatRelativeTime(item.updated_at ?? item.created_at)}
                            </span>
                          </span>
                          {/* "—" rather than 0 while a count is unknown (not loaded, or no
                              pipeline has run): "not counted" and "none" are different facts. */}
                          <span className={styles.rowFigures}>
                            <span>
                              <strong>
                                {bundle.detections ? bundle.detections.items.length : '—'}
                              </strong>{' '}
                              {bundle.detections?.items.length === 1 ? 'slick' : 'slicks'}
                            </span>
                            <span>
                              <strong>
                                {bundle.attributions ? bundle.attributions.items.length : '—'}
                              </strong>{' '}
                              {bundle.attributions?.items.length === 1 ? 'candidate' : 'candidates'}
                            </span>
                          </span>
                        </span>
                      </button>
                      <Link
                        href={`/cases/${item.id}`}
                        className={styles.rowOpen}
                        aria-label={`Open investigation: ${item.title}`}
                        title="Open investigation"
                      >
                        <IconArrowUpRight size={16} />
                      </Link>
                    </li>
                  );
                })}
              </Reveal>
            )}
          </section>

          <section
            className={cx(styles.panelSection, styles.panelFoot)}
            aria-label="About these figures"
          >
            {universe.isLoadingDetails ? (
              <p className={styles.fineprint}>Loading detections and candidates for each case…</p>
            ) : null}
            {model.unplaced > 0 ? (
              <p className={styles.fineprint}>
                {pluralize(model.unplaced, 'slick')} {model.unplaced === 1 ? 'has' : 'have'} no
                recorded centre and {model.unplaced === 1 ? 'is' : 'are'} counted but not drawn.
              </p>
            ) : null}
            {universe.truncated ? (
              <p className={styles.fineprint}>
                The map covers the {UNIVERSE_CASE_LIMIT} most recent of {universe.total} cases.
              </p>
            ) : null}
            {universe.failedDetails > 0 ? (
              <p className={styles.fineprint}>
                {pluralize(universe.failedDetails, 'per-case request')} could not be loaded; the
                slicks and candidate counts above exclude them.
              </p>
            ) : null}
            <NoticeStack notices={detectionNotices} label="Detections" />
            {uniqueDisclaimers.map((text) => (
              <Disclaimer key={text} text={text} label="Candidates" />
            ))}
          </section>
        </aside>
      </div>
    </main>
  );
}
