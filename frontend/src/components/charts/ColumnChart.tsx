'use client';

import { useState } from 'react';
import { cx } from '@/lib/cx';
import { formatInteger } from '@/lib/format';
import styles from './charts.module.css';
import { useElementWidth } from './useElementWidth';
import { useGrowIn } from './useGrowIn';

export interface ColumnDatum {
  key: string;
  /** X-axis tick text. */
  label: string;
  value: number;
  /** Longer label for the tooltip, e.g. "Week of 4 Aug 2026". */
  detail?: string;
}

export interface ColumnChartProps {
  data: readonly ColumnDatum[];
  /** Accessible summary of what the chart shows. */
  label: string;
  /** Unit word for the tooltip: "cases", "detections". */
  unit?: string;
  height?: number;
  /** Text for the tooltip value; defaults to an integer. */
  format?: (value: number) => string;
}

/** 0, 1, 2 … or 0, 5, 10 … — clean integer steps that cover `max`. */
function niceTicks(max: number, count = 4): number[] {
  if (max <= 0) return [0, 1];
  const raw = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? raw;
  const niceStep = Math.max(1, Math.ceil(step));
  const ticks: number[] = [];
  for (let v = 0; v <= max + niceStep * 0.001; v += niceStep) ticks.push(v);
  if (ticks[ticks.length - 1]! < max) ticks.push(ticks[ticks.length - 1]! + niceStep);
  return ticks;
}

const PAD = { top: 18, right: 8, bottom: 26, left: 32 };

/**
 * A single-series column chart for counts over time.
 *
 * One hue, columns capped at 24 px, 4 px rounded caps squared at the baseline,
 * hairline grid. Only the tallest column is direct-labelled; every other value
 * is reachable by hover, by keyboard focus (each column is a focusable mark)
 * and in the frame's table view.
 */
export function ColumnChart({
  data,
  label,
  unit = '',
  height = 200,
  format = (value) => formatInteger(value),
}: ColumnChartProps) {
  const { ref: wrapRef, width } = useElementWidth<HTMLDivElement>();
  const svgRef = useGrowIn<SVGSVGElement>([data.length, width]);
  const [active, setActive] = useState<number | null>(null);

  const max = Math.max(0, ...data.map((d) => d.value));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1] ?? 1;
  const plotW = Math.max(40, width - PAD.left - PAD.right);
  const plotH = height - PAD.top - PAD.bottom;
  const band = data.length ? plotW / data.length : plotW;
  const colW = Math.min(24, Math.max(4, band * 0.62));
  const y = (value: number) => PAD.top + plotH - (value / top) * plotH;
  const labelEvery = Math.max(1, Math.ceil(data.length / Math.max(1, Math.floor(plotW / 56))));
  const maxIndex = data.findIndex((d) => d.value === max && max > 0);

  const activeDatum = active === null ? null : data[active];

  return (
    <div className={styles.columnWrap} ref={wrapRef}>
      <svg
        ref={svgRef}
        className={styles.columnSvg}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label={label}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              className={tick === 0 ? styles.axisLine : styles.gridLine}
              x1={PAD.left}
              x2={width - PAD.right}
              y1={y(tick)}
              y2={y(tick)}
            />
            <text className={styles.axisText} x={PAD.left - 8} y={y(tick) + 3} textAnchor="end">
              {formatInteger(tick)}
            </text>
          </g>
        ))}

        {data.map((datum, index) => {
          const cx0 = PAD.left + band * index + band / 2;
          const h = Math.max(0, (datum.value / top) * plotH);
          const r = Math.min(4, colW / 2, h);
          const x0 = cx0 - colW / 2;
          const yTop = PAD.top + plotH - h;
          // Rounded data-end, square at the baseline.
          const path =
            h <= 0
              ? ''
              : `M${x0},${PAD.top + plotH} V${yTop + r} Q${x0},${yTop} ${x0 + r},${yTop} H${x0 + colW - r} Q${x0 + colW},${yTop} ${x0 + colW},${yTop + r} V${PAD.top + plotH} Z`;
          return (
            <g key={datum.key}>
              {path ? (
                <path
                  d={path}
                  data-grow="y"
                  className={cx(styles.column, active === index && styles.columnActive)}
                  style={{ transformBox: 'fill-box', transformOrigin: 'bottom' }}
                />
              ) : null}
              {index === maxIndex ? (
                <text className={styles.columnLabel} x={cx0} y={yTop - 6} textAnchor="middle">
                  {format(datum.value)}
                </text>
              ) : null}
              {index % labelEvery === 0 ? (
                <text
                  className={styles.axisText}
                  x={cx0}
                  y={height - PAD.bottom + 16}
                  textAnchor="middle"
                >
                  {datum.label}
                </text>
              ) : null}
              {/* Hit target: the whole band, not just the mark. */}
              <rect
                className={styles.columnHit}
                x={PAD.left + band * index}
                y={PAD.top}
                width={band}
                height={plotH}
                tabIndex={0}
                aria-label={`${datum.detail ?? datum.label}: ${format(datum.value)} ${unit}`.trim()}
                onPointerEnter={() => setActive(index)}
                onPointerLeave={() => setActive(null)}
                onFocus={() => setActive(index)}
                onBlur={() => setActive(null)}
              />
            </g>
          );
        })}
      </svg>

      {activeDatum && active !== null ? (
        <div
          className={styles.tooltip}
          style={{
            left: PAD.left + band * active + band / 2,
            top: y(activeDatum.value),
          }}
          aria-hidden="true"
        >
          <span className={styles.tooltipLabel}>{activeDatum.detail ?? activeDatum.label}</span>
          <span className={styles.tooltipValue}>
            {format(activeDatum.value)} {unit}
          </span>
        </div>
      ) : null}
    </div>
  );
}
