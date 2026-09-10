'use client';

import { useEffect } from 'react';
import { ErrorState } from '@/components/ui/ErrorState';
import { LinkButton } from '@/components/ui/LinkButton';
import styles from '@/styles/pages.module.css';

/**
 * Route-level error boundary (P4-011, NFR-012).
 *
 * `digest` is the only identifier the framework gives the client for a server
 * error; showing it is what lets an analyst quote something an engineer can grep
 * for. The raw message and stack are never rendered (NFR-011).
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[spilltrace] unhandled route error', error);
  }, [error]);

  return (
    <main className={styles.centeredScreen} id="main-content">
      <div className={styles.centeredCard}>
        <ErrorState
          title="This screen failed to render"
          description={
            error.digest
              ? `An unexpected error interrupted this page. Reference ${error.digest}.`
              : 'An unexpected error interrupted this page.'
          }
          onRetry={reset}
          retryLabel="Reload this screen"
          action={
            <LinkButton href="/cases" variant="ghost" size="sm">
              Back to cases
            </LinkButton>
          }
        />
      </div>
    </main>
  );
}
