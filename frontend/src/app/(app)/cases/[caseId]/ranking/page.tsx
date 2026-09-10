'use client';

import { useParams } from 'next/navigation';
import { useMemo, useState } from 'react';
import { CaseSubNav } from '@/components/common/CaseSubNav';
import { MetaList } from '@/components/common/MetaList';
import { Notice } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { ConfidenceBadge } from '@/components/attribution/ConfidenceBadge';
import { Disclaimer } from '@/components/attribution/Disclaimer';
import { FactorTable } from '@/components/attribution/FactorTable';
import { PageHeader } from '@/components/layout/PageHeader';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { LinkButton } from '@/components/ui/LinkButton';
import { Table, type Column } from '@/components/ui/Table';
import { IconShip, IconTarget } from '@/components/ui/Icons';
import { useAttributions, useCase } from '@/lib/api/hooks';
import type { Attribution } from '@/lib/api/types';
import {
  EMPTY_VALUE,
  formatDateTimeCompact,
  formatDistanceKm,
  formatMmsi,
  formatScore,
} from '@/lib/format';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';
import attributionStyles from '@/components/attribution/attribution.module.css';

/** UI-007 — the ranked candidate vessels and the evidence behind each rank. */
export default function VesselRankingPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = params?.caseId;

  const caseQuery = useCase(caseId);
  const attributionsQuery = useAttributions(caseId);
  const [expanded, setExpanded] = useState<string | null>(null);

  const attributions = useMemo(() => attributionsQuery.data?.items ?? [], [attributionsQuery.data]);
  const listDisclaimer = attributionsQuery.data?.disclaimer ?? null;
  const scoringVersion = attributions[0]?.scoring_version;

  const columns: Column<Attribution>[] = [
    {
      key: 'rank',
      header: 'Rank',
      numeric: true,
      mono: true,
      width: '4.5rem',
      render: (row) => row.rank,
    },
    {
      key: 'vessel',
      header: 'Candidate vessel',
      render: (row) => (
        <span className={styles.cellPrimary}>
          <LinkButton
            href={`/vessels/${row.vessel.id}?case=${caseId}`}
            variant="ghost"
            size="sm"
            className={styles.cellLink}
          >
            {row.vessel.name?.trim() || 'Unnamed vessel'}
          </LinkButton>
          <span className={styles.cellSub}>MMSI {formatMmsi(row.vessel.mmsi)}</span>
        </span>
      ),
    },
    {
      key: 'score',
      header: 'Investigative score',
      numeric: true,
      mono: true,
      width: '10rem',
      render: (row) => formatScore(row.final_score),
    },
    {
      key: 'confidence',
      header: 'Evidence strength',
      width: '14rem',
      render: (row) => <ConfidenceBadge label={row.confidence_label} />,
    },
    {
      key: 'approach',
      header: 'Closest approach',
      numeric: true,
      mono: true,
      width: '9rem',
      render: (row) =>
        row.closest_approach_km === null || row.closest_approach_km === undefined
          ? EMPTY_VALUE
          : formatDistanceKm(row.closest_approach_km),
    },
    {
      key: 'when',
      header: 'At',
      mono: true,
      width: '11rem',
      render: (row) => formatDateTimeCompact(row.closest_approach_time ?? null),
    },
    {
      key: 'provenance',
      header: 'Data',
      width: '7rem',
      render: (row) => <ProvenanceBadge provenance={row.data_provenance} />,
    },
    {
      key: 'expand',
      header: 'Evidence',
      headerHidden: true,
      width: '9rem',
      render: (row) => (
        <Button
          size="sm"
          variant="ghost"
          aria-expanded={expanded === row.id}
          onClick={() => setExpanded((current) => (current === row.id ? null : row.id))}
        >
          {expanded === row.id ? 'Hide evidence' : 'Show evidence'}
        </Button>
      ),
    },
  ];

  if (!caseId) return null;

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        title="Candidate vessel ranking"
        subtitle={
          caseQuery.data
            ? `Vessels ranked for further investigation in ${caseQuery.data.title}. Ranking prioritises enquiry; it never establishes responsibility.`
            : 'Vessels ranked for further investigation. Ranking prioritises enquiry; it never establishes responsibility.'
        }
        actions={
          <LinkButton href={`/cases/${caseId}`} variant="secondary" size="md">
            Back to the map
          </LinkButton>
        }
      />
      <CaseSubNav caseId={caseId} />

      <div className={styles.detailStack}>
        {/*
          Every disclaimer the server sends, verbatim and before the numbers.
          CON-001 / CON-003: a score is investigative evidence, and the wording
          that says so is the server's, not ours.
        */}
        <Disclaimer text={listDisclaimer} />
        <Notice text={attributionsQuery.data?.score_disclaimer} label="What this score is" />
        <Notice text={attributionsQuery.data?.proximity_disclaimer} label="What proximity means" />
        <Notice
          text={attributionsQuery.data?.shortfall_note}
          label="Fewer candidates than usual"
          tone="info"
        />

        <Card
          title="Ranked candidates"
          description={
            scoringVersion
              ? `Scored with ${scoringVersion}. Every rank is auditable: expand a row to see all six weighted factors.`
              : 'Every rank is auditable: expand a row to see all six weighted factors.'
          }
          actions={
            attributions.length > 0 ? (
              <Badge tone="neutral">{attributions.length} candidates</Badge>
            ) : null
          }
          flush
        >
          <Table
            caption="Candidate vessels ranked by investigative score"
            columns={columns}
            rows={attributions}
            getRowKey={(row) => row.id}
            loading={attributionsQuery.isPending}
            error={
              attributionsQuery.isError ? (
                <ErrorState
                  compact
                  title="Ranking unavailable"
                  error={attributionsQuery.error}
                  onRetry={() => void attributionsQuery.refetch()}
                  description="The candidate ranking could not be loaded."
                />
              ) : undefined
            }
            empty={
              <EmptyState
                icon={<IconTarget size={18} />}
                title="No candidate vessels yet"
                description="Correlation and scoring have not produced any candidates for this case. Run the correlate and score stages once AIS trajectories and an origin probability region exist."
              />
            }
          />
        </Card>

        {attributions.length > 0 && attributions.length < 3 ? (
          <p className={attributionStyles.footnote}>
            Only {attributions.length} candidate{' '}
            {attributions.length === 1 ? 'vessel was' : 'vessels were'} found in the origin region
            and time window. The list is never padded to reach a target count.
          </p>
        ) : null}

        {attributions.map((attribution) => {
          if (expanded !== attribution.id) return null;
          const vesselName = attribution.vessel.name?.trim() || 'Unnamed vessel';
          return (
            <Card
              key={attribution.id}
              title={`Evidence for rank ${attribution.rank} — ${vesselName}`}
              description="All six factors, with the weight applied, the normalised score and the resulting contribution to the combined score."
              actions={
                <LinkButton
                  href={`/vessels/${attribution.vessel.id}?case=${caseId}`}
                  size="sm"
                  variant="secondary"
                  leadingIcon={<IconShip size={14} />}
                >
                  Vessel details
                </LinkButton>
              }
            >
              <MetaList
                dense
                entries={[
                  {
                    key: 'score',
                    term: 'Investigative score',
                    mono: true,
                    value: formatScore(attribution.final_score),
                    hint: 'Sum of the six contributions below.',
                  },
                  {
                    key: 'confidence',
                    term: 'Evidence strength',
                    value: <ConfidenceBadge label={attribution.confidence_label} />,
                    hint: 'How strong the supporting evidence is — not a likelihood of responsibility.',
                  },
                  {
                    key: 'version',
                    term: 'Scoring version',
                    mono: true,
                    value: attribution.scoring_version,
                  },
                  {
                    key: 'mmsi',
                    term: 'MMSI',
                    mono: true,
                    value: formatMmsi(attribution.vessel.mmsi),
                  },
                ]}
              />

              <div style={{ marginTop: 'var(--space-3)' }}>
                <FactorTable factors={attribution.factors} candidateLabel={vesselName} />
              </div>

              <div className={attributionStyles.weightsRow} style={{ marginTop: 'var(--space-3)' }}>
                {Object.entries(attribution.weights).map(([key, weight]) => (
                  <span key={key}>
                    {key}={formatScore(weight)}
                  </span>
                ))}
              </div>

              <p className={attributionStyles.footnote} style={{ marginTop: 'var(--space-2)' }}>
                Weights are versioned engineering defaults for this prototype, not scientifically
                validated legal probabilities; they must be calibrated on labelled cases before any
                score is treated as a measured likelihood.
              </p>

              <div style={{ marginTop: 'var(--space-3)' }}>
                <Disclaimer text={attribution.disclaimer} label="Applies to this candidate" />
              </div>
            </Card>
          );
        })}
      </div>
    </main>
  );
}
