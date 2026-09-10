'use client';

import { useParams } from 'next/navigation';
import { useMemo } from 'react';
import { CaseSubNav } from '@/components/common/CaseSubNav';
import { MetaList, Readout, ReadoutGrid, Unmeasured } from '@/components/common/MetaList';
import { Notice, NoticeStack } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { RunManifestCard } from '@/components/common/RunManifestCard';
import { RulesTable, ruleOutcome } from '@/components/detection/RulesTable';
import { PageHeader } from '@/components/layout/PageHeader';
import { MapView, type MapDataLayer } from '@/components/map/MapView';
import { styleForLayer } from '@/components/map/layerStyles';
import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { LinkButton } from '@/components/ui/LinkButton';
import { Skeleton } from '@/components/ui/Skeleton';
import {
  useCase,
  useDetection,
  useDetections,
  useEnvironment,
  useLayerData,
  useVerification,
} from '@/lib/api/hooks';
import {
  EMPTY_VALUE,
  formatAreaKm2,
  formatCoordinate,
  formatDateTime,
  formatDistanceKm,
  formatNumber,
  formatPercent,
  formatScore,
  humanizeIdentifier,
  truncateId,
} from '@/lib/format';
import type { VerificationStatus } from '@/lib/api/types';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';

const VERIFICATION_TONE: Record<string, BadgeTone> = {
  VERIFIED: 'success',
  UNCERTAIN: 'warning',
  FALSE_POSITIVE: 'danger',
  REJECTED: 'danger',
};

const VERIFICATION_MEANING: Record<string, string> = {
  VERIFIED:
    'The rules that could be evaluated are consistent with an oil-like surface film. That is a classification of the image feature, not a finding about any vessel.',
  UNCERTAIN:
    'The evidence is mixed. This feature may be oil, and it may be a natural look-alike; it needs a human read before it is used.',
  FALSE_POSITIVE:
    'The rules indicate a natural look-alike — low wind, a biogenic film, a rain cell — rather than an oil slick.',
  REJECTED: 'A veto rule rejected this feature outright.',
};

/** UI-005 — the detection, its metrics, and the look-alike verification result. */
export default function SpillDetailsPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = params?.caseId;

  const caseQuery = useCase(caseId);
  const detectionsQuery = useDetections(caseId);
  const spillId = detectionsQuery.data?.items[0]?.id;
  const detectionQuery = useDetection(spillId);
  const verificationQuery = useVerification(spillId);
  const environmentQuery = useEnvironment(caseId);
  const spillLayer = useLayerData(caseId, 'spill', Boolean(caseId));
  const footprintLayer = useLayerData(caseId, 'scene_footprint', Boolean(caseId));

  const detection = detectionQuery.data;
  const verification = verificationQuery.data;
  const environment = environmentQuery.data?.items[0];

  const mapLayers = useMemo<MapDataLayer[]>(() => {
    const footprintStyle = styleForLayer({ id: 'scene_footprint', type: 'geojson' });
    const spillStyle = styleForLayer({ id: 'spill', type: 'geojson' });
    return [
      {
        id: 'scene_footprint',
        kind: footprintStyle.kind,
        colorVar: footprintStyle.colorVar,
        colorFallback: footprintStyle.fallback,
        visible: true,
        opacity: 0.6,
        data: footprintLayer.data ?? null,
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
  }, [spillLayer.dataUpdatedAt, footprintLayer.dataUpdatedAt]);

  const centroid = detection?.centroid?.coordinates;
  const fitTo = useMemo(() => {
    if (!centroid) return null;
    const [lon, lat] = centroid;
    if (typeof lon !== 'number' || typeof lat !== 'number') return null;
    return [lon - 0.6, lat - 0.4, lon + 0.6, lat + 0.4] as [number, number, number, number];
  }, [centroid]);

  const manifest = detection?.run_manifest ?? null;
  const modelName = manifest?.model_name ?? null;
  const modelVersion = manifest?.model_version ?? null;

  const ruleCounts = useMemo(() => {
    const rules = verification?.rules ?? [];
    return rules.reduce(
      (totals, rule) => {
        totals[ruleOutcome(rule)] += 1;
        return totals;
      },
      { pass: 0, fail: 0, 'not-evaluated': 0 },
    );
  }, [verification]);

  if (!caseId) return null;

  const pending = detectionsQuery.isPending || detectionQuery.isPending;
  const failed = detectionsQuery.isError || detectionQuery.isError;

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        title="Spill detection"
        subtitle={
          caseQuery.data
            ? `Detection metrics and the look-alike verification result for ${caseQuery.data.title}.`
            : 'Detection metrics and the look-alike verification result.'
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
          error={detectionsQuery.error ?? detectionQuery.error}
          onRetry={() => {
            void detectionsQuery.refetch();
            void detectionQuery.refetch();
          }}
          description="The detection for this case could not be loaded."
        />
      ) : pending ? (
        <div className={styles.detailStack} aria-busy="true">
          <span className="sr-only">Loading detection</span>
          <Skeleton height="6rem" radius="var(--radius-lg)" />
          <Skeleton height="18rem" radius="var(--radius-lg)" />
        </div>
      ) : !detection ? (
        <EmptyState
          title="No detection for this case"
          description="Nothing oil-like has been detected in this area and time window yet. Run the ml.detect and detect.verify stages to produce a detection, or accept the negative result: an empty AOI is a legitimate outcome."
          action={
            <LinkButton href={`/cases/${caseId}`} variant="primary" size="sm">
              Back to the map
            </LinkButton>
          }
        />
      ) : (
        <div className={styles.detailStack}>
          <div className={styles.badgeRow}>
            <ProvenanceBadge provenance={detection.data_provenance} />
            {verification ? (
              <Badge
                tone={VERIFICATION_TONE[verification.status] ?? 'neutral'}
                dot
                title={VERIFICATION_MEANING[verification.status as VerificationStatus] ?? undefined}
              >
                {humanizeIdentifier(verification.status)}
              </Badge>
            ) : null}
          </div>

          <NoticeStack
            notices={[detectionsQuery.data?.notice, verificationQuery.data?.notice]}
            label="What a detection is"
          />

          <ReadoutGrid>
            <Readout
              label="Slick area"
              value={formatAreaKm2(detection.area_km2)}
              caption={`Perimeter ${formatDistanceKm(detection.perimeter_km ?? null)}`}
            />
            <Readout
              label="Detection confidence"
              value={formatScore(detection.detection_confidence)}
              caption="How oil-like the pixels are. It is not a probability that any vessel discharged."
            />
            <Readout
              label="Verification confidence"
              value={verification ? formatScore(verification.verification_confidence) : EMPTY_VALUE}
              caption="How well the feature survives the look-alike rules. Kept separate from the detection confidence and never multiplied with it."
            />
            <Readout
              label="Acquired"
              value={formatDateTime(detection.detected_at)}
              caption="SAR acquisition time of the scene the feature was found in."
            />
          </ReadoutGrid>

          <div className={styles.detailGrid}>
            <div className={styles.detailStack}>
              <Card
                title="Look-alike verification"
                description="A dark patch in SAR imagery is not automatically oil. Each rule below is evaluated independently, and the ones that could not be evaluated are shown as such rather than counted either way."
              >
                {verificationQuery.isError ? (
                  <ErrorState
                    compact
                    error={verificationQuery.error}
                    onRetry={() => void verificationQuery.refetch()}
                    description="The verification result could not be loaded."
                  />
                ) : (
                  <>
                    {verification?.explanation ? (
                      <p className={styles.explanation}>{verification.explanation}</p>
                    ) : null}

                    <div className={styles.badgeRow} style={{ margin: 'var(--space-3) 0' }}>
                      <Badge tone="success">{ruleCounts.pass} passed</Badge>
                      <Badge tone="warning">{ruleCounts.fail} failed</Badge>
                      <Badge
                        tone="neutral"
                        title="These rules had no input to evaluate. They are not failures."
                      >
                        {ruleCounts['not-evaluated']} not evaluated
                      </Badge>
                    </div>

                    <RulesTable
                      rules={verification?.rules ?? []}
                      loading={verificationQuery.isPending}
                    />
                  </>
                )}
              </Card>

              <Card
                title="Detection metrics"
                description="Everything the detector measured, at the precision it measured it."
              >
                <MetaList
                  entries={[
                    {
                      key: 'mean',
                      term: 'Mean oil probability',
                      mono: true,
                      value: formatPercent(detection.mean_probability ?? null, 1),
                    },
                    {
                      key: 'max',
                      term: 'Peak oil probability',
                      mono: true,
                      value: formatPercent(detection.max_probability ?? null, 1),
                    },
                    {
                      key: 'threshold',
                      term: 'Decision threshold',
                      mono: true,
                      value:
                        detection.threshold === null || detection.threshold === undefined
                          ? EMPTY_VALUE
                          : formatScore(detection.threshold),
                      hint: 'Pixels above this probability are counted as part of the slick.',
                    },
                    {
                      key: 'centroid',
                      term: 'Centroid',
                      mono: true,
                      value: centroid
                        ? formatCoordinate(centroid[0] ?? null, centroid[1] ?? null)
                        : EMPTY_VALUE,
                    },
                    {
                      key: 'scene',
                      term: 'Scene id',
                      mono: true,
                      value: detection.scene_id ? (
                        <span title={detection.scene_id}>
                          {truncateId(detection.scene_id, 8, 6)}
                        </span>
                      ) : (
                        EMPTY_VALUE
                      ),
                    },
                    {
                      key: 'spill',
                      term: 'Detection id',
                      mono: true,
                      value: <span title={detection.id}>{truncateId(detection.id, 8, 6)}</span>,
                    },
                  ]}
                />
              </Card>

              <Card
                title="Model"
                description="Which detector produced this result, and what is known about how well it performs."
              >
                <MetaList
                  entries={[
                    {
                      key: 'name',
                      term: 'Model',
                      mono: true,
                      value: modelName ?? <Unmeasured>No model recorded</Unmeasured>,
                      hint: modelName
                        ? undefined
                        : 'This detection came from the deterministic analytical detector, which has no trained checkpoint.',
                    },
                    {
                      key: 'version',
                      term: 'Model version',
                      mono: true,
                      value: modelVersion ?? <Unmeasured>Not applicable</Unmeasured>,
                    },
                    {
                      key: 'provider',
                      term: 'Provider',
                      mono: true,
                      value: manifest?.provider ?? EMPTY_VALUE,
                    },
                    {
                      key: 'stage',
                      term: 'Produced by stage',
                      mono: true,
                      value: manifest?.stage ?? EMPTY_VALUE,
                    },
                  ]}
                />
                <Notice
                  tone="info"
                  label="Measured accuracy"
                  text="No evaluation metrics are recorded against this detector, so its accuracy on independent data is unknown. Treat the confidence as a relative ranking signal, not as a measured error rate."
                />
              </Card>
            </div>

            <div className={styles.detailStack}>
              <Card title="Where" flush>
                <div className={styles.detailMap}>
                  <MapView
                    label="Detected slick and the SAR scene footprint"
                    layers={mapLayers}
                    fitTo={fitTo}
                    badges={<ProvenanceBadge provenance={detection.data_provenance} />}
                  />
                </div>
              </Card>

              {environment ? (
                <Card
                  title="Conditions at acquisition"
                  description="The wind and current fields the verification rules were evaluated against."
                >
                  <MetaList
                    dense
                    entries={[
                      {
                        key: 'wind',
                        term: 'Wind speed',
                        mono: true,
                        value: verification?.wind?.speed_ms
                          ? `${formatNumber(verification.wind.speed_ms, { maximumFractionDigits: 1 })} m/s`
                          : EMPTY_VALUE,
                        hint:
                          verification?.wind?.direction_deg !== undefined &&
                          verification?.wind?.direction_deg !== null
                            ? `from ${formatNumber(verification.wind.direction_deg, { maximumFractionDigits: 0 })}°`
                            : undefined,
                      },
                      {
                        key: 'source',
                        term: 'Wind source',
                        mono: true,
                        value: verification?.wind?.source ?? environment.source,
                      },
                      {
                        key: 'grid',
                        term: 'Grid resolution',
                        mono: true,
                        value:
                          environment.grid_resolution_deg === null ||
                          environment.grid_resolution_deg === undefined
                            ? EMPTY_VALUE
                            : `${environment.grid_resolution_deg}°`,
                      },
                    ]}
                  />
                </Card>
              ) : null}

              <RunManifestCard manifest={manifest} />
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
