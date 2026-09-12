'use client';

import { useEffect, useRef } from 'react';
import { gsap, prefersReducedMotion } from '@/lib/motion/gsap';
import { CASE, DRIFT, TECH_LABELS } from './content';
import styles from './cinematic.module.css';
import { AOI_CENTER_LAT, AOI_CENTER_LON, ORIGIN_CENTER, worldToLonLat } from './scene/world';
import { lerp, phase, scrollStore, SECTIONS, sectionIndex, smoothstep } from './timeline';

const SIGNAL_ON: Record<(typeof TECH_LABELS)[number], number> = {
  SAR: 1,
  AIS: 3,
  DRIFT: 4,
  TRAJECTORY: 4,
  ATTRIBUTION: 5,
};

function fmtLon(v: number) {
  return `${Math.abs(v).toFixed(3)}°${v >= 0 ? 'E' : 'W'}`;
}
function fmtLat(v: number) {
  return `${Math.abs(v).toFixed(3)}°${v >= 0 ? 'N' : 'S'}`;
}

/**
 * Corner instruments: case identity and provenance, the coordinates the camera
 * is looking at, the current stage, the backtrack clock and the signal chain.
 * Written straight to the DOM on GSAP's ticker — no React state per frame.
 */
export function Hud() {
  const root = useRef<HTMLDivElement>(null);
  const coords = useRef<HTMLSpanElement>(null);
  const stageNo = useRef<HTMLSpanElement>(null);
  const stageName = useRef<HTMLSpanElement>(null);
  const clock = useRef<HTMLSpanElement>(null);
  const clockWrap = useRef<HTMLDivElement>(null);
  const ticks = useRef<HTMLDivElement>(null);
  const chips = useRef<(HTMLSpanElement | null)[]>([]);

  useEffect(() => {
    if (prefersReducedMotion()) return;
    let lastSection = -1;
    const tick = () => {
      const p = scrollStore.progress;
      const idx = sectionIndex(p);
      if (idx !== lastSection) {
        lastSection = idx;
        scrollStore.section = idx;
        const s = SECTIONS[idx]!;
        if (stageNo.current) stageNo.current.textContent = String(idx).padStart(2, '0');
        if (stageName.current) stageName.current.textContent = s.label.toUpperCase();
        for (let i = 0; i < TECH_LABELS.length; i += 1) {
          const chip = chips.current[i];
          if (chip) chip.dataset.on = idx >= SIGNAL_ON[TECH_LABELS[i]!] ? '' : undefined;
        }
        root.current?.setAttribute('data-section', s.id);
      }

      // The gaze drifts from the slick to the origin region as the oil is traced back.
      const back = smoothstep(0, 1, phase(p, 'backtrack'));
      const x = lerp(0, ORIGIN_CENTER.x, back);
      const z = lerp(0, ORIGIN_CENTER.z, back);
      const [lon, lat] = worldToLonLat(x, z);
      if (coords.current) coords.current.textContent = `${fmtLat(lat)}  ${fmtLon(lon)}`;

      const inBack = phase(p, 'backtrack');
      const hours = inBack * DRIFT.hours;
      // The clock appears when the reconstruction starts and stays at T−18 h
      // afterwards: that is the moment the candidates are held at.
      if (clockWrap.current) clockWrap.current.dataset.on = inBack > 0 ? '' : undefined;
      if (clock.current) clock.current.textContent = `T−${hours.toFixed(1).padStart(4, '0')} H`;
      if (ticks.current) ticks.current.style.setProperty('--t', inBack.toFixed(4));
    };
    gsap.ticker.add(tick);
    return () => gsap.ticker.remove(tick);
  }, []);

  const [lon0, lat0] = [AOI_CENTER_LON, AOI_CENTER_LAT];

  return (
    <div ref={root} className={styles.hud} data-section="hero">
      <div className={`${styles.hudCorner} ${styles.hudTL}`}>
        <span className={styles.hudLabel}>CASE</span>
        <span className={styles.hudValue}>
          {CASE.ref} · {CASE.provenance}
        </span>
        <span className={styles.hudLabel}>LOOKING AT</span>
        <span ref={coords} className={styles.hudValue}>
          {fmtLat(lat0)} {fmtLon(lon0)}
        </span>
      </div>

      <div className={`${styles.hudCorner} ${styles.hudTR}`}>
        <span className={styles.hudLabel}>STAGE</span>
        <span className={styles.hudValue}>
          <span ref={stageNo}>00</span> / <span ref={stageName}>SIGNAL</span>
        </span>
      </div>

      <div ref={clockWrap} className={`${styles.hudCorner} ${styles.hudBL}`}>
        <span className={styles.hudLabel}>REVERSE DRIFT</span>
        <span ref={clock} className={`${styles.hudValue} ${styles.hudClock}`}>
          T−00.0 H
        </span>
        <div ref={ticks} className={styles.hudTimeline} style={{ '--t': 0 } as React.CSSProperties}>
          {[0, 6, 12, 18].map((h) => (
            <span
              key={h}
              className={styles.hudTick}
              style={{ '--h': h / 18 } as React.CSSProperties}
            >
              T−{h}H
            </span>
          ))}
        </div>
      </div>

      <div className={`${styles.hudCorner} ${styles.hudBR}`}>
        <span className={styles.hudLabel}>SIGNAL CHAIN</span>
        <span className={styles.hudChips}>
          {TECH_LABELS.map((label, i) => (
            <span
              key={label}
              ref={(el) => {
                chips.current[i] = el;
              }}
              className={styles.hudChip}
            >
              {label}
            </span>
          ))}
        </span>
        <span className={styles.hudLabel}>
          SCENARIO {CASE.scenario} · SEED {CASE.seed}
        </span>
      </div>
    </div>
  );
}
