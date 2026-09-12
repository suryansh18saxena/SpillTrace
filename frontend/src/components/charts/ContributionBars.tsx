'use client';

import type { AttributionFactor } from '@/lib/api/types';
import { formatScore } from '@/lib/format';
import styles from './charts.module.css';
import { useGrowIn } from './useGrowIn';

export interface ContributionBarsProps {
  factors: readonly AttributionFactor[];
  candidateLabel: string;
}

/**
 * "How the score was built": each factor's contribution against the most it
 * could have contributed.
 *
 * The pale track is the factor's weight — its full share of the score — and the
 * solid fill is weight × factor score, the contribution it actually made. So
 * "0.34 / 0.35" reads directly as "origin proximity delivered almost all of its
 * 35 %". Every number is printed as text beside its bar; the bars are a
 * reading aid, and the full arithmetic is in the factor table.
 */
export function ContributionBars({ factors, candidateLabel }: ContributionBarsProps) {
  const ref = useGrowIn<HTMLUListElement>([factors.length]);
  const maxWeight = Math.max(0.0001, ...factors.map((f) => f.weight));

  return (
    <ul className={styles.contrib} ref={ref} aria-label={`Score build-up for ${candidateLabel}`}>
      {factors.map((factor) => {
        const capacity = (factor.weight / maxWeight) * 100;
        const fill = (Math.max(0, factor.contribution) / maxWeight) * 100;
        return (
          <li key={factor.key} className={styles.contribRow}>
            <span className={styles.contribLabel}>{factor.label}</span>
            <span className={styles.barTrackWide} aria-hidden="true">
              <span className={styles.contribCapacity} style={{ width: `${capacity}%` }} />
              <span className={styles.contribFill} data-grow="x" style={{ width: `${fill}%` }} />
            </span>
            <span className={styles.contribValue}>
              <strong>{formatScore(factor.contribution)}</strong> of {formatScore(factor.weight)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
