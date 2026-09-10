'use client';

import { useParams } from 'next/navigation';
import { useMemo, useState } from 'react';
import { CaseSubNav } from '@/components/common/CaseSubNav';
import { MetaList, Readout, ReadoutGrid } from '@/components/common/MetaList';
import { Notice, NoticeStack } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { RunManifestCard } from '@/components/common/RunManifestCard';
import { ParticleControls, type ParticleStep } from '@/components/drift/ParticleControls';
import { PageHeader } from '@/components/layout/PageHeader';
import { MapView, type MapDataLayer } from '@/components/map/MapView';
import { styleForLayer } from '@/components/map/layerStyles';
import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { LinkButton } from '@/components/ui/LinkButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { Table, type Column } from '@/components/ui/Table';
import {
  useCase,
  useDriftParticles,
  useDriftRun,
  useDriftRuns,
  useEnvironment,
  useLayerData,
} from '@/lib/api/hooks';
import type { EnvironmentSummaryEntry, OriginContourProperties } from '@/lib/api/types';
import {
  EMPTY_VALUE,
  formatAreaKm2,
  formatDateTime,
  formatDuration,
  formatInteger,
  formatNumber,
  formatPercent,
  formatScore,
  formatTimeRange,
  humanizeIdentifier,
} from '@/lib/format';
import layout from '@/components/layout/layout.module.css';
import driftStyles from '@/components/drift/drift.module.css';
import styles from '@/styles/pages.module.css';

interface ContourRow {
  label: string;
  probabilityMass: number | null;
  areaKm2: number | null;
}

interface EnvRow {
  variable: string;
  entry: EnvironmentSummaryEntry;
}

/** UI-006 — the reverse-drift run, its origin probability region and its particles. */
export default function DriftViewPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = params?.caseId;

  const [stepIndex, setStepIndex] = useState(0);
  const [playing, setPlaying] = useState(false);

  const caseQuery = useCase(caseId);
  const driftRunsQuery = useDriftRuns(caseId);
  const runId = driftRunsQuery.data?.items[0]?.id;
  const runQuery = useDriftRun(runId);
  const particlesQuery = useDriftParticles(runId);
  const environmentQuery = useEnvironment(caseId);
  const spillLayer = useLayerData(caseId, 'spill', Boolean(caseId));

  const run = runQuery.data;
  const particles = particlesQuery.data;

  /** Step indices with the wall-clock time each one represents. */
  const steps = useMemo<ParticleStep[]>(() => {
    const byStep = new Map<number, string>();
    for (const feature of particles?.features ?? []) {
      const props = feature.properties;
      if (!props) continue;
      if (!byStep.has(props.step_index)) byStep.set(props.step_index, props.timestamp);
    }
    const declared = particles?.steps ?? [];
    const ordered = declared.length > 0 ? declared : [...byStep.keys()].sort((a, b) => a - b);
    return ordered
      .filter((step) => byStep.has(step))
      .map((step) => ({ step, time: byStep.get(step) as string }));
  }, [particles]);

  const activeStep = steps[Math.min(stepIndex, Math.max(steps.length - 1, 0))]?.step ?? null;

  const particlesAtStep = useMemo(
    () =>
      (particles?.features ?? []).filter(
        (feature) => feature.properties?.step_index === activeStep,
      ),
    [particles, activeStep],
  );

  const contours = runQuery.data?.contours ?? null;

  const contourRows = useMemo<ContourRow[]>(() => {
    const features = contours?.features ?? [];
    return features
      .map((feature) => {
        const props = (feature.properties ?? {}) as OriginContourProperties;
        return {
          label: props.label ?? 'Probability contour',
          probabilityMass:
            typeof props.probability_mass === 'number' ? props.probability_mass : null,
          areaKm2: typeof props.area_km2 === 'number' ? props.area_km2 : null,
        };
      })
      .sort((a, b) => (b.probabilityMass ?? 0) - (a.probabilityMass ?? 0));
  }, [contours]);

  const mapLayers = useMemo<MapDataLayer[]>(() => {
    const originStyle = styleForLayer({ id: 'origin_region', type: 'geojson' });
    const particleStyle = styleForLayer({ id: 'drift_particles', type: 'geojson' });
    const spillStyle = styleForLayer({ id: 'spill', type: 'geojson' });
    return [
      {
        id: 'origin_region',
        kind: originStyle.kind,
        colorVar: originStyle.colorVar,
        colorFallback: originStyle.fallback,
        visible: true,
        opacity: 1,
        graduatedBy: 'probability_mass',
        graduatedInverse: true,
        selectable: true,
        data: contours ?? null,
      },
      {
        id: 'drift_particles',
        kind: particleStyle.kind,
        colorVar: particleStyle.colorVar,
        colorFallback: particleStyle.fallback,
        visible: true,
        opacity: 0.8,
        circleRadius: 2.5,
        data: { type: 'FeatureCollection', features: particlesAtStep },
      },
      {
        id: 'spill',
        kind: spillStyle.kind,
        colorVar: spillStyle.colorVar,
        colorFallback: spillStyle.fallback,
        visible: true,
        opacity: 1,
        lineWidth: 2,
        data: spillLayer.data ?? null,
      },
    ];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contours, activeStep, particlesAtStep.length, spillLayer.dataUpdatedAt]);

  const contourColumns: Column<ContourRow>[] = [
    {
      key: 'label',
      header: 'Contour',
      render: (row) => (
        <span>
          <span
            className={driftStyles.contourSwatch}
            aria-hidden="true"
            style={{
              background: 'var(--map-origin)',
              opacity: row.probabilityMass === null ? 0.4 : 1.1 - row.probabilityMass,
            }}
          />
          {row.label}
        </span>
      ),
    },
    {
      key: 'mass',
      header: 'Probability mass',
      numeric: true,
      mono: true,
      width: '10rem',
      render: (row) => formatPercent(row.probabilityMass),
    },
    {
      key: 'area',
      header: 'Area',
      numeric: true,
      mono: true,
      width: '9rem',
      render: (row) => formatAreaKm2(row.areaKm2),
    },
    {
      key: 'meaning',
      header: 'What it means',
      render: (row) =>
        row.probabilityMass === null
          ? EMPTY_VALUE
          : `${formatPercent(row.probabilityMass)} of the back-tracked particle density falls inside this region.`,
    },
  ];

  const environment = environmentQuery.data?.items[0];
  const envRows = useMemo<EnvRow[]>(
    () =>
      Object.entries(environment?.summary ?? {}).map(([variable, entry]) => ({ variable, entry })),
    [environment],
  );

  const envColumns: Column<EnvRow>[] = [
    { key: 'variable', header: 'Variable', render: (row) => humanizeIdentifier(row.variable) },
    {
      key: 'mean',
      header: 'Mean',
      numeric: true,
      mono: true,
      render: (row) => formatNumber(row.entry.mean ?? null, { maximumFractionDigits: 3 }),
    },
    {
      key: 'min',
      header: 'Min',
      numeric: true,
      mono: true,
      render: (row) => formatNumber(row.entry.min ?? null, { maximumFractionDigits: 3 }),
    },
    {
      key: 'max',
      header: 'Max',
      numeric: true,
      mono: true,
      render: (row) => formatNumber(row.entry.max ?? null, { maximumFractionDigits: 3 }),
    },
    { key: 'units', header: 'Units', mono: true, render: (row) => row.entry.units ?? EMPTY_VALUE },
  ];

  if (!caseId) return null;

  const pending = driftRunsQuery.isPending || (Boolean(runId) && runQuery.isPending);
  const failed = driftRunsQuery.isError || runQuery.isError;

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        title="Drift &amp; origin region"
        subtitle={
          caseQuery.data
            ? `Reverse-drift simulation and the origin probability region for ${caseQuery.data.title}.`
            : 'Reverse-drift simulation and the origin probability region.'
        }
        actions={
          <LinkButton href={`/cases/${caseId}`} variant="secondary" size="md">
            Back to the map
          </LinkButton>
        }
      />
      <CaseSubNav caseId={caseId} />

      {failed ? (
        <ErrorState
          error={driftRunsQuery.error ?? runQuery.error}
          onRetry={() => {
            void driftRunsQuery.refetch();
            void runQuery.refetch();
          }}
          description="The drift run for this case could not be loaded."
        />
      ) : pending ? (
        <div className={styles.detailStack} aria-busy="true">
          <span className="sr-only">Loading drift run</span>
          <Skeleton height="6rem" radius="var(--radius-lg)" />
          <Skeleton height="20rem" radius="var(--radius-lg)" />
        </div>
      ) : !run ? (
        <EmptyState
          title="No drift run yet"
          description="Reverse drift has not been simulated for this case. Run the env.fetch and drift.hindcast stages to produce an origin probability region and an inferred discharge window."
          action={
            <LinkButton href={`/cases/${caseId}`} variant="primary" size="sm">
              Back to the map
            </LinkButton>
          }
        />
      ) : (
        <div className={styles.detailStack}>
          <div className={styles.badgeRow}>
            <ProvenanceBadge provenance={run.data_provenance} />
            <Badge tone="neutral">{humanizeIdentifier(run.mode)} simulation</Badge>
            <Badge tone="neutral">engine {run.engine}</Badge>
          </div>

          {/*
            The origin-region disclaimer is not decoration. A probability region
            is not a discharge coordinate, and the server sends the exact wording
            it wants used — so it is rendered verbatim, above the map, before any
            number.
          */}
          <NoticeStack notices={[driftRunsQuery.data?.notice]} label="What the origin region is" />

          <ReadoutGrid>
            <Readout
              label="Origin confidence"
              value={formatScore(run.origin_confidence)}
              caption="How concentrated the back-tracked particle density is. It is not a probability that a discharge occurred, and it is never combined with the detection confidence."
            />
            <Readout
              label="Origin region area"
              value={formatAreaKm2(run.origin_area_km2 ?? null)}
              caption="Area of the widest probability contour."
            />
            <Readout
              label="Inferred discharge window"
              value={
                run.inferred_start && run.inferred_end
                  ? formatTimeRange(run.inferred_start, run.inferred_end)
                  : EMPTY_VALUE
              }
              caption="The interval the reverse simulation places the discharge in, not a timestamp."
            />
            <Readout
              label="Particles"
              value={formatInteger(run.number_of_particles)}
              caption={`${formatInteger(run.ensemble_members)} ensemble members over ${formatDuration(run.duration_hours * 3600)}`}
            />
          </ReadoutGrid>

          <div className={styles.detailGrid}>
            <div className={styles.detailStack}>
              <Card title="Origin probability region" flush>
                <div className={styles.detailMap}>
                  <MapView
                    label="Origin probability contours and back-tracked particles"
                    layers={mapLayers}
                    badges={<ProvenanceBadge provenance={run.data_provenance} />}
                    describeFeature={(layerId, properties) =>
                      layerId === 'origin_region'
                        ? `${String(properties['label'] ?? 'Probability contour')}\nA probability region, not a discharge coordinate.`
                        : null
                    }
                  />
                </div>
              </Card>

              {particlesQuery.isError ? (
                <ErrorState
                  compact
                  error={particlesQuery.error}
                  onRetry={() => void particlesQuery.refetch()}
                  description="The particle cloud could not be loaded, so playback is unavailable. The contours above are unaffected."
                />
              ) : particlesQuery.isPending ? (
                <Skeleton height="8rem" radius="var(--radius-md)" />
              ) : steps.length === 0 ? (
                <EmptyState
                  compact
                  title="No particle snapshots stored"
                  description="This drift run recorded contours but no per-step particle positions, so there is nothing to animate."
                />
              ) : (
                <ParticleControls
                  steps={steps}
                  index={stepIndex}
                  onIndexChange={setStepIndex}
                  playing={playing}
                  onTogglePlay={() => setPlaying((value) => !value)}
                  particleCount={particlesAtStep.length}
                />
              )}

              <Card
                title="Probability contours"
                description="Nested regions, drawn so the tightest one reads strongest. Each is a share of the back-tracked particle density, not a boundary of certainty."
                flush
              >
                <Table
                  caption="Origin probability contours"
                  columns={contourColumns}
                  rows={contourRows}
                  getRowKey={(row, index) => `${row.label}-${index}`}
                  loading={runQuery.isPending}
                  empty={
                    <EmptyState
                      compact
                      title="No contours recorded"
                      description="The drift run completed without producing probability contours."
                    />
                  }
                />
              </Card>
            </div>

            <div className={styles.detailStack}>
              <Card
                title="Simulation parameters"
                description="The exact configuration this run used. With the seed, it reproduces byte-for-byte."
              >
                <MetaList
                  dense
                  entries={[
                    { key: 'engine', term: 'Engine', mono: true, value: run.engine },
                    { key: 'mode', term: 'Mode', mono: true, value: run.mode },
                    {
                      key: 'seed',
                      term: 'Seed',
                      mono: true,
                      value: run.seed === null ? 'Not fixed' : String(run.seed),
                      hint: run.seed === null ? 'This run is not exactly reproducible.' : undefined,
                    },
                    {
                      key: 'particles',
                      term: 'Particles',
                      mono: true,
                      value: formatInteger(run.number_of_particles),
                    },
                    {
                      key: 'members',
                      term: 'Ensemble members',
                      mono: true,
                      value: formatInteger(run.ensemble_members),
                    },
                    {
                      key: 'duration',
                      term: 'Duration',
                      mono: true,
                      value: `${formatNumber(run.duration_hours, { maximumFractionDigits: 1 })} h`,
                    },
                    {
                      key: 'timestep',
                      term: 'Time step',
                      mono: true,
                      value: formatDuration(run.time_step_seconds),
                    },
                    {
                      key: 'started',
                      term: 'Window start',
                      mono: true,
                      value: formatDateTime(run.inferred_start),
                    },
                    {
                      key: 'ended',
                      term: 'Window end',
                      mono: true,
                      value: formatDateTime(run.inferred_end),
                    },
                  ]}
                />
                <Notice
                  tone="info"
                  label="Model scope"
                  text="The reverse drift models advection and turbulent diffusion only. Evaporation, emulsification, entrainment, vertical mixing and Stokes drift are not simulated, so the region widens with time faster than a full weathering model would predict."
                />
              </Card>

              {environment ? (
                <Card
                  title="Environmental forcing"
                  description={`Fields from ${environment.provider ?? environment.source}, ${environment.variables.length} variables.`}
                  flush
                >
                  <Table
                    caption="Environmental field summary"
                    columns={envColumns}
                    rows={envRows}
                    getRowKey={(row) => row.variable}
                    loading={environmentQuery.isPending}
                    empty={
                      <EmptyState
                        compact
                        title="No field summary"
                        description="The environmental run recorded no summary statistics."
                      />
                    }
                  />
                </Card>
              ) : null}

              <RunManifestCard manifest={run.run_manifest ?? null} />
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
