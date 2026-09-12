'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { formatInteger } from '@/lib/format';
import styles from './charts.module.css';
import { useGrowIn } from './useGrowIn';

export interface BarListItem {
  key: string;
  label: string;
  value: number;
  /** Text shown at the bar's tip; defaults to the integer value. */
  display?: string;
  /** CSS colour for the bar. Defaults to the single series hue. */
  color?: string;
  icon?: ReactNode;
  href?: string;
}

export interface BarListProps {
  items: readonly BarListItem[];
  /** Scale maximum; defaults to the largest value. */
  max?: number;
  label: string;
  empty?: ReactNode;
  /** Maximum width of the label column (CSS length). Long names need more. */
  labelWidth?: string;
}

/**
 * Horizontal bars with the label and the value printed on every row.
 *
 * Because every value is already visible as text, the list is its own table
 * view: a screen reader reads "label, value" per row and the bar is hidden
 * from it. One hue for nominal categories (a value-ramp on unordered
 * categories would double-encode length as colour).
 */
export function BarList({ items, max, label, empty, labelWidth }: BarListProps) {
  const ref = useGrowIn<HTMLUListElement>([items.length]);
  const top = max ?? Math.max(1, ...items.map((item) => item.value));

  if (items.length === 0) {
    return <p className={styles.empty}>{empty ?? 'Nothing to show yet.'}</p>;
  }

  return (
    <ul
      className={styles.barList}
      ref={ref}
      aria-label={label}
      style={labelWidth ? ({ '--bar-label-width': labelWidth } as React.CSSProperties) : undefined}
    >
      {items.map((item) => {
        const text = item.display ?? formatInteger(item.value);
        const labelNode = (
          <span className={styles.barLabel}>
            {item.icon}
            <span className={styles.barLabelText} title={item.label}>
              {item.label}
            </span>
          </span>
        );
        return (
          <li key={item.key} className={styles.barRow}>
            {item.href ? (
              <Link href={item.href} style={{ minWidth: 0 }}>
                {labelNode}
              </Link>
            ) : (
              labelNode
            )}
            <span className={styles.barTrack} aria-hidden="true">
              <span
                className={styles.barFill}
                data-grow="x"
                style={
                  {
                    width: `${Math.max(0, Math.min(1, item.value / top)) * 100}%`,
                    '--bar-color': item.color,
                  } as React.CSSProperties
                }
              />
            </span>
            <span className={styles.barValue}>{text}</span>
          </li>
        );
      })}
    </ul>
  );
}
