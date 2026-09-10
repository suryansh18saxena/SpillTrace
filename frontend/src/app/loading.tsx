import { Skeleton } from '@/components/ui/Skeleton';
import styles from '@/styles/pages.module.css';

/**
 * Route-transition fallback. It mirrors the coarse shape of a page — a title, a
 * toolbar, a block of content — so navigation feels like the page arriving
 * rather than the screen blanking.
 */
export default function Loading() {
  return (
    <div className={styles.pageSkeleton} aria-busy="true">
      <span className="sr-only">Loading</span>
      <Skeleton height="1.75rem" width="16rem" />
      <Skeleton height="0.875rem" width="28rem" />
      <Skeleton height="14rem" radius="var(--radius-lg)" />
    </div>
  );
}
