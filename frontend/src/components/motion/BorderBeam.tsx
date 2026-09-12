'use client';

import type { CSSProperties } from 'react';
import { cx } from '@/lib/cx';
import styles from './motion.module.css';

export interface BorderBeamProps {
  /** Seconds for one revolution. */
  duration?: number;
  className?: string;
}

/**
 * A thin light travelling around the edge of its parent.
 *
 * Render it as the last child of a `position: relative` element with a border
 * radius; it inherits the radius and stays out of the way of pointer events.
 * Pure CSS (a conic gradient behind a masked ring); static under reduced motion.
 */
export function BorderBeam({ duration = 9, className }: BorderBeamProps) {
  return (
    <span
      aria-hidden="true"
      className={cx(styles.beam, className)}
      style={{ '--beam-duration': `${duration}s` } as CSSProperties}
    />
  );
}
