import { Skeleton } from '@/components/ui/Skeleton';
import layout from '@/components/layout/layout.module.css';
import styles from './analytics.module.css';

/** Header, scope bar, KPI row and the first chart pair — the page arrives rather than pops in. */
export default function AnalyticsLoading() {
  return (
    <div className={layout.content} aria-busy="true">
      <span className="sr-only">Loading analytics</span>
      <Skeleton height="2rem" width="20rem" />
      <div style={{ height: 'var(--space-6)' }} />
      <Skeleton height="3.25rem" radius="var(--radius-lg)" />
      <div style={{ height: 'var(--space-5)' }} />
      <div className={styles.kpis}>
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} height="8.5rem" radius="var(--radius-lg)" />
        ))}
      </div>
      <div style={{ height: 'var(--space-10)' }} />
      <div className={styles.grid}>
        <Skeleton height="18rem" radius="var(--radius-lg)" />
        <Skeleton height="18rem" radius="var(--radius-lg)" />
      </div>
    </div>
  );
}
