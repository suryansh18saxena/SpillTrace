'use client';

import { useState, type ReactNode } from 'react';
import { Card } from '@/components/ui/Card';
import styles from './charts.module.css';

export interface ChartTable {
  caption: string;
  columns: string[];
  rows: Array<Array<string | number>>;
}

export interface ChartFrameProps {
  title: ReactNode;
  subtitle?: ReactNode;
  /** The chart's table-view twin. Every chart has one (WCAG-clean equivalent). */
  table?: ChartTable;
  foot?: ReactNode;
  className?: string;
  children: ReactNode;
}

/**
 * A card that holds one chart, with a Chart / Table switch.
 *
 * The table view is not an afterthought: a tooltip must never be the only way
 * to read a value, so every chart ships the same numbers as a plain table.
 */
export function ChartFrame({ title, subtitle, table, foot, className, children }: ChartFrameProps) {
  const [view, setView] = useState<'chart' | 'table'>('chart');

  return (
    <Card className={className}>
      <div className={styles.chartCard}>
        <div className={styles.chartHead}>
          <div>
            <h2 className={styles.chartTitle}>{title}</h2>
            {subtitle ? <p className={styles.chartSubtitle}>{subtitle}</p> : null}
          </div>
          {table ? (
            <div className={styles.viewToggle} role="group" aria-label="Display as">
              <button
                type="button"
                aria-pressed={view === 'chart'}
                onClick={() => setView('chart')}
              >
                Chart
              </button>
              <button
                type="button"
                aria-pressed={view === 'table'}
                onClick={() => setView('table')}
              >
                Table
              </button>
            </div>
          ) : null}
        </div>

        {view === 'table' && table ? (
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.dataTable}>
              <caption className="sr-only">{table.caption}</caption>
              <thead>
                <tr>
                  {table.columns.map((column) => (
                    <th key={column} scope="col">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row, index) => (
                  <tr key={index}>
                    {row.map((cell, cellIndex) => (
                      <td key={cellIndex}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          children
        )}

        {foot ? <p className={styles.chartFoot}>{foot}</p> : null}
      </div>
    </Card>
  );
}
