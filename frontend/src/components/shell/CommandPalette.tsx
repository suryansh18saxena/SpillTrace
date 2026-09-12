'use client';

import { useRouter } from 'next/navigation';
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react';
import { navGroupsForRole } from '@/components/layout/nav';
import {
  IconArrowRight,
  IconCases,
  IconMoon,
  IconPlus,
  IconSearch,
  IconSparkle,
} from '@/components/ui/Icons';
import { useCases } from '@/lib/api/hooks';
import type { UserRole } from '@/lib/api/types';
import { cx } from '@/lib/cx';
import { humanizeIdentifier, truncateId } from '@/lib/format';
import { OPEN_PALETTE_EVENT, requestTour } from '@/lib/preferences';
import { toggleThemeWithTransition } from '@/lib/themeTransition';
import styles from './shell.module.css';

interface PaletteItem {
  id: string;
  group: 'Actions' | 'Pages' | 'Cases';
  label: string;
  description: string;
  icon: ReactNode;
  keywords?: string;
  run: () => void;
}

function matches(item: PaletteItem, query: string): boolean {
  if (!query) return true;
  const haystack = `${item.label} ${item.description} ${item.keywords ?? ''}`.toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((term) => haystack.includes(term));
}

/**
 * ⌘K / Ctrl+K from anywhere in the app: jump to a screen, open a case by
 * title, or run a quick action.
 *
 * Built on the native `<dialog>` in modal mode, so focus containment, the
 * inert background and Escape-to-close come from the platform. The list is an
 * ARIA listbox driven by `aria-activedescendant`, so the text input keeps
 * focus while the arrow keys move the selection.
 */
export function CommandPalette({ role }: { role: UserRole | null }) {
  const router = useRouter();
  const dialogRef = useRef<HTMLDialogElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');
  const [active, setActive] = useState(0);
  const listId = useId();

  // Global shortcut and the programmatic "open" event.
  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setOpen((value) => !value);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener('keydown', onKey);
    window.addEventListener(OPEN_PALETTE_EVENT, onOpen);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener(OPEN_PALETTE_EVENT, onOpen);
    };
  }, []);

  useEffect(() => {
    const node = dialogRef.current;
    if (!node || typeof node.showModal !== 'function') return;
    if (open && !node.open) {
      node.showModal();
      setQuery('');
      setDebounced('');
      setActive(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
    if (!open && node.open) node.close();
  }, [open]);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 180);
    return () => clearTimeout(timer);
  }, [query]);

  const casesQuery = useCases(
    { limit: 6, offset: 0, ...(debounced ? { q: debounced } : {}) },
    { enabled: open },
  );

  const close = useCallback(() => setOpen(false), []);
  const go = useCallback(
    (href: string) => {
      close();
      router.push(href);
    },
    [close, router],
  );

  const items = useMemo<PaletteItem[]>(() => {
    const actions: PaletteItem[] = [
      {
        id: 'action:new-case',
        group: 'Actions',
        label: 'Create a new case',
        description: 'Draw an area of interest and pin it to a time window.',
        icon: <IconPlus size={16} />,
        keywords: 'new open start',
        run: () => go('/cases/new'),
      },
      {
        id: 'action:theme',
        group: 'Actions',
        label: 'Toggle light / dark theme',
        description: 'Switch the display theme.',
        icon: <IconMoon size={16} />,
        keywords: 'dark light mode appearance',
        run: () => {
          close();
          toggleThemeWithTransition();
        },
      },
      {
        id: 'action:tour',
        group: 'Actions',
        label: 'Take the product tour',
        description: 'A five-step walkthrough of the workspace.',
        icon: <IconSparkle size={16} />,
        keywords: 'onboarding guide walkthrough help',
        run: () => {
          close();
          requestTour();
        },
      },
    ];

    const pages: PaletteItem[] = navGroupsForRole(role).flatMap((group) =>
      group.items.map((item) => ({
        id: `page:${item.href}`,
        group: 'Pages' as const,
        label: item.label,
        description: item.description,
        icon: item.icon(16),
        keywords: `${group.heading} ${item.keywords ?? ''}`,
        run: () => go(item.href),
      })),
    );

    const cases: PaletteItem[] = (casesQuery.data?.items ?? []).map((item) => ({
      id: `case:${item.id}`,
      group: 'Cases' as const,
      label: item.title,
      description: `${item.case_ref ?? truncateId(item.id, 8, 4)} · ${humanizeIdentifier(item.status)}`,
      icon: <IconCases size={16} />,
      run: () => go(`/cases/${item.id}`),
    }));

    const q = query.trim();
    // Cases are already filtered server-side by the same query.
    return [
      ...pages.filter((item) => matches(item, q)),
      ...cases,
      ...actions.filter((item) => matches(item, q)),
    ];
  }, [role, casesQuery.data, query, go, close]);

  useEffect(() => {
    setActive((index) => Math.min(index, Math.max(items.length - 1, 0)));
  }, [items.length]);

  useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`);
    node?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActive((index) => (items.length ? (index + 1) % items.length : 0));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActive((index) => (items.length ? (index - 1 + items.length) % items.length : 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      items[active]?.run();
    }
  };

  let lastGroup: string | null = null;

  return (
    <dialog
      ref={dialogRef}
      className={styles.palette}
      aria-label="Search and jump"
      onClose={() => setOpen(false)}
      onCancel={() => setOpen(false)}
      onClick={(event) => {
        // A click on the backdrop lands on the <dialog> element itself.
        if (event.target === event.currentTarget) close();
      }}
    >
      {open ? (
        <>
          <div className={styles.paletteSearch}>
            <IconSearch size={18} />
            <input
              ref={inputRef}
              className={styles.paletteInput}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
              placeholder="Search cases, screens and actions…"
              role="combobox"
              aria-expanded="true"
              aria-controls={listId}
              aria-activedescendant={items[active] ? `${listId}-${active}` : undefined}
              aria-autocomplete="list"
              spellCheck={false}
            />
            <kbd>Esc</kbd>
          </div>

          <div className={styles.paletteResults} ref={listRef} id={listId} role="listbox">
            {items.length === 0 ? (
              <p className={styles.paletteEmpty}>
                {casesQuery.isFetching ? 'Searching…' : `Nothing matches “${query}”.`}
              </p>
            ) : (
              items.map((item, index) => {
                const showGroup = item.group !== lastGroup;
                lastGroup = item.group;
                return (
                  <div key={item.id}>
                    {showGroup ? (
                      <p className={styles.paletteGroup} aria-hidden="true">
                        {item.group}
                      </p>
                    ) : null}
                    <div
                      id={`${listId}-${index}`}
                      role="option"
                      aria-selected={index === active}
                      data-index={index}
                      className={cx(
                        styles.paletteItem,
                        index === active && styles.paletteItemActive,
                      )}
                      onPointerMove={() => setActive(index)}
                      onClick={() => item.run()}
                    >
                      <span className={styles.paletteIcon}>{item.icon}</span>
                      <span style={{ minWidth: 0 }}>
                        <span className={styles.paletteLabel}>{item.label}</span>
                        <span className={styles.paletteDescription}>{item.description}</span>
                      </span>
                      <span className={styles.paletteHint} aria-hidden="true">
                        <IconArrowRight size={15} />
                      </span>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          <div className={styles.paletteFooter} aria-hidden="true">
            <span>
              <kbd>↑</kbd>
              <kbd>↓</kbd> navigate
            </span>
            <span>
              <kbd>↵</kbd> open
            </span>
            <span>
              <kbd>Esc</kbd> close
            </span>
          </div>
        </>
      ) : null}
    </dialog>
  );
}
