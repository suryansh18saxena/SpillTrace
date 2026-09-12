import * as THREE from 'three';

/**
 * Scene colours, read from the design tokens at mount so the WebGL layer and
 * the DOM share one palette. The fallbacks are the dark-theme values from
 * `styles/tokens.css`; the cinematic page pins itself to the dark theme, so in
 * practice these are the values in use.
 */

const TOKENS = {
  bg: ['--color-bg', '#03060c'],
  ocean: ['--map-ocean', '#07121f'],
  oceanDeep: ['--map-ocean-deep', '#040a13'],
  horizon: ['--map-horizon', '#2b5c9e'],
  sky: ['--map-sky', '#0b1a2e'],
  accent: ['--color-accent', '#4f8dff'],
  accent2: ['--color-accent-2', '#3dd5ff'],
  spill: ['--map-spill', '#f2c24c'],
  origin: ['--map-origin', '#a77bff'],
  vessel: ['--map-vessel', '#5fd3c4'],
  track: ['--map-track', '#7a8798'],
  confidence1: ['--confidence-1', '#726c61'],
  confidence2: ['--confidence-2', '#bf8a33'],
  confidence3: ['--confidence-3', '#f2c24c'],
  text: ['--color-text', '#eaf0f9'],
} as const;

export type Palette = { -readonly [K in keyof typeof TOKENS]: THREE.Color };

export function readPalette(): Palette {
  const style = typeof window !== 'undefined' ? getComputedStyle(document.documentElement) : null;
  const out = {} as Palette;
  for (const key of Object.keys(TOKENS) as (keyof typeof TOKENS)[]) {
    const [name, fallback] = TOKENS[key];
    const raw = style?.getPropertyValue(name).trim();
    const value = raw && /^#[0-9a-f]{6}$/i.test(raw) ? raw : fallback;
    out[key] = new THREE.Color(value);
  }
  return out;
}
