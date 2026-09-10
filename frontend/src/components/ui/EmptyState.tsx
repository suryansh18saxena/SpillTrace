import type { ReactNode } from 'react';
import { cx } from '@/lib/cx';
import { IconInbox } from './Icons';
import styles from './ui.module.css';

export interface EmptyStateProps {
  title: string;
  /**
   * Say what is missing and what would produce it. "No data" is not an empty
   * state; "No scenes yet — run a scene search to populate this case" is.
   */
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  className?: string;
}

export function EmptyState({
  title,
  description,
  icon,
  action,
  compact = false,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cx(styles.placeholder, compact && styles.placeholderCompact, className)}
      data-testid="empty-state"
    >
      <span className={styles.placeholderIcon}>{icon ?? <IconInbox size={18} />}</span>
      <p className={styles.placeholderTitle}>{title}</p>
      {description ? <p className={styles.placeholderBody}>{description}</p> : null}
      {action ? <div className={styles.placeholderActions}>{action}</div> : null}
    </div>
  );
}
