import type { CSSProperties } from 'react';
import { cx } from '@/lib/cx';
import { formatScore } from '@/lib/format';
import {
  BAND_HIGH_MIN,
  BAND_MODERATE_MIN,
  NO_TIME_OVERLAP_CEILING,
  bandFor,
  type Band,
} from '@/app/transparency/content';
import styles from './help.module.css';

const ZONES: ReadonlyArray<{ key: Band; from: number; to: number }> = [
  { key: 'LOW', from: 0, to: BAND_MODERATE_MIN },
  { key: 'MODERATE', from: BAND_MODERATE_MIN, to: BAND_HIGH_MIN },
  { key: 'HIGH', from: BAND_HIGH_MIN, to: 1 },
];

export interface BandMeterProps {
  value: number;
  /** Accessible name prefix; ignored when `decorative`. */
  label?: string;
  /** Hide from assistive technology when a control nearby already states the value. */
  decorative?: boolean;
  /** Ease the marker to a new value (used when a preset is picked, not while dragging). */
  smooth?: boolean;
  /** Draw the 0.79 "no time overlap" ceiling. */
  showCeiling?: boolean;
}

/**
 * A 0–1 axis with the three evidence-strength bands, for teaching.
 *
 * Why not the product's `ScoreMeter`? Two reasons, both reported upstream:
 * it replays its entrance from zero whenever the value changes (fine on a
 * result, janky under a slider), and its tick labels are spaced evenly rather
 * than at 0.45 and 0.80. Here every tick sits at its true position, the marker
 * moves by transform only, and nothing is ever expressed as a percentage.
 */
export function BandMeter({
  value,
  label = 'Illustrative score',
  decorative = false,
  smooth = false,
  showCeiling = false,
}: BandMeterProps) {
  const clamped = Math.max(0, Math.min(1, value));
  const band = bandFor(clamped);

  const a11y = decorative
    ? { 'aria-hidden': true as const }
    : {
        role: 'img',
        'aria-label': `${label} ${formatScore(value)} on a 0 to 1 scale, in the ${band} band. Bands: LOW below ${formatScore(BAND_MODERATE_MIN)}, MODERATE ${formatScore(BAND_MODERATE_MIN)} to ${formatScore(BAND_HIGH_MIN)}, HIGH ${formatScore(BAND_HIGH_MIN)} and above.`,
      };

  return (
    <div className={styles.explorerMeter} {...a11y}>
      <div className={cx(styles.explorerRailBox, showCeiling && styles.explorerRailBoxCeiling)}>
        {showCeiling ? (
          <span
            className={styles.explorerCeiling}
            style={{ left: `${NO_TIME_OVERLAP_CEILING * 100}%` }}
          >
            {formatScore(NO_TIME_OVERLAP_CEILING)} · ceiling with no time overlap
          </span>
        ) : null}
        <div className={styles.explorerZones}>
          {ZONES.map((zone) => (
            <span
              key={zone.key}
              data-band={zone.key}
              className={cx(styles.explorerZone, zone.key === band && styles.explorerZoneActive)}
              style={{ flexBasis: `${(zone.to - zone.from) * 100}%` }}
            />
          ))}
        </div>
        {/* Labels sit under the bar, so the marker never cuts through a word. */}
        <div className={styles.explorerZoneLabels}>
          {ZONES.map((zone) => (
            <span
              key={zone.key}
              className={cx(zone.key === band && styles.explorerZoneLabelActive)}
              style={{ flexBasis: `${(zone.to - zone.from) * 100}%` }}
            >
              {zone.key}
            </span>
          ))}
        </div>
        <span
          className={cx(styles.explorerMarkerTrack, smooth && styles.explorerMarkerSmooth)}
          style={{ '--v': clamped } as CSSProperties}
        >
          <span className={styles.explorerMarker} />
        </span>
        <div className={styles.explorerTicks}>
          <span style={{ left: '0%' }}>0</span>
          <span style={{ left: `${BAND_MODERATE_MIN * 100}%` }}>
            {formatScore(BAND_MODERATE_MIN)}
          </span>
          <span style={{ left: `${BAND_HIGH_MIN * 100}%` }}>{formatScore(BAND_HIGH_MIN)}</span>
          <span style={{ left: '100%' }}>1</span>
        </div>
      </div>
    </div>
  );
}
