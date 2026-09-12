'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { ConfidenceBadge } from '@/components/attribution/ConfidenceBadge';
import { StatTile } from '@/components/charts';
import { NoticeStack } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { PageHeader } from '@/components/layout/PageHeader';
import { Reveal } from '@/components/motion/Reveal';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { IconCases, IconHistory, IconSearch, IconShip, IconTarget } from '@/components/ui/Icons';
import { Input } from '@/components/ui/Input';
import { LinkButton } from '@/components/ui/LinkButton';
import { Select } from '@/components/ui/Select';
import { Skeleton } from '@/components/ui/Skeleton';
import { Table, type Column } from '@/components/ui/Table';
import { type CaseBundle, UNIVERSE_CASE_LIMIT, useCaseUniverse } from '@/lib/api/aggregate';
import type { ConfidenceLabel } from '@/lib/api/types';
import {
  EMPTY_VALUE,
  formatDateTimeCompact,
  formatImo,
  formatMmsi,
  formatRelativeTime,
  pluralize,
} from '@/lib/format';
import { type VesselAppearance, vesselAppearances } from '@/lib/insights';
import layout from '@/components/layout/layout.module.css';
import styles from './vessels.module.css';

// -------------------------------------------------------------------- model

interface BestRanking {
  caseId: string;
  caseTitle: string;
  rank: number;
  /** How many candidates that case ranked, when its list is loaded. */
  of: number | null;
  score: number;
  band: ConfidenceLabel;
}

interface RegistryRow extends VesselAppearance {
  imos: number[];
  callsigns: string[];
  /**
   * Every provenance the vessel's rows arrived with. A vessel seen in a REAL
   * case and a SYNTHETIC one carries both labels, never just the first one
   * encountered (CON-009).
   */
  provenances: string[];
  best: BestRanking | null;
}

type FilterKey = 'all' | 'candidates' | 'repeat';
type SortKey = 'recent' | 'cases' | 'rank' | 'name';
type ViewKey = 'table' | 'cards';

const FILTERS: ReadonlyArray<{
  key: FilterKey;
  label: string;
  test: (row: RegistryRow) => boolean;
}> = [
  { key: 'all', label: 'All', test: () => true },
  { key: 'candidates', label: 'Candidates only', test: (row) => row.candidateIn.length > 0 },
  { key: 'repeat', label: 'Seen in 2+ cases', test: (row) => row.observedIn.length > 1 },
];

const SORT_OPTIONS: ReadonlyArray<{ value: SortKey; label: string }> = [
  { value: 'recent', label: 'Sort: most recently seen' },
  { value: 'cases', label: 'Sort: most cases' },
  { value: 'rank', label: 'Sort: best rank' },
  { value: 'name', label: 'Sort: name (A–Z)' },
];

const UNRANKED = Number.MAX_SAFE_INTEGER;

function byName(a: RegistryRow, b: RegistryRow): number {
  // Unnamed vessels sort last, then by MMSI so the order is always stable.
  const left = a.name?.trim();
  const right = b.name?.trim();
  if (left && right) return left.localeCompare(right, 'en') || a.mmsi - b.mmsi;
  if (left) return -1;
  if (right) return 1;
  return a.mmsi - b.mmsi;
}

const SORTERS: Record<SortKey, (a: RegistryRow, b: RegistryRow) => number> = {
  recent: (a, b) =>
    (Date.parse(b.lastSeen ?? '') || 0) - (Date.parse(a.lastSeen ?? '') || 0) || byName(a, b),
  cases: (a, b) =>
    b.observedIn.length - a.observedIn.length ||
    b.candidateIn.length - a.candidateIn.length ||
    byName(a, b),
  // A rank is only comparable within one case; across cases this is a way to
  // find the vessels worth opening, not a league table.
  rank: (a, b) =>
    (a.best?.rank ?? UNRANKED) - (b.best?.rank ?? UNRANKED) ||
    (b.best?.score ?? -1) - (a.best?.score ?? -1) ||
    byName(a, b),
  name: byName,
};

/**
 * `vesselAppearances` groups by MMSI but keeps only the fields every screen
 * needs. The registry also searches by IMO and call sign, and must label every
 * provenance a vessel was seen with — so those come from the same bundles here.
 */
function buildRegistry(bundles: readonly CaseBundle[]): RegistryRow[] {
  const identities = new Map<
    number,
    { imos: Set<number>; callsigns: Set<string>; observed: Set<string>; ranked: Set<string> }
  >();
  const identity = (mmsi: number) => {
    let entry = identities.get(mmsi);
    if (!entry) {
      entry = { imos: new Set(), callsigns: new Set(), observed: new Set(), ranked: new Set() };
      identities.set(mmsi, entry);
    }
    return entry;
  };
  const candidateTotals = new Map<string, number>();

  for (const bundle of bundles) {
    if (bundle.attributions) {
      candidateTotals.set(
        bundle.case.id,
        bundle.attributions.total ?? bundle.attributions.items.length,
      );
    }
    for (const vessel of bundle.vessels?.items ?? []) {
      const entry = identity(vessel.mmsi);
      if (vessel.imo !== null && vessel.imo !== undefined) entry.imos.add(vessel.imo);
      if (vessel.callsign?.trim()) entry.callsigns.add(vessel.callsign.trim());
      if (vessel.data_provenance) entry.observed.add(vessel.data_provenance);
    }
    for (const attribution of bundle.attributions?.items ?? []) {
      if (attribution.data_provenance) {
        identity(attribution.vessel.mmsi).ranked.add(attribution.data_provenance);
      }
    }
  }

  return vesselAppearances(bundles).map((entry) => {
    const id = identities.get(entry.mmsi);
    // The vessel's own rows say what its AIS data was; only a vessel known
    // solely through a ranking falls back to that ranking's provenance.
    const provenances = id?.observed.size
      ? [...id.observed]
      : id?.ranked.size
        ? [...id.ranked]
        : entry.provenance
          ? [entry.provenance]
          : [];

    let best: VesselAppearance['candidateIn'][number] | null = null;
    for (const ranking of entry.candidateIn) {
      if (
        !best ||
        ranking.rank < best.rank ||
        (ranking.rank === best.rank && ranking.score > best.score)
      ) {
        best = ranking;
      }
    }

    return {
      ...entry,
      imos: [...(id?.imos ?? [])],
      callsigns: [...(id?.callsigns ?? [])],
      provenances,
      best: best ? { ...best, of: candidateTotals.get(best.caseId) ?? null } : null,
    };
  });
}

/** Name and call sign by substring; MMSI and IMO by digits, tolerating an "IMO" prefix. */
function matchesQuery(row: RegistryRow, query: string): boolean {
  if (!query) return true;
  const needle = query.toLowerCase();
  if (row.name?.toLowerCase().includes(needle)) return true;
  if (row.callsigns.some((callsign) => callsign.toLowerCase().includes(needle))) return true;
  const digits = needle.replace(/^imo/, '').replace(/[\s-]/g, '');
  if (/^\d+$/.test(digits)) {
    if (String(row.mmsi).includes(digits)) return true;
    if (row.imos.some((imo) => String(imo).includes(digits))) return true;
  }
  return false;
}

function vesselLabel(row: RegistryRow): string {
  return row.name?.trim() || 'Unnamed vessel';
}

function vesselDetails(row: RegistryRow): string {
  return [row.flag, row.shipType].filter(Boolean).join(' · ') || 'Flag and ship type not broadcast';
}

// --------------------------------------------------------------- cells

function VesselIdentity({ row }: { row: RegistryRow }) {
  return (
    <span className={styles.identity}>
      <span className={styles.glyph} aria-hidden="true">
        <IconShip size={15} />
      </span>
      <span className={styles.identityText}>
        <Link href={`/vessels/${row.vesselId}`} className={styles.vesselLink}>
          {vesselLabel(row)}
        </Link>
        <span className={styles.identifiers}>
          <span>MMSI {formatMmsi(row.mmsi)}</span>
          {row.imos.length ? <span>{row.imos.map(formatImo).join(' / ')}</span> : null}
          {row.callsigns.length ? <span>{row.callsigns.join(' / ')}</span> : null}
        </span>
        <span className={styles.identitySub}>{vesselDetails(row)}</span>
      </span>
    </span>
  );
}

function Provenances({ row }: { row: RegistryRow }) {
  if (row.provenances.length === 0) return <span className={styles.muted}>{EMPTY_VALUE}</span>;
  return (
    <span className={styles.badges}>
      {row.provenances.map((provenance) => (
        <ProvenanceBadge key={provenance} provenance={provenance} />
      ))}
    </span>
  );
}

/**
 * The best rank the vessel reached in any one case, with that case's band.
 * Every rank is drawn the same way — a #1 is not highlighted, because a first
 * place in one enquiry is still only a lead (CON-001).
 */
function BestRank({ best }: { best: BestRanking | null }) {
  if (!best) return <span className={styles.muted}>Not ranked</span>;
  return (
    <span className={styles.rankCell} title={`Best rank reached in “${best.caseTitle}”`}>
      <span className={styles.rankValue}>
        #{best.rank}
        {best.of ? <span className={styles.rankOf}> of {best.of}</span> : null}
      </span>
      <ConfidenceBadge label={best.band} />
    </span>
  );
}

function LastSeen({ value }: { value: string | null }) {
  if (!value) return <span className={styles.muted}>{EMPTY_VALUE}</span>;
  return (
    <span className={styles.seen}>
      <time dateTime={value}>{formatRelativeTime(value)}</time>
      <span className={styles.seenExact}>{formatDateTimeCompact(value)}</span>
    </span>
  );
}

const COLUMNS: Column<RegistryRow>[] = [
  { key: 'vessel', header: 'Vessel', render: (row) => <VesselIdentity row={row} /> },
  {
    key: 'provenance',
    header: 'Provenance',
    width: '8.5rem',
    render: (row) => <Provenances row={row} />,
  },
  {
    key: 'observed',
    header: 'Observed in',
    numeric: true,
    width: '7.5rem',
    render: (row) => pluralize(row.observedIn.length, 'case'),
  },
  {
    key: 'candidate',
    header: 'Candidate in',
    numeric: true,
    width: '7.5rem',
    render: (row) =>
      row.candidateIn.length ? (
        pluralize(row.candidateIn.length, 'case')
      ) : (
        <span className={styles.muted}>0 cases</span>
      ),
  },
  {
    key: 'rank',
    header: 'Best rank',
    width: '14.5rem',
    render: (row) => <BestRank best={row.best} />,
  },
  {
    key: 'seen',
    header: 'Last seen (AIS)',
    width: '9.5rem',
    render: (row) => <LastSeen value={row.lastSeen} />,
  },
];

function VesselCard({ row }: { row: RegistryRow }) {
  return (
    <li className={styles.vesselCard}>
      <div className={styles.cardHead}>
        <span className={styles.glyph} aria-hidden="true">
          <IconShip size={15} />
        </span>
        <div className={styles.identityText}>
          <h3 className={styles.cardName}>
            <Link href={`/vessels/${row.vesselId}`} className={styles.cardLink}>
              {vesselLabel(row)}
            </Link>
          </h3>
          <span className={styles.identifiers}>
            <span>MMSI {formatMmsi(row.mmsi)}</span>
            {row.imos.length ? <span>{row.imos.map(formatImo).join(' / ')}</span> : null}
          </span>
          <span className={styles.identitySub}>{vesselDetails(row)}</span>
        </div>
      </div>
      <dl className={styles.cardStats}>
        <div className={styles.cardStat}>
          <dt>Observed in</dt>
          <dd>{pluralize(row.observedIn.length, 'case')}</dd>
        </div>
        <div className={styles.cardStat}>
          <dt>Candidate in</dt>
          <dd>{pluralize(row.candidateIn.length, 'case')}</dd>
        </div>
        <div className={styles.cardStat}>
          <dt>Best rank</dt>
          <dd>
            {row.best ? (
              <>
                #{row.best.rank}
                {row.best.of ? <span className={styles.rankOf}> of {row.best.of}</span> : null}
              </>
            ) : (
              EMPTY_VALUE
            )}
          </dd>
        </div>
      </dl>
      <div className={styles.cardFoot}>
        <span className={styles.badges}>
          <Provenances row={row} />
          {row.best ? <ConfidenceBadge label={row.best.band} /> : null}
        </span>
        <span>
          {row.lastSeen ? (
            <>
              Last seen <time dateTime={row.lastSeen}>{formatRelativeTime(row.lastSeen)}</time>
            </>
          ) : (
            'Last seen unknown'
          )}
        </span>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------- page

/** Vessel registry — every vessel observed across the analyst's cases. */
export default function VesselRegistryPage() {
  const universe = useCaseUniverse({ vessels: true, attributions: true });
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<FilterKey>('all');
  const [sort, setSort] = useState<SortKey>('recent');
  const [view, setView] = useState<ViewKey>('table');

  // Debounced so a long registry is not re-filtered on every keystroke.
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 200);
    return () => clearTimeout(timer);
  }, [search]);

  const details = universe.isPending || universe.isLoadingDetails;
  const registry = buildRegistry(universe.bundles);
  const searched = registry.filter((row) => matchesQuery(row, query));
  const counts: Record<FilterKey, number> = {
    all: searched.length,
    candidates: searched.filter((row) => row.candidateIn.length > 0).length,
    repeat: searched.filter((row) => row.observedIn.length > 1).length,
  };
  const activeFilter = FILTERS.find((item) => item.key === filter) ?? FILTERS[0]!;
  const visible = searched.filter(activeFilter.test).sort(SORTERS[sort]);

  const rankedCount = registry.filter((row) => row.candidateIn.length > 0).length;
  const repeatCount = registry.filter((row) => row.observedIn.length > 1).length;
  const casesCovered = universe.bundles.filter((bundle) => bundle.vessels).length;

  const vesselNotices = universe.bundles.map((bundle) => bundle.vessels?.notice);
  const rankingNotices = universe.bundles.map((bundle) => bundle.attributions?.disclaimer);

  const reset = () => {
    setSearch('');
    setQuery('');
    setFilter('all');
  };

  const empty =
    registry.length > 0 ? (
      <EmptyState
        icon={<IconSearch size={18} />}
        title="No vessels match"
        description="Nothing matches this search and filter. Try part of the name, a partial MMSI, an IMO number or a call sign."
        action={
          <Button variant="secondary" size="sm" onClick={reset}>
            Clear search and filters
          </Button>
        }
      />
    ) : universe.cases.length === 0 ? (
      <EmptyState
        icon={<IconCases size={18} />}
        title="No vessels observed yet"
        description="Vessels appear here once a case's AIS stage has run. Create a case and run its pipeline to populate the registry."
        action={
          <LinkButton href="/cases/new" variant="primary" size="sm">
            Create a case
          </LinkButton>
        }
      />
    ) : (
      <EmptyState
        icon={<IconShip size={18} />}
        title="No vessels observed in your cases"
        description={`None of the ${pluralize(universe.cases.length, 'case')} aggregated here recorded an AIS vessel. That does not mean no vessels were there — public AIS coverage is incomplete.`}
      />
    );

  const error = universe.isError ? (
    <ErrorState error={universe.error} onRetry={universe.refetch} />
  ) : undefined;

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        eyebrow="Intelligence"
        title="Vessel registry"
        subtitle="Every vessel your cases observed in AIS, grouped by MMSI. Search by name, MMSI, IMO or call sign, and open a vessel for its track, AIS quality and history across your cases."
        actions={
          <LinkButton
            href="/cases"
            variant="secondary"
            size="md"
            leadingIcon={<IconCases size={15} />}
          >
            All cases
          </LinkButton>
        }
      />

      <Reveal className={styles.kpis} stagger={0.07} y={22}>
        <StatTile
          label="Distinct vessels observed"
          value={details ? undefined : registry.length}
          loading={details}
          icon={<IconShip size={16} />}
          caption={`Grouped by MMSI across ${pluralize(casesCovered, 'case')} with AIS data.`}
        />
        <StatTile
          label="Ranked as a candidate at least once"
          value={details ? undefined : rankedCount}
          loading={details}
          icon={<IconTarget size={16} />}
          tone="signal"
          caption="A ranking prioritises enquiry. It is a lead, never a finding."
        />
        <StatTile
          label="Seen in more than one case"
          value={details ? undefined : repeatCount}
          loading={details}
          icon={<IconHistory size={16} />}
          tone="neutral"
          caption="Recurrence reflects where traffic runs as much as anything else."
        />
      </Reveal>

      <Reveal className={styles.guards} stagger={0.08}>
        <div className={styles.guard}>
          <span className={styles.guardId}>CON-007</span>
          <span>
            <strong>Absence from this list is not absence from the sea.</strong> Public AIS coverage
            is incomplete — receivers miss vessels out of range, transmissions collide, and some
            vessels carry no AIS at all. This registry holds only what your cases observed.
          </span>
        </div>
        <div className={styles.guard}>
          <span className={styles.guardId}>CON-001</span>
          <span>
            <strong>History, not evidence.</strong> Appearing as a candidate in several cases is
            history, not evidence of wrongdoing — a vessel on a regular route through a busy lane
            will reappear simply because it is often there.
          </span>
        </div>
      </Reveal>

      <Reveal y={18}>
        <Card
          title="Observed vessels"
          description="One row per MMSI. Counts cover the cases aggregated on this screen."
          flush
          footer={
            <div className={styles.footNotices}>
              <NoticeStack notices={vesselNotices} label="About AIS coverage" />
              <NoticeStack notices={rankingNotices} label="About the rankings" />
            </div>
          }
        >
          <div className={styles.toolbar}>
            <div className={styles.search}>
              <span className={styles.searchIcon} aria-hidden="true">
                <IconSearch size={15} />
              </span>
              <Input
                label="Search vessels"
                labelHidden
                type="search"
                placeholder="Name, MMSI, IMO or call sign"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                className={styles.searchInput}
                autoComplete="off"
                spellCheck={false}
              />
            </div>
            <div className={styles.chips} role="group" aria-label="Filter vessels">
              {FILTERS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={styles.chip}
                  aria-pressed={filter === item.key}
                  onClick={() => setFilter(item.key)}
                >
                  {item.label}
                  {details ? null : <span className={styles.chipCount}>{counts[item.key]}</span>}
                </button>
              ))}
            </div>
            <Select
              label="Sort vessels"
              labelHidden
              options={SORT_OPTIONS}
              value={sort}
              onChange={(event) => {
                const next = SORT_OPTIONS.find((option) => option.value === event.target.value);
                if (next) setSort(next.value);
              }}
              containerClassName={styles.sort}
            />
            <div className={styles.viewToggle} role="group" aria-label="Display as">
              <button
                type="button"
                aria-pressed={view === 'table'}
                onClick={() => setView('table')}
              >
                Table
              </button>
              <button
                type="button"
                aria-pressed={view === 'cards'}
                onClick={() => setView('cards')}
              >
                Cards
              </button>
            </div>
          </div>

          <p className={styles.resultLine} aria-live="polite">
            {universe.isPending ? (
              'Loading your cases…'
            ) : (
              <>
                Showing <strong>{visible.length}</strong> of {pluralize(registry.length, 'vessel')}
                {query ? ` matching “${query}”` : ''}
                {filter !== 'all' ? ` · ${activeFilter.label.toLowerCase()}` : ''}
                {universe.isLoadingDetails ? ' · still loading some cases…' : ''}
              </>
            )}
          </p>

          {/* Error and empty states sit outside the table: inside its scroll
              container they would be centred on the table's full width and
              clipped on a phone. */}
          {error ? (
            error
          ) : !details && visible.length === 0 ? (
            empty
          ) : view === 'table' ? (
            <Table
              caption="Vessels observed across your cases"
              columns={COLUMNS}
              rows={visible}
              getRowKey={(row) => String(row.mmsi)}
              loading={details}
            />
          ) : visible.length === 0 ? (
            <div className={styles.cardSkeletons} aria-busy="true">
              <span className="sr-only">Loading vessels</span>
              {Array.from({ length: 6 }, (_, index) => (
                <Skeleton key={index} height="11rem" radius="var(--radius-lg)" />
              ))}
            </div>
          ) : (
            <ul className={styles.cardGrid} aria-label="Vessels observed across your cases">
              {visible.map((row) => (
                <VesselCard key={row.mmsi} row={row} />
              ))}
            </ul>
          )}
        </Card>
      </Reveal>

      {universe.truncated ? (
        <p className={styles.coverageNote}>
          Figures cover the {UNIVERSE_CASE_LIMIT} most recent of {universe.total} cases.
        </p>
      ) : null}
      {universe.failedDetails > 0 ? (
        <p className={styles.coverageNote}>
          {universe.failedDetails} per-case request{universe.failedDetails === 1 ? '' : 's'} could
          not be loaded; the registry above excludes them.
        </p>
      ) : null}
    </main>
  );
}
