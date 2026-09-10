import { Skeleton } from '@/components/ui/Skeleton';
import layout from '@/components/layout/layout.module.css';
import styles from '@/styles/pages.module.css';

export interface DetailLoadingProps {
  /** What is loading, announced once to assistive technology. */
  label: string;
}

/**
 * The route-level loading skeleton shared by every case detail screen.
 *
 * It reserves the same shape the loaded page takes — header, tab bar, readout
 * row, two columns — so nothing jumps when the data lands.
 */
export function DetailLoading({ label }: DetailLoadingProps) {
  return (
    <div className={layout.content} aria-busy="true">
      <span className="sr-only">{label}</span>
      <div className={styles.detailStack}>
        <Skeleton height="2rem" width="18rem" />
        <Skeleton height="2.25rem" />
        <div className={styles.readoutRowSkeleton}>
          <Skeleton height="5rem" radius="var(--radius-md)" />
          <Skeleton height="5rem" radius="var(--radius-md)" />
          <Skeleton height="5rem" radius="var(--radius-md)" />
          <Skeleton height="5rem" radius="var(--radius-md)" />
        </div>
        <Skeleton height="20rem" radius="var(--radius-lg)" />
      </div>
    </div>
  );
}
