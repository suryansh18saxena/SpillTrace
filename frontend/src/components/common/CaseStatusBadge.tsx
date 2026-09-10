import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { humanizeIdentifier } from '@/lib/format';
import type { CaseStatus } from '@/lib/api/types';

export interface CaseStatusBadgeProps {
  status: CaseStatus;
  className?: string;
}

const TONE: Record<string, BadgeTone> = {
  DRAFT: 'neutral',
  QUEUED: 'neutral',
  RUNNING: 'accent',
  COMPLETED: 'success',
  FAILED: 'danger',
  ARCHIVED: 'neutral',
};

/** Unknown statuses render neutrally rather than throwing — see `Known<T>`. */
export function CaseStatusBadge({ status, className }: CaseStatusBadgeProps) {
  return (
    <Badge tone={TONE[status] ?? 'neutral'} dot className={className}>
      {humanizeIdentifier(status)}
    </Badge>
  );
}
