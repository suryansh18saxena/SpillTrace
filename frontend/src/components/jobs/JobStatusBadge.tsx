import { Badge, type BadgeTone } from '@/components/ui/Badge';
import type { JobStatus } from '@/lib/api/types';

export interface JobStatusBadgeProps {
  status: JobStatus;
  className?: string;
}

/**
 * Job status, colour-coded.
 *
 * Red here means a **pipeline stage failed** — a system fault. It is never used
 * for a score or a vessel, where red would read as an accusation (CON-001).
 */
const STATUS_TONE: Record<string, BadgeTone> = {
  QUEUED: 'neutral',
  RUNNING: 'accent',
  COMPLETED: 'success',
  FAILED: 'danger',
  CANCELLED: 'neutral',
};

const STATUS_LABEL: Record<string, string> = {
  QUEUED: 'Queued',
  RUNNING: 'Running',
  COMPLETED: 'Completed',
  FAILED: 'Failed',
  CANCELLED: 'Cancelled',
};

export function JobStatusBadge({ status, className }: JobStatusBadgeProps) {
  const tone = STATUS_TONE[status] ?? 'neutral';
  return (
    <Badge tone={tone} dot className={className}>
      {STATUS_LABEL[status] ?? status}
    </Badge>
  );
}
