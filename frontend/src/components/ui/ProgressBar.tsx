import { cx } from '@/lib/cx';
import styles from './ui.module.css';

export type ProgressTone = 'accent' | 'success' | 'danger' | 'neutral';

export interface ProgressBarProps {
  /** 0..max. Ignored when `indeterminate`. */
  value?: number;
  max?: number;
  /** Accessible name, e.g. "drift.hindcast progress". */
  label: string;
  /** Use when the backend reports no percentage — a QUEUED job, for instance. */
  indeterminate?: boolean;
  /** Human text read instead of the bare percentage, e.g. the job's `step`. */
  valueText?: string;
  showValue?: boolean;
  tone?: ProgressTone;
  className?: string;
}

const TONE_CLASS: Record<ProgressTone, string | undefined> = {
  accent: styles.progressFill,
  success: cx(styles.progressFill, styles.progressFillSuccess),
  danger: cx(styles.progressFill, styles.progressFillDanger),
  neutral: cx(styles.progressFill, styles.progressFillNeutral),
};

export function ProgressBar({
  value = 0,
  max = 100,
  label,
  indeterminate = false,
  valueText,
  showValue = true,
  tone = 'accent',
  className,
}: ProgressBarProps) {
  const clamped = Math.min(Math.max(value, 0), max);
  const percent = max > 0 ? (clamped / max) * 100 : 0;

  return (
    <div className={cx(styles.progressRow, className)}>
      <div
        className={styles.progressTrack}
        role="progressbar"
        aria-label={label}
        aria-valuemin={indeterminate ? undefined : 0}
        aria-valuemax={indeterminate ? undefined : max}
        aria-valuenow={indeterminate ? undefined : Math.round(clamped)}
        aria-valuetext={valueText}
      >
        {indeterminate ? (
          <div className={styles.progressIndeterminate} />
        ) : (
          <div className={TONE_CLASS[tone]} style={{ width: `${percent}%` }} />
        )}
      </div>
      {showValue ? (
        <span className={styles.progressValue} aria-hidden="true">
          {indeterminate ? '—' : `${Math.round(percent)}%`}
        </span>
      ) : null}
    </div>
  );
}
