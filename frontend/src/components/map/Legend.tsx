'use client';

import { cx } from '@/lib/cx';
import { cssVar } from './useMap';
import styles from './map.module.css';

export interface LegendItem {
  id: string;
  title: string;
  colorVar: string;
  colorFallback: string;
  shape: 'polygon' | 'line' | 'point' | 'raster';
  /** One line explaining what the symbol means. */
  description?: string | null;
}

export interface LegendProps {
  items: readonly LegendItem[];
  /** A standing caveat shown under the symbols, e.g. the origin-region notice. */
  note?: string | null;
  className?: string;
}

/**
 * The map key.
 *
 * It lists only the layers that are actually switched on, so it always describes
 * what is on screen. Each entry carries a plain-language description because a
 * colour swatch alone cannot say that a purple region is a *probability* region
 * and not a discharge point (CON-008).
 */
export function Legend({ items, note, className }: LegendProps) {
  if (items.length === 0) return null;
  return (
    <div className={cx(styles.legend, className)} role="group" aria-label="Map legend">
      <span className={styles.legendTitle}>Legend</span>
      {items.map((item) => {
        const color = cssVar(item.colorVar, item.colorFallback);
        return (
          <span key={item.id} className={styles.legendItem} title={item.description ?? undefined}>
            <span
              aria-hidden="true"
              className={cx(
                styles.legendSwatch,
                item.shape === 'line' && styles.legendSwatchLine,
                item.shape === 'point' && styles.legendSwatchPoint,
              )}
              style={item.shape === 'line' ? { borderTopColor: color } : { background: color }}
            />
            <span>{item.title}</span>
          </span>
        );
      })}
      {note ? <span className={styles.legendNote}>{note}</span> : null}
    </div>
  );
}
