'use client';

import { useMemo, type ReactNode } from 'react';
import { BarList, ChartFrame, StatTile } from '@/components/charts';
import { MetaList, Unmeasured } from '@/components/common/MetaList';
import { NoticeStack } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { PageHeader } from '@/components/layout/PageHeader';
import { Reveal } from '@/components/motion/Reveal';
import { useSpotlight } from '@/components/motion/useSpotlight';
import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import {
  IconActivity,
  IconAdmin,
  IconAlert,
  IconCheck,
  IconClock,
  IconCpu,
  IconDatabase,
  IconGauge,
  IconInfo,
  IconMinus,
  IconRefresh,
  IconSatellite,
  IconShield,
  IconShip,
} from '@/components/ui/Icons';
import { LinkButton } from '@/components/ui/LinkButton';
import { Skeleton } from '@/components/ui/Skeleton';
import { useSystemProviders, useSystemStatus } from '@/lib/api/hooks';
import { hasMetrics, type Job, type ModelVersion, type SystemProvider } from '@/lib/api/types';
import { cx } from '@/lib/cx';
import {
  EMPTY_VALUE,
  formatDateTime,
  formatDateTimeCompact,
  formatDuration,
  formatInteger,
  formatNumber,
  formatRelativeTime,
  humanizeIdentifier,
  pluralize,
} from '@/lib/format';
import layout from '@/components/layout/layout.module.css';
import styles from './ml-ops.module.css';

// ---------------------------------------------------------------- metrics

interface MetricChip {
  key: string;
  label: string;
  value: string;
  /** `true` when the server recorded the key but no value. */
  missing?: boolean;
}

interface MetricGroup {
  key: string;
  label: string | null;
  chips: MetricChip[];
  notes: string[];
}

/** Headline metrics first, in the order the ML spec reports them (ML_PIPELINE §7). */
const HEADLINE_METRICS = ['dice', 'iou', 'precision', 'recall'];

/**
 * Keys whose values are thresholds, losses or counts. They can fall inside
 * [0, 1] without being rates, so they are never turned into a percentage.
 */
const NON_RATE_KEY =
  /threshold|loss|epoch|count|seconds|size|samples|tiles|images|params|lr$|learning_rate|^n_|_n$/i;

const ACRONYMS: ReadonlyArray<[RegExp, string]> = [
  [/\bmiou\b/gi, 'mIoU'],
  [/\biou\b/gi, 'IoU'],
  [/\bf1\b/gi, 'F1'],
  [/\bauc\b/gi, 'AUC'],
  [/\broc\b/gi, 'ROC'],
  [/\bais\b/gi, 'AIS'],
  [/\bsar\b/gi, 'SAR'],
  [/\bml\b/gi, 'ML'],
];

/** Short strings read as chips; longer ones (an aggregation note) as text, verbatim. */
const CHIP_TEXT_MAX = 24;

/** `humanizeIdentifier`, with acronyms kept upright: `ais` → "AIS", `iou` → "IoU". */
function readable(key: string): string {
  return ACRONYMS.reduce(
    (label, [pattern, word]) => label.replace(pattern, word),
    humanizeIdentifier(key),
  );
}

/** Stage names as an analyst would say them; unknown job types fall back to `readable`. */
const STAGE_LABELS: Record<string, string> = {
  'scene.search': 'Scene search',
  'scene.download': 'Scene download',
  'sar.preprocess': 'SAR preprocessing',
  'ml.detect': 'Slick detection',
  'detect.verify': 'Look-alike checks',
  'env.fetch': 'Environment fetch',
  'drift.hindcast': 'Drift hindcast',
  'ais.ingest': 'AIS ingest',
  'ais.clean': 'AIS cleaning',
  'traj.build': 'Track building',
  correlate: 'Correlation',
  score: 'Scoring',
  'report.build': 'Report build',
  'demo.seed': 'Demo seed',
};

function stageLabel(jobType: string): string {
  return STAGE_LABELS[jobType] ?? readable(jobType);
}

function formatMetricValue(key: string, value: number): string {
  if (!NON_RATE_KEY.test(key) && value >= 0 && value <= 1) {
    return `${formatNumber(value * 100, { maximumFractionDigits: 1 })}%`;
  }
  return formatNumber(value, { maximumFractionDigits: 3 });
}

function headlineOrder(key: string): number {
  const index = HEADLINE_METRICS.indexOf(key.toLowerCase());
  return index === -1 ? HEADLINE_METRICS.length : index;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function metricGroup(
  key: string,
  label: string | null,
  entries: Record<string, unknown>,
): MetricGroup {
  const chips: MetricChip[] = [];
  const notes: string[] = [];
  const ordered = Object.entries(entries).sort(([a], [b]) => headlineOrder(a) - headlineOrder(b));
  for (const [name, value] of ordered) {
    const title = readable(name);
    if (typeof value === 'number' && Number.isFinite(value)) {
      chips.push({ key: name, label: title, value: formatMetricValue(name, value) });
    } else if (typeof value === 'string') {
      if (value.length <= CHIP_TEXT_MAX) chips.push({ key: name, label: title, value });
      else notes.push(`${title}: ${value}`);
    } else if (typeof value === 'boolean') {
      chips.push({ key: name, label: title, value: value ? 'yes' : 'no' });
    } else if (Array.isArray(value)) {
      notes.push(`${title}: ${pluralize(value.length, 'entry', 'entries')} recorded`);
    } else if (isRecord(value)) {
      notes.push(`${title}: recorded`);
    } else {
      chips.push({ key: name, label: title, value: 'not recorded', missing: true });
    }
  }
  return { key, label, chips, notes };
}

/**
 * The registry types `metrics` as a flat map, but the evaluation script writes
 * a nested one (`operating_point` + a threshold `sweep`). Both are laid out
 * here without inventing anything: nested objects become labelled groups,
 * arrays are counted, and every number shown is one the server returned.
 */
function metricGroups(metrics: Record<string, unknown>): MetricGroup[] {
  const scalars: Record<string, unknown> = {};
  const groups: MetricGroup[] = [];
  for (const [key, value] of Object.entries(metrics)) {
    if (isRecord(value)) groups.push(metricGroup(key, readable(key), value));
    else scalars[key] = value;
  }
  return Object.keys(scalars).length ? [...groups, metricGroup('root', null, scalars)] : groups;
}

/** `input_size` has shipped as `[128, 128]` and as a bare `128`: show what arrived. */
function formatInputSize(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(' × ') : EMPTY_VALUE;
  if (typeof value === 'number' && Number.isFinite(value)) return formatInteger(value);
  return EMPTY_VALUE;
}

// ----------------------------------------------------------- throughput

interface StageTiming {
  jobType: string;
  runs: number;
  median: number;
}

function median(values: readonly number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2;
}

/**
 * Median wall-clock time per stage, from started_at to finished_at, over the
 * recent jobs the status endpoint returns. Only COMPLETED jobs count: a stage
 * that failed after two seconds says nothing about how long the stage takes.
 */
function stageTimings(jobs: readonly Job[]): { stages: StageTiming[]; measured: number } {
  const byType = new Map<string, number[]>();
  for (const job of jobs) {
    if (job.status !== 'COMPLETED' || !job.started_at || !job.finished_at) continue;
    const seconds = (Date.parse(job.finished_at) - Date.parse(job.started_at)) / 1000;
    if (!Number.isFinite(seconds) || seconds < 0) continue;
    const list = byType.get(job.job_type) ?? [];
    list.push(seconds);
    byType.set(job.job_type, list);
  }
  const stages = [...byType]
    .map(([jobType, values]) => ({ jobType, runs: values.length, median: median(values) }))
    .sort((a, b) => b.median - a.median);
  return { stages, measured: stages.reduce((sum, stage) => sum + stage.runs, 0) };
}

/**
 * `formatDuration` rounds to whole seconds, so a 70 ms stage would print "0s"
 * — which reads as "took no time". Sub-second stages keep milliseconds and
 * short ones a tenth of a second; anything longer uses the shared format.
 */
function formatStageDuration(seconds: number): string {
  if (seconds < 1) return `${formatInteger(Math.max(1, Math.round(seconds * 1000)))}ms`;
  if (seconds < 60) return `${formatNumber(seconds, { maximumFractionDigits: 1 })}s`;
  return formatDuration(seconds);
}

const NO_CODE = '__none__';

function failureReasons(jobs: readonly Job[]) {
  const counts = new Map<string, number>();
  for (const job of jobs) {
    const code = job.error_code?.trim() || NO_CODE;
    counts.set(code, (counts.get(code) ?? 0) + 1);
  }
  return [...counts]
    .sort((a, b) => b[1] - a[1])
    .map(([code, value]) => ({
      key: code,
      label: code === NO_CODE ? 'No error code recorded' : code,
      value,
    }));
}

const COMPONENT_TONE: Record<string, BadgeTone> = {
  UP: 'success',
  DEGRADED: 'warning',
  DOWN: 'danger',
};

// ------------------------------------------------------------- lifecycle

interface LifecycleStep {
  key: string;
  title: string;
  icon: ReactNode;
  where: string;
  /** Whether the step leaves a record this API can report. */
  recorded: boolean;
  body: ReactNode;
}

/** Summarised from docs/ML_PIPELINE.md and the scripts under `ml/`. */
const LIFECYCLE: LifecycleStep[] = [
  {
    key: 'dataset',
    title: 'Dataset',
    icon: <IconDatabase size={16} />,
    where: 'Offline',
    recorded: false,
    body: (
      <>
        Sentinel-1 VV/VH scenes with oil, look-alike and no-oil masks (Trujillo-Acatitla et al.,
        CC-BY-4.0), or a deterministic synthetic set for offline tests. Split by image before
        tiling, so no scene leaks across splits.
      </>
    ),
  },
  {
    key: 'training',
    title: 'Training',
    icon: <IconCpu size={16} />,
    where: 'Offline',
    recorded: false,
    body: (
      <>
        A configurable U-Net on 2 × 128 × 128 tiles with a BCE + Dice loss, stopped early on
        validation oil-class Dice. Runs on a CPU or in a Colab GPU notebook; the config is saved
        beside every checkpoint.
      </>
    ),
  },
  {
    key: 'evaluation',
    title: 'Evaluation',
    icon: <IconGauge size={16} />,
    where: 'Offline',
    recorded: false,
    body: (
      <>
        Oil-class Dice, IoU, precision and recall on a held-out split, with a threshold sweep to
        choose the operating point. Only measured numbers are kept — a published benchmark is never
        substituted.
      </>
    ),
  },
  {
    key: 'registration',
    title: 'Registration',
    icon: <IconShield size={16} />,
    where: 'Recorded here',
    recorded: true,
    body: (
      <>
        <code>register_model.py</code> uploads the checkpoint with its SHA-256 and training manifest
        and writes a registry row. Metrics are copied only from a manifest that measured them, and
        it refuses to activate an unevaluated version.
      </>
    ),
  },
  {
    key: 'serving',
    title: 'Serving',
    icon: <IconSatellite size={16} />,
    where: 'Pipeline · ml.detect',
    recorded: true,
    body: (
      <>
        The detection stage runs the one active version, and every detection records the version
        that produced it. With none active, the deterministic analytical detector runs and its
        output is labelled SYNTHETIC.
      </>
    ),
  },
];

// ------------------------------------------------------------ components

function SectionHead({
  id,
  eyebrow,
  title,
  lead,
  meta,
}: {
  id: string;
  eyebrow: string;
  title: string;
  lead: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <div className={styles.sectionHead}>
      <div className={styles.sectionHeadText}>
        <p className="eyebrow">{eyebrow}</p>
        <h2 id={id} className={styles.sectionTitle}>
          {title}
        </h2>
        <p className={styles.sectionLead}>{lead}</p>
      </div>
      {meta ? <div className={styles.sectionMeta}>{meta}</div> : null}
    </div>
  );
}

function ModelCard({ model }: { model: ModelVersion }) {
  const ref = useSpotlight<HTMLElement>();
  const groups = hasMetrics(model) ? metricGroups(model.metrics) : [];

  return (
    <article ref={ref} className={cx(styles.model, model.is_active && styles.modelActive)}>
      <header className={styles.modelHead}>
        <span className={styles.modelGlyph} aria-hidden="true">
          <IconCpu size={18} />
        </span>
        <div>
          <h3 className={styles.modelName}>{model.name}</h3>
          <p className={styles.modelVersion}>
            version <span>{model.version}</span>
          </p>
        </div>
        <Badge tone={model.is_active ? 'accent' : 'neutral'} dot={model.is_active}>
          {model.is_active ? 'Active' : 'Idle'}
        </Badge>
      </header>

      {model.task ? <p className={styles.modelTask}>{humanizeIdentifier(model.task)}</p> : null}

      <MetaList
        dense
        entries={[
          {
            key: 'framework',
            term: 'Framework',
            mono: true,
            value: model.framework ?? EMPTY_VALUE,
          },
          {
            key: 'channels',
            term: 'Input channels',
            mono: true,
            value: formatInteger(model.input_channels ?? null),
          },
          {
            key: 'size',
            term: 'Input size',
            mono: true,
            value: formatInputSize(model.input_size),
          },
          {
            key: 'created',
            term: 'Registered',
            mono: true,
            value: formatDateTime(model.created_at ?? null),
            hint: model.created_at ? formatRelativeTime(model.created_at) : undefined,
          },
        ]}
      />

      <div className={styles.evaluation}>
        <p className={styles.evaluationLabel}>Evaluation</p>
        {groups.length > 0 ? (
          groups.map((group) => (
            <div key={group.key} className={styles.metricGroup}>
              {group.label ? <p className={styles.metricGroupLabel}>{group.label}</p> : null}
              {group.chips.length > 0 ? (
                <ul className={styles.metricChips}>
                  {group.chips.map((chip) => (
                    <li key={chip.key} className={styles.metricChip}>
                      {chip.label}
                      {chip.missing ? <em>{chip.value}</em> : <strong>{chip.value}</strong>}
                    </li>
                  ))}
                </ul>
              ) : null}
              {group.notes.map((note) => (
                <p key={note} className={styles.metricNote}>
                  {note}
                </p>
              ))}
            </div>
          ))
        ) : (
          // `metrics: {}` means nobody measured this checkpoint. That is
          // unknown, not zero, so it is words in an empty box — never a number
          // and never an empty bar (A-06).
          <p className={styles.unmeasuredBox}>
            <span className={styles.unmeasuredIcon} aria-hidden="true">
              <IconMinus size={14} />
            </span>
            <Unmeasured>
              No evaluation recorded — accuracy on independent data is unknown
            </Unmeasured>
          </p>
        )}
      </div>
    </article>
  );
}

function ProvidersCard({
  providers,
  loading,
}: {
  providers: readonly SystemProvider[];
  loading: boolean;
}) {
  return (
    <Card
      title="Pipeline inputs"
      titleAs="h3"
      description="Which adapter backs each port right now. A port in SYNTHETIC mode produces deterministic demonstration data, labelled as such everywhere it appears."
    >
      {loading ? (
        <div className={styles.skeletonStack}>
          <Skeleton height="2.5rem" radius="var(--radius-md)" />
          <Skeleton height="2.5rem" radius="var(--radius-md)" />
          <Skeleton height="2.5rem" radius="var(--radius-md)" />
        </div>
      ) : providers.length === 0 ? (
        <EmptyState
          compact
          title="No providers reported"
          description="No adapter ports were reported by the API."
        />
      ) : (
        <div className={styles.sourceList}>
          {providers.map((provider) => (
            <div key={provider.port} className={styles.source}>
              <span className={styles.sourceIcon} aria-hidden="true">
                {provider.port.includes('ais') ? (
                  <IconShip size={15} />
                ) : (
                  <IconDatabase size={15} />
                )}
              </span>
              <span>
                <span className={styles.sourceName}>{readable(provider.port)}</span>
                <span className={styles.sourceImpl}>{provider.implementation}</span>
              </span>
              <ProvenanceBadge provenance={provider.mode} />
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function Lifecycle() {
  return (
    <section className={styles.section} aria-labelledby="ml-lifecycle">
      <SectionHead
        id="ml-lifecycle"
        eyebrow="Model lifecycle"
        title="How models reach production"
        lead="Five steps, from labelled radar scenes to the detector the pipeline runs. Only the last two leave a record this API can show."
      />
      <div className={styles.lifecycle}>
        <Reveal as="ol" className={styles.steps} stagger={0.08} y={18}>
          {LIFECYCLE.map((step, index) => (
            <li key={step.key} className={cx(styles.step, step.recorded && styles.stepRecorded)}>
              <span className={styles.stepNode} aria-hidden="true">
                {step.icon}
              </span>
              <div className={styles.stepText}>
                <p className={styles.stepIndex}>STEP {String(index + 1).padStart(2, '0')}</p>
                <h3 className={styles.stepTitle}>{step.title}</h3>
                <p className={styles.stepBody}>{step.body}</p>
                <span className={styles.stepWhere}>{step.where}</span>
              </div>
            </li>
          ))}
        </Reveal>
        <p className={styles.offlineNote}>
          <span className={styles.offlineIcon} aria-hidden="true">
            <IconInfo size={16} />
          </span>
          <span>
            <strong>Training happens offline, and this API never sees it.</strong> Training runs
            execute in notebooks and in the scripts under <code>ml/</code> (<code>train.py</code>,{' '}
            <code>evaluate.py</code>) and report nothing to this server. That is why this page draws
            no training history, epoch counts or accuracy curves: none are recorded here, and
            SPILLTRACE does not chart what it did not measure. A model reaches the registry only
            once it is registered, carrying whatever evaluation was measured for it.
          </span>
        </p>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ page

/** ML Ops — model registry, evaluation status and pipeline throughput (admin). */
export default function MlOpsPage() {
  const status = useSystemStatus();
  // Readable by every signed-in user, so even the 403 view can say whether the
  // pipeline's inputs are synthetic (CON-009).
  const providers = useSystemProviders();
  const data = status.data;

  const forbidden = Boolean(status.error?.isForbidden || status.error?.isUnauthenticated);
  const pending = status.isPending && !status.isError;
  const unavailable = status.isError;

  const models = data?.models ?? [];
  const activeCount = models.filter((model) => model.is_active).length;
  const evaluatedCount = models.filter((model) => hasMetrics(model)).length;
  const timing = useMemo(() => stageTimings(data?.recent_jobs ?? []), [data]);
  const failures = useMemo(() => failureReasons(data?.failed_jobs ?? []), [data]);
  const failedJobs = data?.failed_jobs ?? [];
  const failed24h = data?.jobs.failed_24h;
  const providerList = data?.providers ?? providers.data?.providers ?? [];

  const refresh = (
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
  );

  if (forbidden) {
    return (
      <main className={layout.content} id="main-content">
        <PageHeader
          eyebrow="System"
          title="ML Ops"
          subtitle="Registered model versions, their evaluation status and how the analysis pipeline is running."
        />
        <div className={styles.stack}>
          <ErrorState
            title="Administrator access required"
            error={status.error}
            description="Model versions, evaluation status and pipeline statistics are restricted to administrators. The pipeline's inputs and how models reach production are shown below for everyone."
            action={
              <LinkButton href="/dashboard" variant="ghost" size="sm">
                Back to the dashboard
              </LinkButton>
            }
          />
          <ProvidersCard
            providers={providers.data?.providers ?? []}
            loading={providers.isPending}
          />
          <NoticeStack
            notices={[providers.data?.notice]}
            label="Data provenance"
            tone="synthetic"
          />
          <Lifecycle />
        </div>
      </main>
    );
  }

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        eyebrow="System"
        title="ML Ops"
        subtitle="Registered model versions, whether each has been evaluated, and how the analysis pipeline is running. Refreshes every 15 seconds."
        actions={
          <>
            <LinkButton
              href="/admin"
              variant="ghost"
              size="md"
              leadingIcon={<IconAdmin size={15} />}
            >
              System status
            </LinkButton>
            {refresh}
          </>
        }
      />

      <div className={styles.stack}>
        {unavailable || (data?.notices?.length ?? 0) > 0 || providers.data?.notice ? (
          <div className={styles.section}>
            {unavailable ? (
              <ErrorState error={status.error} onRetry={() => void status.refetch()} />
            ) : null}
            <NoticeStack
              notices={[...(data?.notices ?? []), providers.data?.notice]}
              label="Standing caveats"
              tone="synthetic"
            />
          </div>
        ) : null}

        {/* ------------------------------------------------------ registry */}
        <section className={styles.section} aria-labelledby="ml-registry">
          <SectionHead
            id="ml-registry"
            eyebrow="Model registry"
            title="Registered model versions"
            lead="Every checkpoint the API knows about. A version with no recorded evaluation is shown as unmeasured — never as a score of zero."
            meta={
              data ? (
                <>
                  <span className={styles.metaPill}>
                    <strong>{models.length}</strong> registered
                  </span>
                  <span className={styles.metaPill}>
                    <strong>{activeCount}</strong> active
                  </span>
                  <span className={styles.metaPill}>
                    <strong>{evaluatedCount}</strong> with a recorded evaluation
                  </span>
                </>
              ) : null
            }
          />
          {pending ? (
            <div className={styles.models} aria-busy="true">
              <span className="sr-only">Loading model versions</span>
              <Skeleton height="19rem" radius="var(--radius-lg)" />
              <Skeleton height="19rem" radius="var(--radius-lg)" />
            </div>
          ) : unavailable ? (
            // A failed request is not an empty registry: saying "none registered"
            // here would be a false statement.
            <EmptyState
              compact
              icon={<IconAlert size={18} />}
              title="Model registry unavailable"
              description="The status request failed, so which versions are registered is unknown right now."
            />
          ) : models.length === 0 ? (
            <EmptyState
              icon={<IconCpu size={18} />}
              title="No model versions registered"
              description="No trained checkpoint has been registered yet. Detection falls back to the deterministic analytical detector, and its output is labelled SYNTHETIC."
            />
          ) : (
            <Reveal className={styles.models} stagger={0.08} y={20}>
              {models.map((model) => (
                <ModelCard key={`${model.name}@${model.version}`} model={model} />
              ))}
            </Reveal>
          )}
        </section>

        {/* ---------------------------------------------------- throughput */}
        <section className={styles.section} aria-labelledby="ml-throughput">
          <SectionHead
            id="ml-throughput"
            eyebrow="Pipeline"
            title="Pipeline throughput"
            lead="The job queue right now and over the last 24 hours, with the stage timings and failure reasons from the most recent jobs the status endpoint returned."
            meta={
              data?.generated_at ? (
                <span className={styles.metaPill}>
                  Snapshot{' '}
                  <time
                    dateTime={data.generated_at}
                    title={formatDateTime(data.generated_at, true)}
                  >
                    {formatRelativeTime(data.generated_at)}
                  </time>
                </span>
              ) : null
            }
          />

          <Reveal className={styles.kpis} stagger={0.07} y={20}>
            <StatTile
              label="Queued"
              value={data?.jobs.queued}
              loading={pending}
              icon={<IconClock size={16} />}
              tone="neutral"
              caption="Waiting for a worker."
            />
            <StatTile
              label="Running"
              value={data?.jobs.running}
              loading={pending}
              icon={<IconActivity size={16} />}
              caption="Executing right now."
            />
            <StatTile
              label="Completed (24h)"
              value={data?.jobs.completed_24h}
              loading={pending}
              icon={<IconCheck size={16} />}
              tone="success"
              caption="Finished successfully in the last 24 hours."
            />
            <StatTile
              label="Failed (24h)"
              value={failed24h}
              loading={pending}
              icon={<IconAlert size={16} />}
              // Red is reserved for system failure, and only when there is one.
              tone={failed24h ? 'danger' : 'neutral'}
              caption="Every failure states its reason — see below."
            />
          </Reveal>

          <div className={styles.grid}>
            <div className={styles.column}>
              <Reveal>
                <ChartFrame
                  title="Stage timing"
                  subtitle={
                    timing.measured > 0
                      ? `Median wall-clock time per stage, over the ${pluralize(timing.measured, 'most recent completed job', 'most recent completed jobs')} returned by the status endpoint. Queue wait is excluded.`
                      : 'Median wall-clock time per stage, from the most recent completed jobs.'
                  }
                  table={{
                    caption: 'Median duration per pipeline stage',
                    columns: ['Stage', 'Jobs measured', 'Median duration'],
                    rows: timing.stages.map((stage) => [
                      `${stageLabel(stage.jobType)} (${stage.jobType})`,
                      stage.runs,
                      formatStageDuration(stage.median),
                    ]),
                  }}
                  foot="A snapshot of recent work, not a long-run average: the status endpoint returns only the latest jobs."
                >
                  {pending ? (
                    <div className={styles.skeletonStack}>
                      <Skeleton height="1rem" />
                      <Skeleton height="1rem" />
                      <Skeleton height="1rem" />
                    </div>
                  ) : (
                    <BarList
                      label="Median duration per pipeline stage"
                      empty={
                        unavailable
                          ? 'Stage timings are unavailable because the status request failed.'
                          : 'No recent completed job recorded both a start and a finish time.'
                      }
                      items={timing.stages.map((stage) => ({
                        key: stage.jobType,
                        label: `${stageLabel(stage.jobType)} (${pluralize(stage.runs, 'run')})`,
                        value: stage.median,
                        display: formatStageDuration(stage.median),
                      }))}
                    />
                  )}
                </ChartFrame>
              </Reveal>

              <Reveal>
                <Card
                  title="Workers and infrastructure"
                  titleAs="h3"
                  description="The health checks behind this snapshot. Latency is the probe's own round trip, where one was timed."
                >
                  {pending ? (
                    <div className={styles.skeletonStack}>
                      <Skeleton height="2rem" />
                      <Skeleton height="2rem" />
                      <Skeleton height="2rem" />
                    </div>
                  ) : (data?.components.length ?? 0) === 0 ? (
                    <EmptyState
                      compact
                      title={unavailable ? 'Health checks unavailable' : 'No components reported'}
                      description={
                        unavailable
                          ? 'The status request failed, so component health is unknown right now.'
                          : 'The status endpoint returned no component checks.'
                      }
                    />
                  ) : (
                    <ul className={styles.componentList}>
                      {data?.components.map((component) => (
                        <li key={component.name} className={styles.componentRow}>
                          <span>
                            <span className={styles.componentName}>{component.name}</span>
                            {component.detail ? (
                              <span className={styles.componentDetail}>{component.detail}</span>
                            ) : null}
                          </span>
                          <span className={styles.componentLatency}>
                            {component.latency_ms === null
                              ? EMPTY_VALUE
                              : `${formatNumber(component.latency_ms, { maximumFractionDigits: 1 })} ms`}
                          </span>
                          <Badge tone={COMPONENT_TONE[component.status] ?? 'neutral'} dot>
                            {component.status}
                          </Badge>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </Reveal>
            </div>
            <div className={styles.column}>
              <Reveal>
                <ChartFrame
                  title="Failure reasons"
                  subtitle="Recent failed jobs grouped by error code. The table view lists every failure with its message, verbatim."
                  table={{
                    caption: 'Recent failed jobs with their error messages',
                    columns: ['Error code', 'Stage', 'Message', 'Failed at'],
                    rows: failedJobs.map((job) => [
                      job.error_code ?? EMPTY_VALUE,
                      stageLabel(job.job_type),
                      job.error_message ?? 'No message recorded',
                      formatDateTimeCompact(job.finished_at ?? job.queued_at),
                    ]),
                  }}
                >
                  {pending ? (
                    <div className={styles.skeletonStack}>
                      <Skeleton height="1rem" />
                      <Skeleton height="1rem" />
                    </div>
                  ) : (
                    <BarList
                      label="Recent failed jobs by error code"
                      empty={
                        unavailable
                          ? 'Failures are unavailable because the status request failed.'
                          : 'No job has failed in the reporting window.'
                      }
                      items={failures}
                    />
                  )}
                </ChartFrame>
              </Reveal>

              <Reveal>
                <ProvidersCard providers={providerList} loading={pending && providers.isPending} />
              </Reveal>
            </div>
          </div>
        </section>

        {/* ----------------------------------------------------- lifecycle */}
        <Lifecycle />
      </div>
    </main>
  );
}
