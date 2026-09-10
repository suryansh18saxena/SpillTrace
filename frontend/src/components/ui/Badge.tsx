import type { ReactNode } from 'react';
import { cx } from '@/lib/cx';
import styles from './ui.module.css';

export type BadgeTone =
  | 'neutral'
  | 'accent'
  | 'success'
  | 'warning'
  | 'danger'
  | 'info'
  | 'synthetic'
  | 'confidence-1'
  | 'confidence-2'
  | 'confidence-3';

export interface BadgeProps {
  tone?: BadgeTone;
  /** Small leading dot — useful when the badge is a status in a dense table. */
  dot?: boolean;
  title?: string;
  className?: string;
  children: ReactNode;
}

const TONE_CLASS: Record<BadgeTone, string | undefined> = {
  neutral: styles.badgeNeutral,
  accent: styles.badgeAccent,
  success: styles.badgeSuccess,
  warning: styles.badgeWarning,
  danger: styles.badgeDanger,
  info: styles.badgeInfo,
  synthetic: styles.badgeSynthetic,
  'confidence-1': styles.badgeConfidence1,
  'confidence-2': styles.badgeConfidence2,
  'confidence-3': styles.badgeConfidence3,
};

/**
 * A label, never an interactive control.
 *
 * The `confidence-*` tones are the 3-step probability ramp. They are the only
 * place that ramp appears, and it is deliberately not the red/green semantic
 * scale: a high investigative score is a lead, not a verdict (CON-001/CON-003).
 */
export function Badge({ tone = 'neutral', dot = false, title, className, children }: BadgeProps) {
  return (
    <span className={cx(styles.badge, TONE_CLASS[tone], className)} title={title}>
      {dot ? <span className={styles.badgeDot} aria-hidden="true" /> : null}
      {children}
    </span>
  );
}
