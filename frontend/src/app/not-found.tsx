import type { Metadata } from 'next';
import { EmptyState } from '@/components/ui/EmptyState';
import { LinkButton } from '@/components/ui/LinkButton';
import { IconSearch } from '@/components/ui/Icons';
import styles from '@/styles/pages.module.css';

export const metadata: Metadata = { title: 'Page not found' };

export default function NotFound() {
  return (
    <main className={styles.centeredScreen} id="main-content">
      <div className={styles.centeredCard}>
        <EmptyState
          icon={<IconSearch size={18} />}
          title="That page does not exist"
          description="The address may be mistyped, or the case may have been archived or deleted. Everything you can reach is listed under Cases."
          action={
            <LinkButton href="/cases" variant="primary" size="sm">
              Go to cases
            </LinkButton>
          }
        />
      </div>
    </main>
  );
}
