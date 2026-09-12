import { Skeleton } from '@/components/ui/Skeleton';
import layout from '@/components/layout/layout.module.css';
import styles from './vessels.module.css';

/**
 * Matches the registry's shape — KPI strip, safeguards, list — so the page
 * arrives rather than pops in. `[vesselId]/loading.tsx` still wins for the
 * detail route, being the nearer boundary.
 */
export default function VesselRegistryLoading() {
  return (
    <div className={layout.content} aria-busy="true">
      <span className="sr-only">Loading the vessel registry</span>
      <Skeleton height="1.75rem" width="14rem" />
      <div style={{ height: 'var(--space-6)' }} />
      <div className={styles.kpis}>
        {Array.from({ length: 3 }, (_, index) => (
          <Skeleton key={index} height="8.5rem" radius="var(--radius-lg)" />
        ))}
      </div>
      <div className={styles.guards}>
        <Skeleton height="5rem" radius="var(--radius-lg)" />
        <Skeleton height="5rem" radius="var(--radius-lg)" />
      </div>
      <Skeleton height="26rem" radius="var(--radius-lg)" />
    </div>
  );
}
