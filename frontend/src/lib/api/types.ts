/**
 * Types for the SPILLTRACE API.
 *
 * These are reconciled against the **live** OpenAPI document served by the
 * running backend (`GET /openapi.json`) and against real recorded responses, not
 * against a paper contract: several endpoints named in `docs/API.md` never
 * shipped (`/cases/{id}/scenes`, `/cases/{id}/candidates`,
 * `/drift-runs/{id}/origin`, `/vessels/{id}/trajectory`) and several that did
 * ship return more than the contract described.
 *
 * Two rules hold throughout:
 *  - every server-provided enum is widened with `Known<T>` so an unfamiliar value
 *    renders as a neutral badge instead of throwing;
 *  - every `notice` / `disclaimer` string the server sends is modelled, because
 *    the UI is required to render them verbatim (CON-001, CON-003, CON-008).
 */

import type { FeatureCollection, LineString, MultiPolygon, Point, Polygon } from 'geojson';

/**
 * A string union that still accepts unknown values from the server.
 *
 * Enumerations grow. Rendering an unfamiliar status as a neutral badge is always
 * better than throwing, so every server-provided enum is widened this way and
 * every consumer has a `default` branch.
 */
export type Known<T extends string> = T | (string & {});

// --------------------------------------------------------------- conventions

/** RFC 3339 UTC timestamp with a `Z` suffix. */
export type IsoDateTime = string;

/** Every pipeline-produced object carries provenance (CON-009). */
export type DataProvenance = Known<'REAL' | 'SYNTHETIC' | 'MIXED'>;

/** The error envelope. Never a raw stack trace (NFR-011). */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
}

/** The list envelope used by every collection endpoint. */
export interface Paginated<T> {
  items: T[];
  total: number;
  /** Only the genuinely paginated endpoints (positions, cases, jobs) send these. */
  limit?: number;
  offset?: number;
  /** Several collections carry a standing caveat that must be rendered. */
  notice?: string | null;
}

export interface PageParams {
  limit?: number;
  offset?: number;
}

/**
 * The reproducibility envelope attached to every derived artifact (NFR-005/AD-6).
 * Rendered verbatim rather than interpreted: its keys are stage-specific.
 */
export interface RunManifest {
  stage?: string | null;
  provider?: string | null;
  seed?: number | null;
  git_sha?: string | null;
  software_version?: string | null;
  model_name?: string | null;
  model_version?: string | null;
  created_at?: IsoDateTime | null;
  data_provenance?: DataProvenance;
  notes?: string[];
  inputs?: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  provider_parameters?: Record<string, unknown>;
  [key: string]: unknown;
}

// -------------------------------------------------------------- health/system

export interface HealthResponse {
  status: Known<'ok' | 'degraded'>;
  version: string;
}

export type ComponentStatus = Known<'UP' | 'DEGRADED' | 'DOWN'>;

export interface SystemComponent {
  name: string;
  status: ComponentStatus;
  latency_ms: number | null;
  detail: string | null;
}

export interface SystemProvider {
  /** Hexagonal port name: `satellite`, `ais`, `environment`, … */
  port: string;
  /** The adapter actually resolved at runtime, e.g. `fixture`, `copernicus`. */
  implementation: string;
  mode: DataProvenance;
  configured: boolean;
  /** Credentials this port would need to run in REAL mode. */
  requires?: string[] | null;
}

export interface ProvidersResponse {
  providers: SystemProvider[];
  any_synthetic?: boolean;
  notice?: string | null;
}

/**
 * A registered model checkpoint.
 *
 * `metrics` is frequently `{}`. That means **no evaluation has been recorded**,
 * which is not the same as a score of zero and must never be rendered as one
 * (A-06). `hasMetrics()` is the only sanctioned test.
 */
export interface ModelVersion {
  name: string;
  version: string;
  is_active: boolean;
  metrics: Record<string, number | string | null>;
  framework?: string | null;
  task?: string | null;
  input_channels?: number | null;
  input_size?: number[] | null;
  created_at?: IsoDateTime | null;
}

/** `true` only when the server actually recorded an evaluation. */
export function hasMetrics(model: Pick<ModelVersion, 'metrics'>): boolean {
  return Boolean(model.metrics) && Object.keys(model.metrics).length > 0;
}

export interface JobStats {
  queued: number;
  running: number;
  completed_24h: number;
  failed_24h: number;
}

export interface SystemStatus {
  version?: string;
  environment?: string;
  generated_at?: IsoDateTime;
  components: SystemComponent[];
  providers: SystemProvider[];
  models: ModelVersion[];
  jobs: JobStats;
  recent_jobs: Job[];
  failed_jobs: Job[];
  /** Standing caveats, e.g. "at least one source is running in SYNTHETIC mode". */
  notices?: string[];
}

// ---------------------------------------------------------------------- auth

export type UserRole = Known<'analyst' | 'admin'>;

export interface User {
  id: string;
  email: string;
  role: UserRole;
  full_name?: string | null;
  is_active?: boolean;
  last_login_at?: IsoDateTime | null;
  created_at?: IsoDateTime;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

// --------------------------------------------------------------------- cases

export type CaseStatus = Known<
  'DRAFT' | 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'ARCHIVED'
>;

/** Counts of child objects on the case detail response. */
export interface CaseCounts {
  scenes?: number;
  detections?: number;
  environmental_runs?: number;
  drift_runs?: number;
  trajectories?: number;
  vessels?: number;
  attributions?: number;
  jobs?: number;
  artifacts?: number;
}

export interface Case {
  id: string;
  title: string;
  description: string | null;
  status: CaseStatus;
  aoi: Polygon;
  start_time: IsoDateTime;
  end_time: IsoDateTime;
  created_at: IsoDateTime;
  updated_at?: IsoDateTime;
  /** Human-facing reference, e.g. `ST-2026-0001`. */
  case_ref?: string;
  owner?: User | null;
  owner_id?: string;
  archived_at?: IsoDateTime | null;
  /** Server-computed; preferred over the client's own geodesic estimate. */
  aoi_area_km2?: number | null;
  scenario?: string | null;
  counts?: CaseCounts;
  data_provenance?: DataProvenance;
  /** Rendered wherever the case is shown — e.g. the SYNTHETIC demo warning. */
  notice?: string | null;
}

export interface CreateCaseRequest {
  title: string;
  description?: string;
  aoi: Polygon;
  start_time: IsoDateTime;
  end_time: IsoDateTime;
}

export type UpdateCaseRequest = Partial<CreateCaseRequest>;

export interface CaseListParams extends PageParams {
  status?: string;
  q?: string;
  from?: IsoDateTime;
  to?: IsoDateTime;
  include_archived?: boolean;
}

// ------------------------------------------------------------ pipeline & jobs

/** Stable job-type identifiers. */
export const JOB_TYPES = [
  'scene.search',
  'scene.download',
  'sar.preprocess',
  'ml.detect',
  'detect.verify',
  'env.fetch',
  'drift.hindcast',
  'ais.ingest',
  'ais.clean',
  'traj.build',
  'correlate',
  'score',
  'report.build',
  'demo.seed',
] as const;

export type JobType = Known<(typeof JOB_TYPES)[number]>;

export type JobStatus = Known<'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'>;

export interface Job {
  id: string;
  case_id: string;
  pipeline_id: string | null;
  job_type: JobType;
  status: JobStatus;
  progress: number;
  step: string | null;
  attempt: number;
  max_attempts: number;
  queued_at: IsoDateTime;
  started_at: IsoDateTime | null;
  finished_at: IsoDateTime | null;
  error_code: string | null;
  error_message: string | null;
  result_ref: Record<string, unknown> | null;
  created_at?: IsoDateTime;
}

export type PipelineMode = 'DEMO' | 'REAL';

export interface StartPipelineRequest {
  mode: PipelineMode;
  stages?: JobType[];
  params?: Record<string, unknown>;
}

export interface StartPipelineResponse {
  pipeline_id: string;
  jobs: Job[];
}

/** One row of `GET /cases/{id}/pipeline` — a compact projection of a job. */
export interface PipelineStage {
  job_id: string;
  job_type: JobType;
  status: JobStatus;
  progress: number;
  step: string | null;
  error_code: string | null;
  error_message: string | null;
}

export interface Pipeline {
  pipeline_id: string;
  case_id?: string;
  status?: JobStatus;
  mode?: PipelineMode;
  stages?: PipelineStage[];
  /** Older shape; kept so a mixed deployment cannot crash the progress panel. */
  jobs?: Job[];
  started_at?: IsoDateTime | null;
  finished_at?: IsoDateTime | null;
}

export interface CreateJobRequest {
  job_type: JobType;
  payload?: Record<string, unknown>;
}

/**
 * A frame from `GET /cases/{id}/events` (SSE).
 *
 * `open` and `keepalive` carry no job. `started` / `progress` / `finished` are
 * published by the worker as it advances a stage.
 */
export type JobEventType = Known<'open' | 'keepalive' | 'started' | 'progress' | 'finished'>;

export interface JobEvent {
  type?: JobEventType;
  job_id?: string;
  case_id?: string | null;
  job_type?: JobType;
  progress?: number;
  step?: string | null;
  status?: JobStatus;
}

// ------------------------------------------------ detections and verification

export type VerificationStatus = Known<'VERIFIED' | 'UNCERTAIN' | 'FALSE_POSITIVE' | 'REJECTED'>;

/** The verification summary embedded in a detection row. */
export interface DetectionVerificationSummary {
  status: VerificationStatus;
  confidence: number | null;
  explanation: string | null;
}

export interface SpillDetection {
  id: string;
  case_id: string;
  scene_id: string | null;
  detected_at: IsoDateTime;
  area_km2: number;
  perimeter_km: number | null;
  /** A-06: three separately named confidences that are never combined. */
  detection_confidence: number;
  mean_probability: number | null;
  max_probability: number | null;
  threshold: number | null;
  centroid: Point | null;
  probability_raster_uri?: string | null;
  data_provenance?: DataProvenance;
  verification?: DetectionVerificationSummary | null;
}

/** `GET /detections/{id}` adds the geometry and the reproducibility envelope. */
export interface SpillDetectionDetail extends SpillDetection {
  geometry: MultiPolygon | null;
  run_manifest?: RunManifest | null;
}

export interface DetectionListResponse {
  items: SpillDetection[];
  total: number;
  /** The SAR look-alike caveat. Always rendered next to a detection. */
  notice?: string | null;
}

/**
 * One look-alike rule.
 *
 * A rule that did not apply (`applicable === false`) is *not* a failure and must
 * be rendered as "not evaluated"; a `veto` rule can reject a detection on its
 * own. `observed` and `threshold` are deliberately loose: a threshold may be a
 * scalar, a `[min, max]` window, or a named object of bounds.
 */
export interface VerificationRule {
  rule_id: string;
  label: string;
  passed: boolean;
  applicable?: boolean;
  veto?: boolean;
  weight?: number | null;
  evidence?: number | null;
  message?: string | null;
  observed?: number | string | null;
  threshold?: number | string | number[] | Record<string, unknown> | null;
}

export interface VerificationResult {
  spill_id: string;
  status: VerificationStatus;
  verification_confidence: number;
  explanation: string;
  rules: VerificationRule[];
  /** Shape and radiometric features the rules were evaluated against. */
  features?: Record<string, number | string | null>;
  wind?: { speed_ms?: number | null; direction_deg?: number | null; source?: string | null } | null;
  classifier?: { name?: string | null; score?: number | null } | null;
  created_at?: IsoDateTime;
  data_provenance?: DataProvenance;
  notice?: string | null;
}

// -------------------------------------------------------- environment & drift

export interface EnvironmentSummaryEntry {
  min?: number | null;
  max?: number | null;
  mean?: number | null;
  units?: string | null;
}

export interface EnvironmentalRun {
  id: string;
  source: string;
  provider?: string | null;
  dataset_id?: string | null;
  variables: string[];
  time_start: IsoDateTime;
  time_end: IsoDateTime;
  grid_resolution_deg?: number | null;
  summary?: Record<string, EnvironmentSummaryEntry>;
  storage_uri?: string | null;
  checksum_sha256?: string | null;
  status?: Known<'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'>;
  data_provenance?: DataProvenance;
}

export type DriftMode = Known<'BACKWARD' | 'FORWARD'>;

export interface DriftRun {
  id: string;
  case_id: string;
  spill_id: string | null;
  engine: string;
  mode: DriftMode;
  seed: number | null;
  number_of_particles: number;
  ensemble_members: number;
  duration_hours: number;
  time_step_seconds: number;
  parameters: Record<string, unknown>;
  /** A-06: never multiplied with the detection or verification confidences. */
  origin_confidence: number;
  origin_area_km2?: number | null;
  /** A-02: the discharge window inferred from back-tracked particle density. */
  inferred_start: IsoDateTime | null;
  inferred_end: IsoDateTime | null;
  density_grid_uri?: string | null;
  status?: Known<'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'>;
  data_provenance?: DataProvenance;
  created_at?: IsoDateTime;
}

/** Properties on each origin-region contour feature. */
export interface OriginContourProperties {
  label?: string;
  probability_mass?: number;
  area_km2?: number;
  engine?: string;
  origin_confidence?: number;
  inferred_start?: IsoDateTime;
  inferred_end?: IsoDateTime;
  data_provenance?: DataProvenance;
}

export interface DriftRunDetail extends DriftRun {
  /** Nested 90 / 75 / 50 % probability contours. */
  contours?: FeatureCollection | null;
  origin_geometry?: MultiPolygon | null;
  run_manifest?: RunManifest | null;
}

export interface DriftRunListResponse {
  items: DriftRun[];
  total: number;
  /** ORIGIN_REGION_DISCLAIMER — mandatory wherever the origin region is shown. */
  notice?: string | null;
}

export interface ParticleProperties {
  particle_id: number;
  step_index: number;
  member: number;
  timestamp: IsoDateTime;
}

export interface ParticleCollection {
  drift_run_id: string;
  engine?: string;
  /** The step indices that actually exist. They are NOT `0..n`. */
  steps: number[];
  features: Array<{
    type: 'Feature';
    geometry: Point;
    properties: ParticleProperties;
  }>;
}

// ------------------------------------------------- AIS, vessels, trajectories

/** One continuous stretch of AIS reporting for a vessel. */
export interface TrajectorySegment {
  trajectory_id: string;
  time_start: IsoDateTime;
  time_end: IsoDateTime;
  position_count: number;
  distance_km: number | null;
  gap_count: number;
  max_gap_minutes: number | null;
  coverage_ratio: number | null;
  quality_score: number | null;
  quality_flags?: string[];
}

export interface Vessel {
  id: string;
  mmsi: number;
  imo: number | null;
  name: string | null;
  callsign?: string | null;
  ship_type?: number | null;
  ship_type_name?: string | null;
  flag_country?: string | null;
  length_m?: number | null;
  width_m?: number | null;
  draught_m?: number | null;
  destination?: string | null;
  static_completeness?: number | null;
  first_seen?: IsoDateTime | null;
  last_seen?: IsoDateTime | null;
  source?: string | null;
  data_provenance?: DataProvenance;
  segments?: TrajectorySegment[];
}

/** A-03 — the documented inputs to the AIS-reliability factor. */
export interface AisQuality {
  position_count: number;
  rejected_count: number;
  first_position: IsoDateTime | null;
  last_position: IsoDateTime | null;
}

export interface VesselDetail extends Vessel {
  ais?: AisQuality | null;
  /** "A gap in AIS reporting is not evidence of wrongdoing." */
  notice?: string | null;
}

export interface AisPosition {
  timestamp: IsoDateTime;
  position: Point;
  sog_knots: number | null;
  cog_deg: number | null;
  heading_deg: number | null;
  nav_status: number | null;
  message_type?: string | null;
  source?: string | null;
  is_valid: boolean;
  quality_flags?: string[];
  rejection_reason?: string | null;
}

export interface VesselListResponse {
  items: Vessel[];
  total: number;
  /** "Absence of a vessel is not evidence of absence." */
  notice?: string | null;
}

export interface VesselPositionsParams extends PageParams {
  include_invalid?: boolean;
}

// --------------------------------------------- correlation, scoring, ranking

/** SCORE-001..006 — the six independent factors, in PRD weight order. */
export type AttributionFactorKey = Known<
  | 'origin_proximity'
  | 'time_match'
  | 'trajectory_match'
  | 'heading_match'
  | 'speed_match'
  | 'ais_reliability'
>;

export interface AttributionFactor {
  key: AttributionFactorKey;
  label: string;
  weight: number;
  score: number;
  contribution: number;
  explanation: string;
  evidence?: Record<string, unknown>;
}

/**
 * Evidence-strength band, from the server's own enum (`LOW` / `MODERATE` /
 * `HIGH`). It describes how strong the supporting evidence is — never a
 * likelihood of responsibility.
 */
export type ConfidenceLabel = Known<'LOW' | 'MODERATE' | 'HIGH'>;

/**
 * The heart of the product (SCORE-007).
 *
 * `disclaimer` is mandatory and non-empty on every attribution response and is
 * asserted server-side by `backend/tests/unit/test_disclaimers.py` and
 * client-side by `tests/candidate-ranking.test.tsx` (CON-003, AC-13).
 */
export interface Attribution {
  id: string;
  rank: number;
  vessel: { id: string; mmsi: number; name?: string | null };
  final_score: number;
  confidence_label: ConfidenceLabel;
  factors: AttributionFactor[];
  weights: Record<string, number>;
  scoring_version: string;
  closest_approach_km?: number | null;
  closest_approach_time?: IsoDateTime | null;
  disclaimer: string;
  data_provenance: DataProvenance;
}

export interface AttributionEvidence {
  confidence_label?: ConfidenceLabel;
  disclaimer?: string;
  correlation?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface AttributionDetail extends Attribution {
  evidence?: AttributionEvidence | null;
  run_manifest?: RunManifest | null;
}

export interface AttributionListResponse {
  items: Attribution[];
  total: number;
  /**
   * Set when the engine produced fewer candidates than it would normally rank —
   * the list is never padded to reach a target count (A-10).
   */
  shortfall_note?: string | null;
  disclaimer: string;
  score_disclaimer?: string | null;
  proximity_disclaimer?: string | null;
}

// ---------------------------------------------------------------- map layers

export type LayerType = Known<'geojson' | 'raster'>;
export type LayerGeometry = Known<'polygon' | 'line' | 'point'>;

/** The manifest the map builds itself from. */
export interface LayerDescriptor {
  id: string;
  title: string;
  type: LayerType;
  url: string;
  geometry?: LayerGeometry;
  available?: boolean;
  visible?: boolean;
  feature_count?: number | null;
  /** `true` for layers with a `step_index` dimension (drift particles). */
  animated?: boolean;
  /** A caveat that must be shown wherever the layer is offered. */
  notice?: string | null;
}

export interface LayerManifest {
  case_id?: string;
  data_provenance?: DataProvenance;
  layers: LayerDescriptor[];
}

export type GeoJsonLayerData = FeatureCollection;

// --------------------------------------------------------------------- report

export interface EvidenceArtifact {
  id: string;
  artifact_type: Known<
    'PROBABILITY_RASTER' | 'ENV_NETCDF' | 'DENSITY_GRID' | 'REPORT_HTML' | 'REPORT_PDF'
  >;
  label?: string | null;
  media_type?: string | null;
  size_bytes?: number | null;
  checksum_sha256: string;
  storage_uri?: string | null;
  data_provenance?: DataProvenance;
  created_at?: IsoDateTime;
}

// ----------------------------------------------------------------------- demo

export interface DemoScenario {
  /** The scenario identifier used in `POST /demo/cases`. */
  key: string;
  title: string;
  description?: string | null;
  aoi_bbox?: number[];
  acquisition_time?: IsoDateTime;
  vessel_count?: number;
  /** Teaching notes about what the scenario is designed to demonstrate. */
  notes?: string[];
}

export interface DemoScenariosResponse {
  scenarios: DemoScenario[];
  notice?: string | null;
}

export interface CreateDemoCaseRequest {
  scenario: string;
  seed?: number;
  /** Queue the full pipeline immediately rather than leaving the case DRAFT. */
  run_pipeline?: boolean;
}

/** `POST /demo/cases` wraps the case rather than returning it bare. */
export interface DemoCaseResponse {
  case: Case;
  scenario: DemoScenario;
  pipeline_id: string | null;
  notice?: string | null;
}

// ------------------------------------------------------------------ geometry

export type { FeatureCollection, LineString, MultiPolygon, Point, Polygon };
