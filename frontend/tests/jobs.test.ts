import { describe, expect, it } from 'vitest';
import type { Job } from '@/lib/api/types';
import { groupJobsByRun } from '@/lib/jobs';

function job(
  id: string,
  pipelineId: string | null,
  jobType: string,
  queuedAt: string,
  status = 'COMPLETED',
): Job {
  return {
    id,
    case_id: 'c1',
    pipeline_id: pipelineId,
    job_type: jobType,
    status,
    progress: 100,
    step: null,
    attempt: 1,
    max_attempts: 3,
    queued_at: queuedAt,
    started_at: null,
    finished_at: null,
    error_code: null,
    error_message: null,
    result_ref: null,
  } as Job;
}

describe('groupJobsByRun', () => {
  it('puts the newest run first and each run in pipeline stage order', () => {
    const jobs = [
      job('a3', 'old', 'score', '2026-09-10T01:00:00Z'),
      job('b2', 'new', 'report.build', '2026-09-12T01:00:00Z', 'QUEUED'),
      job('a1', 'old', 'demo.seed', '2026-09-10T01:00:00Z'),
      job('b1', 'new', 'sar.preprocess', '2026-09-12T01:00:00Z', 'RUNNING'),
      job('a2', 'old', 'detect.verify', '2026-09-10T01:00:00Z'),
      job('b3', 'new', 'env.fetch', '2026-09-12T01:00:00Z', 'FAILED'),
    ];

    const runs = groupJobsByRun(jobs);

    expect(runs.map((run) => run.pipelineId)).toEqual(['new', 'old']);
    expect(runs[0]?.jobs.map((j) => j.job_type)).toEqual([
      'sar.preprocess',
      'env.fetch',
      'report.build',
    ]);
    expect(runs[1]?.jobs.map((j) => j.job_type)).toEqual(['demo.seed', 'detect.verify', 'score']);
    expect(runs[0]).toMatchObject({ completed: 0, failed: 1, active: 2 });
    expect(runs[1]).toMatchObject({ completed: 3, failed: 0, active: 0 });
  });

  it('keeps stages started outside a pipeline in their own group', () => {
    const runs = groupJobsByRun([job('x', null, 'score', '2026-09-11T00:00:00Z')]);
    expect(runs).toHaveLength(1);
    expect(runs[0]?.pipelineId).toBeNull();
  });
});
