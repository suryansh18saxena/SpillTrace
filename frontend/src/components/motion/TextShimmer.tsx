import type { CSSProperties, ElementType, ReactNode } from 'react';
import { cx } from '@/lib/cx';
import styles from './motion.module.css';

export interface TextShimmerProps {
  as?: ElementType;
  children?: ReactNode;
  className?: string;
  /** Seconds per sweep. */
  duration?: number;
  /** Use the gold confidence hue instead of the accent. Decorative only. */
  gold?: boolean;
}

/**
 * A slow sheen passing through a headline. CSS only, so it works in server
 * components; under reduced motion the text is plain and static.
 */
export function TextShimmer({
  as: Tag = 'span',
  children,
  className,
  duration = 4.5,
  gold = false,
}: TextShimmerProps) {
  return (
    <Tag
      className={cx(styles.shimmer, gold && styles.shimmerGold, className)}
      style={{ '--shimmer-duration': `${duration}s` } as CSSProperties}
    >
      {children}
    </Tag>
  );
}
