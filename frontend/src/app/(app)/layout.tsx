'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useCallback, useEffect, useState, useSyncExternalStore, type ReactNode } from 'react';
import { Header } from '@/components/layout/Header';
import { Sidebar } from '@/components/layout/Sidebar';
import { Spinner } from '@/components/ui/Spinner';
import { useLogout, useMe } from '@/lib/api/hooks';
import { onUnauthenticated } from '@/lib/api/client';
import {
  bootstrapSession,
  getSessionSnapshot,
  setCurrentUser,
  subscribeToSession,
  type SessionState,
} from '@/lib/auth/session';
import styles from '@/components/layout/layout.module.css';

const SIDEBAR_ID = 'app-sidebar';
const SERVER_SNAPSHOT: SessionState = { status: 'unknown', user: null };

/**
 * The authenticated shell (P4-004, P4-006).
 *
 * Route protection is client-side by design: the access token lives only in
 * memory, so there is nothing for a server middleware to check without either
 * putting the token in a readable cookie (defeating the point) or proxying every
 * request. On load, one silent refresh decides between "signed in" and "send to
 * login" — the boot screen exists so the analyst never sees a flash of the app
 * before being redirected.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname() ?? '/cases';
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const session = useSyncExternalStore(
    subscribeToSession,
    getSessionSnapshot,
    () => SERVER_SNAPSHOT,
  );
  const logout = useLogout();

  useEffect(() => {
    void bootstrapSession();
  }, []);

  // A rejected request that survived the refresh means the session is really
  // gone; every screen relies on this one listener rather than redirecting
  // from inside its own error handler.
  useEffect(() => onUnauthenticated(() => router.replace('/login')), [router]);

  useEffect(() => {
    if (session.status !== 'anonymous') return;
    const target = pathname && pathname !== '/' ? `?redirect=${encodeURIComponent(pathname)}` : '';
    router.replace(`/login${target}`);
  }, [session.status, pathname, router]);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setSidebarOpen(false);
  }, [pathname]);

  const meQuery = useMe(session.status === 'authenticated' && !session.user);
  useEffect(() => {
    if (meQuery.data) setCurrentUser(meQuery.data);
  }, [meQuery.data]);

  const handleSignOut = useCallback(() => {
    logout.mutate(undefined, {
      onSettled: () => router.replace('/login'),
    });
  }, [logout, router]);

  if (session.status !== 'authenticated') {
    return (
      <div className={styles.bootScreen}>
        <div className={styles.bootInner} aria-busy="true">
          <Spinner size="md" label={null} />
          <p>{session.status === 'anonymous' ? 'Redirecting to sign in…' : 'Restoring session…'}</p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.shell}>
      {sidebarOpen ? (
        <button
          type="button"
          className={styles.scrim}
          aria-label="Close navigation"
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}

      <Sidebar
        id={SIDEBAR_ID}
        open={sidebarOpen}
        role={session.user?.role ?? null}
        onNavigate={() => setSidebarOpen(false)}
      />

      <div className={styles.main}>
        <Header
          user={session.user}
          sidebarId={SIDEBAR_ID}
          sidebarOpen={sidebarOpen}
          onToggleSidebar={() => setSidebarOpen((open) => !open)}
          onSignOut={handleSignOut}
          signingOut={logout.isPending}
        />
        {children}
      </div>
    </div>
  );
}
