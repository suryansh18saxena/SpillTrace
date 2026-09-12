'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useLayoutEffect, useRef } from 'react';
import { RadarMark } from '@/components/brand/RadarMark';
import { IconChevronLeft } from '@/components/ui/Icons';
import { useSystemProviders } from '@/lib/api/hooks';
import type { UserRole } from '@/lib/api/types';
import { APP_NAME, APP_TAGLINE } from '@/lib/config';
import { cx } from '@/lib/cx';
import { gsap, prefersReducedMotion } from '@/lib/motion/gsap';
import { isNavItemActive, navGroupsForRole } from './nav';
import styles from './layout.module.css';

export interface SidebarProps {
  open: boolean;
  onNavigate: () => void;
  role: UserRole | null;
  /** Desktop icon-rail mode. */
  collapsed?: boolean;
  onToggleCollapsed?: () => void;
  /** Id of the element that labels the drawer when it is open on mobile. */
  id?: string;
}

/**
 * Which adapters are live, as one honest chip (CON-009).
 *
 * `/system/providers` is readable by every signed-in user precisely so an
 * analyst can always tell whether the data in front of them is synthetic.
 */
function DataModeChip({ collapsed }: { collapsed: boolean }) {
  const providers = useSystemProviders();
  const data = providers.data;
  const synthetic = data?.any_synthetic ?? data?.providers.some((p) => p.mode !== 'REAL');
  const label = !data
    ? 'Checking sources…'
    : synthetic
      ? 'Synthetic data in use'
      : 'Live providers';
  const detail = !data
    ? 'Resolving which adapter backs each data source.'
    : synthetic
      ? 'At least one data source runs on deterministic synthetic data. Every such result is labelled SYNTHETIC.'
      : 'Every data source is backed by a real provider.';

  return (
    <div
      className={cx(styles.modeChip, synthetic ? styles.modeSynthetic : styles.modeLive)}
      title={detail}
      data-tour="data-mode"
    >
      <span className={styles.modeDot} aria-hidden="true" />
      <span className={cx(styles.modeText, collapsed && 'sr-only')}>
        <span className={styles.modeLabel}>{label}</span>
        {data ? (
          <span className={styles.modeMeta}>
            {data.providers.length} source{data.providers.length === 1 ? '' : 's'} ·{' '}
            {data.providers.filter((p) => p.mode === 'REAL').length} real
          </span>
        ) : null}
      </span>
    </div>
  );
}

export function Sidebar({
  open,
  onNavigate,
  role,
  collapsed = false,
  onToggleCollapsed,
  id = 'app-sidebar',
}: SidebarProps) {
  const pathname = usePathname() ?? '';
  const groups = navGroupsForRole(role);
  const listRef = useRef<HTMLDivElement | null>(null);
  const indicatorRef = useRef<HTMLSpanElement | null>(null);
  const placedRef = useRef(false);

  // The active pill glides to whichever link is current. Measured from the DOM
  // (not computed from indexes) so it is right whatever the groups contain.
  useLayoutEffect(() => {
    const list = listRef.current;
    const indicator = indicatorRef.current;
    if (!list || !indicator) return;

    const place = (animate: boolean) => {
      const active = list.querySelector<HTMLElement>('[aria-current="page"]');
      if (!active) {
        gsap.to(indicator, { autoAlpha: 0, duration: 0.2 });
        return;
      }
      const vars = {
        y: active.offsetTop,
        height: active.offsetHeight,
        autoAlpha: 1,
      };
      if (!animate || prefersReducedMotion()) gsap.set(indicator, vars);
      else gsap.to(indicator, { ...vars, duration: 0.55, ease: 'expo.out' });
    };

    place(placedRef.current);
    placedRef.current = true;

    // Re-measure when the rail collapses/expands or fonts settle.
    const observer = new ResizeObserver(() => place(false));
    observer.observe(list);
    return () => observer.disconnect();
  }, [pathname, collapsed, groups.length]);

  return (
    <nav
      id={id}
      aria-label="Primary"
      data-tour="sidebar"
      className={cx(
        styles.sidebar,
        open && styles.sidebarOpen,
        collapsed && styles.sidebarCollapsed,
      )}
    >
      <Link href="/dashboard" className={styles.brand} onClick={onNavigate}>
        <span className={styles.brandMark}>
          <RadarMark size={30} />
        </span>
        <span className={styles.brandText}>
          <span className={styles.brandName}>{APP_NAME}</span>
          <span className={styles.brandTagline}>{APP_TAGLINE}</span>
        </span>
      </Link>

      <div className={styles.navScroll} ref={listRef}>
        <span className={styles.navIndicator} ref={indicatorRef} aria-hidden="true" />
        {groups.map((group) => (
          <div className={styles.navGroup} key={group.heading}>
            <h2 className={styles.navHeading}>{group.heading}</h2>
            {group.items.map((item) => {
              const active = isNavItemActive(pathname, item);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? 'page' : undefined}
                  title={collapsed ? item.label : undefined}
                  data-tour={item.href === '/help' ? 'help' : undefined}
                  className={cx(styles.navLink, active && styles.navLinkActive)}
                >
                  <span className={styles.navIcon}>{item.icon(17)}</span>
                  <span className={styles.navLabel}>{item.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </div>

      <div className={styles.sidebarFooter}>
        <DataModeChip collapsed={collapsed} />
        {collapsed ? null : (
          <p className={styles.provenanceNote}>
            Results are investigative and probabilistic. Rankings identify candidate vessels for
            further enquiry and never establish responsibility.
          </p>
        )}
        {onToggleCollapsed ? (
          <button
            type="button"
            className={styles.collapseButton}
            onClick={onToggleCollapsed}
            aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
            aria-pressed={collapsed}
          >
            <IconChevronLeft size={15} />
            <span className={styles.navLabel}>Collapse</span>
          </button>
        ) : null}
      </div>
    </nav>
  );
}
