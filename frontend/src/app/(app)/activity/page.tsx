'use client';

import { useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { useEffect, useState, type ReactNode } from 'react';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { JobStatusBadge } from '@/components/jobs/JobStatusBadge';
import { PageHeader } from '@/components/layout/PageHeader';
import { Reveal } from '@/components/motion/Reveal';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import {
  IconActivity,
  IconCases,
  IconCpu,
  IconDatabase,
  IconDroplet,
  IconRefresh,
  IconReport,
  IconSatellite,
  IconSearch,
  IconShip,
  IconTarget,
  IconWind,
} from '@/components/ui/Icons';
import { Input } from '@/components/ui/Input';
import { LinkButton } from '@/components/ui/LinkButton';
import { Select } from '@/components/ui/Select';
import { Skeleton } from '@/components/ui/Skeleton';
import { useCaseUniverse, UNIVERSE_CASE_LIMIT, type CaseBundle } from '@/lib/api/aggregate';
import { queryKeys } from '@/lib/api/hooks';
import { JOB_TYPES, type Case, type Job } from '@/lib/api/types';
import { cx } from '@/lib/cx';
import {
  EMPTY_VALUE,
  formatDate,
  formatDateTime,
  formatDuration,
  formatRelativeTime,
  formatTime,
  formatTimeRange,
  humanizeIdentifier,
  pluralize,
  truncateId,
} from '@/lib/format';
import layout from '@/components/layout/layout.module.css';
import styles from './activity.module.css';

/** `useCaseUniverse` asks each case for this many jobs, newest first. */
const JOBS_PER_CASE = 50;
/** Rows rendered at once; "Show more" adds another page. */
const PAGE_SIZE = 60;
/** How often in-flight cases are re-read while a stage is running. */
const POLL_MS = 10_000;
const DAY_MS = 86_400_000;
/** Stage-select value for the synthetic "case opened" events. */
const CASE_STAGE = '__case-opened';

// ---------------------------------------------------------------- stages

/** Plain names for the stable job types; unknown types fall back to humanised ids. */
const STAGE_NAMES: Record<string, string> = {
  'scene.search': 'Scene search',
  'scene.download': 'Scene download',
  'sar.preprocess': 'SAR preprocessing',
  'ml.detect': 'Slick detection',
  'detect.verify': 'Look-alike verification',
  'env.fetch': 'Environmental data',
  'drift.hindcast': 'Drift hindcast',
  'ais.ingest': 'AIS ingestion',
  'ais.clean': 'AIS cleaning',
  'traj.build': 'Trajectory building',
  correlate: 'Vessel correlation',
  score: 'Candidate scoring',
  'report.build': 'Evidence report',
  'demo.seed': 'Synthetic data seeding',
};

function stageName(jobType: string): string {
  return STAGE_NAMES[jobType] ?? humanizeIdentifier(jobType);
}

function stageIcon(jobType: string): ReactNode {
  if (jobType.startsWith('scene.') || jobType.startsWith('sar.'))
    return <IconSatellite size={16} />;
  if (jobType === 'ml.detect' || jobType.startsWith('detect.')) return <IconDroplet size={16} />;
  if (jobType.startsWith('env.') || jobType.startsWith('drift.')) return <IconWind size={16} />;
  if (jobType.startsWith('ais.') || jobType.startsWith('traj.')) return <IconShip size={16} />;
  if (jobType === 'correlate' || jobType === 'score') return <IconTarget size={16} />;
  if (jobType.startsWith('report.')) return <IconReport size={16} />;
  if (jobType.startsWith('demo.')) return <IconDatabase size={16} />;
  return <IconCpu size={16} />;
}

// ---------------------------------------------------------------- events

interface FeedEvent {
  key: string;
  /** Epoch ms used for ordering. */
  at: number;
  iso: string;
  /** `YYYY-MM-DD` in UTC — the day group. */
  day: string;
  caseItem: Case;
  /** `null` for a "case opened" event. */
  job: Job | null;
  /** Lower-cased text the search box matches against. */
  haystack: string;
}

function isActive(job: Job): boolean {
  return job.status === 'RUNNING' || job.status === 'QUEUED';
}

/**
 * The moment a job "happened" in the feed: when it finished if it has, when it
 * started if it is running, when it was queued if it is still waiting. A
 * finished job without a `finished_at` falls back rather than disappearing.
 */
function jobTimestamp(job: Job): string {
  if (job.status === 'RUNNING') return job.started_at ?? job.queued_at;
  if (job.status === 'QUEUED') return job.queued_at;
  return job.finished_at ?? job.started_at ?? job.queued_at;
}

function toEvent(caseItem: Case, job: Job | null): FeedEvent {
  const iso = job ? jobTimestamp(job) : caseItem.created_at;
  const at = Date.parse(iso);
  const caseText = [caseItem.title, caseItem.case_ref, caseItem.id].filter(Boolean).join(' ');
  const text = job
    ? [
        job.job_type,
        stageName(job.job_type),
        job.status,
        job.step,
        job.error_code,
        job.error_message,
        job.id,
        caseText,
      ]
    : ['case opened', caseText, caseItem.owner?.full_name, caseItem.owner?.email];
  return {
    key: job ? job.id : `case-${caseItem.id}`,
    at: Number.isFinite(at) ? at : 0,
    iso,
    day: formatDate(iso),
    caseItem,
    job,
    haystack: text.filter(Boolean).join(' ').toLowerCase(),
  };
}

function buildEvents(bundles: readonly CaseBundle[]): FeedEvent[] {
  const events: FeedEvent[] = [];
  for (const bundle of bundles) {
    events.push(toEvent(bundle.case, null));
    for (const job of bundle.jobs?.items ?? []) events.push(toEvent(bundle.case, job));
  }
  return events.sort((a, b) => b.at - a.at || a.key.localeCompare(b.key));
}

type StatusFilter = 'all' | 'running' | 'completed' | 'failed';

const STATUS_CHIPS: ReadonlyArray<{ key: StatusFilter; label: string; title?: string }> = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running', title: 'Running or queued' },
  { key: 'completed', label: 'Completed' },
  { key: 'failed', label: 'Failed' },
];

function matchesStatus(event: FeedEvent, status: StatusFilter): boolean {
  if (status === 'all') return true;
  if (!event.job) return false;
  if (status === 'running') return isActive(event.job);
  if (status === 'completed') return event.job.status === 'COMPLETED';
  return event.job.status === 'FAILED';
}

// ------------------------------------------------------------ formatting

/**
 * Most stages finish in well under a minute, where `formatDuration`'s whole
 * seconds would print "0s" for nearly everything. Under ten seconds one
 * decimal is kept; longer spans use `formatDuration`.
 */
function formatSpan(ms: number): string {
  if (!Number.isFinite(ms)) return EMPTY_VALUE;
  if (ms < 100) return '< 0.1s';
  if (ms < 10_000) return `${(ms / 1000).toFixed(1)}s`;
  return formatDuration(ms / 1000);
}

function runtimeText(job: Job, now: Date): string | null {
  const started = job.started_at ? Date.parse(job.started_at) : Number.NaN;
  if (job.status === 'RUNNING') {
    return Number.isFinite(started) ? `running ${formatSpan(now.getTime() - started)}` : 'running';
  }
  if (job.status === 'QUEUED') {
    const queued = Date.parse(job.queued_at);
    return Number.isFinite(queued) ? `waiting ${formatSpan(now.getTime() - queued)}` : 'waiting';
  }
  const finished = job.finished_at ? Date.parse(job.finished_at) : Number.NaN;
  if (Number.isFinite(started) && Number.isFinite(finished))
    return `took ${formatSpan(finished - started)}`;
  return null;
}

function dayHeading(day: string, now: Date): { rel: string; long: string } {
  const date = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return { rel: '', long: 'Undated' };
  const long = date.toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  });
  if (day === formatDate(now)) return { rel: 'Today', long };
  if (day === formatDate(now.getTime() - DAY_MS)) return { rel: 'Yesterday', long };
  return { rel: '', long };
}

/** A clock for relative times and running durations; ticks faster while anything runs. */
function useNow(intervalMs: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    setNow(new Date());
    const timer = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

const TONE_CLASS: Record<string, string | undefined> = {
  RUNNING: styles.toneRunning,
  QUEUED: styles.toneQueued,
  COMPLETED: styles.toneDone,
  FAILED: styles.toneFailed,
  CANCELLED: styles.toneCancelled,
};

// ------------------------------------------------------------------ rows

function EventRow({ event, now }: { event: FeedEvent; now: Date }) {
  const { job, caseItem } = event;
  const provenance = caseItem.data_provenance;
  // CON-009: work done for a synthetic case is labelled on every row. REAL is
  // left unbadged on job rows to keep a long feed quiet; the case event shows it.
  const showProvenance = !job || (provenance && provenance !== 'REAL');
  const runtime = job ? runtimeText(job, now) : null;
  const owner = caseItem.owner?.full_name || caseItem.owner?.email;

  return (
    <li className={cx(styles.event, job ? TONE_CLASS[job.status] : styles.toneCase)}>
      <div className={styles.when}>
        <time className={styles.clock} dateTime={event.iso} title={formatDateTime(event.iso, true)}>
          {formatTime(event.iso, true)}Z
        </time>
        <span className={styles.ago}>{formatRelativeTime(event.iso, now)}</span>
      </div>

      <div className={styles.rail} aria-hidden="true">
        <span className={styles.node} />
      </div>

      <article className={styles.card}>
        <div className={styles.cardHead}>
          <span className={styles.glyph} aria-hidden="true">
            {job ? stageIcon(job.job_type) : <IconCases size={16} />}
          </span>
          <div className={styles.headText}>
            <h3 className={styles.title}>
              {job ? stageName(job.job_type) : 'Case opened'}
              <span className={styles.type}>
                {job ? job.job_type : (caseItem.case_ref ?? truncateId(caseItem.id, 8, 4))}
              </span>
            </h3>
            <p className={styles.meta}>
              <Link
                href={`/cases/${caseItem.id}`}
                className={styles.caseLink}
                title={caseItem.title}
              >
                {caseItem.title}
              </Link>
              {showProvenance ? <ProvenanceBadge provenance={provenance} /> : null}
              {job && (job.attempt > 1 || job.status === 'FAILED') ? (
                <span className={styles.attempt}>
                  attempt {job.attempt} of {job.max_attempts}
                </span>
              ) : null}
            </p>
          </div>
          <div className={styles.side}>
            {job ? <JobStatusBadge status={job.status} /> : null}
            {runtime ? <span className={styles.duration}>{runtime}</span> : null}
          </div>
        </div>

        {job?.step ? <p className={styles.step}>{job.step}</p> : null}
        {!job ? (
          <p className={styles.step}>
            Window {formatTimeRange(caseItem.start_time, caseItem.end_time)}
            {owner ? ` · opened by ${owner}` : ''}
          </p>
        ) : null}

        {/* Failures are quoted verbatim: a stated reason, never a silent gap (NFR-011). */}
        {job?.status === 'FAILED' ? (
          <div className={styles.error}>
            <span className="sr-only">Failure reason: </span>
            {job.error_code ? <span className={styles.errorCode}>{job.error_code}</span> : null}
            <span>{job.error_message ?? 'The stage failed without a reported reason.'}</span>
          </div>
        ) : null}
      </article>
    </li>
  );
}

// ------------------------------------------------------------------ page

/**
 * Activity feed — every pipeline stage and case event across the analyst's
 * cases, newest first, grouped by UTC day.
 *
 * The API has no global job feed, so this reads each case's own job list via
 * `useCaseUniverse` (the 50 most recent cases, 50 latest jobs each) and says so
 * on screen. While any stage is running, only the cases with work in flight
 * are re-read, every ten seconds.
 */
export default function ActivityPage() {
  const universe = useCaseUniverse({ jobs: true });
  const queryClient = useQueryClient();

  const [status, setStatus] = useState<StatusFilter>('all');
  const [stage, setStage] = useState('');
  const [caseId, setCaseId] = useState('');
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [visible, setVisible] = useState(PAGE_SIZE);
  const [refreshing, setRefreshing] = useState(false);

  // Debounced, so the feed re-filters (and its rows re-stage) once per pause
  // in typing rather than on every keystroke.
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim().toLowerCase()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const allJobs = universe.bundles.flatMap((bundle) => bundle.jobs?.items ?? []);
  const runningNow = allJobs.filter((job) => job.status === 'RUNNING').length;
  const queuedNow = allJobs.filter((job) => job.status === 'QUEUED').length;
  const now = useNow(runningNow + queuedNow > 0 ? 5_000 : 30_000);

  // ------------------------------------------------------- live polling
  const activeCaseIds = universe.bundles
    .filter(
      (bundle) =>
        bundle.case.status === 'RUNNING' ||
        bundle.case.status === 'QUEUED' ||
        (bundle.jobs?.items ?? []).some(isActive),
    )
    .map((bundle) => bundle.case.id)
    .join(',');

  useEffect(() => {
    if (!activeCaseIds) return;
    const ids = activeCaseIds.split(',');
    const timer = window.setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: [...queryKeys.cases(), 'list'] });
      for (const id of ids) {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.caseJobs(id, { limit: JOBS_PER_CASE }),
        });
      }
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [activeCaseIds, queryClient]);

  // `universe.refetch` re-reads only the case list; a refresh here must also
  // re-read every job list on screen, so the whole cases subtree is invalidated
  // (only mounted queries actually refetch).
  const refresh = () => {
    setRefreshing(true);
    void queryClient
      .invalidateQueries({ queryKey: queryKeys.cases() })
      .finally(() => setRefreshing(false));
  };

  // ------------------------------------------------------------ events
  const events = buildEvents(universe.bundles);
  const terms = search.split(/\s+/).filter(Boolean);
  const scoped = events.filter(
    (event) =>
      (!stage || (stage === CASE_STAGE ? event.job === null : event.job?.job_type === stage)) &&
      (!caseId || event.caseItem.id === caseId) &&
      terms.every((term) => event.haystack.includes(term)),
  );
  const counts: Record<StatusFilter, number> = {
    all: scoped.length,
    running: scoped.filter((event) => matchesStatus(event, 'running')).length,
    completed: scoped.filter((event) => matchesStatus(event, 'completed')).length,
    failed: scoped.filter((event) => matchesStatus(event, 'failed')).length,
  };
  const filtered = scoped.filter((event) => matchesStatus(event, status));
  const shown = filtered.slice(0, visible);

  const dayTotals = new Map<string, number>();
  for (const event of filtered) dayTotals.set(event.day, (dayTotals.get(event.day) ?? 0) + 1);
  const groups: Array<{ day: string; events: FeedEvent[] }> = [];
  for (const event of shown) {
    const last = groups[groups.length - 1];
    if (last && last.day === event.day) last.events.push(event);
    else groups.push({ day: event.day, events: [event] });
  }

  const completedInView = filtered.filter((event) => event.job?.status === 'COMPLETED').length;
  const failedInView = filtered.filter((event) => event.job?.status === 'FAILED').length;

  // ------------------------------------------------------------ filters
  const presentTypes = new Set(allJobs.map((job) => job.job_type));
  const knownTypes: readonly string[] = JOB_TYPES;
  const stageOptions = [
    { value: '', label: 'All stages' },
    { value: CASE_STAGE, label: 'Case opened' },
    ...[
      ...knownTypes.filter((type) => presentTypes.has(type)),
      ...[...presentTypes].filter((type) => !knownTypes.includes(type)).sort(),
    ].map((type) => ({ value: type, label: `${stageName(type)} · ${type}` })),
  ];
  const caseOptions = [
    { value: '', label: 'All cases' },
    ...universe.cases.map((item) => ({
      value: item.id,
      label: item.case_ref ? `${item.case_ref} · ${item.title}` : item.title,
    })),
  ];
  const hasFilters =
    status !== 'all' || Boolean(stage) || Boolean(caseId) || query.trim().length > 0;
  // Remounting the day groups on a filter change gives each group a fresh
  // scroll trigger: a group that moved up into view is never left hidden.
  const filterKey = [status, stage, caseId, terms.join(' ')].join('|');

  const resetPaging = () => setVisible(PAGE_SIZE);
  const clearFilters = () => {
    setStatus('all');
    setStage('');
    setCaseId('');
    setQuery('');
    setSearch('');
    resetPaging();
  };

  // ----------------------------------------------------------- coverage
  const overflowing = universe.bundles.filter(
    (bundle) => bundle.jobs && bundle.jobs.total > bundle.jobs.items.length,
  ).length;

  const loading = universe.isPending || (universe.isLoadingDetails && allJobs.length === 0);
  const summaryValue = (value: number) =>
    loading ? <Skeleton height="1.6rem" width="2.5rem" /> : value;

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        eyebrow="Intelligence"
        title={
          <>
            Activity <span className={cx('serif', styles.titleAccent)}>feed</span>
          </>
        }
        subtitle="Every pipeline stage and case event across your investigations, newest first. Times are UTC."
        actions={
          <Button
            variant="secondary"
            leadingIcon={<IconRefresh size={15} />}
            loading={refreshing}
            loadingLabel="Refreshing activity"
            onClick={refresh}
          >
            Refresh
          </Button>
        }
      />

      {/* --------------------------------------------------------- summary */}
      <div className={styles.summary} role="group" aria-label="Feed summary" aria-busy={loading}>
        <div className={styles.stat}>
          <span className={styles.statLabel}>Events in view</span>
          <span className={styles.statValue}>{summaryValue(filtered.length)}</span>
        </div>
        <div className={cx(styles.stat, styles.statDone)}>
          <span className={styles.statLabel}>
            <span className={styles.statDot} aria-hidden="true" />
            Stages completed
          </span>
          <span className={styles.statValue}>{summaryValue(completedInView)}</span>
        </div>
        <div className={cx(styles.stat, styles.statFailed)}>
          <span className={styles.statLabel}>
            <span className={styles.statDot} aria-hidden="true" />
            Failures
          </span>
          <span className={styles.statValue}>{summaryValue(failedInView)}</span>
        </div>
        <div className={cx(styles.stat, styles.statRunning)}>
          <span className={styles.statLabel}>
            {runningNow > 0 ? (
              <span className={styles.liveDot} aria-hidden="true" />
            ) : (
              <span className={styles.statDot} aria-hidden="true" />
            )}
            Running now
          </span>
          <span className={styles.statValue}>
            {summaryValue(runningNow)}
            {!loading && queuedNow > 0 ? (
              <span className={styles.statNote}>+{queuedNow} queued</span>
            ) : null}
          </span>
        </div>
      </div>

      <div className={styles.coverage}>
        <p>
          Covers the latest {JOBS_PER_CASE} jobs per case for the {UNIVERSE_CASE_LIMIT} most recent
          cases.
          {activeCaseIds ? ' Cases with work in flight refresh every 10 seconds.' : ''}
        </p>
        {universe.truncated ? (
          <p>
            The feed covers the {UNIVERSE_CASE_LIMIT} most recent of {universe.total} cases.
          </p>
        ) : null}
        {overflowing > 0 ? (
          <p>
            {pluralize(overflowing, 'case')} {overflowing === 1 ? 'has' : 'have'} more than{' '}
            {JOBS_PER_CASE} jobs; {overflowing === 1 ? 'its' : 'their'} older stages are not shown.
          </p>
        ) : null}
        {universe.failedDetails > 0 ? (
          <p>
            The job history of {pluralize(universe.failedDetails, 'case')} could not be loaded and
            is missing from the feed.
          </p>
        ) : null}
      </div>

      {/* --------------------------------------------------------- filters */}
      <div className={styles.filters}>
        <div className={styles.chips} role="group" aria-label="Filter by status">
          {STATUS_CHIPS.map((chip) => (
            <button
              key={chip.key}
              type="button"
              title={chip.title}
              aria-pressed={status === chip.key}
              className={cx(
                styles.chip,
                chip.key === 'running' && styles.chipRunning,
                chip.key === 'completed' && styles.chipCompleted,
                chip.key === 'failed' && styles.chipFailed,
              )}
              onClick={() => {
                setStatus(chip.key);
                resetPaging();
              }}
            >
              {chip.key !== 'all' ? <span className={styles.chipDot} aria-hidden="true" /> : null}
              {chip.label}
              <span className={styles.chipCount}>
                {loading ? EMPTY_VALUE : counts[chip.key]}
                <span className="sr-only"> events</span>
              </span>
            </button>
          ))}
        </div>
        <div className={styles.controls}>
          <Select
            label="Stage"
            labelHidden
            options={stageOptions}
            value={stage}
            onChange={(event) => {
              setStage(event.target.value);
              resetPaging();
            }}
            containerClassName={styles.control}
          />
          <Select
            label="Case"
            labelHidden
            options={caseOptions}
            value={caseId}
            onChange={(event) => {
              setCaseId(event.target.value);
              resetPaging();
            }}
            containerClassName={styles.control}
          />
          <Input
            label="Search events"
            labelHidden
            type="search"
            placeholder="Search stage, case, step or error"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              resetPaging();
            }}
            containerClassName={styles.search}
          />
          {hasFilters ? (
            <Button variant="ghost" size="sm" onClick={clearFilters}>
              Clear
            </Button>
          ) : null}
        </div>
      </div>

      {/* ------------------------------------------------------------ feed */}
      {universe.isError ? (
        <ErrorState error={universe.error} onRetry={refresh} />
      ) : loading ? (
        <div className={styles.skeletonFeed} aria-busy="true">
          <span className="sr-only">Loading activity</span>
          {Array.from({ length: 6 }, (_, index) => (
            <div key={index} className={styles.skeletonRow}>
              <Skeleton height="0.75rem" width="4rem" />
              <span />
              <Skeleton height="4.5rem" radius="var(--radius-md)" />
            </div>
          ))}
        </div>
      ) : events.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconActivity size={18} />}
            title="No activity yet"
            description="Each case you open, and every pipeline stage it runs, appears here as it happens."
            action={
              <LinkButton href="/cases/new" variant="primary" size="sm">
                Open a case
              </LinkButton>
            }
          />
        </Card>
      ) : filtered.length === 0 ? (
        <Card>
          <EmptyState
            icon={<IconSearch size={18} />}
            title="No events match these filters"
            description="Try another stage or case, or clear the search to see the whole feed."
            action={
              <Button variant="secondary" size="sm" onClick={clearFilters}>
                Clear filters
              </Button>
            }
          />
        </Card>
      ) : (
        <div className={styles.feed} key={filterKey}>
          {groups.map((group) => {
            const heading = dayHeading(group.day, now);
            return (
              <section key={group.day} className={styles.day} aria-labelledby={`day-${group.day}`}>
                <h2 className={styles.dayHead} id={`day-${group.day}`}>
                  <span className={styles.dayRel}>{heading.rel}</span>
                  <span className={styles.dayMark} aria-hidden="true" />
                  <span className={styles.dayMain}>
                    <span className={styles.dayTitle}>{heading.long}</span>
                    <span className={styles.dayCount}>
                      {pluralize(dayTotals.get(group.day) ?? group.events.length, 'event')}
                    </span>
                  </span>
                </h2>
                <Reveal
                  as="ol"
                  className={styles.events}
                  stagger={Math.min(0.04, 0.9 / group.events.length)}
                  y={12}
                  duration={0.7}
                >
                  {group.events.map((event) => (
                    <EventRow key={event.key} event={event} now={now} />
                  ))}
                </Reveal>
              </section>
            );
          })}

          {filtered.length > shown.length ? (
            <div className={styles.more}>
              <p>
                Showing {shown.length} of {pluralize(filtered.length, 'event')}
              </p>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setVisible((v) => v + PAGE_SIZE)}
              >
                Show {Math.min(PAGE_SIZE, filtered.length - shown.length)} more
              </Button>
            </div>
          ) : (
            <p className={styles.end}>
              That is everything loaded — {pluralize(filtered.length, 'event')}.
              {overflowing > 0
                ? ' Older stages beyond the latest 50 per case are not fetched.'
                : ''}
            </p>
          )}
        </div>
      )}
    </main>
  );
}
