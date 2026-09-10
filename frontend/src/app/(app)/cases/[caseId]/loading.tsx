import { Skeleton } from '@/components/ui/Skeleton';
import { Spinner } from '@/components/ui/Spinner';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';

/** The map is the hero, so the skeleton keeps its footprint reserved. */
export default function InvestigationLoading() {
  return (
    <div className={`${layout.content} ${layout.contentFlush}`} aria-busy="true">
      <span className="sr-only">Loading investigation</span>
      <div className={styles.investigation}>
        <div
          className={styles.investigationMap}
          style={{ display: 'grid', placeItems: 'center', background: 'var(--map-ocean)' }}
        >
          <Spinner size="md" label={null} />
        </div>
        <div className={styles.investigationPanel}>
          <div className={styles.panelSection}>
            <Skeleton height="1.25rem" width="70%" />
            <div style={{ height: 'var(--space-3)' }} />
            <Skeleton height="4rem" />
          </div>
          <div className={styles.panelSection}>
            <Skeleton height="12rem" />
          </div>
        </div>
      </div>
    </div>
  );
}
