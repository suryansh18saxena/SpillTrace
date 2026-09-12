'use client';

/**
 * Cross-case views over a strictly case-scoped API.
 *
 * The backend exposes no global vessel list, job feed or analytics endpoint —
 * every resource hangs off a case. The overview screens (dashboard, situational
 * map, analytics, vessel registry, activity feed, notifications) therefore read
 * the most recent cases and fan out to each case's own endpoints.
 *
 * Two properties keep that honest and cheap:
 *  - every per-case query uses the **same query key** the case pages use, so a
 *    case the analyst already opened costs nothing here and vice versa;
 *  - the fan-out is bounded (`UNIVERSE_CASE_LIMIT`), and every screen that
 *    aggregates says how many cases it covered when it could not cover them all.
 *    A figure computed from 50 of 80 cases is labelled as such, never presented
 *    as a total.
 */

import { useQueries, type UseQueryResult } from '@tanstack/react-query';
import { api, type ApiError } from '@/lib/api/client';
import { queryKeys, retryPolicy, useCases } from '@/lib/api/hooks';
import type {
  AttributionListResponse,
  Case,
  CaseListParams,
  DetectionListResponse,
  DriftRunListResponse,
  Job,
  Paginated,
  VesselListResponse,
} from '@/lib/api/types';

/** Upper bound on cases fanned out to. The API's own page limit is 200. */
export const UNIVERSE_CASE_LIMIT = 50;

export interface UniverseOptions {
  attributions?: boolean;
  detections?: boolean;
  vessels?: boolean;
  jobs?: boolean;
  driftRuns?: boolean;
  includeArchived?: boolean;
  /** Poll the case list (e.g. for notifications). Milliseconds. */
  refetchInterval?: number;
}

export interface CaseBundle {
  case: Case;
  attributions?: AttributionListResponse;
  detections?: DetectionListResponse;
  vessels?: VesselListResponse;
  jobs?: Paginated<Job>;
  driftRuns?: DriftRunListResponse;
}

export interface CaseUniverse {
  cases: Case[];
  /** Server-side total, which can exceed `cases.length`. */
  total: number;
  /** `true` when more cases exist than were aggregated. */
  truncated: boolean;
  bundles: CaseBundle[];
  /** The case list itself is still loading. */
  isPending: boolean;
  /** At least one per-case detail query is still loading. */
  isLoadingDetails: boolean;
  /** Per-case detail queries that failed (the rest still render). */
  failedDetails: number;
  isError: boolean;
  error: ApiError | null;
  refetch: () => void;
}

/** A case that has never run a pipeline has no derived data to fetch. */
function hasPipelineData(item: Case): boolean {
  return item.status !== 'DRAFT';
}

const DETAIL_STALE_MS = 60_000;

export function useCaseUniverse(options: UniverseOptions = {}): CaseUniverse {
  const params: CaseListParams = {
    limit: UNIVERSE_CASE_LIMIT,
    offset: 0,
    ...(options.includeArchived ? { include_archived: true } : {}),
  };
  const casesQuery = useCases(
    params,
    options.refetchInterval ? { refetchInterval: options.refetchInterval } : {},
  );
  const cases = casesQuery.data?.items ?? [];

  const withData = cases.filter(hasPipelineData);

  const attributions = useQueries({
    queries: withData.map((item) => ({
      queryKey: queryKeys.caseAttributions(item.id),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.listAttributions(item.id, signal),
      enabled: Boolean(options.attributions),
      retry: retryPolicy,
      staleTime: DETAIL_STALE_MS,
    })),
  }) as UseQueryResult<AttributionListResponse, ApiError>[];

  const detections = useQueries({
    queries: withData.map((item) => ({
      queryKey: queryKeys.caseDetections(item.id),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.listDetections(item.id, signal),
      enabled: Boolean(options.detections),
      retry: retryPolicy,
      staleTime: DETAIL_STALE_MS,
    })),
  }) as UseQueryResult<DetectionListResponse, ApiError>[];

  const vessels = useQueries({
    queries: withData.map((item) => ({
      queryKey: queryKeys.caseVessels(item.id),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.listVessels(item.id, signal),
      enabled: Boolean(options.vessels),
      retry: retryPolicy,
      staleTime: DETAIL_STALE_MS,
    })),
  }) as UseQueryResult<VesselListResponse, ApiError>[];

  const jobs = useQueries({
    queries: withData.map((item) => ({
      queryKey: queryKeys.caseJobs(item.id, { limit: 50 }),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api.listJobs(item.id, { limit: 50 }, signal),
      enabled: Boolean(options.jobs),
      retry: retryPolicy,
      staleTime: DETAIL_STALE_MS,
    })),
  }) as UseQueryResult<Paginated<Job>, ApiError>[];

  const driftRuns = useQueries({
    queries: withData.map((item) => ({
      queryKey: queryKeys.caseDriftRuns(item.id),
      queryFn: ({ signal }: { signal: AbortSignal }) => api.listDriftRuns(item.id, signal),
      enabled: Boolean(options.driftRuns),
      retry: retryPolicy,
      staleTime: DETAIL_STALE_MS,
    })),
  }) as UseQueryResult<DriftRunListResponse, ApiError>[];

  const indexOf = new Map(withData.map((item, index) => [item.id, index]));
  const bundles: CaseBundle[] = cases.map((item) => {
    const index = indexOf.get(item.id);
    if (index === undefined) return { case: item };
    return {
      case: item,
      attributions: attributions[index]?.data,
      detections: detections[index]?.data,
      vessels: vessels[index]?.data,
      jobs: jobs[index]?.data,
      driftRuns: driftRuns[index]?.data,
    };
  });

  const enabledGroups = [
    options.attributions ? attributions : [],
    options.detections ? detections : [],
    options.vessels ? vessels : [],
    options.jobs ? jobs : [],
    options.driftRuns ? driftRuns : [],
  ];
  const isLoadingDetails = enabledGroups.some((group) => group.some((q) => q.isPending));
  const failedDetails = enabledGroups.reduce(
    (sum, group) => sum + group.filter((q) => q.isError).length,
    0,
  );

  const total = casesQuery.data?.total ?? cases.length;

  return {
    cases,
    total,
    truncated: total > cases.length,
    bundles,
    isPending: casesQuery.isPending,
    isLoadingDetails,
    failedDetails,
    isError: casesQuery.isError,
    error: casesQuery.error ?? null,
    // "Refresh" means everything on screen, not just the list of cases.
    refetch: () => {
      void casesQuery.refetch();
      for (const group of enabledGroups) for (const query of group) void query.refetch();
    },
  };
}
