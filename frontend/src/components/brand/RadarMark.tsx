import { useId } from 'react';
import { cx } from '@/lib/cx';
import styles from './brand.module.css';

export interface RadarMarkProps {
  size?: number;
  /** Rotate the sweep. Off for tiny inline uses; always off under reduced motion. */
  animated?: boolean;
  className?: string;
}

/**
 * The SPILLTRACE mark: range rings, a sweep and one contact.
 *
 * It is the product in miniature — a radar looking at the sea — and it is drawn
 * rather than an image so it inherits `currentColor` and the accent tokens in
 * both themes. Decorative, so it is `aria-hidden`; the brand name next to it is
 * the accessible text.
 */
export function RadarMark({ size = 28, animated = true, className }: RadarMarkProps) {
  const id = useId().replace(/:/g, '');
  return (
    <svg
      className={cx(styles.mark, className)}
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={`${id}-ring`} x1="0" y1="0" x2="32" y2="32">
          <stop offset="0" stopColor="var(--color-accent-2)" />
          <stop offset="1" stopColor="var(--color-accent)" />
        </linearGradient>
        <radialGradient id={`${id}-core`} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="var(--color-accent-2)" stopOpacity="0.35" />
          <stop offset="1" stopColor="var(--color-accent)" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${id}-sweep`} x1="16" y1="16" x2="30" y2="9">
          <stop offset="0" stopColor="var(--color-accent-2)" stopOpacity="0.85" />
          <stop offset="1" stopColor="var(--color-accent-2)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <circle cx="16" cy="16" r="15" fill={`url(#${id}-core)`} />
      <circle cx="16" cy="16" r="14" stroke={`url(#${id}-ring)`} strokeWidth="1.5" opacity="0.55" />
      <circle cx="16" cy="16" r="8.5" stroke={`url(#${id}-ring)`} strokeWidth="1.5" opacity="0.8" />
      <g className={cx(animated && styles.sweep)}>
        <path d="M16 16 L29.2 9.6 A14.6 14.6 0 0 1 30.6 16 Z" fill={`url(#${id}-sweep)`} />
        <path
          d="M16 16 L29.4 10"
          stroke="var(--color-accent-2)"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
      </g>
      <circle cx="16" cy="16" r="2.2" fill="var(--color-accent-2)" />
      <circle
        className={cx(animated && styles.blip)}
        cx="22.6"
        cy="11.4"
        r="1.5"
        fill="var(--confidence-3)"
      />
    </svg>
  );
}
