'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { CountUp } from '@/components/motion/CountUp';
import { useSpotlight } from '@/components/motion/useSpotlight';
import { Skeleton } from '@/components/ui/Skeleton';
import { cx } from '@/lib/cx';
import { EMPTY_VALUE } from '@/lib/format';
import { Sparkline } from './Sparkline';
import styles from './stat.module.css';

export type StatTone = 'accent' | 'signal' | 'synthetic' | 'success' | 'danger' | 'neutral';

export interface StatTileProps {
  label: string;
  /** `null` means "not known" and renders as a dash — never as zero. */
  value: number | null | undefined;
  decimals?: number;
  suffix?: string;
  caption?: ReactNode;
  icon?: ReactNode;
  /** Colours the icon chip only; the number is always in text ink. */
  tone?: StatTone;
  trend?: readonly number[];
  trendLabel?: string;
  href?: string;
  loading?: boolean;
  className?: string;
}

const TONE_CLASS: Record<StatTone, string | undefined> = {
  accent: styles.toneAccent,
  signal: styles.toneSignal,
  synthetic: styles.toneSynthetic,
  success: styles.toneSuccess,
  danger: styles.toneDanger,
  neutral: styles.toneNeutral,
};

/**
 * A KPI tile: sentence-case label, one number (sans, semibold, proportional
 * figures) that counts up once, an optional caption and an optional trend.
 *
 * An unknown value renders as "—" with its caption, never as 0: "we could
 * not count this" and "there were none" are different facts.
 */
export function StatTile({
  label,
  value,
  decimals = 0,
  suffix = '',
  caption,
  icon,
  tone = 'accent',
  trend,
  trendLabel,
  href,
  loading = false,
  className,
}: StatTileProps) {
  const ref = useSpotlight<HTMLDivElement>({ tilt: 4 });

  const body = (
    <>
      <div className={styles.head}>
        <span className={styles.label}>{label}</span>
        {icon ? <span className={cx(styles.icon, TONE_CLASS[tone])}>{icon}</span> : null}
      </div>
      <div className={styles.value}>
        {loading ? (
          <Skeleton height="2rem" width="4.5rem" />
        ) : value === null || value === undefined || !Number.isFinite(value) ? (
          EMPTY_VALUE
        ) : (
          <CountUp value={value} decimals={decimals} suffix={suffix} />
        )}
      </div>
      {trend && trend.length > 1 ? (
        <div className={styles.trend}>
          <Sparkline values={trend} label={trendLabel ?? `${label} trend`} />
        </div>
      ) : null}
      {caption ? <p className={styles.caption}>{caption}</p> : null}
    </>
  );

  return (
    <div ref={ref} className={cx(styles.tile, href && styles.tileLink, className)} data-enter="">
      {href ? (
        <Link href={href} className={styles.cover}>
          {body}
        </Link>
      ) : (
        body
      )}
    </div>
  );
}
