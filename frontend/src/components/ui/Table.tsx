'use client';

import type { ReactNode } from 'react';
import { cx } from '@/lib/cx';
import { Skeleton } from './Skeleton';
import styles from './ui.module.css';

export interface Column<T> {
  key: string;
  header: ReactNode;
  /** Right-align and tabular-nums — for every numeric column. */
  numeric?: boolean;
  /** Monospace — for MMSI, IMO, product ids, checksums, job ids. */
  mono?: boolean;
  width?: string;
  /** Header text that exists only for screen readers (e.g. an actions column). */
  headerHidden?: boolean;
  render: (row: T, index: number) => ReactNode;
}

export interface TableProps<T> {
  /** Always required: a table without a caption is unnavigable by screen reader. */
  caption: string;
  captionVisible?: boolean;
  columns: ReadonlyArray<Column<T>>;
  rows: readonly T[];
  getRowKey: (row: T, index: number) => string;
  loading?: boolean;
  skeletonRows?: number;
  /** Rendered in place of the body when set — pass an `<ErrorState />`. */
  error?: ReactNode;
  /** Rendered when there are no rows — pass an `<EmptyState />`. */
  empty?: ReactNode;
  className?: string;
}

/**
 * A dense data table with the four data states built in, so no screen has to
 * reinvent them (NFR-012): loading (skeleton rows that keep the column widths),
 * error, empty, and populated.
 */
export function Table<T>({
  caption,
  captionVisible = false,
  columns,
  rows,
  getRowKey,
  loading = false,
  skeletonRows = 5,
  error,
  empty,
  className,
}: TableProps<T>) {
  const showSkeleton = loading && rows.length === 0;
  const showError = Boolean(error) && !loading;
  const showEmpty = !loading && !error && rows.length === 0;

  // The error and empty states render *below* the table, outside its
  // horizontal scroll container: inside a wide table they would be laid out
  // across its full width and clipped on a phone.
  return (
    <div className={className}>
      <div className={styles.tableWrap}>
        <table className={styles.table} aria-busy={loading || undefined}>
          <caption className={captionVisible ? undefined : 'sr-only'}>{caption}</caption>
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={column.key}
                  scope="col"
                  style={column.width ? { width: column.width } : undefined}
                  className={cx(column.numeric && styles.cellNumeric)}
                >
                  <span className={column.headerHidden ? 'sr-only' : undefined}>
                    {column.header}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {showSkeleton
              ? Array.from({ length: skeletonRows }, (_, rowIndex) => (
                  <tr key={`skeleton-${rowIndex}`}>
                    {columns.map((column) => (
                      <td key={column.key}>
                        <Skeleton height="0.75rem" width={column.numeric ? '3rem' : '70%'} />
                      </td>
                    ))}
                  </tr>
                ))
              : null}

            {!showError &&
              rows.map((row, index) => (
                <tr key={getRowKey(row, index)}>
                  {columns.map((column) => (
                    <td
                      key={column.key}
                      className={cx(
                        column.numeric && styles.cellNumeric,
                        column.mono && styles.cellMono,
                      )}
                    >
                      {column.render(row, index)}
                    </td>
                  ))}
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      {showError ? <div className={styles.tableState}>{error}</div> : null}
      {showEmpty && empty ? <div className={styles.tableState}>{empty}</div> : null}
    </div>
  );
}
