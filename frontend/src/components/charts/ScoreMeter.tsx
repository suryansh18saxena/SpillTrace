'use client';

import { useRef } from 'react';
import type { ConfidenceLabel } from '@/lib/api/types';
import { formatScore } from '@/lib/format';
import { gsap, prefersReducedMotion, useGSAP } from '@/lib/motion/gsap';
import styles from './charts.module.css';

/** Band edges from `core/scoring/model.py` (CONFIDENCE_MODERATE_MIN / _HIGH_MIN). */
export const BAND_MODERATE_MIN = 0.45;
export const BAND_HIGH_MIN = 0.8;

const ZONES = [
  {
    key: 'LOW',
    from: 0,
    to: BAND_MODERATE_MIN,
    color: 'var(--confidence-1-subtle)',
    solid: 'var(--confidence-1)',
  },
  {
    key: 'MODERATE',
    from: BAND_MODERATE_MIN,
    to: BAND_HIGH_MIN,
    color: 'var(--confidence-2-subtle)',
    solid: 'var(--confidence-2)',
  },
  {
    key: 'HIGH',
    from: BAND_HIGH_MIN,
    to: 1,
    color: 'var(--confidence-3-subtle)',
    solid: 'var(--confidence-3)',
  },
];

export interface ScoreMeterProps {
  value: number;
  /**
   * The evidence band the SERVER assigned. It wins over the band the score
   * alone would fall in: the engine caps every label when the evidence cannot
   * separate the candidates, and the meter must never contradict that.
   */
  band?: ConfidenceLabel;
  label?: string;
}

function normaliseBand(band: ConfidenceLabel | undefined): string | undefined {
  return band === 'MEDIUM' ? 'MODERATE' : band;
}

/**
 * Where a final score sits against the three evidence-strength bands.
 *
 * The band edges are the server's own (LOW < 0.45 ≤ MODERATE < 0.80 ≤ HIGH),
 * drawn in the one-hue confidence ramp. The highlighted band is the one the
 * server assigned; when that is lower than the score's own range (a capped
 * label) the meter says so rather than lighting the higher band. It never
 * turns the score into a probability (CON-003): the axis is 0–1, never %.
 */
export function ScoreMeter({ value, band, label = 'Investigative score' }: ScoreMeterProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const clamped = Math.max(0, Math.min(1, value));
  const range = ZONES.find((z) => clamped >= z.from && clamped < z.to) ?? ZONES[2]!;
  const assigned = normaliseBand(band);
  const zone = ZONES.find((z) => z.key === assigned) ?? range;
  const capped = zone.key !== range.key;

  // The marker sweeps in from 0 once, the first time the meter is seen. Later
  // value changes (another candidate selected, a slider) just move it: React
  // owns `left`, so replaying the entrance on every change would stutter.
  const initialLeft = useRef(`${clamped * 100}%`);
  useGSAP(
    () => {
      const marker = ref.current?.querySelector('[data-marker]');
      if (!marker || prefersReducedMotion()) return;
      gsap.fromTo(
        marker,
        { left: '0%' },
        {
          left: initialLeft.current,
          duration: 1.4,
          ease: 'expo.out',
          scrollTrigger: { trigger: ref.current, start: 'top 92%', once: true },
        },
      );
    },
    { scope: ref },
  );

  return (
    <div
      ref={ref}
      className={styles.meter}
      role="img"
      aria-label={`${label} ${formatScore(value)} on a 0 to 1 scale. Evidence band ${zone.key}${capped ? `, capped below the ${range.key} range the score falls in` : ''}. Bands: LOW below ${BAND_MODERATE_MIN}, MODERATE ${BAND_MODERATE_MIN} to ${BAND_HIGH_MIN}, HIGH ${BAND_HIGH_MIN} and above.`}
    >
      <div className={styles.meterZones} aria-hidden="true">
        {ZONES.map((z) => (
          <span
            key={z.key}
            className={styles.meterZone}
            style={
              {
                flexBasis: `${(z.to - z.from) * 100}%`,
                '--zone-color': z.key === zone.key ? z.solid : z.color,
              } as React.CSSProperties
            }
          />
        ))}
      </div>
      <div
        className={styles.meterMarker}
        data-marker=""
        style={{ left: `${clamped * 100}%` }}
        aria-hidden="true"
      >
        <span className={styles.meterMarkerValue}>{formatScore(value)}</span>
        <span className={styles.meterMarkerStem} />
      </div>
      <div
        className={styles.meterZoneLabels}
        style={{ gridTemplateColumns: ZONES.map((z) => `${(z.to - z.from) * 100}fr`).join(' ') }}
        aria-hidden="true"
      >
        {ZONES.map((z) => (
          <span key={z.key}>{z.key}</span>
        ))}
      </div>
      {/* Ticks at their true positions: 0.45 and 0.80 are not thirds. */}
      <div className={styles.meterScale} aria-hidden="true">
        {[0, BAND_MODERATE_MIN, BAND_HIGH_MIN, 1].map((tick) => (
          <span key={tick} className={styles.meterTick} style={{ left: `${tick * 100}%` }}>
            {tick === 0 || tick === 1 ? tick : tick.toFixed(2)}
          </span>
        ))}
      </div>
      {capped ? (
        <p className={styles.meterCap} aria-hidden="true">
          The score sits in the {range.key} range, but the evidence band is capped at {zone.key}.
        </p>
      ) : null}
    </div>
  );
}
