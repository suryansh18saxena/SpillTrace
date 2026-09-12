'use client';

/**
 * The one place GSAP plugins are registered.
 *
 * Every animated component imports from here rather than from `gsap` directly,
 * so a plugin is registered exactly once and never on the server (GSAP touches
 * `window` at registration time).
 *
 * All motion in the product is decorative. Nothing a screen needs to be
 * understood is ever conveyed only by an animation, and every entry point below
 * honours `prefers-reduced-motion` — see `prefersReducedMotion()`.
 */

import { useGSAP } from '@gsap/react';
import { gsap } from 'gsap';
import { DrawSVGPlugin } from 'gsap/DrawSVGPlugin';
import { MotionPathPlugin } from 'gsap/MotionPathPlugin';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { SplitText } from 'gsap/SplitText';

if (typeof window !== 'undefined') {
  gsap.registerPlugin(useGSAP, ScrollTrigger, SplitText, DrawSVGPlugin, MotionPathPlugin);
  gsap.defaults({ ease: 'expo.out', duration: 0.9 });
}

/** `true` when the visitor asked the OS for reduced motion (or on the server). */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** `true` on a mouse/trackpad device — hover-only effects are skipped on touch. */
export function hasFinePointer(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  return window.matchMedia('(hover: hover) and (pointer: fine)').matches;
}

export { DrawSVGPlugin, gsap, MotionPathPlugin, ScrollTrigger, SplitText, useGSAP };
