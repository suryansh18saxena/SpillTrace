'use client';

import { usePathname } from 'next/navigation';
import Link from 'next/link';
import { cx } from '@/lib/cx';
import styles from '@/styles/pages.module.css';

export interface CaseSubNavProps {
  caseId: string;
  className?: string;
}

/**
 * "Walkthrough" sits first on purpose: it is the one section that assumes no
 * prior knowledge, and someone opening a case for the first time should land on
 * an explanation before a dashboard of measurements.
 */
const SECTIONS = [
  { segment: 'walkthrough', label: 'Walkthrough' },
  { segment: '', label: 'Map' },
  { segment: 'spill', label: 'Spill details' },
  { segment: 'drift', label: 'Drift & origin' },
  { segment: 'ranking', label: 'Vessel ranking' },
  { segment: 'report', label: 'Evidence report' },
];

/** The investigation's own tab bar, shared by every case-scoped screen. */
export function CaseSubNav({ caseId, className }: CaseSubNavProps) {
  const pathname = usePathname() ?? '';
  const base = `/cases/${caseId}`;

  return (
    <nav aria-label="Investigation sections" className={cx(styles.caseNav, className)}>
      {SECTIONS.map((section) => {
        const href = section.segment ? `${base}/${section.segment}` : base;
        const active = pathname === href;
        return (
          <Link
            key={section.label}
            href={href}
            aria-current={active ? 'page' : undefined}
            className={cx(styles.caseNavLink, active && styles.caseNavLinkActive)}
          >
            {section.label}
          </Link>
        );
      })}
    </nav>
  );
}
