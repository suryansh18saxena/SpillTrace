import { Skeleton } from '@/components/ui/Skeleton';
import layout from '@/components/layout/layout.module.css';
import styles from './activity.module.css';

/** Header, summary strip, filter row and a few timeline rows. */
export default function ActivityLoading() {
  return (
    <div className={layout.content} aria-busy="true">
      <span className="sr-only">Loading activity</span>
      <Skeleton height="2rem" width="16rem" />
      <div style={{ height: 'var(--space-6)' }} />
      <Skeleton height="5.5rem" radius="var(--radius-lg)" />
      <div style={{ height: 'var(--space-6)' }} />
      <Skeleton height="3.5rem" radius="var(--radius-lg)" />
      <div style={{ height: 'var(--space-6)' }} />
      <div className={styles.skeletonFeed}>
        {Array.from({ length: 5 }, (_, index) => (
          <div key={index} className={styles.skeletonRow}>
            <Skeleton height="0.75rem" width="4rem" />
            <span />
            <Skeleton height="4.5rem" radius="var(--radius-md)" />
          </div>
        ))}
      </div>
    </div>
  );
}
