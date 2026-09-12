'use client';

import { useRef, type CSSProperties, type ReactNode } from 'react';
import { gsap, prefersReducedMotion, useGSAP } from '@/lib/motion/gsap';

export interface ParallaxProps {
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  /**
   * Depth. Positive values drift up faster than the page (foreground),
   * negative values lag behind it (background). 0.2 is subtle; 0.6 is a lot.
   */
  speed?: number;
  /** Also rotate while scrolling, in degrees over the element's scroll range. */
  rotate?: number;
  'aria-hidden'?: boolean;
}

/**
 * Scroll-linked depth: the element translates at a different rate from the page
 * while it crosses the viewport. Transform-only, scrubbed by ScrollTrigger, and
 * inert under reduced motion.
 */
export function Parallax({
  children,
  className,
  style,
  speed = 0.2,
  rotate = 0,
  'aria-hidden': ariaHidden,
}: ParallaxProps) {
  const ref = useRef<HTMLDivElement | null>(null);

  useGSAP(
    () => {
      const el = ref.current;
      if (!el || prefersReducedMotion()) return;
      const distance = () => window.innerHeight * speed * 0.5;
      gsap.fromTo(
        el,
        { y: () => distance(), rotate: -rotate / 2 },
        {
          y: () => -distance(),
          rotate: rotate / 2,
          ease: 'none',
          scrollTrigger: {
            trigger: el,
            start: 'top bottom',
            end: 'bottom top',
            scrub: true,
            invalidateOnRefresh: true,
          },
        },
      );
    },
    { scope: ref, dependencies: [speed, rotate] },
  );

  return (
    <div ref={ref} className={className} style={style} aria-hidden={ariaHidden}>
      {children}
    </div>
  );
}
