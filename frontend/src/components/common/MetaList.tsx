import type { ReactNode } from 'react';
import { cx } from '@/lib/cx';
import { EMPTY_VALUE } from '@/lib/format';
import styles from './common.module.css';

export interface MetaEntry {
  /** Stable key; also the fallback label. */
  key: string;
  term: ReactNode;
  value: ReactNode;
  /** Monospace the value — ids, checksums, coordinates, counts. */
  mono?: boolean;
  /** One line of context under the value. */
  hint?: ReactNode;
  /** Span the whole row — for long values such as a time window. */
  wide?: boolean;
}

export interface MetaListProps {
  entries: ReadonlyArray<MetaEntry | null | false | undefined>;
  dense?: boolean;
  className?: string;
}

/**
 * A `<dl>` of labelled facts.
 *
 * A real description list rather than a grid of `<span>`s: screen readers
 * announce "term, definition" pairs, which is exactly what an analyst reading a
 * detection or a drift run needs. Falsy entries are dropped so callers can
 * inline conditions without building an array first.
 */
export function MetaList({ entries, dense = false, className }: MetaListProps) {
  const rows = entries.filter((entry): entry is MetaEntry => Boolean(entry));
  if (rows.length === 0) return null;

  return (
    <dl className={cx(styles.metaList, dense && styles.metaListDense, className)}>
      {rows.map((row) => (
        <div key={row.key} className={cx(styles.metaEntry, row.wide && styles.metaEntryWide)}>
          <dt className={styles.metaTerm}>{row.term}</dt>
          <dd className={cx(styles.metaDefinition, row.mono && styles.metaDefinitionMono)}>
            {row.value ?? EMPTY_VALUE}
          </dd>
          {row.hint ? <dd className={styles.metaHint}>{row.hint}</dd> : null}
        </div>
      ))}
    </dl>
  );
}

export interface ReadoutProps {
  label: ReactNode;
  value: ReactNode;
  caption?: ReactNode;
  className?: string;
}

/** A single prominent number with its label and a one-line caveat. */
export function Readout({ label, value, caption, className }: ReadoutProps) {
  return (
    <div className={cx(styles.readout, className)}>
      <p className={styles.readoutLabel}>{label}</p>
      <p className={styles.readoutValue}>{value}</p>
      {caption ? <p className={styles.readoutCaption}>{caption}</p> : null}
    </div>
  );
}

export interface ReadoutGridProps {
  children: ReactNode;
  className?: string;
}

export function ReadoutGrid({ children, className }: ReadoutGridProps) {
  return <div className={cx(styles.readoutGrid, className)}>{children}</div>;
}

/**
 * Renders "not evaluated" for a measurement that was never taken.
 *
 * An empty `metrics: {}` on a model version means no evaluation has been
 * recorded. Rendering that as `0%` would assert a measured failure that nobody
 * measured, so it is always words, never a number (A-06).
 */
export function Unmeasured({ children = 'No evaluation recorded' }: { children?: ReactNode }) {
  return <span className={styles.unmeasured}>{children}</span>;
}
