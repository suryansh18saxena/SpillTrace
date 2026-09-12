'use client';

/**
 * TanStack Query v5 bindings for the endpoint surface in `client.ts`.
 *
 * Conventions:
 *  - One hierarchical key factory (`queryKeys`) so invalidating a case
 *    invalidates everything derived from it.
 *  - Retries are decided by `ApiError.isRetryable`: a 404 or a 422 is a fact, not
 *    a blip, and retrying it just delays the empty/error state the analyst needs
 *    to see.
 *  - Job-bearing queries poll while anything is still running and stop as soon as
 *    the pipeline settles, so an idle investigation costs nothing.
 */

import {
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryOptions,
  type UseQueryResult,
} from '@tanstack/react-query';
import { api, ApiError } from '@/lib/api/client';
import { clearSession, setSession } from '@/lib/auth/session';
import type {
  AisPosition,
  AttributionDetail,
  AttributionListResponse,
  Case,
  CaseListParams,
  CreateCaseRequest,
  CreateDemoCaseRequest,
  CreateJobRequest,
  DemoCaseResponse,
  DemoScenariosResponse,
  DetectionListResponse,
  DriftRunDetail,
  DriftRunListResponse,
  EnvironmentalRun,
  EvidenceArtifact,
  FeatureCollection,
  HealthResponse,
  Job,
  JobStatus,
  LayerDescriptor,
  LayerManifest,
  LoginRequest,
  LoginResponse,
  PageParams,
  Paginated,
  ParticleCollection,
  Pipeline,
  PipelineStage,
  ProvidersResponse,
  SpillDetectionDetail,
  StartPipelineRequest,
  StartPipelineResponse,
  SystemStatus,
  UpdateCaseRequest,
  User,
  VerificationResult,
  VesselDetail,
  VesselListResponse,
  VesselPositionsParams,
} from '@/lib/api/types';

// ----------------------------------------------------------------- query keys

export const queryKeys = {
  all: ['spilltrace'] as const,
  health: () => [...queryKeys.all, 'health'] as const,
  system: () => [...queryKeys.all, 'system'] as const,
  systemStatus: () => [...queryKeys.system(), 'status'] as const,
  systemProviders: () => [...queryKeys.system(), 'providers'] as const,
  me: () => [...queryKeys.all, 'me'] as const,
  cases: () => [...queryKeys.all, 'cases'] as const,
  caseList: (params: CaseListParams) => [...queryKeys.cases(), 'list', params] as const,
  case: (caseId: string) => [...queryKeys.cases(), 'detail', caseId] as const,
  caseJobs: (caseId: string, params: PageParams) =>
    [...queryKeys.case(caseId), 'jobs', params] as const,
  casePipeline: (caseId: string) => [...queryKeys.case(caseId), 'pipeline'] as const,
  caseDetections: (caseId: string) => [...queryKeys.case(caseId), 'detections'] as const,
  caseEnvironment: (caseId: string) => [...queryKeys.case(caseId), 'environment'] as const,
  caseDriftRuns: (caseId: string) => [...queryKeys.case(caseId), 'drift-runs'] as const,
  caseVessels: (caseId: string) => [...queryKeys.case(caseId), 'vessels'] as const,
  caseAttributions: (caseId: string) => [...queryKeys.case(caseId), 'attributions'] as const,
  caseLayers: (caseId: string) => [...queryKeys.case(caseId), 'layers'] as const,
  caseLayerData: (caseId: string, layerId: string) =>
    [...queryKeys.caseLayers(caseId), layerId] as const,
  caseReportHtml: (caseId: string) => [...queryKeys.case(caseId), 'report', 'html'] as const,
  caseReportPdf: (caseId: string) => [...queryKeys.case(caseId), 'report', 'pdf'] as const,
  caseArtifacts: (caseId: string) => [...queryKeys.case(caseId), 'artifacts'] as const,
  detection: (spillId: string) => [...queryKeys.all, 'detections', spillId] as const,
  verification: (spillId: string) => [...queryKeys.detection(spillId), 'verification'] as const,
  driftRun: (runId: string) => [...queryKeys.all, 'drift-runs', runId] as const,
  driftParticles: (runId: string, step: number | null) =>
    [...queryKeys.driftRun(runId), 'particles', step] as const,
  vessel: (vesselId: string) => [...queryKeys.all, 'vessels', vesselId] as const,
  vesselPositions: (vesselId: string, params: VesselPositionsParams) =>
    [...queryKeys.vessel(vesselId), 'positions', params] as const,
  attribution: (attributionId: string) =>
    [...queryKeys.all, 'attributions', attributionId] as const,
  job: (jobId: string) => [...queryKeys.all, 'jobs', jobId] as const,
  demoScenarios: () => [...queryKeys.all, 'demo', 'scenarios'] as const,
} as const;

// -------------------------------------------------------------------- policy

/** Shared retry policy: transient failures only, at most twice. */
export function retryPolicy(failureCount: number, error: unknown): boolean {
  if (failureCount >= 2) return false;
  return error instanceof ApiError ? error.isRetryable : false;
}

const ACTIVE_JOB_STATUSES = new Set<JobStatus>(['QUEUED', 'RUNNING']);

export function hasActiveJob(jobs: readonly { status: JobStatus }[] | undefined): boolean {
  return Boolean(jobs?.some((job) => ACTIVE_JOB_STATUSES.has(job.status)));
}

/** The stages of a pipeline, whichever of the two response shapes arrived. */
export function pipelineStages(pipeline: Pipeline | undefined): PipelineStage[] {
  if (!pipeline) return [];
  if (pipeline.stages?.length) return pipeline.stages;
  return (pipeline.jobs ?? []).map((job) => ({
    job_id: job.id,
    job_type: job.job_type,
    status: job.status,
    progress: job.progress,
    step: job.step,
    error_code: job.error_code,
    error_message: job.error_message,
  }));
}

/**
 * Poll interval used whenever the SSE stream is unavailable or has errored.
 *
 * `useJobStream` is the primary transport; this is the fallback, and it is
 * bounded — it stops the moment nothing is QUEUED or RUNNING.
 */
export const JOB_POLL_MS = 4_000;

// ---------------------------------------------------------------------- auth

export function useLogin(): UseMutationResult<LoginResponse, ApiError, LoginRequest> {
  const queryClient = useQueryClient();
  return useMutation<LoginResponse, ApiError, LoginRequest>({
    mutationFn: (credentials) => api.login(credentials),
    onSuccess: (data) => {
      setSession(data);
      queryClient.setQueryData(queryKeys.me(), data.user);
    },
  });
}

export function useLogout(): UseMutationResult<void, ApiError, void> {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: () => api.logout(),
    // Whether or not the server call succeeds, the local session must go.
    onSettled: () => {
      clearSession();
      queryClient.clear();
    },
  });
}

export function useMe(enabled = true): UseQueryResult<User, ApiError> {
  return useQuery<User, ApiError>({
    queryKey: queryKeys.me(),
    queryFn: ({ signal }) => api.me(signal),
    enabled,
    retry: retryPolicy,
    staleTime: 5 * 60_000,
  });
}

// --------------------------------------------------------------------- system

export function useHealth(): UseQueryResult<HealthResponse, ApiError> {
  return useQuery<HealthResponse, ApiError>({
    queryKey: queryKeys.health(),
    queryFn: ({ signal }) => api.health(signal),
    retry: retryPolicy,
    refetchInterval: 30_000,
  });
}

export function useSystemStatus(enabled = true): UseQueryResult<SystemStatus, ApiError> {
  return useQuery<SystemStatus, ApiError>({
    queryKey: queryKeys.systemStatus(),
    queryFn: ({ signal }) => api.systemStatus(signal),
    enabled,
    retry: retryPolicy,
    refetchInterval: 15_000,
  });
}

/**
 * Which adapter each port resolved to. Unlike `/system/status` this is open to
 * every signed-in user, because an analyst has to be able to see that the data
 * in front of them is SYNTHETIC without holding an admin role (CON-009).
 */
export function useSystemProviders(enabled = true): UseQueryResult<ProvidersResponse, ApiError> {
  return useQuery<ProvidersResponse, ApiError>({
    queryKey: queryKeys.systemProviders(),
    queryFn: ({ signal }) => api.systemProviders(signal),
    enabled,
    retry: retryPolicy,
    staleTime: 60_000,
  });
}

// ---------------------------------------------------------------------- cases

export function useCases(
  params: CaseListParams = {},
  options: { enabled?: boolean; refetchInterval?: number } = {},
): UseQueryResult<Paginated<Case>, ApiError> {
  return useQuery<Paginated<Case>, ApiError>({
    queryKey: queryKeys.caseList(params),
    queryFn: ({ signal }) => api.listCases(params, signal),
    enabled: options.enabled ?? true,
    retry: retryPolicy,
    placeholderData: (previous) => previous,
    ...(options.refetchInterval ? { refetchInterval: options.refetchInterval } : {}),
  });
}

export function useCase(
  caseId: string | undefined,
  options: Partial<UseQueryOptions<Case, ApiError>> = {},
): UseQueryResult<Case, ApiError> {
  return useQuery<Case, ApiError>({
    queryKey: queryKeys.case(caseId ?? ''),
    queryFn: ({ signal }) => api.getCase(caseId as string, signal),
    retry: retryPolicy,
    ...options,
    // Deliberately after the spread: a caller must never be able to enable a
    // query that has no case id, which would request `/cases/undefined`.
    enabled: Boolean(caseId) && (options.enabled ?? true),
  });
}

export function useCreateCase(): UseMutationResult<Case, ApiError, CreateCaseRequest> {
  const queryClient = useQueryClient();
  return useMutation<Case, ApiError, CreateCaseRequest>({
    mutationFn: (body) => api.createCase(body),
    onSuccess: (created) => {
      queryClient.setQueryData(queryKeys.case(created.id), created);
      void queryClient.invalidateQueries({ queryKey: queryKeys.cases() });
    },
  });
}

export function useUpdateCase(
  caseId: string,
): UseMutationResult<Case, ApiError, UpdateCaseRequest> {
  const queryClient = useQueryClient();
  return useMutation<Case, ApiError, UpdateCaseRequest>({
    mutationFn: (body) => api.updateCase(caseId, body),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.case(caseId), updated);
      void queryClient.invalidateQueries({ queryKey: queryKeys.cases() });
    },
  });
}

export function useArchiveCase(): UseMutationResult<Case, ApiError, string> {
  const queryClient = useQueryClient();
  return useMutation<Case, ApiError, string>({
    mutationFn: (caseId) => api.archiveCase(caseId),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.case(updated.id), updated);
      void queryClient.invalidateQueries({ queryKey: queryKeys.cases() });
    },
  });
}

// ------------------------------------------------------------ pipeline & jobs

export function useJobs(
  caseId: string | undefined,
  params: PageParams = {},
  options: { poll?: boolean } = {},
): UseQueryResult<Paginated<Job>, ApiError> {
  const poll = options.poll ?? true;
  return useQuery<Paginated<Job>, ApiError>({
    queryKey: queryKeys.caseJobs(caseId ?? '', params),
    queryFn: ({ signal }) => api.listJobs(caseId as string, params, signal),
    enabled: Boolean(caseId),
    retry: retryPolicy,
    refetchInterval: (query) =>
      poll && hasActiveJob(query.state.data?.items) ? JOB_POLL_MS : false,
  });
}

export function useJob(jobId: string | undefined): UseQueryResult<Job, ApiError> {
  return useQuery<Job, ApiError>({
    queryKey: queryKeys.job(jobId ?? ''),
    queryFn: ({ signal }) => api.getJob(jobId as string, signal),
    enabled: Boolean(jobId),
    retry: retryPolicy,
    refetchInterval: (query) =>
      query.state.data && ACTIVE_JOB_STATUSES.has(query.state.data.status) ? JOB_POLL_MS : false,
  });
}

export function usePipeline(
  caseId: string | undefined,
  options: { poll?: boolean } = {},
): UseQueryResult<Pipeline, ApiError> {
  const poll = options.poll ?? true;
  return useQuery<Pipeline, ApiError>({
    queryKey: queryKeys.casePipeline(caseId ?? ''),
    queryFn: ({ signal }) => api.getPipeline(caseId as string, signal),
    enabled: Boolean(caseId),
    // A case that has never been run has no pipeline; that is an empty state,
    // not an error, so a 404 here must not be retried.
    retry: retryPolicy,
    refetchInterval: (query) =>
      poll && hasActiveJob(pipelineStages(query.state.data)) ? JOB_POLL_MS : false,
  });
}

export function useStartPipeline(
  caseId: string,
): UseMutationResult<StartPipelineResponse, ApiError, StartPipelineRequest> {
  const queryClient = useQueryClient();
  return useMutation<StartPipelineResponse, ApiError, StartPipelineRequest>({
    mutationFn: (body) => api.startPipeline(caseId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.case(caseId) });
    },
  });
}

export function useCreateJob(caseId: string): UseMutationResult<Job, ApiError, CreateJobRequest> {
  const queryClient = useQueryClient();
  return useMutation<Job, ApiError, CreateJobRequest>({
    mutationFn: (body) => api.createJob(caseId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.case(caseId) });
    },
  });
}

export function useCancelJob(caseId?: string): UseMutationResult<Job, ApiError, string> {
  const queryClient = useQueryClient();
  return useMutation<Job, ApiError, string>({
    mutationFn: (jobId) => api.cancelJob(jobId),
    onSuccess: (job) => {
      queryClient.setQueryData(queryKeys.job(job.id), job);
      if (caseId) void queryClient.invalidateQueries({ queryKey: queryKeys.case(caseId) });
    },
  });
}

export function useRetryJob(caseId?: string): UseMutationResult<Job, ApiError, string> {
  const queryClient = useQueryClient();
  return useMutation<Job, ApiError, string>({
    mutationFn: (jobId) => api.retryJob(jobId),
    onSuccess: (job) => {
      queryClient.setQueryData(queryKeys.job(job.id), job);
      if (caseId) void queryClient.invalidateQueries({ queryKey: queryKeys.case(caseId) });
    },
  });
}

// ------------------------------------------------ detections & verification

export function useDetections(
  caseId: string | undefined,
): UseQueryResult<DetectionListResponse, ApiError> {
  return useQuery<DetectionListResponse, ApiError>({
    queryKey: queryKeys.caseDetections(caseId ?? ''),
    queryFn: ({ signal }) => api.listDetections(caseId as string, signal),
    enabled: Boolean(caseId),
    retry: retryPolicy,
  });
}

export function useDetection(
  spillId: string | undefined,
): UseQueryResult<SpillDetectionDetail, ApiError> {
  return useQuery<SpillDetectionDetail, ApiError>({
    queryKey: queryKeys.detection(spillId ?? ''),
    queryFn: ({ signal }) => api.getDetection(spillId as string, signal),
    enabled: Boolean(spillId),
    retry: retryPolicy,
  });
}

export function useVerification(
  spillId: string | undefined,
): UseQueryResult<VerificationResult, ApiError> {
  return useQuery<VerificationResult, ApiError>({
    queryKey: queryKeys.verification(spillId ?? ''),
    queryFn: ({ signal }) => api.getVerification(spillId as string, signal),
    enabled: Boolean(spillId),
    retry: retryPolicy,
  });
}

// -------------------------------------------------------- environment & drift

export function useEnvironment(
  caseId: string | undefined,
): UseQueryResult<Paginated<EnvironmentalRun>, ApiError> {
  return useQuery<Paginated<EnvironmentalRun>, ApiError>({
    queryKey: queryKeys.caseEnvironment(caseId ?? ''),
    queryFn: ({ signal }) => api.getEnvironment(caseId as string, signal),
    enabled: Boolean(caseId),
    retry: retryPolicy,
  });
}

export function useDriftRuns(
  caseId: string | undefined,
): UseQueryResult<DriftRunListResponse, ApiError> {
  return useQuery<DriftRunListResponse, ApiError>({
    queryKey: queryKeys.caseDriftRuns(caseId ?? ''),
    queryFn: ({ signal }) => api.listDriftRuns(caseId as string, signal),
    enabled: Boolean(caseId),
    retry: retryPolicy,
  });
}

export function useDriftRun(runId: string | undefined): UseQueryResult<DriftRunDetail, ApiError> {
  return useQuery<DriftRunDetail, ApiError>({
    queryKey: queryKeys.driftRun(runId ?? ''),
    queryFn: ({ signal }) => api.getDriftRun(runId as string, signal),
    enabled: Boolean(runId),
    retry: retryPolicy,
  });
}

/**
 * Particles for a drift run.
 *
 * `step` must be one of the values in `ParticleCollection.steps` — they are the
 * simulation's own step indices (0, 6, 12, …), not a dense range. Asking for a
 * step that does not exist returns an empty collection, so the animator always
 * seeds itself from the full response first.
 */
export function useDriftParticles(
  runId: string | undefined,
  step: number | null = null,
): UseQueryResult<ParticleCollection, ApiError> {
  return useQuery<ParticleCollection, ApiError>({
    queryKey: queryKeys.driftParticles(runId ?? '', step),
    queryFn: ({ signal }) => api.getDriftParticles(runId as string, step, signal),
    enabled: Boolean(runId),
    retry: retryPolicy,
    staleTime: 5 * 60_000,
  });
}

// ------------------------------------------------------------------- vessels

export function useVessels(
  caseId: string | undefined,
): UseQueryResult<VesselListResponse, ApiError> {
  return useQuery<VesselListResponse, ApiError>({
    queryKey: queryKeys.caseVessels(caseId ?? ''),
    queryFn: ({ signal }) => api.listVessels(caseId as string, signal),
    enabled: Boolean(caseId),
    retry: retryPolicy,
  });
}

export function useVessel(vesselId: string | undefined): UseQueryResult<VesselDetail, ApiError> {
  return useQuery<VesselDetail, ApiError>({
    queryKey: queryKeys.vessel(vesselId ?? ''),
    queryFn: ({ signal }) => api.getVessel(vesselId as string, signal),
    enabled: Boolean(vesselId),
    retry: retryPolicy,
  });
}

export function useVesselPositions(
  vesselId: string | undefined,
  params: VesselPositionsParams = {},
): UseQueryResult<Paginated<AisPosition>, ApiError> {
  return useQuery<Paginated<AisPosition>, ApiError>({
    queryKey: queryKeys.vesselPositions(vesselId ?? '', params),
    queryFn: ({ signal }) => api.listVesselPositions(vesselId as string, params, signal),
    enabled: Boolean(vesselId),
    retry: retryPolicy,
    placeholderData: (previous) => previous,
  });
}

// ------------------------------------------------------------- attributions

export function useAttributions(
  caseId: string | undefined,
): UseQueryResult<AttributionListResponse, ApiError> {
  return useQuery<AttributionListResponse, ApiError>({
    queryKey: queryKeys.caseAttributions(caseId ?? ''),
    queryFn: ({ signal }) => api.listAttributions(caseId as string, signal),
    enabled: Boolean(caseId),
    retry: retryPolicy,
  });
}

export function useAttribution(
  attributionId: string | undefined,
): UseQueryResult<AttributionDetail, ApiError> {
  return useQuery<AttributionDetail, ApiError>({
    queryKey: queryKeys.attribution(attributionId ?? ''),
    queryFn: ({ signal }) => api.getAttribution(attributionId as string, signal),
    enabled: Boolean(attributionId),
    retry: retryPolicy,
  });
}

// ------------------------------------------------------- report & artifacts

export function useReportHtml(caseId: string | undefined): UseQueryResult<string, ApiError> {
  return useQuery<string, ApiError>({
    queryKey: queryKeys.caseReportHtml(caseId ?? ''),
    queryFn: ({ signal }) => api.getReportHtml(caseId as string, signal),
    enabled: Boolean(caseId),
    retry: retryPolicy,
    staleTime: 60_000,
  });
}

/**
 * Download the PDF export, which legitimately may not exist.
 *
 * A mutation rather than a query: a 404 here is normal (`report.pdf` is only
 * produced when the PDF toolchain is installed) and must not look like a failed
 * page load. The report screen calls this from a button and renders "not
 * available on this deployment" when it 404s.
 */
export function useReportPdfDownload(
  caseId: string | undefined,
): UseMutationResult<Blob, ApiError, void> {
  return useMutation<Blob, ApiError, void>({
    mutationFn: () => api.getReportPdf(caseId as string),
  });
}

export function useArtifacts(
  caseId: string | undefined,
): UseQueryResult<Paginated<EvidenceArtifact>, ApiError> {
  return useQuery<Paginated<EvidenceArtifact>, ApiError>({
    queryKey: queryKeys.caseArtifacts(caseId ?? ''),
    queryFn: ({ signal }) => api.listArtifacts(caseId as string, signal),
    enabled: Boolean(caseId),
    retry: retryPolicy,
  });
}

// ---------------------------------------------------------------- map layers

export function useLayerManifest(
  caseId: string | undefined,
): UseQueryResult<LayerManifest, ApiError> {
  return useQuery<LayerManifest, ApiError>({
    queryKey: queryKeys.caseLayers(caseId ?? ''),
    queryFn: ({ signal }) => api.getLayerManifest(caseId as string, signal),
    enabled: Boolean(caseId),
    retry: retryPolicy,
  });
}

export function useLayerData(
  caseId: string | undefined,
  layerId: string | undefined,
  enabled = true,
): UseQueryResult<FeatureCollection, ApiError> {
  return useQuery<FeatureCollection, ApiError>({
    queryKey: queryKeys.caseLayerData(caseId ?? '', layerId ?? ''),
    queryFn: ({ signal }) => api.getLayerData(caseId as string, layerId as string, signal),
    enabled: Boolean(caseId) && Boolean(layerId) && enabled,
    retry: retryPolicy,
    staleTime: 60_000,
  });
}

/**
 * Fetches the GeoJSON for several manifest layers at once.
 *
 * `useQueries` rather than a `useLayerData` call per layer: the manifest length
 * is decided by the server, and React forbids calling a hook in a variable-length
 * loop. Only layers the analyst has switched on are fetched, so an investigation
 * with eight layers does not pull eight payloads to draw two.
 */
export function useLayerDataSet(
  caseId: string | undefined,
  layers: readonly LayerDescriptor[],
  isVisible: (layerId: string) => boolean,
) {
  return useQueries({
    queries: layers.map((layer) => ({
      queryKey: queryKeys.caseLayerData(caseId ?? '', layer.id),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        api.getLayerData(caseId as string, layer.id, signal),
      enabled:
        Boolean(caseId) &&
        layer.type === 'geojson' &&
        layer.available !== false &&
        isVisible(layer.id),
      retry: retryPolicy,
      staleTime: 60_000,
    })),
  });
}

// ---------------------------------------------------------------------- demo

export function useDemoScenarios(): UseQueryResult<DemoScenariosResponse, ApiError> {
  return useQuery<DemoScenariosResponse, ApiError>({
    queryKey: queryKeys.demoScenarios(),
    queryFn: ({ signal }) => api.listDemoScenarios(signal),
    retry: retryPolicy,
    staleTime: 5 * 60_000,
  });
}

/**
 * Create a demo case.
 *
 * The endpoint returns `{case, scenario, pipeline_id, notice}` rather than a
 * bare case, so the caller gets the wrapper and the cache is seeded from
 * `result.case` — reading `result.id` here would silently be `undefined`.
 */
export function useCreateDemoCase(): UseMutationResult<
  DemoCaseResponse,
  ApiError,
  CreateDemoCaseRequest
> {
  const queryClient = useQueryClient();
  return useMutation<DemoCaseResponse, ApiError, CreateDemoCaseRequest>({
    mutationFn: (body) => api.createDemoCase(body),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.case(result.case.id), result.case);
      void queryClient.invalidateQueries({ queryKey: queryKeys.cases() });
    },
  });
}
