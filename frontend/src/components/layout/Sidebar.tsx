'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ReactNode } from 'react';
import { IconAdmin, IconCases, IconPlus, IconTarget } from '@/components/ui/Icons';
import { cx } from '@/lib/cx';
import { APP_NAME, APP_TAGLINE } from '@/lib/config';
import type { UserRole } from '@/lib/api/types';
import styles from './layout.module.css';

interface NavItem {
  href: string;
  label: string;
  icon: ReactNode;
  /** Only rendered for these roles; omitted means "everyone". */
  roles?: UserRole[];
  /** Active for the exact path only (otherwise prefix matching is used). */
  exact?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { href: '/cases', label: 'Cases', icon: <IconCases size={16} />, exact: true },
  { href: '/cases/new', label: 'New case', icon: <IconPlus size={16} />, exact: true },
  { href: '/admin', label: 'System status', icon: <IconAdmin size={16} />, roles: ['admin'] },
];

export interface SidebarProps {
  open: boolean;
  onNavigate: () => void;
  role: UserRole | null;
  /** Id of the element that labels the drawer when it is open on mobile. */
  id?: string;
}

function isActive(pathname: string, item: NavItem): boolean {
  if (item.exact) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

export function Sidebar({ open, onNavigate, role, id = 'app-sidebar' }: SidebarProps) {
  const pathname = usePathname() ?? '';
  const items = NAV_ITEMS.filter((item) => !item.roles || (role && item.roles.includes(role)));

  return (
    <nav
      id={id}
      aria-label="Primary"
      className={cx(styles.sidebar, open && styles.sidebarOpen)}
      // Hidden from the accessibility tree when the drawer is closed on small
      // screens is handled by CSS transform + the header's aria-expanded; the
      // links stay reachable on desktop where the sidebar is always visible.
    >
      <Link href="/cases" className={styles.brand} onClick={onNavigate}>
        <span className={styles.brandMark} aria-hidden="true">
          <IconTarget size={16} />
        </span>
        <span className={styles.brandText}>
          <span className={styles.brandName}>{APP_NAME}</span>
          <span className={styles.brandTagline}>{APP_TAGLINE}</span>
        </span>
      </Link>

      <div className={styles.navGroup}>
        <h2 className={styles.navHeading}>Investigations</h2>
        {items.map((item) => {
          const active = isActive(pathname, item);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              aria-current={active ? 'page' : undefined}
              className={cx(styles.navLink, active && styles.navLinkActive)}
            >
              <span className={styles.navIcon}>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </div>

      <div className={styles.sidebarFooter}>
        <p className={styles.provenanceNote}>
          Results are investigative and probabilistic. Rankings identify candidate vessels for
          further enquiry and never establish responsibility.
        </p>
      </div>
    </nav>
  );
}
