'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { IconGlobe, IconLayers } from '@/components/ui/Icons';
import { cx } from '@/lib/cx';
import { BASEMAPS, type BasemapId } from '@/lib/map/basemaps';
import styles from './map.module.css';

export interface BasemapControlProps {
  basemap: BasemapId;
  onBasemapChange: (id: BasemapId) => void;
  labels: boolean;
  onLabelsChange: (labels: boolean) => void;
  /** Globe projection toggle; omitted when the screen has no use for it. */
  globe?: boolean;
  onGlobeChange?: (globe: boolean) => void;
  /** Theme the map is rendered in — hides the reference map made for the other theme. */
  theme: 'dark' | 'light';
  /** Set when imagery could not be reached and the map fell back to Offline. */
  fallbackNotice?: string | null;
  className?: string;
}

/**
 * Basemap switcher rendered inside the map frame.
 *
 * A real `<fieldset>` of radio inputs: keyboard users move between basemaps
 * with the arrow keys and the choice is announced. The attribution for the
 * active basemap is shown by MapLibre's own attribution control, so this panel
 * only lists what each option is and where it comes from.
 */
export function BasemapControl({
  basemap,
  onBasemapChange,
  labels,
  onLabelsChange,
  globe,
  onGlobeChange,
  theme,
  fallbackNotice,
  className,
}: BasemapControlProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const groupId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const options = BASEMAPS.filter((item) => item.theme === null || item.theme === theme);
  const active = BASEMAPS.find((item) => item.id === basemap);

  return (
    <div ref={rootRef} className={cx(styles.basemapControl, className)}>
      <button
        type="button"
        className={cx(styles.basemapButton, open && styles.basemapButtonOpen)}
        aria-expanded={open}
        aria-controls={`${groupId}-panel`}
        onClick={() => setOpen((value) => !value)}
        title="Change basemap"
      >
        <IconLayers size={14} />
        <span>{active?.label ?? 'Basemap'}</span>
      </button>

      {open ? (
        <div id={`${groupId}-panel`} className={styles.basemapPanel}>
          <fieldset className={styles.basemapFieldset}>
            <legend className={styles.basemapLegend}>Basemap</legend>
            {options.map((item) => (
              <label
                key={item.id}
                className={cx(styles.basemapOption, item.id === basemap && styles.basemapOptionOn)}
                title={item.description}
              >
                <input
                  type="radio"
                  name={`${groupId}-basemap`}
                  value={item.id}
                  checked={item.id === basemap}
                  onChange={() => onBasemapChange(item.id)}
                />
                <span className={cx(styles.basemapSwatch, styles[`basemapSwatch_${item.id}`])} />
                <span className={styles.basemapOptionText}>
                  <span>{item.label}</span>
                  <span className={styles.basemapOptionMeta}>
                    {item.external ? 'Public tiles' : 'No external requests'}
                  </span>
                </span>
              </label>
            ))}
          </fieldset>

          {basemap === 'satellite' ? (
            <label className={styles.basemapToggle}>
              <input
                type="checkbox"
                checked={labels}
                onChange={(event) => onLabelsChange(event.target.checked)}
              />
              <span>Place names &amp; boundaries</span>
            </label>
          ) : null}

          {onGlobeChange ? (
            <label className={styles.basemapToggle}>
              <input
                type="checkbox"
                checked={Boolean(globe)}
                onChange={(event) => onGlobeChange(event.target.checked)}
              />
              <span className={styles.basemapToggleIcon}>
                <IconGlobe size={13} />
              </span>
              <span>Globe view</span>
            </label>
          ) : null}

          <p className={styles.basemapNote}>
            Imagery is context only. Every evidence layer is served by the SPILLTRACE API; the
            Offline basemap makes no request outside this origin.
          </p>
        </div>
      ) : null}

      {fallbackNotice ? (
        <p className={styles.basemapFallback} role="status">
          {fallbackNotice}
        </p>
      ) : null}
    </div>
  );
}
