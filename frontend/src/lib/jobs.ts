import type { Job } from '@/lib/api/types';

/**
 * Stage order of a pipeline, mirroring `PIPELINE_ORDER` / `DEMO_ORDER` in
 * backend/src/spilltrace/core/enums.py and worker/pipeline.py. The API returns jobs
 * newest-first, and every stage of one run is created in the same transaction, so
 * their timestamps tie and the raw order is effectively random. The UI sorts by this.
 */
export const PIPELINE_STAGE_ORDER: readonly string[] = [
  'demo.seed',
  'scene.search',
  'scene.download',
  'sar.preprocess',
  'ml.detect',
  'env.fetch',
  'detect.verify',
  'drift.hindcast',
  'ais.ingest',
  'ais.clean',
  'traj.build',
  'correlate',
  'score',
  'report.build',
];

export interface PipelineRun {
  /** `null` groups stages that were started one at a time, outside a pipeline. */
  pipelineId: string | null;
  jobs: Job[];
  /** When the run was queued (its earliest stage). */
  queuedAt: string;
  completed: number;
  failed: number;
  active: number;
}

function stageRank(jobType: string): number {
  const index = PIPELINE_STAGE_ORDER.indexOf(jobType);
  return index === -1 ? PIPELINE_STAGE_ORDER.length : index;
}

/** Group jobs by pipeline run: newest run first, stages in pipeline order. */
export function groupJobsByRun(jobs: readonly Job[]): PipelineRun[] {
  const byRun = new Map<string, Job[]>();
  for (const job of jobs) {
    const key = job.pipeline_id ?? '';
    const bucket = byRun.get(key);
    if (bucket) bucket.push(job);
    else byRun.set(key, [job]);
  }

  const runs: PipelineRun[] = [];
  for (const [key, runJobs] of byRun) {
    const sorted = [...runJobs].sort(
      (a, b) =>
        stageRank(a.job_type) - stageRank(b.job_type) || a.queued_at.localeCompare(b.queued_at),
    );
    const queuedAt = sorted.reduce(
      (earliest, job) => (job.queued_at < earliest ? job.queued_at : earliest),
      sorted[0]?.queued_at ?? '',
    );
    runs.push({
      pipelineId: key || null,
      jobs: sorted,
      queuedAt,
      completed: sorted.filter((job) => job.status === 'COMPLETED').length,
      failed: sorted.filter((job) => job.status === 'FAILED').length,
      active: sorted.filter((job) => job.status === 'QUEUED' || job.status === 'RUNNING').length,
    });
  }
  return runs.sort((a, b) => b.queuedAt.localeCompare(a.queuedAt));
}
