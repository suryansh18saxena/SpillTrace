'use client';

import { useEffect, useRef } from 'react';
import { CommandPalette } from '@/components/shell/CommandPalette';
import { NotificationCenter } from '@/components/shell/NotificationCenter';
import { UserMenu } from '@/components/shell/UserMenu';
import shell from '@/components/shell/shell.module.css';
import { Button } from '@/components/ui/Button';
import { IconMenu, IconSearch } from '@/components/ui/Icons';
import type { User } from '@/lib/api/types';
import { requestPalette } from '@/lib/preferences';
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
  const headerRef = useRef<HTMLElement>(null);
  // Condense the bar once the page scrolls: one passive listener, one attribute.
  useEffect(() => {
    const el = headerRef.current;
    if (!el) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      el.dataset['condensed'] = window.scrollY > 24 ? 'true' : 'false';
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <header ref={headerRef} className={styles.header}>
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
        <button
          type="button"
          className={shell.searchTrigger}
          onClick={requestPalette}
          data-tour="search"
          aria-label="Search and jump (Ctrl K)"
        >
          <IconSearch size={15} />
          <span className={shell.searchTriggerText}>Search or jump to…</span>
          <span className={shell.searchKbd} aria-hidden="true">
            <kbd>Ctrl</kbd>
            <kbd>K</kbd>
          </span>
        </button>
        <NotificationCenter />
        <ThemeToggle />
        <span className={styles.headerDivider} aria-hidden="true" />
        <UserMenu user={user} onSignOut={onSignOut} signingOut={signingOut} />
      </div>

      <CommandPalette role={user?.role ?? null} />
    </header>
  );
}
