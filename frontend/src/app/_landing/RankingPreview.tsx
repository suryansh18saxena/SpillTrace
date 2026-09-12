'use client';

import { useGrowIn } from '@/components/charts/useGrowIn';
import { Badge } from '@/components/ui/Badge';
import { cx } from '@/lib/cx';
import styles from '../landing.module.css';
import { DEMO_CANDIDATES } from './content';

/**
 * The candidate ranking of the seeded `kutch-01` demo case (see `content.ts`
 * for how the figures were checked). Every row keeps its "(SYNTHETIC)" suffix,
 * exactly as the system returns it (CON-009).
 */
export function RankingPreview() {
  const ref = useGrowIn<HTMLDivElement>();

  return (
    <div className={styles.rankCard} ref={ref}>
      <div className={styles.rankHead}>
        <span className={styles.rankHeadTitle}>Candidate ranking · case kutch-01</span>
        <Badge tone="synthetic">Synthetic</Badge>
      </div>

      {DEMO_CANDIDATES.map((candidate) => (
        <div
          key={candidate.rank}
          className={cx(styles.rankRow, candidate.highlight && styles.rankHighlight)}
        >
          <span className={styles.rankNum}>#{candidate.rank}</span>
          <span style={{ minWidth: 0 }}>
            <span className={styles.rankName}>{candidate.name}</span>
            <span className={styles.rankMeta}>{candidate.meta}</span>
          </span>
          <span className={styles.rankScore}>{candidate.score.toFixed(2)}</span>
          <span className={styles.rankBarTrack} aria-hidden="true">
            <span
              className={styles.rankBarFill}
              data-grow="x"
              style={{ width: `${candidate.score * 100}%` }}
            />
          </span>
        </div>
      ))}

      <p className={styles.rankFoot}>
        Investigative / probabilistic evidence — not automatic legal proof. Scores prioritise which
        vessels an authority should look at next, and never establish responsibility.
      </p>
    </div>
  );
}
