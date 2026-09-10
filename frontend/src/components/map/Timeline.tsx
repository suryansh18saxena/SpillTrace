'use client';

import { useEffect, useMemo, useRef } from 'react';
import { Button } from '@/components/ui/Button';
import { IconPause, IconPlay, IconSkipBack } from '@/components/ui/Icons';
import { Slider } from '@/components/ui/Slider';
import { cx } from '@/lib/cx';
import { formatDateTimeCompact } from '@/lib/format';
import styles from './map.module.css';

export interface TimelineSpan {
  id: string;
  label: string;
  start: string;
  end: string;
  kind: 'window' | 'coverage';
}

export interface TimelineMarker {
  id: string;
  label: string;
  time: string;
}

export interface TimelineProps {
  /** Bounds of the case's time window. */
  start: string;
  end: string;
  /** Current cursor, in epoch milliseconds. `null` means "show every time". */
  value: number | null;
  onChange: (value: number | null) => void;
  playing?: boolean;
  onTogglePlay?: () => void;
  /** Shaded bands: the inferred discharge window and AIS coverage. */
  spans?: readonly TimelineSpan[];
  /** Hairlines: scene acquisition, closest approach. */
  markers?: readonly TimelineMarker[];
  /** Milliseconds of case time advanced per playback tick. */
  playStepMs?: number;
  /** Real milliseconds between playback ticks. */
  playIntervalMs?: number;
  /** Styles the component as a panel rather than a map overlay. */
  variant?: 'overlay' | 'panel';
  className?: string;
}

const MINUTE_MS = 60_000;

function pct(value: number, min: number, max: number): number {
  if (!Number.isFinite(value) || max <= min) return 0;
  return Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100));
}

/**
 * The investigation timeline (UI-004).
 *
 * It is the map's time axis: the scene acquisition, the drift-inferred discharge
 * window and the AIS coverage of the case all appear on one track, and dragging
 * the cursor filters what the map draws to that instant.
 *
 * A native range input carries the interaction, so Left/Right, Home/End and
 * Page Up/Down all work, and `aria-valuetext` reads the UTC timestamp rather
 * than a meaningless epoch number. "Show every time" is always one button away —
 * a scrubbed map that cannot be un-scrubbed is a trap.
 */
export function Timeline({
  start,
  end,
  value,
  onChange,
  playing = false,
  onTogglePlay,
  spans = [],
  markers = [],
  playStepMs = 15 * MINUTE_MS,
  playIntervalMs = 320,
  variant = 'overlay',
  className,
}: TimelineProps) {
  const startMs = Date.parse(start);
  const endMs = Date.parse(end);
  const valid = Number.isFinite(startMs) && Number.isFinite(endMs) && endMs > startMs;

  const current = value ?? startMs;
  const currentRef = useRef(current);
  currentRef.current = current;

  useEffect(() => {
    if (!playing || !valid) return;
    const timer = setInterval(() => {
      const next = currentRef.current + playStepMs;
      onChange(next > endMs ? startMs : next);
    }, playIntervalMs);
    return () => clearInterval(timer);
  }, [playing, valid, playStepMs, playIntervalMs, onChange, startMs, endMs]);

  const bands = useMemo(
    () =>
      spans
        .map((span) => {
          const a = Date.parse(span.start);
          const b = Date.parse(span.end);
          if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
          const left = pct(Math.min(a, b), startMs, endMs);
          const right = pct(Math.max(a, b), startMs, endMs);
          return { ...span, left, width: Math.max(right - left, 0.4) };
        })
        .filter((band): band is TimelineSpan & { left: number; width: number } => Boolean(band)),
    [spans, startMs, endMs],
  );

  const ticks = useMemo(
    () =>
      markers
        .map((marker) => {
          const at = Date.parse(marker.time);
          if (!Number.isFinite(at)) return null;
          return { ...marker, left: pct(at, startMs, endMs) };
        })
        .filter((tick): tick is TimelineMarker & { left: number } => Boolean(tick)),
    [markers, startMs, endMs],
  );

  if (!valid) return null;

  const cursorLeft = value === null ? null : pct(value, startMs, endMs);

  return (
    <section
      className={cx(styles.timeline, variant === 'panel' && styles.timelinePanel, className)}
      aria-label="Investigation timeline"
    >
      <div className={styles.timelineHead}>
        <span className={styles.timelineTitle}>Timeline</span>
        <span className={styles.timelineValue}>
          {value === null ? 'All times' : formatDateTimeCompact(value)}
        </span>
        <span className={styles.timelineSpacer} />
        {onTogglePlay ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={onTogglePlay}
            aria-pressed={playing}
            leadingIcon={playing ? <IconPause size={14} /> : <IconPlay size={14} />}
          >
            {playing ? 'Pause' : 'Play'}
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onChange(null)}
          disabled={value === null}
          leadingIcon={<IconSkipBack size={14} />}
        >
          Show every time
        </Button>
      </div>

      <div className={styles.timelineTrack} aria-hidden="true">
        {bands.map((band) => (
          <span
            key={band.id}
            title={band.label}
            className={cx(
              styles.timelineSpan,
              band.kind === 'window' ? styles.timelineSpanWindow : styles.timelineSpanCoverage,
            )}
            style={{ left: `${band.left}%`, width: `${band.width}%` }}
          />
        ))}
        {ticks.map((tick) => (
          <span
            key={tick.id}
            title={tick.label}
            className={styles.timelineMarker}
            style={{ left: `${tick.left}%` }}
          />
        ))}
        {cursorLeft === null ? null : (
          <span className={styles.timelineCursor} style={{ left: `${cursorLeft}%` }} />
        )}
      </div>

      <Slider
        label="Time cursor"
        labelHidden
        min={startMs}
        max={endMs}
        step={MINUTE_MS}
        value={current}
        valueText={value === null ? 'Every time in the window' : formatDateTimeCompact(value)}
        onChange={(event) => onChange(Number(event.target.value))}
      />

      <div className={styles.timelineBounds}>
        <span>{formatDateTimeCompact(start)}</span>
        <span>{formatDateTimeCompact(end)}</span>
      </div>

      {spans.length > 0 || markers.length > 0 ? (
        <div className={styles.timelineLegend}>
          {spans.map((span) => (
            <span key={span.id}>
              {span.kind === 'window' ? '▮' : '▬'} {span.label}
            </span>
          ))}
          {markers.map((marker) => (
            <span key={marker.id}>│ {marker.label}</span>
          ))}
        </div>
      ) : null}
    </section>
  );
}
