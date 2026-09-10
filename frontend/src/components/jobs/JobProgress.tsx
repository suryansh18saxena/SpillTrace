'use client';

import { Button } from '@/components/ui/Button';
import { ProgressBar, type ProgressTone } from '@/components/ui/ProgressBar';
import { Tooltip } from '@/components/ui/Tooltip';
import { cx } from '@/lib/cx';
import { formatDateTimeCompact, formatElapsed, humanizeIdentifier, truncateId } from '@/lib/format';
import type { Job } from '@/lib/api/types';
import { JobStatusBadge } from './JobStatusBadge';
import styles from './jobs.module.css';

export interface JobProgressProps {
  job: Job;
  onCancel?: (jobId: string) => void;
  onRetry?: (jobId: string) => void;
  /** Disables both actions while a mutation for this job is in flight. */
  busy?: boolean;
  className?: string;
}

const TONE_FOR_STATUS: Record<string, ProgressTone> = {
  QUEUED: 'neutral',
  RUNNING: 'accent',
  COMPLETED: 'success',
  FAILED: 'danger',
  CANCELLED: 'neutral',
};

/**
 * One tracked pipeline stage (FR-019, NFR-003).
 *
 * Everything the requirement asks for is on screen: id, status, progress, the
 * human step label, attempt count, timestamps and — when it failed — the error
 * code and message. A failed provider is a stated reason, never a silent gap
 * (NFR-011).
 */
export function JobProgress({ job, onCancel, onRetry, busy = false, className }: JobProgressProps) {
  const isActive = job.status === 'QUEUED' || job.status === 'RUNNING';
  const isFailed = job.status === 'FAILED';
  const tone = TONE_FOR_STATUS[job.status] ?? 'neutral';
  const label = humanizeIdentifier(job.job_type);

  return (
    <article className={cx(styles.job, isFailed && styles.jobFailed, className)}>
      <div className={styles.jobHead}>
        <span className={styles.jobType}>{job.job_type}</span>
        <JobStatusBadge status={job.status} />
        <span className={styles.jobSpacer} />
        <div className={styles.jobActions}>
          {onCancel && isActive ? (
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => onCancel(job.id)}>
              Cancel
            </Button>
          ) : null}
          {onRetry && isFailed ? (
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => onRetry(job.id)}>
              Retry
            </Button>
          ) : null}
        </div>
      </div>

      <ProgressBar
        label={`${label} progress`}
        value={job.progress}
        tone={tone}
        indeterminate={job.status === 'QUEUED'}
        valueText={job.step ?? undefined}
      />

      {job.step ? <p className={styles.jobStep}>{job.step}</p> : null}

      <div className={styles.jobMeta}>
        <span>
          job <span className={styles.jobMetaValue}>{truncateId(job.id, 8, 4)}</span>
        </span>
        <Tooltip
          content={`Attempt ${job.attempt} of ${job.max_attempts}. A stage is only marked FAILED once every attempt has been used.`}
        >
          <span tabIndex={0} className={styles.jobMetaTrigger}>
            attempt{' '}
            <span className={styles.jobMetaValue}>
              {job.attempt}/{job.max_attempts}
            </span>
          </span>
        </Tooltip>
        <span>
          queued <span className={styles.jobMetaValue}>{formatDateTimeCompact(job.queued_at)}</span>
        </span>
        {job.started_at ? (
          <span>
            runtime{' '}
            <span className={styles.jobMetaValue}>
              {formatElapsed(job.started_at, job.finished_at ?? new Date().toISOString())}
            </span>
          </span>
        ) : null}
      </div>

      {isFailed && (job.error_code || job.error_message) ? (
        <div className={styles.jobError} role="status">
          {job.error_code ? <span className={styles.jobErrorCode}>{job.error_code}</span> : null}
          <span>{job.error_message ?? 'The stage failed without a reported reason.'}</span>
        </div>
      ) : null}
    </article>
  );
}
