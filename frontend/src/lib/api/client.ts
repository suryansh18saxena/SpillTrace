/**
 * Typed fetch wrapper for the SPILLTRACE API (P4-005).
 *
 * Responsibilities, in order of importance:
 *  1. Turn every failure — HTTP status, error envelope, network drop, timeout,
 *     unparseable body — into one `ApiError` with a stable `code`, so the UI has
 *     exactly one error shape to render (NFR-012).
 *  2. Attach the in-memory bearer token, and recover from a single 401 by
 *     refreshing once and replaying the request.
 *  3. Preserve the `request_id` (body or `X-Request-ID` header) so an analyst can
 *     quote it and it can be found in the structured logs (NFR-004).
 */

import { API_BASE_URL, API_PREFIX, REQUEST_TIMEOUT_MS } from '@/lib/config';
import { clearSession, getAccessToken, refreshSession } from '@/lib/auth/session';
import type {
  ApiErrorBody,
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
  LayerManifest,
  LoginRequest,
  LoginResponse,
  PageParams,
  Paginated,
  ParticleCollection,
  Pipeline,
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
  AisPosition,
} from '@/lib/api/types';

// --------------------------------------------------------------------- errors

export const API_ERROR_CODES = {
  BAD_REQUEST: 'BAD_REQUEST',
  UNAUTHENTICATED: 'UNAUTHENTICATED',
  FORBIDDEN: 'FORBIDDEN',
  NOT_FOUND: 'NOT_FOUND',
  CONFLICT: 'CONFLICT',
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  RATE_LIMITED: 'RATE_LIMITED',
  SERVER_ERROR: 'SERVER_ERROR',
  SERVICE_UNAVAILABLE: 'SERVICE_UNAVAILABLE',
  NETWORK_ERROR: 'NETWORK_ERROR',
  TIMEOUT: 'TIMEOUT',
  CANCELLED: 'CANCELLED',
  HTTP_ERROR: 'HTTP_ERROR',
  MALFORMED_RESPONSE: 'MALFORMED_RESPONSE',
  UNKNOWN: 'UNKNOWN',
} as const;

export type ApiErrorCode = (typeof API_ERROR_CODES)[keyof typeof API_ERROR_CODES] | (string & {});

/** API.md §1 — the status → code mapping used when the body has no envelope. */
const STATUS_CODES: Record<number, ApiErrorCode> = {
  400: API_ERROR_CODES.BAD_REQUEST,
  401: API_ERROR_CODES.UNAUTHENTICATED,
  403: API_ERROR_CODES.FORBIDDEN,
  404: API_ERROR_CODES.NOT_FOUND,
  409: API_ERROR_CODES.CONFLICT,
  422: API_ERROR_CODES.VALIDATION_ERROR,
  429: API_ERROR_CODES.RATE_LIMITED,
  500: API_ERROR_CODES.SERVER_ERROR,
  502: API_ERROR_CODES.SERVICE_UNAVAILABLE,
  503: API_ERROR_CODES.SERVICE_UNAVAILABLE,
  504: API_ERROR_CODES.TIMEOUT,
};

/** Analyst-facing fallbacks. Never a stack trace, never a raw exception string. */
const STATUS_MESSAGES: Record<number, string> = {
  400: 'The request was malformed.',
  401: 'Your session has expired. Sign in again to continue.',
  403: 'You are not entitled to this object.',
  404: 'Not found.',
  409: 'That conflicts with the current state — it may already be running.',
  422: 'Some values did not pass validation.',
  429: 'Too many requests. Wait a moment and try again.',
  500: 'The server failed to handle the request.',
  502: 'The server is unreachable.',
  503: 'A required service is unavailable. The job will report the reason.',
  504: 'The server took too long to respond.',
};

export interface ApiErrorOptions {
  code?: ApiErrorCode;
  status?: number;
  details?: Record<string, unknown>;
  requestId?: string | null;
  cause?: unknown;
}

/** The single error type every screen in the application renders. */
export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string | null;

  constructor(message: string, options: ApiErrorOptions = {}) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = 'ApiError';
    this.code = options.code ?? API_ERROR_CODES.UNKNOWN;
    this.status = options.status ?? 0;
    this.details = options.details ?? {};
    this.requestId = options.requestId ?? null;
  }

  get isUnauthenticated(): boolean {
    return this.status === 401 || this.code === API_ERROR_CODES.UNAUTHENTICATED;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  get isValidation(): boolean {
    return this.status === 422 || this.status === 400;
  }

  /** Transient failures worth an automatic retry; 4xx never is. */
  get isRetryable(): boolean {
    if (this.code === API_ERROR_CODES.CANCELLED) return false;
    if (this.status === 0) return this.code !== API_ERROR_CODES.MALFORMED_RESPONSE;
    if (this.status === 429) return true;
    return this.status >= 500;
  }

  /** Field-level messages from a 422, when the backend supplies them. */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    const detail = this.details['detail'] ?? this.details['fields'] ?? this.details['errors'];
    if (Array.isArray(detail)) {
      for (const entry of detail) {
        if (!entry || typeof entry !== 'object') continue;
        const item = entry as { loc?: unknown; msg?: unknown; field?: unknown };
        const field = Array.isArray(item.loc)
          ? String(item.loc[item.loc.length - 1])
          : typeof item.field === 'string'
            ? item.field
            : null;
        if (field && typeof item.msg === 'string') out[field] = item.msg;
      }
    } else if (detail && typeof detail === 'object') {
      for (const [key, value] of Object.entries(detail as Record<string, unknown>)) {
        if (typeof value === 'string') out[key] = value;
      }
    }
    return out;
  }

  /** Normalise anything thrown anywhere into an `ApiError`. */
  static from(error: unknown): ApiError {
    if (error instanceof ApiError) return error;
    if (error instanceof DOMException && error.name === 'AbortError') {
      return new ApiError('The request was cancelled.', {
        code: API_ERROR_CODES.CANCELLED,
        cause: error,
      });
    }
    if (error instanceof Error) {
      return new ApiError(error.message || 'Something went wrong.', {
        code: API_ERROR_CODES.UNKNOWN,
        cause: error,
      });
    }
    return new ApiError('Something went wrong.', { code: API_ERROR_CODES.UNKNOWN, cause: error });
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

// ------------------------------------------------------- unauthenticated signal

type UnauthenticatedListener = () => void;
const unauthenticatedListeners = new Set<UnauthenticatedListener>();

/**
 * Fired when a request is rejected and the refresh could not rescue it. The
 * authenticated shell listens and sends the analyst to the login screen instead
 * of every screen inventing its own redirect.
 */
export function onUnauthenticated(listener: UnauthenticatedListener): () => void {
  unauthenticatedListeners.add(listener);
  return () => {
    unauthenticatedListeners.delete(listener);
  };
}

function emitUnauthenticated(): void {
  for (const listener of unauthenticatedListeners) listener();
}

// ------------------------------------------------------------------- plumbing

export type QueryValue = string | number | boolean | null | undefined | Array<string | number>;
export type QueryParams = Record<string, QueryValue>;

export function buildUrl(path: string, query?: QueryParams): string {
  const base = path.startsWith('http')
    ? path
    : `${API_BASE_URL}${path.startsWith('/api/') || path === '/health' ? '' : API_PREFIX}${path}`;
  if (!query) return base;

  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, String(item));
    } else {
      search.append(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `${base}?${qs}` : base;
}

function combineSignals(signals: Array<AbortSignal | undefined>): {
  signal: AbortSignal;
  dispose: () => void;
} {
  const controller = new AbortController();
  const live = signals.filter((s): s is AbortSignal => Boolean(s));
  const onAbort = (event: Event) => {
    controller.abort((event.target as AbortSignal | null)?.reason);
  };
  for (const signal of live) {
    if (signal.aborted) {
      controller.abort(signal.reason);
      break;
    }
    signal.addEventListener('abort', onAbort);
  }
  return {
    signal: controller.signal,
    dispose: () => {
      for (const signal of live) signal.removeEventListener('abort', onAbort);
    },
  };
}

function readRequestId(response: Response, body: unknown): string | null {
  const fromBody =
    body && typeof body === 'object' && 'error' in body
      ? ((body as ApiErrorBody).error?.request_id ?? null)
      : null;
  return fromBody ?? response.headers.get('X-Request-ID') ?? null;
}

async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204 || response.status === 205) return undefined;
  const text = await response.text();
  if (!text) return undefined;
  const contentType = response.headers.get('Content-Type') ?? '';
  if (contentType.includes('json') || text.startsWith('{') || text.startsWith('[')) {
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  }
  return text;
}

/** Map a non-OK response (and its already-read body) onto an `ApiError`. */
function toApiError(response: Response, body: unknown): ApiError {
  const requestId = readRequestId(response, body);
  const envelope =
    body && typeof body === 'object' && 'error' in body ? (body as ApiErrorBody).error : undefined;

  if (envelope && typeof envelope === 'object') {
    return new ApiError(
      typeof envelope.message === 'string' && envelope.message
        ? envelope.message
        : (STATUS_MESSAGES[response.status] ?? 'The request failed.'),
      {
        code:
          typeof envelope.code === 'string' && envelope.code
            ? envelope.code
            : (STATUS_CODES[response.status] ?? API_ERROR_CODES.HTTP_ERROR),
        status: response.status,
        details: (envelope.details as Record<string, unknown> | undefined) ?? {},
        requestId,
      },
    );
  }

  // Not the documented envelope. Salvage FastAPI's raw `{detail: …}` shape and
  // fall back to a status-derived code so the UI still has something stable.
  const details: Record<string, unknown> =
    body && typeof body === 'object' ? (body as Record<string, unknown>) : {};
  const rawDetail = details['detail'];
  const message =
    typeof rawDetail === 'string' && rawDetail
      ? rawDetail
      : (STATUS_MESSAGES[response.status] ?? `Request failed with status ${response.status}.`);

  return new ApiError(message, {
    code: STATUS_CODES[response.status] ?? API_ERROR_CODES.HTTP_ERROR,
    status: response.status,
    details,
    requestId,
  });
}

export interface ApiRequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  query?: QueryParams;
  body?: unknown;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** Set `false` for endpoints that must not carry a bearer token. */
  auth?: boolean;
  headers?: Record<string, string>;
}

const AUTH_PATHS = new Set(['/auth/login', '/auth/refresh', '/auth/logout']);

async function requestOnce(path: string, options: ApiRequestOptions): Promise<Response> {
  const {
    method = 'GET',
    query,
    body,
    signal,
    timeoutMs = REQUEST_TIMEOUT_MS,
    auth = true,
  } = options;

  const timeoutController = new AbortController();
  const timer = setTimeout(() => {
    timeoutController.abort(new DOMException('Request timed out', 'TimeoutError'));
  }, timeoutMs);
  const combined = combineSignals([signal, timeoutController.signal]);

  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (auth) {
    const token = getAccessToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    return await fetch(buildUrl(path, query), {
      method,
      headers,
      // Always send the httpOnly refresh cookie so `/auth/refresh` works and the
      // server can rotate it. No third-party origin is ever contacted (AD-5).
      credentials: 'include',
      signal: combined.signal,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch (error) {
    if (timeoutController.signal.aborted) {
      throw new ApiError('The request timed out. The server may be busy or unreachable.', {
        code: API_ERROR_CODES.TIMEOUT,
        cause: error,
      });
    }
    if (signal?.aborted) {
      throw new ApiError('The request was cancelled.', {
        code: API_ERROR_CODES.CANCELLED,
        cause: error,
      });
    }
    throw new ApiError('Could not reach the SPILLTRACE API. Check that the service is running.', {
      code: API_ERROR_CODES.NETWORK_ERROR,
      cause: error,
    });
  } finally {
    clearTimeout(timer);
    combined.dispose();
  }
}

/**
 * Perform an API request and return the parsed body.
 *
 * On a 401 the token is refreshed **once** and the request replayed; if that
 * fails the session is cleared and `onUnauthenticated` listeners fire.
 */
export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  let response = await requestOnce(path, options);

  const canRetry = options.auth !== false && !AUTH_PATHS.has(path);
  if (response.status === 401 && canRetry) {
    const refreshed = await refreshSession();
    if (refreshed) {
      response = await requestOnce(path, options);
    }
    if (response.status === 401) {
      clearSession();
      emitUnauthenticated();
    }
  }

  const body = await readBody(response);

  if (!response.ok) throw toApiError(response, body);

  if (body === undefined) return undefined as T;
  if (typeof body === 'string') {
    throw new ApiError('The server returned an unexpected response format.', {
      code: API_ERROR_CODES.MALFORMED_RESPONSE,
      status: response.status,
      requestId: response.headers.get('X-Request-ID'),
    });
  }
  return body as T;
}

// ------------------------------------------------- non-JSON response helpers

/**
 * Fetch a `text/html` endpoint (the rendered evidence report).
 *
 * `apiRequest` deliberately rejects a string body, because everywhere else a
 * string means the server sent HTML when JSON was expected. The report is the
 * one endpoint where HTML *is* the contract, so it gets its own path — with the
 * same 401-refresh, timeout and error mapping.
 */
export async function apiText(path: string, options: ApiRequestOptions = {}): Promise<string> {
  const merged: ApiRequestOptions = {
    ...options,
    headers: { Accept: 'text/html, text/plain;q=0.9, */*;q=0.5', ...options.headers },
  };
  let response = await requestOnce(path, merged);
  if (response.status === 401 && merged.auth !== false) {
    const refreshed = await refreshSession();
    if (refreshed) response = await requestOnce(path, merged);
    if (response.status === 401) {
      clearSession();
      emitUnauthenticated();
    }
  }
  if (!response.ok) throw toApiError(response, await readBody(response));
  return response.text();
}

/** Fetch a binary endpoint (the PDF export) as a Blob, or throw an `ApiError`. */
export async function apiBlob(path: string, options: ApiRequestOptions = {}): Promise<Blob> {
  const merged: ApiRequestOptions = {
    ...options,
    headers: { Accept: 'application/pdf, application/octet-stream', ...options.headers },
  };
  let response = await requestOnce(path, merged);
  if (response.status === 401 && merged.auth !== false) {
    const refreshed = await refreshSession();
    if (refreshed) response = await requestOnce(path, merged);
    if (response.status === 401) {
      clearSession();
      emitUnauthenticated();
    }
  }
  if (!response.ok) throw toApiError(response, await readBody(response));
  return response.blob();
}

/**
 * Absolute URL for the SSE job stream.
 *
 * `EventSource` cannot set an `Authorization` header, so this one read-only
 * endpoint accepts the access token as a query parameter — narrowly, and by the
 * server's own documented design. Nothing else in the client ever puts a token
 * in a URL.
 */
export function jobEventsUrl(caseId: string, accessToken: string): string {
  return buildUrl(`/cases/${encodeURIComponent(caseId)}/events`, { access_token: accessToken });
}

// -------------------------------------------------------------- endpoint map

const get = <T>(path: string, query?: QueryParams, signal?: AbortSignal) =>
  apiRequest<T>(path, { method: 'GET', query, signal });

const post = <T>(path: string, body?: unknown, query?: QueryParams) =>
  apiRequest<T>(path, { method: 'POST', body, query });

/**
 * The typed endpoint surface — one function per route that the running backend
 * actually serves, verified against its live `/openapi.json`.
 *
 * Four routes named in the original contract were never implemented and are
 * absent here on purpose: `/cases/{id}/scenes`, `/cases/{id}/candidates`,
 * `/drift-runs/{id}/origin` and `/vessels/{id}/trajectory`. Scene footprints
 * come from the layer manifest, candidates from `/attributions`, the origin
 * region from the drift-run detail, and vessel tracks from the `trajectories`
 * layer or `/vessels/{id}/positions`.
 */
export const api = {
  // health & system
  health: (signal?: AbortSignal) => get<HealthResponse>('/health', undefined, signal),
  systemStatus: (signal?: AbortSignal) => get<SystemStatus>('/system/status', undefined, signal),
  systemProviders: (signal?: AbortSignal) =>
    get<ProvidersResponse>('/system/providers', undefined, signal),

  // authentication
  login: (body: LoginRequest) =>
    apiRequest<LoginResponse>('/auth/login', { method: 'POST', body, auth: false }),
  logout: () => apiRequest<void>('/auth/logout', { method: 'POST' }),
  me: (signal?: AbortSignal) => get<User>('/auth/me', undefined, signal),

  // cases
  listCases: (params: CaseListParams = {}, signal?: AbortSignal) =>
    get<Paginated<Case>>('/cases', params as QueryParams, signal),
  getCase: (caseId: string, signal?: AbortSignal) =>
    get<Case>(`/cases/${encodeURIComponent(caseId)}`, undefined, signal),
  createCase: (body: CreateCaseRequest) => post<Case>('/cases', body),
  updateCase: (caseId: string, body: UpdateCaseRequest) =>
    apiRequest<Case>(`/cases/${encodeURIComponent(caseId)}`, { method: 'PATCH', body }),
  archiveCase: (caseId: string) => post<Case>(`/cases/${encodeURIComponent(caseId)}/archive`),

  // pipeline & jobs
  startPipeline: (caseId: string, body: StartPipelineRequest) =>
    post<StartPipelineResponse>(`/cases/${encodeURIComponent(caseId)}/pipeline`, body),
  getPipeline: (caseId: string, signal?: AbortSignal) =>
    get<Pipeline>(`/cases/${encodeURIComponent(caseId)}/pipeline`, undefined, signal),
  createJob: (caseId: string, body: CreateJobRequest) =>
    post<Job>(`/cases/${encodeURIComponent(caseId)}/jobs`, body),
  listJobs: (caseId: string, params: PageParams = {}, signal?: AbortSignal) =>
    get<Paginated<Job>>(`/cases/${encodeURIComponent(caseId)}/jobs`, params as QueryParams, signal),
  getJob: (jobId: string, signal?: AbortSignal) =>
    get<Job>(`/jobs/${encodeURIComponent(jobId)}`, undefined, signal),
  cancelJob: (jobId: string) => post<Job>(`/jobs/${encodeURIComponent(jobId)}/cancel`),
  retryJob: (jobId: string) => post<Job>(`/jobs/${encodeURIComponent(jobId)}/retry`),

  // detections & look-alike verification
  listDetections: (caseId: string, signal?: AbortSignal) =>
    get<DetectionListResponse>(
      `/cases/${encodeURIComponent(caseId)}/detections`,
      undefined,
      signal,
    ),
  getDetection: (spillId: string, signal?: AbortSignal) =>
    get<SpillDetectionDetail>(`/detections/${encodeURIComponent(spillId)}`, undefined, signal),
  getVerification: (spillId: string, signal?: AbortSignal) =>
    get<VerificationResult>(
      `/detections/${encodeURIComponent(spillId)}/verification`,
      undefined,
      signal,
    ),

  // environment & drift
  getEnvironment: (caseId: string, signal?: AbortSignal) =>
    get<Paginated<EnvironmentalRun>>(
      `/cases/${encodeURIComponent(caseId)}/environment`,
      undefined,
      signal,
    ),
  listDriftRuns: (caseId: string, signal?: AbortSignal) =>
    get<DriftRunListResponse>(`/cases/${encodeURIComponent(caseId)}/drift-runs`, undefined, signal),
  getDriftRun: (runId: string, signal?: AbortSignal) =>
    get<DriftRunDetail>(`/drift-runs/${encodeURIComponent(runId)}`, undefined, signal),
  getDriftParticles: (runId: string, step?: number | null, signal?: AbortSignal) =>
    get<ParticleCollection>(
      `/drift-runs/${encodeURIComponent(runId)}/particles`,
      step === null || step === undefined ? undefined : { step },
      signal,
    ),

  // AIS, vessels, trajectories
  listVessels: (caseId: string, signal?: AbortSignal) =>
    get<VesselListResponse>(`/cases/${encodeURIComponent(caseId)}/vessels`, undefined, signal),
  getVessel: (vesselId: string, signal?: AbortSignal) =>
    get<VesselDetail>(`/vessels/${encodeURIComponent(vesselId)}`, undefined, signal),
  listVesselPositions: (
    vesselId: string,
    params: VesselPositionsParams = {},
    signal?: AbortSignal,
  ) =>
    get<Paginated<AisPosition>>(
      `/vessels/${encodeURIComponent(vesselId)}/positions`,
      params as QueryParams,
      signal,
    ),

  // correlation, scoring, ranking
  listAttributions: (caseId: string, signal?: AbortSignal) =>
    get<AttributionListResponse>(
      `/cases/${encodeURIComponent(caseId)}/attributions`,
      undefined,
      signal,
    ),
  getAttribution: (attributionId: string, signal?: AbortSignal) =>
    get<AttributionDetail>(`/attributions/${encodeURIComponent(attributionId)}`, undefined, signal),

  // map layers
  getLayerManifest: (caseId: string, signal?: AbortSignal) =>
    get<LayerManifest>(`/cases/${encodeURIComponent(caseId)}/layers`, undefined, signal),
  getLayerData: (caseId: string, layerId: string, signal?: AbortSignal) =>
    get<FeatureCollection>(
      `/cases/${encodeURIComponent(caseId)}/layers/${encodeURIComponent(layerId)}`,
      undefined,
      signal,
    ),

  // evidence report
  getReportHtml: (caseId: string, signal?: AbortSignal) =>
    apiText(`/cases/${encodeURIComponent(caseId)}/report.html`, { signal }),
  getReportPdf: (caseId: string, signal?: AbortSignal) =>
    apiBlob(`/cases/${encodeURIComponent(caseId)}/report.pdf`, { signal }),
  listArtifacts: (caseId: string, signal?: AbortSignal) =>
    get<Paginated<EvidenceArtifact>>(
      `/cases/${encodeURIComponent(caseId)}/artifacts`,
      undefined,
      signal,
    ),

  // demo
  listDemoScenarios: (signal?: AbortSignal) =>
    get<DemoScenariosResponse>('/demo/scenarios', undefined, signal),
  createDemoCase: (body: CreateDemoCaseRequest) => post<DemoCaseResponse>('/demo/cases', body),
} as const;
