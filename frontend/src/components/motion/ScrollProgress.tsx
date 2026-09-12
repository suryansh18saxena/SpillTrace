'use client';

import { useEffect, useRef } from 'react';
import styles from './motion.module.css';

/**
 * A two-pixel reading-progress bar along the top edge of the viewport.
 *
 * Driven by a passive scroll listener writing one custom property per frame —
 * no React state, no layout thrash. Hidden until the page is tall enough to
 * scroll, so a short screen never shows a full bar for nothing.
 */
export function ScrollProgress() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let frame = 0;
    const update = () => {
      frame = 0;
      const doc = document.documentElement;
      const max = doc.scrollHeight - doc.clientHeight;
      const value = max > 80 ? Math.min(1, Math.max(0, window.scrollY / max)) : 0;
      el.style.setProperty('--progress', value.toFixed(4));
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update);
    };
    update();
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    return () => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  return <div ref={ref} className={styles.progress} aria-hidden="true" />;
}
