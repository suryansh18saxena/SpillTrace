import styles from './help.module.css';

/*
 * Schematic figures for the origin-region section. Server-rendered, no hooks,
 * no data: every shape here is drawn by hand to explain the idea and is
 * captioned as an illustration wherever it is used.
 */

// ------------------------------------------------------------- particles

/** A tiny deterministic PRNG, so the "random" particle cloud is identical on every render. */
function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function gaussianCloud(
  count: number,
  cx: number,
  cy: number,
  sx: number,
  sy: number,
  seed: number,
) {
  const rand = lcg(seed);
  const points: Array<{ x: number; y: number }> = [];
  for (let i = 0; i < count; i += 1) {
    // Box–Muller
    const u = Math.max(rand(), 1e-9);
    const v = rand();
    const r = Math.sqrt(-2 * Math.log(u));
    points.push({
      x: Math.round((cx + sx * r * Math.cos(2 * Math.PI * v)) * 10) / 10,
      y: Math.round((cy + sy * r * Math.sin(2 * Math.PI * v)) * 10) / 10,
    });
  }
  return points;
}

const CLOUD = gaussianCloud(74, 214, 176, 44, 30, 20260911);

/** A few particles caught mid-way along the back-tracks, to show motion through time. */
const TRAIL = [
  { x: 452, y: 165 },
  { x: 418, y: 162 },
  { x: 384, y: 164 },
  { x: 350, y: 170 },
  { x: 498, y: 140 },
  { x: 458, y: 133 },
  { x: 414, y: 136 },
  { x: 372, y: 145 },
  { x: 334, y: 152 },
  { x: 540, y: 124 },
  { x: 496, y: 112 },
  { x: 446, y: 110 },
  { x: 398, y: 120 },
  { x: 352, y: 133 },
];

// ---------------------------------------------------------- origin figure

/**
 * A detected slick, dashed back-tracks and the nested 90 / 75 / 50 % contours
 * they settle into. What is conspicuously absent is a pin: CON-008 in picture
 * form.
 */
export function OriginFigure() {
  return (
    <svg
      className={styles.originSvg}
      viewBox="0 0 640 320"
      role="img"
      aria-label="Illustration. On the right, an elongated detected slick. Dashed back-tracks run west, backwards in time, into three nested contours marked 90, 75 and 50 per cent, with simulated particles scattered across them. No single point is marked."
    >
      <defs>
        <marker
          id="help-origin-arrow"
          viewBox="0 0 10 10"
          refX="7"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M0 0 L10 5 L0 10 z" fill="var(--map-track)" />
        </marker>
        <marker
          id="help-forcing-arrow"
          viewBox="0 0 10 10"
          refX="7"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto"
        >
          <path d="M0 0 L10 5 L0 10 z" fill="var(--color-text-muted)" />
        </marker>
      </defs>

      <rect x="0" y="0" width="640" height="320" rx="14" className={styles.originOcean} />
      <g className={styles.originGraticule}>
        {[80, 160, 240, 320, 400, 480, 560].map((x) => (
          <line key={`v${x}`} x1={x} y1="0" x2={x} y2="320" />
        ))}
        {[80, 160, 240].map((y) => (
          <line key={`h${y}`} x1="0" y1={y} x2="640" y2={y} />
        ))}
      </g>

      {/* Forcing direction: forward drift runs west → east in this sketch. */}
      <g className={styles.svgLabel}>
        <line
          x1="470"
          y1="36"
          x2="548"
          y2="36"
          stroke="var(--color-text-muted)"
          strokeWidth="1.5"
          markerEnd="url(#help-forcing-arrow)"
        />
        <text x="468" y="28" className={styles.originTextMuted}>
          wind + current
        </text>
      </g>

      {/* Nested contours, widest first. Tighter reads stronger (inverse opacity). */}
      <path
        className={styles.contour90}
        d="M95 170 C95 110 160 78 225 82 C290 86 338 118 340 165 C342 215 300 262 228 268 C160 274 96 235 95 170 Z"
      />
      <path
        className={styles.contour75}
        d="M128 172 C128 128 170 105 220 107 C270 110 305 135 306 170 C307 208 275 240 222 242 C172 244 128 214 128 172 Z"
      />
      <path
        className={styles.contour50}
        d="M165 176 C164 148 188 133 216 134 C246 136 268 152 268 175 C268 199 246 214 216 214 C188 214 166 200 165 176 Z"
      />

      {/* Back-tracks: from the slick, backwards in time, into the region. */}
      <g className={styles.backtracks}>
        <path d="M470 176 C420 186 360 186 262 190" markerEnd="url(#help-origin-arrow)" />
        <path d="M522 150 C460 150 380 156 270 172" markerEnd="url(#help-origin-arrow)" />
        <path d="M566 124 C500 118 400 128 276 156" markerEnd="url(#help-origin-arrow)" />
      </g>

      <g className={styles.particles}>
        {CLOUD.map((p, i) => (
          <circle key={`c${i}`} cx={p.x} cy={p.y} r="1.9" />
        ))}
        {TRAIL.map((p, i) => (
          <circle key={`t${i}`} cx={p.x} cy={p.y} r="1.6" className={styles.particleTrail} />
        ))}
      </g>

      {/* The observed slick — the only thing in this picture the radar actually saw. */}
      <path
        className={styles.slick}
        d="M430 178 C445 150 500 128 560 112 C585 106 596 118 584 130 C560 152 505 170 455 190 C438 197 422 192 430 178 Z"
      />

      <g className={styles.svgLabel}>
        <text x="520" y="92" className={styles.originText}>
          Detected slick
        </text>
        <text x="352" y="214" className={styles.originTextMuted}>
          ← backwards in time
        </text>
        <text x="100" y="175" className={styles.originTextSmall}>
          90%
        </text>
        <text x="133" y="177" className={styles.originTextSmall}>
          75%
        </text>
        <text x="171" y="180" className={styles.originTextSmall}>
          50%
        </text>
      </g>
    </svg>
  );
}

// ------------------------------------------------ discharge-window figure

/**
 * An illustrative "how many particles were inside the region at each moment"
 * profile. The bracket is computed from the bars themselves — the middle half
 * of the occupancy — exactly as `_inferred_window` in
 * worker/handlers/drift.py takes the 25th–75th percentile of occupancy times.
 */
const OCCUPANCY: readonly number[] = Array.from({ length: 30 }, (_, i) => {
  const main = Math.exp(-(((i - 15) / 4.6) ** 2));
  const shoulder = 0.35 * Math.exp(-(((i - 9) / 3.2) ** 2));
  return Math.round((0.04 + main + shoulder) * 1000) / 1000;
});

function percentileIndex(values: readonly number[], fraction: number): number {
  const total = values.reduce((sum, v) => sum + v, 0);
  let running = 0;
  for (let i = 0; i < values.length; i += 1) {
    running += values[i] ?? 0;
    if (running / total >= fraction) return i;
  }
  return values.length - 1;
}

const WINDOW_START = percentileIndex(OCCUPANCY, 0.25);
const WINDOW_END = percentileIndex(OCCUPANCY, 0.75);
const PEAK = Math.max(...OCCUPANCY);

export function DischargeWindowFigure() {
  const n = OCCUPANCY.length;
  const left = (WINDOW_START / n) * 100;
  const width = ((WINDOW_END - WINDOW_START + 1) / n) * 100;
  return (
    <figure className={styles.windowFigure}>
      <div
        className={styles.windowPlot}
        role="img"
        aria-label="Illustration: bars show how many back-tracked particles were inside the origin region at each moment. A bracket marks the middle half of those times — the inferred discharge window."
      >
        <div className={styles.windowBracket} style={{ left: `${left}%`, width: `${width}%` }}>
          <span className={styles.windowBracketLabel}>Inferred discharge window</span>
        </div>
        <div className={styles.windowBars}>
          {OCCUPANCY.map((value, i) => (
            <span
              key={i}
              className={
                i >= WINDOW_START && i <= WINDOW_END ? styles.windowBarIn : styles.windowBar
              }
              style={{ height: `${(value / PEAK) * 100}%` }}
            />
          ))}
        </div>
      </div>
      <div className={styles.windowAxis} aria-hidden="true">
        <span>← earlier (back-track runs this way)</span>
        <span>image acquired</span>
      </div>
      <figcaption className={styles.caption}>
        <span className={styles.illustrationTag}>Illustration</span>
        Bars: particles inside the origin region over time. The window is the 25th to 75th
        percentile of those times — a period, not a timestamp.
      </figcaption>
    </figure>
  );
}
