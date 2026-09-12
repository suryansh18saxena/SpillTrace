'use client';

import Link from 'next/link';
import { useCallback, useId, useRef, useState } from 'react';
import { Badge } from '@/components/ui/Badge';
import {
  IconChevronDown,
  IconCommand,
  IconHelp,
  IconLogout,
  IconSparkle,
} from '@/components/ui/Icons';
import type { User } from '@/lib/api/types';
import { requestPalette, requestTour } from '@/lib/preferences';
import styles from './shell.module.css';
import { useDismiss } from './useDismiss';

export interface UserMenuProps {
  user: User | null;
  onSignOut: () => void;
  signingOut: boolean;
}

function initials(user: User | null): string {
  const source = user?.full_name?.trim() || user?.email || '?';
  const parts = source.split(/[\s@._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '?') + (parts[1]?.[0] ?? '')).toUpperCase();
}

export function UserMenu({ user, onSignOut, signingOut }: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, close, rootRef, triggerRef);

  const name = user?.full_name?.trim() || user?.email || 'Signed in';

  return (
    <div className={styles.popoverRoot} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className={styles.userButton}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        aria-label={`Account: ${name}`}
        onClick={() => setOpen((value) => !value)}
      >
        <span className={styles.avatar} aria-hidden="true">
          {initials(user)}
        </span>
        <span className={styles.userName} aria-hidden="true">
          <span className={styles.userNamePrimary}>{name}</span>
          <span className={styles.userNameRole}>{user?.role ?? ''}</span>
        </span>
        <IconChevronDown size={14} />
      </button>

      {open ? (
        <div className={styles.popover} id={panelId} role="dialog" aria-label="Account">
          <div className={styles.userCard}>
            <span className={`${styles.avatar} ${styles.avatarLg}`} aria-hidden="true">
              {initials(user)}
            </span>
            <span className={styles.userCardText}>
              <span className={styles.userCardName}>{name}</span>
              {user?.email ? <span className={styles.userCardEmail}>{user.email}</span> : null}
              {user?.role ? (
                <span style={{ display: 'block', marginTop: 'var(--space-1)' }}>
                  <Badge tone="accent">{user.role}</Badge>
                </span>
              ) : null}
            </span>
          </div>
          <div className={styles.menuList}>
            <button
              type="button"
              className={styles.menuItem}
              onClick={() => {
                close();
                requestTour();
              }}
            >
              <IconSparkle size={16} /> Take the product tour
            </button>
            <button
              type="button"
              className={styles.menuItem}
              onClick={() => {
                close();
                requestPalette();
              }}
            >
              <IconCommand size={16} /> Search and jump
              <span className={styles.menuItemEnd}>
                <kbd>Ctrl</kbd> <kbd>K</kbd>
              </span>
            </button>
            <Link href="/help" className={styles.menuItem} onClick={close}>
              <IconHelp size={16} /> How to read this
            </Link>
            <div className={styles.menuDivider} />
            <button
              type="button"
              className={styles.menuItem}
              onClick={() => {
                close();
                onSignOut();
              }}
              disabled={signingOut}
            >
              <IconLogout size={16} /> {signingOut ? 'Signing out…' : 'Sign out'}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
