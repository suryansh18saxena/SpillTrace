import { Skeleton } from '@/components/ui/Skeleton';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';

export default function AdminLoading() {
  return (
    <div className={layout.content} aria-busy="true">
      <span className="sr-only">Loading system status</span>
      <Skeleton height="1.75rem" width="14rem" />
      <div style={{ height: 'var(--space-6)' }} />
      <div className={styles.statGrid}>
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} height="5.5rem" radius="var(--radius-lg)" />
        ))}
      </div>
      <Skeleton height="18rem" radius="var(--radius-lg)" />
    </div>
  );
}
