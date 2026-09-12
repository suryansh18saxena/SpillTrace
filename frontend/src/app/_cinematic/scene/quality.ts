/**
 * Progressive enhancement for the 3D layer.
 *
 * The reference machine is an i3 with integrated graphics, so the default is
 * conservative and the scene only steps up when the device clearly has room.
 * `PerformanceMonitor` in the scene can still step a tier down at runtime.
 */

export type Tier = 'high' | 'low';

export interface Quality {
  tier: Tier;
  oceanSegments: number;
  particles: number;
  dust: number;
  ambientTracks: number;
  maxDpr: number;
}

export const QUALITY: Record<Tier, Quality> = {
  high: {
    tier: 'high',
    oceanSegments: 220,
    particles: 6000,
    dust: 900,
    ambientTracks: 36,
    maxDpr: 1.5,
  },
  low: {
    tier: 'low',
    oceanSegments: 120,
    particles: 2200,
    dust: 300,
    ambientTracks: 16,
    maxDpr: 1,
  },
};

export function hasWebGL(): boolean {
  if (typeof document === 'undefined') return false;
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

export function detectTier(): Tier {
  if (typeof navigator === 'undefined') return 'low';
  const cores = navigator.hardwareConcurrency ?? 4;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? 4;
  const narrow = window.matchMedia('(max-width: 900px)').matches;
  const coarse = window.matchMedia('(pointer: coarse)').matches;
  if (narrow || coarse) return 'low';
  return cores >= 8 && memory >= 8 ? 'high' : 'low';
}
