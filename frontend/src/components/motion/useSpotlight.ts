'use client';

import { useEffect, useRef } from 'react';
import { hasFinePointer, prefersReducedMotion } from '@/lib/motion/gsap';

/**
 * Tracks the pointer over an element and exposes it as `--spot-x` / `--spot-y`
 * (percent), so CSS can draw a soft light that follows the cursor.
 *
 * Writes happen at most once per animation frame, and only custom properties
 * change — no layout, no React re-render. When `tilt` is set the element also
 * gets `--tilt-x` / `--tilt-y` in degrees for a subtle 3D lean.
 */
export function useSpotlight<T extends HTMLElement>({ tilt = 0 }: { tilt?: number } = {}) {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !hasFinePointer()) return;
    const allowTilt = tilt > 0 && !prefersReducedMotion();
    let frame = 0;
    let lastEvent: PointerEvent | null = null;

    const flush = () => {
      frame = 0;
      if (!lastEvent) return;
      const rect = el.getBoundingClientRect();
      const px = (lastEvent.clientX - rect.left) / rect.width;
      const py = (lastEvent.clientY - rect.top) / rect.height;
      el.style.setProperty('--spot-x', `${(px * 100).toFixed(1)}%`);
      el.style.setProperty('--spot-y', `${(py * 100).toFixed(1)}%`);
      el.style.setProperty('--spot-o', '1');
      if (allowTilt) {
        el.style.setProperty('--tilt-x', `${((0.5 - py) * tilt).toFixed(2)}deg`);
        el.style.setProperty('--tilt-y', `${((px - 0.5) * tilt).toFixed(2)}deg`);
      }
    };

    const onMove = (event: PointerEvent) => {
      lastEvent = event;
      if (!frame) frame = requestAnimationFrame(flush);
    };
    const onLeave = () => {
      lastEvent = null;
      el.style.setProperty('--spot-o', '0');
      if (allowTilt) {
        el.style.setProperty('--tilt-x', '0deg');
        el.style.setProperty('--tilt-y', '0deg');
      }
    };

    el.addEventListener('pointermove', onMove);
    el.addEventListener('pointerleave', onLeave);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      el.removeEventListener('pointermove', onMove);
      el.removeEventListener('pointerleave', onLeave);
    };
  }, [tilt]);

  return ref;
}
