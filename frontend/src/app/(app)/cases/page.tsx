'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { CaseStatusBadge } from '@/components/common/CaseStatusBadge';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { PageHeader } from '@/components/layout/PageHeader';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { IconCases, IconPlus, IconSearch } from '@/components/ui/Icons';
import { Input } from '@/components/ui/Input';
import { LinkButton } from '@/components/ui/LinkButton';
import { Select } from '@/components/ui/Select';
import { Table, type Column } from '@/components/ui/Table';
import { useCases } from '@/lib/api/hooks';
import type { Case, CaseListParams } from '@/lib/api/types';
import { DEFAULT_PAGE_SIZE, PAGE_SIZE_OPTIONS } from '@/lib/config';
import { formatAreaKm2, formatDateTimeCompact, formatTimeRange, truncateId } from '@/lib/format';
import { polygonAreaKm2 } from '@/lib/geo';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';

const STATUS_OPTIONS = [
  { value: '', label: 'Any status' },
  { value: 'DRAFT', label: 'Draft' },
  { value: 'QUEUED', label: 'Queued' },
  { value: 'RUNNING', label: 'Running' },
  { value: 'COMPLETED', label: 'Completed' },
  { value: 'FAILED', label: 'Failed' },
  { value: 'ARCHIVED', label: 'Archived' },
];

/** `2026-08-01` from a date input → the RFC 3339 instant the API expects. */
function dateToIso(value: string, endOfDay = false): string | undefined {
  if (!value) return undefined;
  return endOfDay ? `${value}T23:59:59Z` : `${value}T00:00:00Z`;
}

/** UI-002 — Case list with filters, pagination and all five screen states. */
export default function CasesPage() {
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [limit, setLimit] = useState(DEFAULT_PAGE_SIZE);
  const [offset, setOffset] = useState(0);

  // Debounced so typing does not fire a request per keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Any filter change invalidates the current page position.
  useEffect(() => {
    setOffset(0);
  }, [status, debouncedSearch, from, to, limit]);

  const params = useMemo<CaseListParams>(
    () => ({
      limit,
      offset,
      ...(status ? { status } : {}),
      ...(debouncedSearch ? { q: debouncedSearch } : {}),
      ...(dateToIso(from) ? { from: dateToIso(from) } : {}),
      ...(dateToIso(to, true) ? { to: dateToIso(to, true) } : {}),
    }),
    [limit, offset, status, debouncedSearch, from, to],
  );

  const query = useCases(params);
  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const hasFilters = Boolean(status || debouncedSearch || from || to);

  const columns = useMemo<Column<Case>[]>(
    () => [
      {
        key: 'title',
        header: 'Case',
        render: (row) => (
          <span className={styles.cellPrimary}>
            <Link href={`/cases/${row.id}`} className={styles.cellLink}>
              {row.title}
            </Link>
            {row.description ? <span className={styles.cellSub}>{row.description}</span> : null}
          </span>
        ),
      },
      {
        key: 'status',
        header: 'Status',
        width: '11rem',
        render: (row) => (
          <span className={styles.badgeRow}>
            <CaseStatusBadge status={row.status} />
            <ProvenanceBadge provenance={row.data_provenance} />
          </span>
        ),
      },
      {
        key: 'window',
        header: 'Time window (UTC)',
        width: '17rem',
        mono: true,
        render: (row) => formatTimeRange(row.start_time, row.end_time),
      },
      {
        key: 'area',
        header: 'AOI area',
        numeric: true,
        width: '8rem',
        render: (row) => formatAreaKm2(polygonAreaKm2(row.aoi)),
      },
      {
        key: 'created',
        header: 'Created',
        width: '11rem',
        mono: true,
        render: (row) => formatDateTimeCompact(row.created_at),
      },
      {
        key: 'id',
        header: 'Case id',
        width: '9rem',
        mono: true,
        render: (row) => <span title={row.id}>{truncateId(row.id, 8, 4)}</span>,
      },
    ],
    [],
  );

  const resetFilters = () => {
    setStatus('');
    setSearch('');
    setFrom('');
    setTo('');
  };

  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + items.length, total);

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        title="Cases"
        subtitle="Every investigation you can access. Open a case to see its map, pipeline and candidate ranking."
        actions={
          <LinkButton
            href="/cases/new"
            variant="primary"
            size="md"
            leadingIcon={<IconPlus size={15} />}
          >
            New case
          </LinkButton>
        }
      />

      <div className={styles.filters}>
        <Input
          label="Search"
          type="search"
          placeholder="Title or description"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          hint="Matches case titles and descriptions."
        />
        <Select
          label="Status"
          options={STATUS_OPTIONS}
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        />
        <Input
          label="From (UTC)"
          type="date"
          value={from}
          onChange={(event) => setFrom(event.target.value)}
        />
        <Input
          label="To (UTC)"
          type="date"
          value={to}
          onChange={(event) => setTo(event.target.value)}
        />
        <Select
          label="Per page"
          options={PAGE_SIZE_OPTIONS.map((size) => ({ value: String(size), label: String(size) }))}
          value={String(limit)}
          onChange={(event) => setLimit(Number(event.target.value))}
        />
      </div>

      {hasFilters ? (
        <div className={styles.filterActions} style={{ marginBottom: 'var(--space-4)' }}>
          <Button variant="ghost" size="sm" onClick={resetFilters}>
            Clear filters
          </Button>
        </div>
      ) : null}

      <Card
        flush
        footer={
          <div className={styles.pagination}>
            <p className={styles.paginationStatus} aria-live="polite">
              {query.isPending
                ? 'Loading cases…'
                : total === 0
                  ? 'No cases to show'
                  : `Showing ${start}–${end} of ${total}`}
            </p>
            <div className={styles.paginationButtons}>
              <Button
                variant="secondary"
                size="sm"
                disabled={offset === 0 || query.isPending}
                onClick={() => setOffset((current) => Math.max(0, current - limit))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={offset + limit >= total || query.isPending}
                onClick={() => setOffset((current) => current + limit)}
              >
                Next
              </Button>
            </div>
          </div>
        }
      >
        <Table
          caption="Investigation cases"
          columns={columns}
          rows={items}
          getRowKey={(row) => row.id}
          loading={query.isPending}
          error={
            query.isError ? (
              <ErrorState error={query.error} onRetry={() => void query.refetch()} />
            ) : null
          }
          empty={
            hasFilters ? (
              <EmptyState
                icon={<IconSearch size={18} />}
                title="No cases match these filters"
                description="Try a wider time range, a different status, or clear the search term."
                action={
                  <Button variant="secondary" size="sm" onClick={resetFilters}>
                    Clear filters
                  </Button>
                }
              />
            ) : (
              <EmptyState
                icon={<IconCases size={18} />}
                title="No cases yet"
                description="A case pins an area of interest to a time window. Create one to search the Sentinel-1 catalogue and start the investigation chain."
                action={
                  <LinkButton href="/cases/new" variant="primary" size="sm">
                    Create the first case
                  </LinkButton>
                }
              />
            )
          }
        />
      </Card>
    </main>
  );
}
