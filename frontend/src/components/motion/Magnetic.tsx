'use client';

import { useRef, type ReactNode } from 'react';
import { gsap, hasFinePointer, prefersReducedMotion, useGSAP } from '@/lib/motion/gsap';

export interface MagneticProps {
  children: ReactNode;
  /** 0..1 — how far the element follows the pointer. */
  strength?: number;
  className?: string;
}

/**
 * Pulls its child gently toward the pointer while hovered, then springs back.
 *
 * Mouse/trackpad only — on touch there is no hover to follow — and skipped
 * entirely under reduced motion. The wrapper is `display: inline-flex`, so it
 * never changes the layout of the control it wraps.
 */
export function Magnetic({ children, strength = 0.32, className }: MagneticProps) {
  const ref = useRef<HTMLSpanElement | null>(null);

  useGSAP(
    (_context, contextSafe) => {
      const el = ref.current;
      if (!el || !contextSafe || prefersReducedMotion() || !hasFinePointer()) return;

      const xTo = gsap.quickTo(el, 'x', { duration: 0.6, ease: 'power3.out' });
      const yTo = gsap.quickTo(el, 'y', { duration: 0.6, ease: 'power3.out' });

      const onMove = contextSafe((event: PointerEvent) => {
        const rect = el.getBoundingClientRect();
        xTo((event.clientX - (rect.left + rect.width / 2)) * strength);
        yTo((event.clientY - (rect.top + rect.height / 2)) * strength);
      });
      const onLeave = contextSafe(() => {
        gsap.to(el, { x: 0, y: 0, duration: 0.9, ease: 'elastic.out(1, 0.4)' });
      });

      el.addEventListener('pointermove', onMove);
      el.addEventListener('pointerleave', onLeave);
      return () => {
        el.removeEventListener('pointermove', onMove);
        el.removeEventListener('pointerleave', onLeave);
      };
    },
    { scope: ref, dependencies: [strength] },
  );

  return (
    <span ref={ref} className={className} style={{ display: 'inline-flex' }}>
      {children}
    </span>
  );
}
