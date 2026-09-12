'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ContributionBars, ScoreMeter, SegmentBar, StatTile } from '@/components/charts';
import { CaseSubNav } from '@/components/common/CaseSubNav';
import { MetaList } from '@/components/common/MetaList';
import { Notice } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { ConfidenceBadge } from '@/components/attribution/ConfidenceBadge';
import { Disclaimer } from '@/components/attribution/Disclaimer';
import { FactorTable } from '@/components/attribution/FactorTable';
import { PlainLanguageSummary } from '@/components/attribution/PlainLanguageSummary';
import { PageHeader } from '@/components/layout/PageHeader';
import { Reveal } from '@/components/motion/Reveal';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { LinkButton } from '@/components/ui/LinkButton';
import { Table, type Column } from '@/components/ui/Table';
import { IconHistory, IconMap, IconShip, IconTarget } from '@/components/ui/Icons';
import { useCaseUniverse } from '@/lib/api/aggregate';
import { useAttribution, useAttributions, useCase } from '@/lib/api/hooks';
import type { Attribution } from '@/lib/api/types';
import {
  EMPTY_VALUE,
  formatDateTimeCompact,
  formatDistanceKm,
  formatMmsi,
  formatScore,
} from '@/lib/format';
import { confidenceCounts, vesselAppearances } from '@/lib/insights';
import { gsap, prefersReducedMotion } from '@/lib/motion/gsap';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';
import attributionStyles from '@/components/attribution/attribution.module.css';
import local from './ranking.module.css';

/**
 * Where else the analyst has seen this vessel. History, stated as history:
 * a vessel on a regular route through a busy lane reappears simply because it
 * is often there, so this is context for enquiry, never a pattern of guilt.
 */
function CrossCaseHistory({ mmsi, caseId }: { mmsi: number; caseId: string }) {
  const universe = useCaseUniverse({ vessels: true, attributions: true });
  const entry = vesselAppearances(universe.bundles).find((item) => item.mmsi === mmsi);
  const others = (entry?.observedIn ?? []).filter((c) => c.caseId !== caseId);

  return (
    <div className={local.block}>
      <p className={local.blockTitle}>
        <IconHistory size={14} /> Seen in your other cases
      </p>
      {universe.isPending || universe.isLoadingDetails ? (
        <p className={attributionStyles.footnote}>Checking your other cases…</p>
      ) : others.length === 0 ? (
        <p className={attributionStyles.footnote}>
          Not observed in any of your other {Math.max(0, universe.cases.length - 1)} cases.
        </p>
      ) : (
        <div className={local.history}>
          {others.map((ref) => {
            const ranked = entry?.candidateIn.find((c) => c.caseId === ref.caseId);
            return (
              <div key={ref.caseId} className={local.historyRow}>
                <Link href={`/cases/${ref.caseId}/ranking`}>{ref.caseTitle}</Link>
                <span className={local.historyMeta}>
                  {ranked ? (
                    <>
                      rank {ranked.rank} · {formatScore(ranked.score)}
                      <ConfidenceBadge label={ranked.band} />
                    </>
                  ) : (
                    'observed, not ranked'
                  )}
                </span>
              </div>
            );
          })}
        </div>
      )}
      <p className={attributionStyles.footnote}>
        Appearing in several cases is history, not evidence of wrongdoing — a vessel on a regular
        route through a busy lane will reappear simply because it is often there.
      </p>
    </div>
  );
}

/** UI-007 — the ranked candidate vessels and the evidence behind each rank. */
export default function VesselRankingPage() {
  const params = useParams<{ caseId: string }>();
  const caseId = params?.caseId;

  const caseQuery = useCase(caseId);
  const attributionsQuery = useAttributions(caseId);
  const [expanded, setExpanded] = useState<string | null>(null);
  const evidenceRef = useRef<HTMLDivElement | null>(null);

  const attributions = useMemo(() => attributionsQuery.data?.items ?? [], [attributionsQuery.data]);
  const listDisclaimer = attributionsQuery.data?.disclaimer ?? null;

  // The discrimination check's verdict lives on each attribution's detail. It
  // is a statement about the whole field ("capped … for every candidate"), so
  // it is read once, from the top candidate, and shown verbatim above the list.
  const topDetail = useAttribution(attributions[0]?.id);
  const discriminationNote = topDetail.data?.evidence?.['discrimination_note'];
  const scoringVersion = attributions[0]?.scoring_version;
  const bands = confidenceCounts(attributions);
  const scores = attributions.map((a) => a.final_score);

  // Bring the evidence panel into view when a row is expanded.
  useEffect(() => {
    if (!expanded || !evidenceRef.current) return;
    const node = evidenceRef.current;
    node.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
    if (!prefersReducedMotion()) {
      gsap.fromTo(
        node,
        { autoAlpha: 0, y: 16 },
        { autoAlpha: 1, y: 0, duration: 0.7, ease: 'expo.out' },
      );
    }
  }, [expanded]);

  const columns: Column<Attribution>[] = [
    {
      key: 'rank',
      header: 'Rank',
      numeric: true,
      mono: true,
      width: '4rem',
      render: (row) => row.rank,
    },
    {
      key: 'vessel',
      header: 'Candidate vessel',
      render: (row) => (
        <span className={local.vesselCell}>
          <Link href={`/vessels/${row.vessel.id}?case=${caseId}`} className={local.vesselLink}>
            {row.vessel.name?.trim() || 'Unnamed vessel'}
          </Link>
          <span className={local.vesselSub}>
            MMSI {formatMmsi(row.vessel.mmsi)}
            <ProvenanceBadge provenance={row.data_provenance} />
          </span>
        </span>
      ),
    },
    {
      key: 'score',
      header: 'Investigative score',
      numeric: true,
      width: '9rem',
      render: (row) => (
        <span className={local.scoreCell}>
          <span className={local.scoreNumber}>{formatScore(row.final_score)}</span>
          <span className={local.scoreBar} aria-hidden="true">
            <span style={{ width: `${Math.max(0, Math.min(1, row.final_score)) * 100}%` }} />
          </span>
        </span>
      ),
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
      width: '10rem',
      render: (row) => (
        <>
          {row.closest_approach_km === null || row.closest_approach_km === undefined
            ? EMPTY_VALUE
            : formatDistanceKm(row.closest_approach_km)}
          {row.closest_approach_time ? (
            <span className={local.approachSub}>
              {formatDateTimeCompact(row.closest_approach_time)}
            </span>
          ) : null}
        </>
      ),
    },
    {
      key: 'expand',
      header: 'Evidence',
      headerHidden: true,
      width: '8.5rem',
      render: (row) => (
        <Button
          size="sm"
          variant={expanded === row.id ? 'secondary' : 'ghost'}
          aria-expanded={expanded === row.id}
          onClick={() => setExpanded((current) => (current === row.id ? null : row.id))}
        >
          {expanded === row.id ? 'Hide evidence' : 'Show evidence'}
        </Button>
      ),
    },
  ];

  if (!caseId) return null;
  const selected = attributions.find((item) => item.id === expanded);

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        eyebrow={caseQuery.data?.case_ref ? `Case ${caseQuery.data.case_ref}` : 'Case'}
        title="Candidate vessel ranking"
        subtitle={
          caseQuery.data
            ? `Vessels ranked for further investigation in ${caseQuery.data.title}. Ranking prioritises enquiry; it never establishes responsibility.`
            : 'Vessels ranked for further investigation. Ranking prioritises enquiry; it never establishes responsibility.'
        }
        actions={
          <LinkButton
            href={`/cases/${caseId}`}
            variant="secondary"
            size="md"
            leadingIcon={<IconMap size={15} />}
          >
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
        <Notice
          text={typeof discriminationNote === 'string' ? discriminationNote : null}
          label="Why the evidence bands are capped"
          tone="info"
        />

        {attributions.length > 0 ? (
          <Reveal className={local.summary} stagger={0.07}>
            <StatTile
              label="Candidates ranked"
              value={attributions.length}
              icon={<IconTarget size={16} />}
              caption="Never padded to reach a target count."
            />
            <StatTile
              label="Highest investigative score"
              value={Math.max(...scores)}
              decimals={2}
              icon={<IconShip size={16} />}
              caption={`Range ${formatScore(Math.min(...scores))}–${formatScore(Math.max(...scores))} on a 0–1 scale. Not a probability.`}
            />
            <div className={local.bandCard}>
              <p className={local.bandLabel}>Evidence-strength bands</p>
              <SegmentBar
                label="Candidates by evidence-strength band"
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
          </Reveal>
        ) : null}

        <Card
          title="Ranked candidates"
          description={
            scoringVersion
              ? `Scored with ${scoringVersion}. Every rank is auditable: open a row to see all six weighted factors.`
              : 'Every rank is auditable: open a row to see all six weighted factors.'
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

        {selected ? (
          <div ref={evidenceRef} className={local.evidence}>
            <Card
              title={`Evidence for rank ${selected.rank} — ${selected.vessel.name?.trim() || 'Unnamed vessel'}`}
              description="All six factors, with the weight applied, the normalised score and the resulting contribution to the combined score."
              actions={
                <LinkButton
                  href={`/vessels/${selected.vessel.id}?case=${caseId}`}
                  size="sm"
                  variant="secondary"
                  leadingIcon={<IconShip size={14} />}
                >
                  Vessel details
                </LinkButton>
              }
            >
              <div className={local.evidenceGrid}>
                <div className={local.block}>
                  <p className={local.blockTitle}>Where the score sits</p>
                  <ScoreMeter value={selected.final_score} band={selected.confidence_label} />
                  <div className={local.bandLine}>
                    <ConfidenceBadge label={selected.confidence_label} />
                    <span>
                      How strong the supporting evidence is — not a likelihood of responsibility.
                    </span>
                  </div>
                  <MetaList
                    dense
                    entries={[
                      {
                        key: 'version',
                        term: 'Scoring version',
                        mono: true,
                        value: selected.scoring_version,
                      },
                      {
                        key: 'mmsi',
                        term: 'MMSI',
                        mono: true,
                        value: formatMmsi(selected.vessel.mmsi),
                      },
                    ]}
                  />
                  <PlainLanguageSummary attribution={selected} all={attributions} />
                </div>

                <div className={local.block}>
                  <p className={local.blockTitle}>How the score was built</p>
                  <ContributionBars
                    factors={selected.factors}
                    candidateLabel={selected.vessel.name?.trim() || 'Unnamed vessel'}
                  />
                  <p className={attributionStyles.footnote}>
                    Pale track = the factor’s weight (the most it can contribute); solid = what it
                    actually contributed. The contributions sum to the investigative score.
                  </p>
                </div>
              </div>

              <div className={local.divider} />

              <FactorTable
                factors={selected.factors}
                candidateLabel={selected.vessel.name?.trim() || 'Unnamed vessel'}
              />

              <div className={attributionStyles.weightsRow} style={{ marginTop: 'var(--space-4)' }}>
                {Object.entries(selected.weights).map(([key, weight]) => (
                  <span key={key}>
                    {key}={formatScore(weight)}
                  </span>
                ))}
              </div>

              <p className={attributionStyles.footnote} style={{ marginTop: 'var(--space-3)' }}>
                Weights are versioned engineering defaults for this prototype, not scientifically
                validated legal probabilities; they must be calibrated on labelled cases before any
                score is treated as a measured likelihood.
              </p>

              <div className={local.divider} />

              <CrossCaseHistory mmsi={selected.vessel.mmsi} caseId={caseId} />

              <div style={{ marginTop: 'var(--space-5)' }}>
                <Disclaimer text={selected.disclaimer} label="Applies to this candidate" />
              </div>
            </Card>
          </div>
        ) : null}
      </div>
    </main>
  );
}
