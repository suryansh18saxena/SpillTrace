'use client';

import { useRef } from 'react';
import { gsap, prefersReducedMotion, useGSAP } from '@/lib/motion/gsap';

/**
 * Grows every `[data-grow]` mark inside the returned ref from zero the first
 * time the chart scrolls into view. `data-grow="x"` scales horizontally,
 * `data-grow="y"` vertically. Transform-only; skipped under reduced motion,
 * in which case the marks simply render at full size.
 */
export function useGrowIn<T extends Element>(dependencies: unknown[] = []) {
  const ref = useRef<T | null>(null);

  useGSAP(
    () => {
      const root = ref.current;
      if (!root || prefersReducedMotion()) return;
      const horizontal = root.querySelectorAll('[data-grow="x"]');
      const vertical = root.querySelectorAll('[data-grow="y"]');
      const trigger = { trigger: root, start: 'top 90%', once: true };
      if (horizontal.length) {
        gsap.fromTo(
          horizontal,
          { scaleX: 0 },
          { scaleX: 1, duration: 1.1, ease: 'expo.out', stagger: 0.05, scrollTrigger: trigger },
        );
      }
      if (vertical.length) {
        gsap.fromTo(
          vertical,
          { scaleY: 0 },
          { scaleY: 1, duration: 1, ease: 'expo.out', stagger: 0.035, scrollTrigger: trigger },
        );
      }
    },
    { scope: ref, dependencies },
  );

  return ref;
}
