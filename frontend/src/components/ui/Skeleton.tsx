import { cx } from '@/lib/cx';
import styles from './ui.module.css';

export interface SkeletonProps {
  width?: string | number;
  height?: string | number;
  radius?: string;
  className?: string;
}

/**
 * A shape placeholder. It is `aria-hidden` on purpose: the surrounding region
 * announces the loading state once via `aria-busy`, and a screen reader reading
 * out twelve empty boxes is noise, not information.
 */
export function Skeleton({ width = '100%', height = '1rem', radius, className }: SkeletonProps) {
  return (
    <span
      aria-hidden="true"
      data-testid="skeleton"
      className={cx(styles.skeleton, className)}
      style={{ width, height, ...(radius ? { borderRadius: radius } : {}) }}
    />
  );
}

export interface SkeletonTextProps {
  lines?: number;
  className?: string;
}

export function SkeletonText({ lines = 3, className }: SkeletonTextProps) {
  return (
    <span className={cx(styles.skeletonText, className)} aria-hidden="true">
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton key={index} height="0.75rem" width={index === lines - 1 ? '60%' : '100%'} />
      ))}
    </span>
  );
}
