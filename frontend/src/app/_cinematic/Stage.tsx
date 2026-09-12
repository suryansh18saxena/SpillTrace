'use client';

import dynamic from 'next/dynamic';
import { useEffect, useState } from 'react';
import { RadarMark } from '@/components/brand/RadarMark';
import { prefersReducedMotion } from '@/lib/motion/gsap';
import styles from './cinematic.module.css';
import { Hud } from './Hud';
import { hasWebGL } from './scene/quality';

const Scene = dynamic(() => import('./scene/Scene'), { ssr: false, loading: () => null });

/**
 * The fixed layer under the story: the 3D scene when the device can run it,
 * a still poster when it cannot or the visitor asked for reduced motion, and
 * the HUD and film overlays in both cases.
 */
export function Stage() {
  const [mode, setMode] = useState<'pending' | 'scene' | 'poster'>('pending');

  useEffect(() => {
    setMode(!prefersReducedMotion() && hasWebGL() ? 'scene' : 'poster');
  }, []);

  return (
    <div className={styles.stage} aria-hidden="true">
      <div className={styles.poster} data-hidden={mode === 'scene' ? '' : undefined}>
        <div className={styles.posterRings}>
          <RadarMark size={120} />
        </div>
      </div>
      {mode === 'scene' ? (
        <div className={styles.canvasWrap}>
          <Scene />
        </div>
      ) : null}
      <div className={styles.overlays}>
        <div className={styles.grid} />
        <div className={styles.scanlines} />
        <div className={styles.vignette} />
      </div>
      <Hud />
    </div>
  );
}
