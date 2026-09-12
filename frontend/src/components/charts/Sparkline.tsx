import styles from './charts.module.css';

export interface SparklineProps {
  values: readonly number[];
  label: string;
  width?: number;
  height?: number;
}

/** A tiny trend line with an end dot. Decorative beside a printed value. */
export function Sparkline({ values, label, width = 120, height = 32 }: SparklineProps) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  const points = values.map(
    (v, i) => [i * step, height - 4 - ((v - min) / span) * (height - 8)] as const,
  );
  const line = points
    .map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(' ');
  const area = `${line} L${width},${height} L0,${height} Z`;
  const last = points[points.length - 1]!;

  return (
    <svg
      className={styles.sparkline}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      <path className={styles.sparkArea} d={area} />
      <path className={styles.sparkLine} d={line} vectorEffect="non-scaling-stroke" />
      <circle className={styles.sparkDot} cx={last[0]} cy={last[1]} r={3.5} />
    </svg>
  );
}
