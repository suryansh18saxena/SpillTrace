import type { ReactNode } from 'react';
import {
  IconActivity,
  IconAdmin,
  IconCases,
  IconChart,
  IconCompare,
  IconCpu,
  IconDashboard,
  IconGlobe,
  IconHelp,
  IconPlus,
  IconShip,
} from '@/components/ui/Icons';
import type { UserRole } from '@/lib/api/types';

export interface NavItem {
  href: string;
  label: string;
  /** One line shown in the command palette. */
  description: string;
  icon: (size: number) => ReactNode;
  /** Only rendered for these roles; omitted means "everyone". */
  roles?: UserRole[];
  /** Custom active test; defaults to exact-or-prefix matching. */
  match?: (pathname: string) => boolean;
  /** Extra words the command palette should match on. */
  keywords?: string;
}

export interface NavGroup {
  heading: string;
  items: NavItem[];
}

/**
 * The single registry of top-level destinations.
 *
 * The sidebar, the command palette and the breadcrumbs all read from here, so a
 * page cannot be reachable from one and missing from another.
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    heading: 'Overview',
    items: [
      {
        href: '/dashboard',
        label: 'Dashboard',
        description: 'Key figures, recent cases and data-source status at a glance.',
        icon: (size) => <IconDashboard size={size} />,
        keywords: 'home overview kpi summary',
      },
      {
        href: '/map',
        label: 'Situational map',
        description: 'Every case area and detected slick on one operational map.',
        icon: (size) => <IconGlobe size={size} />,
        keywords: 'operations centre globe aoi regions',
      },
      {
        href: '/analytics',
        label: 'Analytics',
        description: 'Trends across cases: detections, verification outcomes, evidence strength.',
        icon: (size) => <IconChart size={size} />,
        keywords: 'charts insights trends statistics',
      },
    ],
  },
  {
    heading: 'Investigations',
    items: [
      {
        href: '/cases',
        label: 'Cases',
        description: 'Every investigation you can access.',
        icon: (size) => <IconCases size={size} />,
        match: (pathname) =>
          pathname === '/cases' ||
          (pathname.startsWith('/cases/') && !pathname.startsWith('/cases/new')),
        keywords: 'investigations list',
      },
      {
        href: '/cases/new',
        label: 'New case',
        description: 'Draw an area of interest and pin it to a time window.',
        icon: (size) => <IconPlus size={size} />,
        match: (pathname) => pathname === '/cases/new',
        keywords: 'create open start aoi',
      },
      {
        href: '/compare',
        label: 'Compare cases',
        description: 'Two investigations side by side, with shared vessels highlighted.',
        icon: (size) => <IconCompare size={size} />,
        keywords: 'side by side diff pattern',
      },
    ],
  },
  {
    heading: 'Intelligence',
    items: [
      {
        href: '/vessels',
        label: 'Vessel registry',
        description: 'Search every vessel observed across your cases by MMSI or name.',
        icon: (size) => <IconShip size={size} />,
        keywords: 'mmsi imo ship search fleet',
      },
      {
        href: '/activity',
        label: 'Activity feed',
        description: 'A timeline of every pipeline stage and case event.',
        icon: (size) => <IconActivity size={size} />,
        keywords: 'audit jobs timeline log events',
      },
    ],
  },
  {
    heading: 'System',
    items: [
      {
        href: '/ml-ops',
        label: 'ML Ops',
        description: 'Registered models, evaluation status and pipeline throughput.',
        icon: (size) => <IconCpu size={size} />,
        roles: ['admin'],
        keywords: 'models training metrics machine learning',
      },
      {
        href: '/admin',
        label: 'System status',
        description: 'Component health, data sources and recent jobs.',
        icon: (size) => <IconAdmin size={size} />,
        roles: ['admin'],
        keywords: 'health providers components admin',
      },
      {
        href: '/help',
        label: 'How to read this',
        description: 'What every score, band, contour and badge means — and what it does not.',
        icon: (size) => <IconHelp size={size} />,
        keywords: 'help guide glossary safeguards disclaimer con',
      },
    ],
  },
];

export function isNavItemActive(pathname: string, item: NavItem): boolean {
  if (item.match) return item.match(pathname);
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

export function navGroupsForRole(role: UserRole | null): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.roles || (role && item.roles.includes(role))),
  })).filter((group) => group.items.length > 0);
}

/** Flat label lookup for breadcrumbs: `/ml-ops` → "ML Ops". */
export const ROUTE_LABELS: Record<string, string> = Object.fromEntries(
  NAV_GROUPS.flatMap((group) => group.items).map((item) => [
    item.href.split('/').filter(Boolean).at(-1) ?? item.href,
    item.label,
  ]),
);
