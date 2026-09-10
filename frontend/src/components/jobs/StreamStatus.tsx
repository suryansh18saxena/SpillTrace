'use client';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { cx } from '@/lib/cx';
import type { JobStreamState } from '@/lib/api/useJobStream';
import styles from './jobs.module.css';

export interface StreamStatusProps {
  state: JobStreamState;
  className?: string;
}

const TONE: Record<string, BadgeTone> = {
  stream: 'success',
  connecting: 'accent',
  polling: 'warning',
  idle: 'neutral',
};

const LABEL: Record<string, string> = {
  stream: 'Live',
  connecting: 'Connecting',
  polling: 'Polling',
  idle: 'Settled',
};

const EXPLANATION: Record<string, string> = {
  stream: 'Progress arrives as the worker publishes it.',
  connecting: 'Opening the live progress stream…',
  polling: 'Progress is refreshed every few seconds.',
  idle: 'No stage is queued or running, so there is nothing to stream.',
};

/**
 * How pipeline progress is currently reaching this screen.
 *
 * Worth stating plainly: an analyst watching a stalled progress bar needs to
 * know whether the number is live or four seconds old, and whether the stream
 * fell back to polling because it dropped. A silent degradation would look
 * identical to a stuck job.
 */
export function StreamStatus({ state, className }: StreamStatusProps) {
  return (
    <p className={cx(styles.streamStatus, className)}>
      <Badge tone={TONE[state.transport] ?? 'neutral'} dot>
        {LABEL[state.transport] ?? state.transport}
      </Badge>
      <span>{state.reason ?? EXPLANATION[state.transport] ?? ''}</span>
    </p>
  );
}
