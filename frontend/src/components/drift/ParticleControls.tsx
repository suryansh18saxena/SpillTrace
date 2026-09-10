'use client';

import { useEffect, useRef } from 'react';
import { Button } from '@/components/ui/Button';
import { IconPause, IconPlay, IconSkipBack } from '@/components/ui/Icons';
import { Slider } from '@/components/ui/Slider';
import { cx } from '@/lib/cx';
import { formatDateTimeCompact, formatInteger } from '@/lib/format';
import styles from './drift.module.css';

export interface ParticleStep {
  /** The simulation's own step index. These are not a dense `0..n` range. */
  step: number;
  /** Wall-clock time this step represents. */
  time: string;
}

export interface ParticleControlsProps {
  steps: readonly ParticleStep[];
  /** Position within `steps`, not the step index itself. */
  index: number;
  onIndexChange: (index: number) => void;
  playing: boolean;
  onTogglePlay: () => void;
  /** Particles drawn at the current step. */
  particleCount?: number | null;
  /** Real milliseconds between frames. */
  intervalMs?: number;
  className?: string;
}

/**
 * Playback for the reverse-drift particle cloud (UI-006).
 *
 * Step 0 is the observed slick; each further step is further *back* in time,
 * which is stated on screen because an animation that runs backwards is
 * genuinely confusing otherwise. Playback loops rather than stopping at the end,
 * so an analyst can leave it running while reading the parameters beside it.
 */
export function ParticleControls({
  steps,
  index,
  onIndexChange,
  playing,
  onTogglePlay,
  particleCount,
  intervalMs = 420,
  className,
}: ParticleControlsProps) {
  const indexRef = useRef(index);
  indexRef.current = index;

  useEffect(() => {
    if (!playing || steps.length < 2) return;
    const timer = setInterval(() => {
      onIndexChange((indexRef.current + 1) % steps.length);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [playing, steps.length, intervalMs, onIndexChange]);

  if (steps.length === 0) return null;

  const current = steps[Math.min(Math.max(index, 0), steps.length - 1)];
  const label = current
    ? `step ${current.step} · ${formatDateTimeCompact(current.time)}`
    : 'no steps';

  return (
    <section className={cx(styles.controls, className)} aria-label="Drift particle playback">
      <div className={styles.controlsRow}>
        <Button
          size="sm"
          variant="secondary"
          onClick={onTogglePlay}
          aria-pressed={playing}
          disabled={steps.length < 2}
          leadingIcon={playing ? <IconPause size={14} /> : <IconPlay size={14} />}
        >
          {playing ? 'Pause' : 'Play'}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onIndexChange(0)}
          disabled={index === 0}
          leadingIcon={<IconSkipBack size={14} />}
        >
          Restart
        </Button>
        <span className={styles.controlsValue}>{label}</span>
        {typeof particleCount === 'number' ? (
          <span className={styles.controlsMeta}>
            {formatInteger(particleCount)} particles drawn
          </span>
        ) : null}
      </div>

      <Slider
        label="Simulation step"
        min={0}
        max={Math.max(steps.length - 1, 0)}
        step={1}
        value={Math.min(Math.max(index, 0), steps.length - 1)}
        valueText={label}
        disabled={steps.length < 2}
        onChange={(event) => onIndexChange(Number(event.target.value))}
      />

      <p className={styles.controlsHint}>
        The simulation runs <strong>backwards</strong>: step 0 is the observed slick and each later
        step is further back in time, towards where the oil is likely to have entered the water.
      </p>
    </section>
  );
}
