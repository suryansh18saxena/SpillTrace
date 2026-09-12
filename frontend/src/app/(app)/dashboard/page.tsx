'use client';

import Link from 'next/link';
import { useSyncExternalStore } from 'react';
import { BarList, ChartFrame, ColumnChart, SegmentBar, StatTile } from '@/components/charts';
import { CaseStatusBadge } from '@/components/common/CaseStatusBadge';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { Reveal } from '@/components/motion/Reveal';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import {
  IconArrowRight,
  IconCases,
  IconDatabase,
  IconDroplet,
  IconGlobe,
  IconPlus,
  IconShield,
  IconShip,
  IconTarget,
} from '@/components/ui/Icons';
import { LinkButton } from '@/components/ui/LinkButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { useCaseUniverse, UNIVERSE_CASE_LIMIT } from '@/lib/api/aggregate';
import { useSystemProviders } from '@/lib/api/hooks';
import { getSessionSnapshot, subscribeToSession, type SessionState } from '@/lib/auth/session';
import { formatRelativeTime, formatTimeRange, humanizeIdentifier, truncateId } from '@/lib/format';
import {
  allAttributions,
  allDetections,
  caseStatusCounts,
  confidenceCounts,
  verificationCounts,
  weeklyBuckets,
} from '@/lib/insights';
import { ScreenGuide } from '@/components/explain/ScreenGuide';
import layout from '@/components/layout/layout.module.css';
import styles from './dashboard.module.css';

const SERVER_SNAPSHOT: SessionState = { status: 'unknown', user: null };

const STATUS_TONE: Record<string, string> = {
  RUNNING: 'var(--color-accent)',
  QUEUED: 'var(--color-accent)',
  COMPLETED: 'var(--color-success)',
  FAILED: 'var(--color-danger)',
};

function greeting(date: Date): string {
  const hour = date.getHours();
  if (hour < 5) return 'Working late';
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

/** Overview — the first screen after sign-in. */
export default function DashboardPage() {
  const session = useSyncExternalStore(
    subscribeToSession,
    getSessionSnapshot,
    () => SERVER_SNAPSHOT,
  );
  const universe = useCaseUniverse({ attributions: true, detections: true, vessels: true });
  const providers = useSystemProviders();

  const cases = universe.cases;
  const statuses = caseStatusCounts(cases);
  const attributions = allAttributions(universe.bundles);
  const detections = allDetections(universe.bundles);
  const bands = confidenceCounts(attributions);
  const verification = verificationCounts(detections);
  const running = (statuses['RUNNING'] ?? 0) + (statuses['QUEUED'] ?? 0);
  const completed = statuses['COMPLETED'] ?? 0;
  const setAside = (verification['FALSE_POSITIVE'] ?? 0) + (verification['REJECTED'] ?? 0);
  const weekly = weeklyBuckets(cases.map((c) => Date.parse(c.created_at)));
  const vesselCount = new Set(
    universe.bundles.flatMap((b) => (b.vessels?.items ?? []).map((v) => v.mmsi)),
  ).size;

  const providerList = providers.data?.providers ?? [];
  const realSources = providerList.filter((p) => p.mode === 'REAL').length;
  const details = universe.isPending || universe.isLoadingDetails;

  const firstName =
    session.user?.full_name?.trim().split(/\s+/)[0] ||
    session.user?.email?.split('@')[0] ||
    'analyst';
  const now = new Date();

  return (
    <main className={layout.content} id="main-content">
      {/* ------------------------------------------------------------- hero */}
      <section className={`${styles.hero} grain`} data-page-header="">
        <svg className={styles.heroRings} viewBox="0 0 416 416" aria-hidden="true">
          <circle cx="208" cy="208" r="70" />
          <circle cx="208" cy="208" r="130" />
          <circle cx="208" cy="208" r="200" />
          <g className={styles.heroSweep}>
            <path
              d="M208 208 L408 150 A206 206 0 0 1 414 208 Z"
              fill="var(--color-accent)"
              opacity="0.14"
            />
          </g>
        </svg>
        <div>
          <p className={`eyebrow ${styles.heroEyebrow}`}>Operations overview</p>
          <h1 className={styles.heroTitle}>
            {greeting(now)}, {firstName}. <em>Here is the sea today.</em>
          </h1>
          <div className={styles.heroMeta}>
            <span className={styles.heroMetaItem}>
              {running > 0 ? <span className={styles.liveDot} aria-hidden="true" /> : null}
              {running > 0
                ? `${running} investigation${running === 1 ? '' : 's'} running`
                : 'No pipelines running'}
            </span>
            <span className={styles.heroMetaItem}>
              {now.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' })}
            </span>
            {providers.data ? (
              <span className={styles.heroMetaItem}>
                {realSources} of {providerList.length} data sources live
              </span>
            ) : null}
          </div>
        </div>
        <div className={styles.heroActions}>
          <LinkButton
            href="/cases/new"
            variant="primary"
            size="lg"
            leadingIcon={<IconPlus size={16} />}
          >
            New case
          </LinkButton>
          <LinkButton
            href="/map"
            variant="secondary"
            size="lg"
            leadingIcon={<IconGlobe size={16} />}
          >
            Situational map
          </LinkButton>
        </div>
      </section>

      {universe.isError ? <ErrorState error={universe.error} onRetry={universe.refetch} /> : null}

      <ScreenGuide />

      {/* ------------------------------------------------------------- KPIs */}
      <Reveal className={styles.kpis} stagger={0.07} y={22} data-tour="dashboard-kpis">
        <StatTile
          label="Investigations"
          value={universe.isPending ? undefined : universe.total}
          loading={universe.isPending}
          icon={<IconCases size={16} />}
          caption={`${running} running · ${completed} completed`}
          trend={weekly.map((b) => b.value)}
          trendLabel="Cases opened per week, last 12 weeks"
          href="/cases"
        />
        <StatTile
          label="Slicks detected"
          value={details ? undefined : detections.length}
          loading={details}
          icon={<IconDroplet size={16} />}
          tone="signal"
          caption={
            detections.length
              ? `${verification['VERIFIED'] ?? 0} passed the look-alike checks · ${setAside} set aside`
              : 'No detections recorded yet'
          }
          href="/analytics"
        />
        <StatTile
          label="Candidate vessels ranked"
          value={details ? undefined : attributions.length}
          loading={details}
          icon={<IconTarget size={16} />}
          caption={`${vesselCount} distinct vessels observed in AIS`}
          href="/vessels"
        />
        <StatTile
          label="HIGH-band investigative signals"
          value={details ? undefined : bands.HIGH}
          loading={details}
          icon={<IconShield size={16} />}
          tone="signal"
          caption="Leads to prioritise for enquiry — not findings."
          href="/analytics"
        />
      </Reveal>

      <div className={styles.columns}>
        {/* ------------------------------------------------ left column */}
        <div className={styles.stack}>
          <Reveal>
            <Card
              title="Recent investigations"
              description="Your latest cases, with what the chain has produced so far."
              actions={
                <LinkButton
                  href="/cases"
                  variant="ghost"
                  size="sm"
                  leadingIcon={<IconArrowRight size={14} />}
                >
                  All cases
                </LinkButton>
              }
              flush
            >
              {universe.isPending ? (
                <div style={{ padding: 'var(--space-5)', display: 'grid', gap: 'var(--space-3)' }}>
                  <Skeleton height="2.75rem" />
                  <Skeleton height="2.75rem" />
                  <Skeleton height="2.75rem" />
                </div>
              ) : cases.length === 0 ? (
                <EmptyState
                  icon={<IconCases size={18} />}
                  title="No investigations yet"
                  description="A case pins an area of interest to a time window. Create one to start the chain."
                  action={
                    <LinkButton href="/cases/new" variant="primary" size="sm">
                      Create the first case
                    </LinkButton>
                  }
                />
              ) : (
                <div className={styles.caseList}>
                  {universe.bundles.slice(0, 6).map((bundle) => {
                    const item = bundle.case;
                    return (
                      <Link key={item.id} href={`/cases/${item.id}`} className={styles.caseRow}>
                        <span
                          className={styles.caseGlyph}
                          style={
                            { '--status-tone': STATUS_TONE[item.status] } as React.CSSProperties
                          }
                          aria-hidden="true"
                        >
                          <IconTarget size={17} />
                        </span>
                        <span className={styles.caseMain}>
                          <span className={styles.caseTitle}>{item.title}</span>
                          <span className={styles.caseMeta}>
                            <CaseStatusBadge status={item.status} />
                            <ProvenanceBadge provenance={item.data_provenance} />
                            <span className={styles.caseMetaMono}>
                              {item.case_ref ?? truncateId(item.id, 8, 4)}
                            </span>
                            <span className={styles.caseMetaMono}>
                              {formatTimeRange(item.start_time, item.end_time)}
                            </span>
                          </span>
                        </span>
                        <span className={styles.caseFigures}>
                          <span className={styles.figure}>
                            <span className={styles.figureValue}>
                              {bundle.detections ? bundle.detections.items.length : '—'}
                            </span>
                            <span className={styles.figureLabel}>slicks</span>
                          </span>
                          <span className={styles.figure}>
                            <span className={styles.figureValue}>
                              {bundle.attributions ? bundle.attributions.items.length : '—'}
                            </span>
                            <span className={styles.figureLabel}>candidates</span>
                          </span>
                          <span className={styles.figure}>
                            <span className={styles.figureLabel}>
                              {formatRelativeTime(item.updated_at ?? item.created_at)}
                            </span>
                          </span>
                          <span className={styles.caseArrow}>
                            <IconArrowRight size={16} />
                          </span>
                        </span>
                      </Link>
                    );
                  })}
                </div>
              )}
            </Card>
          </Reveal>

          <Reveal>
            <ChartFrame
              title="Cases opened per week"
              subtitle="Last 12 weeks, UTC. Hover or focus a column for its count."
              table={{
                caption: 'Cases opened per week',
                columns: ['Week', 'Cases opened'],
                rows: weekly.map((b) => [b.detail, b.value]),
              }}
            >
              <ColumnChart data={weekly} label="Cases opened per week" unit="cases" />
            </ChartFrame>
          </Reveal>
        </div>

        {/* ----------------------------------------------- right column */}
        <div className={styles.stack}>
          <Reveal>
            <ChartFrame
              title="Evidence strength across candidates"
              subtitle="How strong the supporting evidence is for every ranked candidate. A band is not a likelihood of responsibility."
              table={{
                caption: 'Candidates by evidence-strength band',
                columns: ['Band', 'Candidates'],
                rows: [
                  ['LOW', bands.LOW],
                  ['MODERATE', bands.MODERATE],
                  ['HIGH', bands.HIGH],
                ],
              }}
            >
              {details ? (
                <Skeleton height="3rem" />
              ) : attributions.length === 0 ? (
                <p className={styles.coverageNote}>No candidates have been ranked yet.</p>
              ) : (
                <SegmentBar
                  label="Candidates by evidence-strength band"
                  hideEmpty
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
              )}
            </ChartFrame>
          </Reveal>

          <Reveal>
            <ChartFrame
              title="Look-alike verification"
              subtitle="What the physical rules concluded about each detected slick."
            >
              <BarList
                label="Detections by verification outcome"
                empty="No detections have been verified yet."
                items={
                  detections.length === 0
                    ? []
                    : Object.entries(verification)
                        .filter(([, value]) => value > 0)
                        .map(([key, value]) => ({
                          key,
                          label: humanizeIdentifier(key),
                          value,
                        }))
                }
              />
            </ChartFrame>
          </Reveal>

          <Reveal>
            <Card
              title="Data sources"
              description="Which adapter backs each port right now. Synthetic sources are labelled everywhere their data appears."
            >
              {providers.isPending ? (
                <Skeleton height="6rem" />
              ) : (
                <div className={styles.sourceList}>
                  {providerList.map((provider) => (
                    <div key={provider.port} className={styles.source}>
                      <span className={styles.sourceIcon} aria-hidden="true">
                        {provider.port.includes('ais') ? (
                          <IconShip size={15} />
                        ) : (
                          <IconDatabase size={15} />
                        )}
                      </span>
                      <span>
                        <span className={styles.sourceName}>
                          {humanizeIdentifier(provider.port)}
                        </span>
                        <br />
                        <span className={styles.sourceImpl}>{provider.implementation}</span>
                      </span>
                      <ProvenanceBadge provenance={provider.mode} />
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </Reveal>
        </div>
      </div>

      {universe.truncated ? (
        <p className={styles.coverageNote}>
          Figures cover the {UNIVERSE_CASE_LIMIT} most recent of {universe.total} cases.
        </p>
      ) : null}
      {universe.failedDetails > 0 ? (
        <p className={styles.coverageNote}>
          {universe.failedDetails} per-case request{universe.failedDetails === 1 ? '' : 's'} could
          not be loaded; the figures above exclude them.
        </p>
      ) : null}

      <Reveal className={styles.guards} stagger={0.08}>
        <div className={styles.guard}>
          <span className={styles.guardId}>CON-001</span>
          <span>
            <strong>Nearest is not responsible.</strong> Rankings prioritise enquiry; they never
            name a vessel as the source.
          </span>
        </div>
        <div className={styles.guard}>
          <span className={styles.guardId}>CON-002</span>
          <span>
            <strong>A gap is not guilt.</strong> Missing AIS lowers confidence in a track — it is
            not evidence of wrongdoing.
          </span>
        </div>
        <div className={styles.guard}>
          <span className={styles.guardId}>CON-003</span>
          <span>
            <strong>A score is not a probability.</strong> Weights are prototype defaults until
            calibrated. <Link href="/help">How to read this →</Link>
          </span>
        </div>
      </Reveal>
    </main>
  );
}
