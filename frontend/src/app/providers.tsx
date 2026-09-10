'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { ToastProvider } from '@/components/ui/Toast';
import { retryPolicy } from '@/lib/api/hooks';

/**
 * Client providers.
 *
 * The `QueryClient` is created inside `useState` rather than at module scope so
 * that each browser session — and each test — gets its own cache. A module-level
 * client would be shared across server renders and leak one user's data into
 * another's response.
 */
export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            gcTime: 5 * 60_000,
            retry: retryPolicy,
            // An analyst tabbing back to a stale investigation should not
            // trigger a burst of refetches; the polling hooks handle freshness
            // where it actually matters.
            refetchOnWindowFocus: false,
          },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>{children}</ToastProvider>
    </QueryClientProvider>
  );
}
