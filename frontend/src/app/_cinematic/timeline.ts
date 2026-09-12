/**
 * The scroll timeline shared by the DOM story and the WebGL scene.
 *
 * The page is one continuous sequence: every section declares its height in
 * viewport units, and the same table gives the scene the progress range each
 * section occupies. Neither side guesses where the other is.
 *
 * `scrollStore` is a plain mutable object, written once per scroll event by a
 * single ScrollTrigger and read once per frame by the scene and the HUD. No
 * React state is involved on the frame path.
 */

export const SECTIONS = [
  { id: 'hero', label: 'Signal', vh: 170 },
  { id: 'detect', label: 'Detect', vh: 150 },
  { id: 'segment', label: 'Segment', vh: 150 },
  { id: 'match', label: 'Match', vh: 170 },
  { id: 'backtrack', label: 'Backtrack', vh: 200 },
  { id: 'attribution', label: 'Attribute', vh: 170 },
  { id: 'explain', label: 'Explain', vh: 170 },
  { id: 'final', label: 'Trace', vh: 150 },
] as const;

export type SectionId = (typeof SECTIONS)[number]['id'];

export const TOTAL_VH = SECTIONS.reduce((sum, s) => sum + s.vh, 0);

const RANGES: Record<SectionId, readonly [number, number]> = (() => {
  const out = {} as Record<SectionId, readonly [number, number]>;
  let acc = 0;
  for (const s of SECTIONS) {
    out[s.id] = [acc / TOTAL_VH, (acc + s.vh) / TOTAL_VH];
    acc += s.vh;
  }
  return out;
})();

export function sectionRange(id: SectionId): readonly [number, number] {
  return RANGES[id];
}

export function sectionIndex(progress: number): number {
  for (let i = SECTIONS.length - 1; i >= 0; i -= 1) {
    if (progress >= RANGES[SECTIONS[i]!.id][0]) return i;
  }
  return 0;
}

export const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);
export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
export const smoothstep = (a: number, b: number, x: number) => {
  const t = clamp01((x - a) / (b - a));
  return t * t * (3 - 2 * t);
};
export const easeInOut = (t: number) => smoothstep(0, 1, t);

/** 0 → 1 across one section. */
export function phase(progress: number, id: SectionId): number {
  const [a, b] = RANGES[id];
  return clamp01((progress - a) / (b - a));
}

/** 0 → 1 across a span of sections, `from` start to `to` end. */
export function phaseAcross(progress: number, from: SectionId, to: SectionId): number {
  const a = RANGES[from][0];
  const b = RANGES[to][1];
  return clamp01((progress - a) / (b - a));
}

/** A ramp within a section's own phase: 0 before `a`, 1 after `b`, smooth between. */
export function ramp(progress: number, id: SectionId, a: number, b: number): number {
  return smoothstep(a, b, phase(progress, id));
}

export interface ScrollStore {
  progress: number;
  section: number;
  pointerX: number;
  pointerY: number;
}

export const scrollStore: ScrollStore = { progress: 0, section: 0, pointerX: 0, pointerY: 0 };

/** Deterministic PRNG so the scene lays out identically on every visit. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Box–Muller, for the per-particle wind-drift factor. */
export function gaussian(rand: () => number): number {
  const u = Math.max(rand(), 1e-9);
  const v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}
