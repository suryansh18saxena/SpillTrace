'use client';

import { Button } from '@/components/ui/Button';
import { IconLogout, IconMenu } from '@/components/ui/Icons';
import type { User } from '@/lib/api/types';
import { Breadcrumbs } from './Breadcrumbs';
import { ThemeToggle } from './ThemeToggle';
import styles from './layout.module.css';

export interface HeaderProps {
  user: User | null;
  sidebarId: string;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  onSignOut: () => void;
  signingOut: boolean;
}

export function Header({
  user,
  sidebarId,
  sidebarOpen,
  onToggleSidebar,
  onSignOut,
  signingOut,
}: HeaderProps) {
  return (
    <header className={styles.header}>
      <Button
        variant="ghost"
        size="sm"
        iconOnly
        className={styles.menuButton}
        aria-label={sidebarOpen ? 'Close navigation' : 'Open navigation'}
        aria-expanded={sidebarOpen}
        aria-controls={sidebarId}
        onClick={onToggleSidebar}
      >
        <IconMenu size={18} />
      </Button>

      <Breadcrumbs />
      <div className={styles.headerSpacer} />

      <div className={styles.headerActions}>
        {user ? (
          <span className={styles.userChip}>
            <span className={styles.userEmail} title={user.email}>
              {user.full_name || user.email}
            </span>
            <span className={styles.userRole}>{user.role}</span>
          </span>
        ) : null}
        <ThemeToggle />
        <Button
          variant="ghost"
          size="sm"
          onClick={onSignOut}
          loading={signingOut}
          loadingLabel="Signing out"
          leadingIcon={<IconLogout size={15} />}
        >
          Sign out
        </Button>
      </div>
    </header>
  );
}
