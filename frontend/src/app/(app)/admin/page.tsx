'use client';

import { useMemo } from 'react';
import { MetaList, Readout, ReadoutGrid, Unmeasured } from '@/components/common/MetaList';
import { NoticeStack } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { JobProgress } from '@/components/jobs/JobProgress';
import { PageHeader } from '@/components/layout/PageHeader';
import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { IconRefresh } from '@/components/ui/Icons';
import { Skeleton } from '@/components/ui/Skeleton';
import { Table, type Column } from '@/components/ui/Table';
import { useSystemProviders, useSystemStatus } from '@/lib/api/hooks';
import {
  hasMetrics,
  type ModelVersion,
  type SystemComponent,
  type SystemProvider,
} from '@/lib/api/types';
import {
  EMPTY_VALUE,
  formatDateTime,
  formatInteger,
  formatNumber,
  humanizeIdentifier,
} from '@/lib/format';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';

const COMPONENT_TONE: Record<string, BadgeTone> = {
  UP: 'success',
  DEGRADED: 'warning',
  DOWN: 'danger',
};

/**
 * Format one recorded metric.
 *
 * Only reached when the model actually has metrics — the "no evaluation
 * recorded" case is handled before this is ever called, because a model that was
 * never measured must not be rendered as though it scored zero (A-06).
 */
function formatRequires(requires: string | string[] | null | undefined): string {
  const names = Array.isArray(requires) ? requires : requires ? requires.split(/[\s,/]+/) : [];
  const cleaned = names.map((name) => name.trim()).filter(Boolean);
  return cleaned.length > 0 ? cleaned.join(', ') : 'Nothing external';
}

function formatMetric(value: unknown): string {
  if (value === null || value === undefined) return EMPTY_VALUE;
  if (typeof value === 'string') return value;
  if (typeof value === 'number') {
    // Anything in [0,1] is almost certainly a rate; show it as a percentage.
    if (value >= 0 && value <= 1)
      return `${formatNumber(value * 100, { maximumFractionDigits: 1 })}%`;
    return formatNumber(value, { maximumFractionDigits: 3 });
  }
  if (typeof value === 'object' && !Array.isArray(value)) {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, inner]) => `${humanizeIdentifier(key)} ${formatMetric(inner)}`)
      .join(', ');
  }
  // Nested groups (an operating point, a threshold sweep) do not fit in one
  // cell; ML Ops renders them properly. Never print "[object Object]".
  return 'recorded — see ML Ops';
}

const componentColumns: Column<SystemComponent>[] = [
  { key: 'name', header: 'Component', mono: true, render: (row) => row.name },
  {
    key: 'status',
    header: 'Status',
    width: '8rem',
    render: (row) => (
      <Badge tone={COMPONENT_TONE[row.status] ?? 'neutral'} dot>
        {row.status}
      </Badge>
    ),
  },
  {
    key: 'latency',
    header: 'Latency',
    numeric: true,
    width: '7rem',
    render: (row) =>
      row.latency_ms === null
        ? EMPTY_VALUE
        : `${formatNumber(row.latency_ms, { maximumFractionDigits: 1 })} ms`,
  },
  { key: 'detail', header: 'Detail', render: (row) => row.detail ?? EMPTY_VALUE },
];

const providerColumns: Column<SystemProvider>[] = [
  { key: 'port', header: 'Port', mono: true, render: (row) => humanizeIdentifier(row.port) },
  {
    key: 'implementation',
    header: 'Active implementation',
    mono: true,
    render: (row) => row.implementation,
  },
  {
    key: 'mode',
    header: 'Data mode',
    width: '9rem',
    render: (row) => <ProvenanceBadge provenance={row.mode} />,
  },
  {
    key: 'configured',
    header: 'Credentials configured',
    width: '11rem',
    render: (row) => (
      <Badge tone={row.configured ? 'success' : 'neutral'}>{row.configured ? 'Yes' : 'No'}</Badge>
    ),
  },
  {
    key: 'requires',
    header: 'Requires',
    mono: true,
    render: (row) =>
      formatRequires(row.requires),
  },
];

const modelColumns: Column<ModelVersion>[] = [
  {
    key: 'name',
    header: 'Model',
    mono: true,
    render: (row) => (
      <span className={styles.cellPrimary}>
        <span>{row.name}</span>
        {row.task ? <span className={styles.cellSub}>{row.task}</span> : null}
      </span>
    ),
  },
  { key: 'version', header: 'Version', mono: true, width: '7rem', render: (row) => row.version },
  {
    key: 'framework',
    header: 'Framework',
    mono: true,
    width: '8rem',
    render: (row) => row.framework ?? EMPTY_VALUE,
  },
  {
    key: 'active',
    header: 'Active',
    width: '6rem',
    render: (row) => (
      <Badge tone={row.is_active ? 'accent' : 'neutral'}>{row.is_active ? 'Active' : 'Idle'}</Badge>
    ),
  },
  {
    key: 'metrics',
    header: 'Evaluation',
    render: (row) =>
      // An empty `metrics` object means nobody has evaluated this checkpoint.
      // That is *unknown*, not zero, and it is rendered as words on purpose.
      hasMetrics(row) ? (
        <span>
          {Object.entries(row.metrics)
            .map(([key, value]) => `${humanizeIdentifier(key)} ${formatMetric(value)}`)
            .join(' · ')}
        </span>
      ) : (
        <Unmeasured>No evaluation recorded — accuracy on independent data is unknown</Unmeasured>
      ),
  },
];

/** UI-010 — model, data-source and system status. */
export default function AdminPage() {
  const status = useSystemStatus();
  // Providers are readable by any signed-in user, so an analyst who lands here
  // still learns whether the data in front of them is synthetic.
  const providers = useSystemProviders();
  const data = status.data;

  const forbidden = Boolean(status.error?.isForbidden || status.error?.isUnauthenticated);

  const stats = useMemo(
    () => [
      { label: 'Queued', value: data?.jobs.queued, caption: 'Waiting for a worker.' },
      { label: 'Running', value: data?.jobs.running, caption: 'Currently executing.' },
      {
        label: 'Completed (24h)',
        value: data?.jobs.completed_24h,
        caption: 'Finished successfully in the last day.',
      },
      {
        label: 'Failed (24h)',
        value: data?.jobs.failed_24h,
        caption: 'Every failure states its reason.',
      },
    ],
    [data],
  );

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        title="System status"
        subtitle="Component health, which adapter implementation is active for each port, and the model versions currently in use. Refreshes every 15 seconds."
        actions={
          <Button
            variant="secondary"
            size="md"
            onClick={() => {
              void status.refetch();
              void providers.refetch();
            }}
            loading={status.isFetching || providers.isFetching}
            loadingLabel="Refreshing"
            leadingIcon={<IconRefresh size={15} />}
          >
            Refresh
          </Button>
        }
      />

      {forbidden ? (
        <div className={styles.detailStack}>
          <ErrorState
            title="Administrator access required"
            error={status.error}
            description="Component health, job statistics and model versions are restricted to administrators. The data-source table below is readable by every signed-in user, because knowing whether data is synthetic is not an administrative privilege."
          />

          <Card
            title="Data sources"
            description="Which implementation each port resolves to at runtime. Credentials are read server-side only and never reach this bundle."
            flush
          >
            <Table
              caption="Adapter implementations per port"
              columns={providerColumns}
              rows={providers.data?.providers ?? []}
              getRowKey={(row) => row.port}
              loading={providers.isPending}
              error={
                providers.isError ? (
                  <ErrorState
                    compact
                    error={providers.error}
                    onRetry={() => void providers.refetch()}
                  />
                ) : undefined
              }
              empty={
                <EmptyState
                  compact
                  title="No providers reported"
                  description="No adapter ports were reported by the API."
                />
              }
            />
          </Card>

          <NoticeStack
            notices={[providers.data?.notice]}
            label="Data provenance"
            tone="synthetic"
          />
        </div>
      ) : (
        <div className={styles.detailStack}>
          {status.isError ? (
            <ErrorState error={status.error} onRetry={() => void status.refetch()} />
          ) : null}

          <NoticeStack
            notices={[...(data?.notices ?? []), providers.data?.notice]}
            label="Standing caveats"
            tone="synthetic"
          />

          <MetaList
            dense
            entries={[
              {
                key: 'version',
                term: 'API version',
                mono: true,
                value: data?.version ?? EMPTY_VALUE,
              },
              {
                key: 'environment',
                term: 'Environment',
                mono: true,
                value: data?.environment ?? EMPTY_VALUE,
              },
              {
                key: 'generated',
                term: 'Reported at',
                mono: true,
                value: formatDateTime(data?.generated_at ?? null),
              },
              {
                key: 'synthetic',
                term: 'Any synthetic source',
                value: providers.data ? (
                  <Badge tone={providers.data.any_synthetic ? 'synthetic' : 'success'}>
                    {providers.data.any_synthetic ? 'Yes' : 'No'}
                  </Badge>
                ) : (
                  EMPTY_VALUE
                ),
              },
            ]}
          />

          <ReadoutGrid>
            {stats.map((stat) => (
              <Readout
                key={stat.label}
                label={stat.label}
                value={
                  status.isPending ? (
                    <Skeleton height="1.75rem" width="3rem" />
                  ) : (
                    formatInteger(stat.value ?? null)
                  )
                }
                caption={stat.caption}
              />
            ))}
          </ReadoutGrid>

          <Card title="Components" flush>
            <Table
              caption="Backend component health"
              columns={componentColumns}
              rows={data?.components ?? []}
              getRowKey={(row) => row.name}
              loading={status.isPending}
              empty={
                <EmptyState
                  compact
                  title="No components reported"
                  description="The status endpoint returned no component checks. That usually means the API is running without its readiness probes wired up."
                />
              }
            />
          </Card>

          <Card
            title="Data sources"
            description="Which implementation each port resolves to at runtime, and whether it is backed by real credentials. A port in SYNTHETIC mode produces deterministic demonstration data that is labelled as such everywhere it appears."
            flush
          >
            <Table
              caption="Adapter implementations per port"
              columns={providerColumns}
              rows={data?.providers ?? providers.data?.providers ?? []}
              getRowKey={(row) => row.port}
              loading={status.isPending && providers.isPending}
              empty={
                <EmptyState
                  compact
                  title="No providers reported"
                  description="No adapter ports were reported by the API."
                />
              }
            />
          </Card>

          <Card
            title="Model versions"
            description="Registered checkpoints. A model with no recorded evaluation is shown as unmeasured — never as a score of zero."
            flush
          >
            <Table
              caption="Registered model versions"
              columns={modelColumns}
              rows={data?.models ?? []}
              getRowKey={(row) => `${row.name}@${row.version}`}
              loading={status.isPending}
              empty={
                <EmptyState
                  compact
                  title="No model versions registered"
                  description="No trained checkpoint has been registered yet. Detection falls back to the deterministic analytical detector, and its output is labelled SYNTHETIC."
                />
              }
            />
          </Card>

          <Card title="Recent jobs">
            {status.isPending ? (
              <div className={styles.jobsScroll} aria-busy="true">
                <Skeleton height="4.5rem" radius="var(--radius-md)" />
                <Skeleton height="4.5rem" radius="var(--radius-md)" />
              </div>
            ) : (data?.recent_jobs?.length ?? 0) === 0 ? (
              <EmptyState
                compact
                title="No jobs in the recent window"
                description="Nothing has been queued yet."
              />
            ) : (
              <div className={styles.jobsScroll}>
                {data?.recent_jobs?.map((job) => (
                  <JobProgress key={job.id} job={job} />
                ))}
              </div>
            )}
          </Card>

          <Card
            title="Failed jobs"
            description="Every failure states its reason. An unavailable provider produces a failed stage, never a silent fake result (NFR-011)."
          >
            {status.isPending ? (
              <Skeleton height="4.5rem" radius="var(--radius-md)" />
            ) : (data?.failed_jobs?.length ?? 0) === 0 ? (
              <EmptyState
                compact
                title="No failures"
                description="No job has failed in the reporting window."
              />
            ) : (
              <div className={styles.jobsScroll}>
                {data?.failed_jobs?.map((job) => (
                  <JobProgress key={job.id} job={job} />
                ))}
              </div>
            )}
          </Card>
        </div>
      )}
    </main>
  );
}
