'use client';

import { useEffect, useRef } from 'react';
import styles from './shell.module.css';

/**
 * The authenticated app's atmosphere: slow aurora light, a faint graticule, a
 * radar sweep and film grain.
 *
 * The aurora blobs animate with transforms only. They pause while the tab is
 * hidden (so a background tab costs nothing) and are static under
 * `prefers-reduced-motion` via CSS.
 */
export function AppBackdrop() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const sync = () => {
      el.dataset['paused'] = document.hidden ? 'true' : 'false';
    };
    sync();
    document.addEventListener('visibilitychange', sync);
    return () => document.removeEventListener('visibilitychange', sync);
  }, []);

  return (
    <div ref={ref} className={`${styles.backdrop} grain`} aria-hidden="true">
      <div className={styles.aurora}>
        <span className={`${styles.auroraBlob} ${styles.auroraBlob1}`} />
        <span className={`${styles.auroraBlob} ${styles.auroraBlob2}`} />
        <span className={`${styles.auroraBlob} ${styles.auroraBlob3}`} />
      </div>
      <div className={styles.backdropGrid} />
      <div className={styles.backdropSweep} />
    </div>
  );
}
