'use client';

import { formatInteger, formatPercent } from '@/lib/format';
import styles from './charts.module.css';
import { useGrowIn } from './useGrowIn';

export interface Segment {
  key: string;
  label: string;
  value: number;
  /** CSS colour — an ordinal ramp step or a status token, never a guess. */
  color: string;
}

export interface SegmentBarProps {
  segments: readonly Segment[];
  label: string;
  /** Hide zero-valued segments from the bar (they stay in the legend). */
  hideEmpty?: boolean;
}

/**
 * Part-to-whole in one horizontal bar (≤ 6 parts), separated by 2 px surface
 * gaps. The legend always prints each part's count and share, so identity
 * never rests on colour and the legend doubles as the table view.
 */
export function SegmentBar({ segments, label, hideEmpty = true }: SegmentBarProps) {
  const total = segments.reduce((sum, segment) => sum + Math.max(0, segment.value), 0);
  const ref = useGrowIn<HTMLDivElement>([total, segments.length]);
  const visible = segments.filter((segment) => !hideEmpty || segment.value > 0);

  return (
    <div ref={ref}>
      <div className={styles.segmentBar} aria-hidden="true">
        {total > 0
          ? visible.map((segment) => (
              <span
                key={segment.key}
                className={styles.segment}
                data-grow="x"
                style={
                  {
                    width: `${(segment.value / total) * 100}%`,
                    '--segment-color': segment.color,
                  } as React.CSSProperties
                }
                title={`${segment.label}: ${formatInteger(segment.value)}`}
              />
            ))
          : null}
      </div>
      <ul className={styles.legend} aria-label={label}>
        {segments.map((segment) => (
          <li
            key={segment.key}
            className={styles.legendItem}
            style={{ '--segment-color': segment.color } as React.CSSProperties}
          >
            <span className={styles.legendSwatch} aria-hidden="true" />
            {segment.label}
            <span className={styles.legendValue}>{formatInteger(segment.value)}</span>
            <span>({total > 0 ? formatPercent(segment.value / total) : '0%'})</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
