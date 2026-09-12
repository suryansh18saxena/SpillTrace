import { Skeleton } from '@/components/ui/Skeleton';
import { cx } from '@/lib/cx';
import layout from '@/components/layout/layout.module.css';
import styles from './map.module.css';

/** Holds the map-and-panel shape so the situational map arrives rather than pops in. */
export default function SituationalMapLoading() {
  return (
    <div className={cx(layout.content, layout.contentFlush)} aria-busy="true">
      <span className="sr-only">Loading the situational map</span>
      <div className={styles.stage}>
        <div className={styles.mapArea}>
          <div className={styles.mapFrame}>
            <Skeleton height="100%" radius="0" />
          </div>
        </div>
        <div className={styles.panel}>
          <div className={styles.panelHead}>
            <Skeleton height="0.75rem" width="8rem" />
            <div style={{ height: 'var(--space-3)' }} />
            <Skeleton height="1.75rem" width="12rem" />
            <div style={{ height: 'var(--space-3)' }} />
            <Skeleton height="2.5rem" />
          </div>
          <div className={styles.panelSection}>
            <Skeleton height="1.75rem" />
            <Skeleton height="4.75rem" radius="var(--radius-md)" />
            <Skeleton height="4.75rem" radius="var(--radius-md)" />
          </div>
        </div>
      </div>
    </div>
  );
}
