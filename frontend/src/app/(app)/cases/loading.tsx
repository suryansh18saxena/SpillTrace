import { Skeleton } from '@/components/ui/Skeleton';
import layout from '@/components/layout/layout.module.css';

/** Matches the shape of the case list so the page arrives rather than pops in. */
export default function CasesLoading() {
  return (
    <div className={layout.content} aria-busy="true">
      <span className="sr-only">Loading cases</span>
      <Skeleton height="1.75rem" width="10rem" />
      <div style={{ height: 'var(--space-6)' }} />
      <Skeleton height="4rem" radius="var(--radius-lg)" />
      <div style={{ height: 'var(--space-4)' }} />
      <Skeleton height="22rem" radius="var(--radius-lg)" />
    </div>
  );
}
