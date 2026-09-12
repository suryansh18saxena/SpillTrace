'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Fragment } from 'react';
import { IconChevronRight } from '@/components/ui/Icons';
import { useCase } from '@/lib/api/hooks';
import { humanizeIdentifier, truncateId } from '@/lib/format';
import { ROUTE_LABELS } from './nav';
import styles from './layout.module.css';

interface Crumb {
  label: string;
  href?: string;
}

const STATIC_LABELS: Record<string, string> = {
  ...ROUTE_LABELS,
  walkthrough: 'Walkthrough',
  spill: 'Spill details',
  drift: 'Drift & origin',
  ranking: 'Vessel ranking',
  report: 'Evidence report',
};

/**
 * Breadcrumbs derived from the route.
 *
 * The case-id segment resolves to the case title through the *same* React Query
 * key the page uses, so this costs no extra request; before the case has loaded
 * it shows a truncated id rather than a spinner, because a breadcrumb that
 * changes height makes the whole header jump.
 */
export function Breadcrumbs() {
  const pathname = usePathname() ?? '/';
  const segments = pathname.split('/').filter(Boolean);

  const caseId =
    segments[0] === 'cases' && segments[1] && segments[1] !== 'new' ? segments[1] : undefined;
  const { data: caseData } = useCase(caseId, { enabled: Boolean(caseId) });

  const crumbs: Crumb[] = [];
  let href = '';
  for (const [index, segment] of segments.entries()) {
    href += `/${segment}`;
    if (segment === caseId) {
      crumbs.push({ label: caseData?.title ?? truncateId(caseId, 8, 4), href });
    } else if (segments[0] === 'vessels' && index === 1) {
      crumbs.push({ label: `Vessel ${truncateId(segment, 8, 4)}`, href });
    } else {
      crumbs.push({ label: STATIC_LABELS[segment] ?? humanizeIdentifier(segment), href });
    }
  }

  if (crumbs.length === 0) return null;

  return (
    <nav aria-label="Breadcrumb" className={styles.breadcrumbs}>
      <ol className={styles.breadcrumbList}>
        {crumbs.map((crumb, index) => {
          const isLast = index === crumbs.length - 1;
          return (
            <Fragment key={crumb.href ?? crumb.label}>
              <li className={styles.breadcrumbItem}>
                {isLast || !crumb.href ? (
                  <span className={styles.breadcrumbCurrent} aria-current="page">
                    {crumb.label}
                  </span>
                ) : (
                  <Link href={crumb.href} className={styles.breadcrumbLink}>
                    {crumb.label}
                  </Link>
                )}
              </li>
              {isLast ? null : (
                <li aria-hidden="true" className={styles.breadcrumbSeparator}>
                  <IconChevronRight size={12} />
                </li>
              )}
            </Fragment>
          );
        })}
      </ol>
    </nav>
  );
}
