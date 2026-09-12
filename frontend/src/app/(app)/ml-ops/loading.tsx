import { Skeleton } from '@/components/ui/Skeleton';
import layout from '@/components/layout/layout.module.css';
import styles from './ml-ops.module.css';

/** Matches the ML Ops layout — header, model cards, throughput tiles. */
export default function MlOpsLoading() {
  return (
    <div className={layout.content} aria-busy="true">
      <span className="sr-only">Loading ML Ops</span>
      <Skeleton height="1.75rem" width="10rem" />
      <div style={{ height: 'var(--space-6)' }} />
      <div className={styles.stack}>
        <div className={styles.models}>
          <Skeleton height="19rem" radius="var(--radius-lg)" />
          <Skeleton height="19rem" radius="var(--radius-lg)" />
        </div>
        <div className={styles.kpis}>
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} height="8rem" radius="var(--radius-lg)" />
          ))}
        </div>
      </div>
    </div>
  );
}
