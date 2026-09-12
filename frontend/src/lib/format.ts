/**
 * Formatting helpers.
 *
 * Two rules hold everywhere:
 *  - Times are rendered in **UTC**, because API.md §1 says every timestamp is
 *    RFC 3339 UTC and an investigation timeline that silently shifts with the
 *    analyst's device timezone is worse than useless as evidence.
 *  - The locale is pinned to `en-US` so a screenshot taken on one machine reads
 *    identically on another, and so unit tests are deterministic.
 */

/** Rendered in place of any missing value, so a blank cell is never ambiguous. */
export const EMPTY_VALUE = '—';

const LOCALE = 'en-US';

function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

const pad = (n: number, width = 2): string => String(n).padStart(width, '0');

/** `2026-08-01` */
export function formatDate(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return EMPTY_VALUE;
  return `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
}

/** `18:20` (UTC). Pass `withSeconds` for `18:20:37`. */
export function formatTime(
  value: string | number | Date | null | undefined,
  withSeconds = false,
): string {
  const date = toDate(value);
  if (!date) return EMPTY_VALUE;
  const base = `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
  return withSeconds ? `${base}:${pad(date.getUTCSeconds())}` : base;
}

/** `2026-08-01 18:20 UTC` — the default timestamp rendering. */
export function formatDateTime(
  value: string | number | Date | null | undefined,
  withSeconds = false,
): string {
  const date = toDate(value);
  if (!date) return EMPTY_VALUE;
  return `${formatDate(date)} ${formatTime(date, withSeconds)} UTC`;
}

/** `2026-08-01 18:20Z` — the compact form used inside dense tables. */
export function formatDateTimeCompact(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return EMPTY_VALUE;
  return `${formatDate(date)} ${formatTime(date)}Z`;
}

/** `2026-08-01 → 2026-08-03 (2 days)` */
export function formatTimeRange(
  start: string | number | Date | null | undefined,
  end: string | number | Date | null | undefined,
): string {
  const a = toDate(start);
  const b = toDate(end);
  if (!a || !b) return EMPTY_VALUE;
  const sameDay = formatDate(a) === formatDate(b);
  const right = sameDay ? `${formatTime(b)}Z` : formatDateTimeCompact(b);
  return `${formatDateTimeCompact(a)} → ${right}`;
}

/** `4 minutes ago`, `in 2 hours`, `just now`. */
export function formatRelativeTime(
  value: string | number | Date | null | undefined,
  now: Date = new Date(),
): string {
  const date = toDate(value);
  if (!date) return EMPTY_VALUE;

  const deltaSeconds = Math.round((date.getTime() - now.getTime()) / 1000);
  const absolute = Math.abs(deltaSeconds);
  if (absolute < 45) return 'just now';

  const units: Array<[Intl.RelativeTimeFormatUnit, number]> = [
    ['year', 31_536_000],
    ['month', 2_592_000],
    ['week', 604_800],
    ['day', 86_400],
    ['hour', 3_600],
    ['minute', 60],
    ['second', 1],
  ];
  const formatter = new Intl.RelativeTimeFormat(LOCALE, { numeric: 'auto' });
  for (const [unit, seconds] of units) {
    if (absolute >= seconds) {
      return formatter.format(Math.round(deltaSeconds / seconds), unit);
    }
  }
  return 'just now';
}

/** `1h 04m`, `47s`, `2d 3h`, `420 ms` — for job runtimes. Input is seconds. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return EMPTY_VALUE;
  // A stage that took 0.4 s did take time; "0s" would read as "did not run".
  if (seconds > 0 && seconds < 1) return `${Math.max(1, Math.round(seconds * 1000))} ms`;
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;

  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3_600);
  const minutes = Math.floor((total % 3_600) / 60);
  const secs = total % 60;

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${pad(minutes)}m`;
  return `${minutes}m ${pad(secs)}s`;
}

/** Elapsed time between two timestamps, formatted by `formatDuration`. */
export function formatElapsed(
  start: string | number | Date | null | undefined,
  end: string | number | Date | null | undefined,
): string {
  const a = toDate(start);
  const b = toDate(end);
  if (!a || !b) return EMPTY_VALUE;
  return formatDuration((b.getTime() - a.getTime()) / 1000);
}

// ------------------------------------------------------------------- numbers

export function formatNumber(
  value: number | null | undefined,
  options: Intl.NumberFormatOptions = {},
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  return new Intl.NumberFormat(LOCALE, options).format(value);
}

export function formatInteger(value: number | null | undefined): string {
  return formatNumber(value, { maximumFractionDigits: 0 });
}

/** `0.812` → `81%`. Input is a 0..1 fraction. */
export function formatPercent(value: number | null | undefined, fractionDigits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  return new Intl.NumberFormat(LOCALE, {
    style: 'percent',
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

/**
 * `0.812` → `0.81`. Scores are shown at two decimals and never as a percentage
 * on their own, so that an 81 is not read as "81% probability of guilt"
 * (CON-003). Where a percentage is genuinely useful it is always accompanied by
 * the word "investigative".
 */
export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  return value.toFixed(2);
}

/** `1234.5` → `1,235 km²`; small areas keep two decimals. */
export function formatAreaKm2(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  const digits = Math.abs(value) < 10 ? 2 : 0;
  return `${formatNumber(value, { minimumFractionDigits: digits, maximumFractionDigits: digits })} km²`;
}

/** `1.4` → `1.4 km`; below 1 km switches to metres. */
export function formatDistanceKm(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  if (Math.abs(value) < 1) {
    return `${formatNumber(Math.round(value * 1000), { maximumFractionDigits: 0 })} m`;
  }
  const digits = Math.abs(value) < 100 ? 1 : 0;
  return `${formatNumber(value, { minimumFractionDigits: digits, maximumFractionDigits: digits })} km`;
}

/** Knots, as reported by AIS. */
export function formatSpeedKn(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  return `${formatNumber(value, { minimumFractionDigits: 1, maximumFractionDigits: 1 })} kn`;
}

/** Course/heading in degrees. */
export function formatBearing(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  return `${formatNumber(((value % 360) + 360) % 360, { maximumFractionDigits: 0 })}°`;
}

export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value) || value < 0) {
    return EMPTY_VALUE;
  }
  if (value < 1024) return `${Math.round(value)} B`;
  const units = ['kB', 'MB', 'GB', 'TB'];
  let size = value / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${formatNumber(size, { maximumFractionDigits: size < 10 ? 1 : 0 })} ${units[unitIndex]}`;
}

// --------------------------------------------------------------- identifiers

/** MMSI is always exactly 9 digits; render it verbatim, in monospace. */
export function formatMmsi(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return EMPTY_VALUE;
  return String(value);
}

/** `IMO 9074729` — the IMO number is conventionally shown with its prefix. */
export function formatImo(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === '') return EMPTY_VALUE;
  const raw = String(value).replace(/^IMO\s*/i, '');
  return `IMO ${raw}`;
}

/** Shorten a long opaque identifier for a dense table: `01J8F…K3QZ`. */
export function truncateId(value: string | null | undefined, head = 6, tail = 4): string {
  if (!value) return EMPTY_VALUE;
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

// --------------------------------------------------------------- coordinates

/** `22.6000° N` / `69.6000° E`. */
export function formatLatitude(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  return `${Math.abs(value).toFixed(digits)}° ${value >= 0 ? 'N' : 'S'}`;
}

export function formatLongitude(value: number | null | undefined, digits = 4): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  return `${Math.abs(value).toFixed(digits)}° ${value >= 0 ? 'E' : 'W'}`;
}

/** `22.6000° N, 69.6000° E` — latitude first for humans, unlike GeoJSON. */
export function formatCoordinate(
  lon: number | null | undefined,
  lat: number | null | undefined,
  digits = 4,
): string {
  if (lat === null || lat === undefined || lon === null || lon === undefined) return EMPTY_VALUE;
  return `${formatLatitude(lat, digits)}, ${formatLongitude(lon, digits)}`;
}

// ------------------------------------------------------------------- strings

/** Words that stay upper-case when an identifier is humanised. */
const ACRONYMS = new Set([
  'ais',
  'aoi',
  'api',
  'cdse',
  'cmems',
  'cpu',
  'gpu',
  'id',
  'imo',
  'iou',
  'ml',
  'mmsi',
  'sar',
  'sog',
  'cog',
  'url',
  'utc',
]);

/**
 * `drift.hindcast` → `Drift hindcast`; `FALSE_POSITIVE` → `False positive`;
 * `ais.ingest` → `AIS ingest` (known acronyms keep their capitals).
 */
export function humanizeIdentifier(value: string | null | undefined): string {
  if (!value) return EMPTY_VALUE;
  const words = value
    .replace(/[._-]+/g, ' ')
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .map((word) => (ACRONYMS.has(word) ? word.toUpperCase() : word));
  const sentence = words.join(' ');
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

/** `1` → `1st`, `2` → `2nd` — used for candidate rank. */
export function formatOrdinal(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EMPTY_VALUE;
  const n = Math.trunc(value);
  const mod100 = Math.abs(n) % 100;
  const mod10 = Math.abs(n) % 10;
  const suffix =
    mod100 >= 11 && mod100 <= 13
      ? 'th'
      : mod10 === 1
        ? 'st'
        : mod10 === 2
          ? 'nd'
          : mod10 === 3
            ? 'rd'
            : 'th';
  return `${n}${suffix}`;
}

/** `1 case` / `3 cases`. */
export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${formatInteger(count)} ${Math.abs(count) === 1 ? singular : plural}`;
}
