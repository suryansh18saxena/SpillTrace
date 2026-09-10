'use client';

import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { Skeleton } from '@/components/ui/Skeleton';
import { Slider } from '@/components/ui/Slider';
import { Spinner } from '@/components/ui/Spinner';
import { cx } from '@/lib/cx';
import { formatInteger } from '@/lib/format';
import { cssVar } from './useMap';
import styles from './map.module.css';

export interface LayerPanelItem {
  id: string;
  title: string;
  /** Design-token name for the legend swatch, matching the map layer colour. */
  colorVar: string;
  colorFallback: string;
  visible: boolean;
  /** 0..1 — the analyst's per-layer opacity. */
  opacity: number;
  /** `null` while the layer's data is still loading. */
  featureCount?: number | null;
  loading?: boolean;
  /** Why the layer cannot be switched on — e.g. "no drift run yet". */
  disabledReason?: string | null;
  /** The server's caveat for this layer, rendered verbatim under the row. */
  notice?: string | null;
}

export interface LayerPanelProps {
  items: readonly LayerPanelItem[];
  onToggle: (id: string, visible: boolean) => void;
  onOpacityChange: (id: string, opacity: number) => void;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  className?: string;
}

/**
 * Layer switchboard built from the manifest the API returns.
 *
 * Every row is a real `<input type="checkbox">` with a real `<label>` plus a
 * native range input for opacity, so the whole panel is keyboard- and
 * screen-reader-navigable without any custom interaction code. A layer that has
 * no data yet is disabled with the reason stated, never silently missing, and a
 * layer the API attached a `notice` to shows that notice here — the caveat
 * travels with the layer rather than living in a help page.
 */
export function LayerPanel({
  items,
  onToggle,
  onOpacityChange,
  loading = false,
  error,
  onRetry,
  className,
}: LayerPanelProps) {
  if (error) {
    return (
      <ErrorState
        compact
        title="Layers unavailable"
        error={error}
        onRetry={onRetry}
        description="The layer manifest could not be loaded, so the map is showing the basemap only."
      />
    );
  }

  if (loading && items.length === 0) {
    return (
      <div className={cx(styles.layerPanel, className)} aria-busy="true">
        <span className="sr-only">Loading map layers</span>
        {Array.from({ length: 5 }, (_, index) => (
          <div key={index} className={styles.layerRow}>
            <Skeleton width="1rem" height="1rem" />
            <Skeleton width="60%" height="0.75rem" />
          </div>
        ))}
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        compact
        title="No layers yet"
        description="This case has not produced any map layers. Run the pipeline to generate the scene footprint, detection, origin region and vessel tracks."
      />
    );
  }

  return (
    <fieldset className={cx(styles.layerPanel, className)}>
      <legend className="sr-only">Map layers</legend>
      {items.map((item) => {
        const disabled = Boolean(item.disabledReason);
        const inputId = `layer-toggle-${item.id}`;
        const on = item.visible && !disabled;
        return (
          <div key={item.id} className={styles.layerRowStack}>
            <div className={styles.layerRow} style={{ padding: 0 }}>
              <input
                id={inputId}
                type="checkbox"
                className={styles.layerCheckbox}
                checked={on}
                disabled={disabled}
                onChange={(event) => onToggle(item.id, event.target.checked)}
              />
              <label
                htmlFor={inputId}
                className={cx(styles.layerLabel, disabled && styles.layerLabelDisabled)}
                title={item.disabledReason ?? undefined}
              >
                <span
                  className={styles.layerSwatch}
                  aria-hidden="true"
                  style={{ background: cssVar(item.colorVar, item.colorFallback) }}
                />
                <span className={styles.layerName}>{item.title}</span>
              </label>
              <span className={styles.layerMeta}>
                {item.loading ? (
                  <Spinner size="xs" label={`Loading ${item.title}`} />
                ) : disabled ? (
                  item.disabledReason
                ) : typeof item.featureCount === 'number' ? (
                  formatInteger(item.featureCount)
                ) : null}
              </span>
            </div>

            <Slider
              containerClassName={styles.layerOpacity}
              label={`${item.title} opacity`}
              labelHidden
              min={0}
              max={100}
              step={5}
              value={Math.round(item.opacity * 100)}
              disabled={disabled || !on}
              valueText={`${Math.round(item.opacity * 100)}%`}
              onChange={(event) => onOpacityChange(item.id, Number(event.target.value) / 100)}
            />

            {item.notice ? <p className={styles.layerNotice}>{item.notice}</p> : null}
          </div>
        );
      })}
    </fieldset>
  );
}
