'use client';

import { useMemo, useRef, useState, type ReactNode } from 'react';
import type { FeatureCollection } from 'geojson';
import { MapView, type MapDataLayer } from '@/components/map/MapView';
import { styleForLayer } from '@/components/map/layerStyles';
import type { BBox } from '@/lib/geo';
import { cx } from '@/lib/cx';
import { gsap, prefersReducedMotion } from '@/lib/motion/gsap';
import styles from './reveal.module.css';

export interface ModelOutputRevealProps {
  label: string;
  footprint: FeatureCollection | null;
  spill: FeatureCollection | null;
  /** `{z}/{x}/{y}` template for the oil-probability tiles, or null if not produced. */
  probabilityTiles: string | null;
  fitTo: BBox | null;
  badges?: ReactNode;
}

/**
 * Before / after for the detector.
 *
 * "Before" is what the model was given to look at — the SAR scene footprint;
 * "after" overlays what it produced — the per-pixel oil-probability field and
 * the slick outline cut from it. The toggle cross-fades between them (one GSAP
 * tween on a single 0–1 value), and the slider lets the analyst hold any mix.
 *
 * This deployment serves no raw-backscatter tile layer, so "before" is honestly
 * the footprint on the basemap rather than an imitation radar image.
 *
 * Known gap (backend): the layer manifest advertises `oil_probability` tiles at
 * `/cases/{id}/probability/{z}/{x}/{y}.png`, but no such route is served yet,
 * so today only the outline appears. The raster stays wired so it lights up as
 * soon as the route exists; the surrounding copy does not claim it meanwhile.
 */
export function ModelOutputReveal({
  label,
  footprint,
  spill,
  probabilityTiles,
  fitTo,
  badges,
}: ModelOutputRevealProps) {
  const [reveal, setReveal] = useState(1);
  const tween = useRef<gsap.core.Tween | null>(null);

  const animateTo = (target: number) => {
    tween.current?.kill();
    if (prefersReducedMotion()) {
      setReveal(target);
      return;
    }
    const state = { v: reveal };
    tween.current = gsap.to(state, {
      v: target,
      duration: 1.1,
      ease: 'power2.inOut',
      onUpdate: () => setReveal(state.v),
    });
  };

  const layers = useMemo<MapDataLayer[]>(() => {
    const footprintStyle = styleForLayer({ id: 'scene_footprint', type: 'geojson' });
    const spillStyle = styleForLayer({ id: 'spill', type: 'geojson' });
    const probabilityStyle = styleForLayer({ id: 'oil_probability', type: 'raster' });
    const list: MapDataLayer[] = [
      {
        id: 'scene_footprint',
        kind: footprintStyle.kind,
        colorVar: footprintStyle.colorVar,
        colorFallback: footprintStyle.fallback,
        visible: true,
        opacity: 0.6,
        data: footprint,
      },
    ];
    if (probabilityTiles) {
      list.push({
        id: 'oil_probability',
        kind: 'raster',
        colorVar: probabilityStyle.colorVar,
        colorFallback: probabilityStyle.fallback,
        visible: reveal > 0.01,
        opacity: 0.85 * reveal,
        tiles: [probabilityTiles],
      });
    }
    list.push({
      id: 'spill',
      kind: spillStyle.kind,
      colorVar: spillStyle.colorVar,
      colorFallback: spillStyle.fallback,
      visible: reveal > 0.01,
      opacity: reveal,
      lineWidth: 2,
      data: spill,
    });
    return list;
  }, [footprint, spill, probabilityTiles, reveal]);

  const after = reveal > 0.5;

  return (
    <div className={styles.root}>
      <MapView
        label={label}
        layers={layers}
        fitTo={fitTo}
        badges={badges}
        overlay={
          <div className={styles.bar}>
            <div className={styles.segment} role="group" aria-label="Show model output">
              <button
                type="button"
                aria-pressed={!after}
                className={cx(styles.option, !after && styles.optionActive)}
                onClick={() => animateTo(0)}
              >
                Before · scene
              </button>
              <button
                type="button"
                aria-pressed={after}
                className={cx(styles.option, after && styles.optionActive)}
                onClick={() => animateTo(1)}
              >
                After · model output
              </button>
            </div>
            <label className={styles.slider}>
              <span className="sr-only">Model output opacity</span>
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round(reveal * 100)}
                onChange={(event) => {
                  tween.current?.kill();
                  setReveal(Number(event.target.value) / 100);
                }}
              />
              <span className={styles.sliderValue} aria-hidden="true">
                {Math.round(reveal * 100)}%
              </span>
            </label>
          </div>
        }
      />
    </div>
  );
}
