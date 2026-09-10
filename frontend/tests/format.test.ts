import { describe, expect, it } from 'vitest';
import {
  EMPTY_VALUE,
  formatAreaKm2,
  formatBearing,
  formatBytes,
  formatCoordinate,
  formatDate,
  formatDateTime,
  formatDateTimeCompact,
  formatDistanceKm,
  formatDuration,
  formatElapsed,
  formatImo,
  formatInteger,
  formatMmsi,
  formatOrdinal,
  formatPercent,
  formatRelativeTime,
  formatScore,
  formatSpeedKn,
  formatTimeRange,
  humanizeIdentifier,
  pluralize,
  truncateId,
} from '@/lib/format';

describe('timestamps', () => {
  // Everything is rendered in UTC on purpose: an evidence timeline that shifts
  // with the analyst's device timezone is not evidence.
  const iso = '2026-08-01T18:20:37Z';

  it('formats dates and times in UTC regardless of the host timezone', () => {
    expect(formatDate(iso)).toBe('2026-08-01');
    expect(formatDateTime(iso)).toBe('2026-08-01 18:20 UTC');
    expect(formatDateTime(iso, true)).toBe('2026-08-01 18:20:37 UTC');
    expect(formatDateTimeCompact(iso)).toBe('2026-08-01 18:20Z');
  });

  it('collapses a same-day range to a single date', () => {
    expect(formatTimeRange('2026-08-01T00:00:00Z', '2026-08-01T06:30:00Z')).toBe(
      '2026-08-01 00:00Z → 06:30Z',
    );
  });

  it('shows both dates for a multi-day range', () => {
    expect(formatTimeRange('2026-08-01T00:00:00Z', '2026-08-03T00:00:00Z')).toBe(
      '2026-08-01 00:00Z → 2026-08-03 00:00Z',
    );
  });

  it.each([null, undefined, '', 'not-a-date'])('renders %p as the empty marker', (value) => {
    expect(formatDate(value as string | null)).toBe(EMPTY_VALUE);
    expect(formatDateTime(value as string | null)).toBe(EMPTY_VALUE);
  });

  it('formats relative times against a fixed "now"', () => {
    const now = new Date('2026-08-01T12:00:00Z');
    expect(formatRelativeTime('2026-08-01T11:56:00Z', now)).toBe('4 minutes ago');
    expect(formatRelativeTime('2026-08-01T14:00:00Z', now)).toBe('in 2 hours');
    expect(formatRelativeTime('2026-08-01T11:59:30Z', now)).toBe('just now');
  });
});

describe('durations', () => {
  it.each([
    [0, '0s'],
    [47, '47s'],
    [59, '59s'],
    [60, '1m 00s'],
    [125, '2m 05s'],
    [3_840, '1h 04m'],
    [180_000, '2d 2h'],
  ])('formats %i seconds as %s', (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });

  it('returns the empty marker for a missing duration', () => {
    expect(formatDuration(null)).toBe(EMPTY_VALUE);
    expect(formatDuration(Number.NaN)).toBe(EMPTY_VALUE);
  });

  it('computes elapsed time between two timestamps', () => {
    expect(formatElapsed('2026-08-01T10:00:00Z', '2026-08-01T10:02:30Z')).toBe('2m 30s');
    expect(formatElapsed('2026-08-01T10:00:00Z', null)).toBe(EMPTY_VALUE);
  });
});

describe('numbers and quantities', () => {
  it('formats integers with thousands separators', () => {
    expect(formatInteger(250000)).toBe('250,000');
  });

  it('shows a score at two decimals and never as a bare percentage', () => {
    // CON-003: 0.81 is an investigative score, not an 81% legal probability.
    expect(formatScore(0.812)).toBe('0.81');
    expect(formatScore(1)).toBe('1.00');
    expect(formatScore(null)).toBe(EMPTY_VALUE);
  });

  it('formats percentages from 0..1 fractions', () => {
    expect(formatPercent(0.812)).toBe('81%');
    expect(formatPercent(0.812, 1)).toBe('81.2%');
  });

  it('keeps two decimals for small areas and none for large ones', () => {
    expect(formatAreaKm2(0.42)).toBe('0.42 km²');
    expect(formatAreaKm2(1234.5)).toBe('1,235 km²');
    expect(formatAreaKm2(null)).toBe(EMPTY_VALUE);
  });

  it('switches to metres below one kilometre', () => {
    expect(formatDistanceKm(1.4)).toBe('1.4 km');
    expect(formatDistanceKm(0.82)).toBe('820 m');
    expect(formatDistanceKm(1420)).toBe('1,420 km');
  });

  it('formats AIS speed and bearing', () => {
    expect(formatSpeedKn(12.34)).toBe('12.3 kn');
    expect(formatBearing(371)).toBe('11°');
    expect(formatBearing(-10)).toBe('350°');
  });

  it('formats byte sizes', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2 kB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5 MB');
    expect(formatBytes(-1)).toBe(EMPTY_VALUE);
  });
});

describe('identifiers and strings', () => {
  it('renders MMSI verbatim and IMO with its prefix', () => {
    expect(formatMmsi(419001234)).toBe('419001234');
    expect(formatMmsi(null)).toBe(EMPTY_VALUE);
    expect(formatImo(9074729)).toBe('IMO 9074729');
    expect(formatImo('IMO 9074729')).toBe('IMO 9074729');
  });

  it('truncates long opaque identifiers around an ellipsis', () => {
    expect(truncateId('01J8F3ZK9QWERTY0123', 6, 4)).toBe('01J8F3…0123');
    expect(truncateId('short')).toBe('short');
    expect(truncateId(null)).toBe(EMPTY_VALUE);
  });

  it('humanizes job types and enum values', () => {
    expect(humanizeIdentifier('drift.hindcast')).toBe('Drift hindcast');
    expect(humanizeIdentifier('FALSE_POSITIVE')).toBe('False positive');
  });

  it('formats ordinals for candidate rank', () => {
    expect(formatOrdinal(1)).toBe('1st');
    expect(formatOrdinal(2)).toBe('2nd');
    expect(formatOrdinal(3)).toBe('3rd');
    expect(formatOrdinal(4)).toBe('4th');
    expect(formatOrdinal(11)).toBe('11th');
    expect(formatOrdinal(21)).toBe('21st');
  });

  it('pluralizes counts', () => {
    expect(pluralize(1, 'case')).toBe('1 case');
    expect(pluralize(3, 'case')).toBe('3 cases');
  });
});

describe('coordinates', () => {
  it('renders latitude first, with hemispheres', () => {
    expect(formatCoordinate(69.6, 22.6)).toBe('22.6000° N, 69.6000° E');
    expect(formatCoordinate(-69.6, -22.6)).toBe('22.6000° S, 69.6000° W');
    expect(formatCoordinate(null, 22.6)).toBe(EMPTY_VALUE);
  });
});
