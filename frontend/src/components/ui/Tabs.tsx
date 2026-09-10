'use client';

import { useCallback, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { cx } from '@/lib/cx';
import styles from './ui.module.css';

export interface TabItem {
  id: string;
  label: ReactNode;
  /** Shown after the label in monospace — e.g. how many rows the panel holds. */
  count?: number | null;
  disabled?: boolean;
}

export interface TabsProps {
  /** Accessible name for the tab list, e.g. "Investigation sections". */
  label: string;
  items: readonly TabItem[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
}

export const tabId = (id: string) => `tab-${id}`;
export const tabPanelId = (id: string) => `tabpanel-${id}`;

/**
 * WAI-ARIA tabs with a roving tabindex: one Tab stop for the whole list, then
 * Left/Right/Home/End to move between tabs. Disabled tabs are skipped rather
 * than trapping the keyboard.
 */
export function Tabs({ label, items, value, onChange, className }: TabsProps) {
  const listRef = useRef<HTMLDivElement>(null);

  const focusTab = useCallback((id: string) => {
    const node = listRef.current?.querySelector<HTMLButtonElement>(`#${CSS.escape(tabId(id))}`);
    node?.focus();
  }, []);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      const enabled = items.filter((item) => !item.disabled);
      if (enabled.length === 0) return;
      const currentIndex = enabled.findIndex((item) => item.id === value);

      let nextIndex: number | null = null;
      switch (event.key) {
        case 'ArrowRight':
          nextIndex = (currentIndex + 1) % enabled.length;
          break;
        case 'ArrowLeft':
          nextIndex = (currentIndex - 1 + enabled.length) % enabled.length;
          break;
        case 'Home':
          nextIndex = 0;
          break;
        case 'End':
          nextIndex = enabled.length - 1;
          break;
        default:
          return;
      }

      event.preventDefault();
      const next = enabled[nextIndex];
      if (!next) return;
      onChange(next.id);
      focusTab(next.id);
    },
    [focusTab, items, onChange, value],
  );

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label={label}
      className={cx(styles.tabList, className)}
      onKeyDown={handleKeyDown}
    >
      {items.map((item) => {
        const selected = item.id === value;
        return (
          <button
            key={item.id}
            id={tabId(item.id)}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={tabPanelId(item.id)}
            tabIndex={selected ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onChange(item.id)}
            className={cx(styles.tab, selected && styles.tabSelected)}
          >
            {item.label}
            {typeof item.count === 'number' ? (
              <span className={styles.tabCount}>{item.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export interface TabPanelProps {
  id: string;
  active: boolean;
  className?: string;
  children: ReactNode;
}

export function TabPanel({ id, active, className, children }: TabPanelProps) {
  return (
    <div
      id={tabPanelId(id)}
      role="tabpanel"
      aria-labelledby={tabId(id)}
      hidden={!active}
      tabIndex={0}
      className={cx(styles.tabPanel, className)}
    >
      {active ? children : null}
    </div>
  );
}
