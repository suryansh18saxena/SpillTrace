'use client';

import { useState } from 'react';
import { ConfidenceBadge } from '@/components/attribution/ConfidenceBadge';
import { Button } from '@/components/ui/Button';
import { Slider } from '@/components/ui/Slider';
import { formatScore } from '@/lib/format';
import {
  BAND_HIGH_MIN,
  BAND_MEANINGS,
  BAND_MODERATE_MIN,
  NO_TIME_OVERLAP_CEILING,
  bandFor,
  type Band,
} from '@/app/transparency/content';
import { BandMeter } from './BandMeter';
import styles from './help.module.css';

/**
 * Every preset is an edge or a ceiling the scoring model itself defines; 0.44
 * is simply one slider step below the MODERATE edge.
 */
const PRESETS: ReadonlyArray<{ value: number; label: string }> = [
  { value: 0.44, label: 'just under MODERATE' },
  { value: BAND_MODERATE_MIN, label: 'MODERATE edge' },
  { value: NO_TIME_OVERLAP_CEILING, label: 'ceiling with no time overlap' },
  { value: BAND_HIGH_MIN, label: 'HIGH edge' },
];

function noteFor(value: number, band: Band): string {
  const fixed = formatScore(value);
  if (fixed === formatScore(NO_TIME_OVERLAP_CEILING)) {
    return 'This is the most a candidate can score when it has no overlap with the inferred discharge window: the arithmetic stops it one hundredth short of HIGH. Being near the origin is never enough on its own.';
  }
  if (fixed === formatScore(BAND_MODERATE_MIN) || fixed === formatScore(BAND_HIGH_MIN)) {
    return 'The bands are half-open, so a score sitting exactly on an edge belongs to the band above it: 0.45 is MODERATE and 0.80 is HIGH.';
  }
  if (band === 'LOW') {
    return 'A well-tracked vessel moving at a plausible speed collects roughly 0.25 from heading, speed and AIS reliability wherever and whenever it was. Below 0.45 there is no real link to the place or the time.';
  }
  if (band === 'MODERATE') {
    return 'Some genuine link to the origin region or the discharge window, short of the HIGH edge. This is also where labels are held when the evidence cannot tell candidates apart.';
  }
  return 'The six factors broadly agree. Worth enquiring into first — and still only a reason to look, never a finding.';
}

/**
 * A drag-to-explore view of the three evidence-strength bands.
 *
 * The meter follows the thumb directly (transform only) and eases only when a
 * preset is chosen — see `BandMeter` for why this is not `ScoreMeter`. Same
 * band edges, same one-hue ramp, same 0–1 axis (never a percentage).
 */
export function BandExplorer() {
  const [value, setValue] = useState(0.62);
  const [smooth, setSmooth] = useState(false);
  const band = bandFor(value);

  return (
    <div className={styles.explorer}>
      <div className={styles.panelHead}>
        <div>
          <p className={styles.panelKicker}>Try it</p>
          <h3 className={styles.panelTitle}>Where the band edges fall</h3>
        </div>
        <span className={styles.illustrationTag}>Illustration</span>
      </div>

      <div className={styles.explorerReadout}>
        <span className={styles.explorerScore}>{formatScore(value)}</span>
        <div className={styles.explorerBand}>
          <ConfidenceBadge label={band} />
          <p className={styles.explorerMeaning}>{BAND_MEANINGS[band]}</p>
        </div>
      </div>

      {/* The slider below states the value for assistive technology. */}
      <BandMeter value={value} smooth={smooth} showCeiling decorative />

      <Slider
        label="Illustrative score"
        min={0}
        max={1}
        step={0.01}
        value={value}
        valueText={`${formatScore(value)} — ${band} band`}
        containerClassName={styles.explorerSlider}
        onChange={(event) => {
          setSmooth(false);
          setValue(Number(event.target.value));
        }}
      />

      <div
        className={styles.explorerPresets}
        role="group"
        aria-label="Jump to a value the model defines"
      >
        {PRESETS.map((preset) => (
          <Button
            key={preset.value}
            size="sm"
            variant="secondary"
            aria-pressed={formatScore(value) === formatScore(preset.value)}
            onClick={() => {
              setSmooth(true);
              setValue(preset.value);
            }}
          >
            <span className={styles.presetValue}>{formatScore(preset.value)}</span>
            {preset.label}
          </Button>
        ))}
      </div>

      <p className={styles.explorerNote} aria-live="polite">
        {noteFor(value, band)}
      </p>

      <p className={styles.caption}>
        Illustration — not a real vessel. Drag the slider or pick a preset; the band edges are the
        server’s own (LOW &lt; 0.45 ≤ MODERATE &lt; 0.80 ≤ HIGH).
      </p>
    </div>
  );
}
