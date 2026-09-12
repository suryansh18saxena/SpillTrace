'use client';

import Lenis from 'lenis';
import 'lenis/dist/lenis.css';
import { useEffect, type ReactNode } from 'react';
import { gsap, prefersReducedMotion, ScrollTrigger } from '@/lib/motion/gsap';

/**
 * Inertial scrolling for the public, long-form pages only.
 *
 * Never mounted inside the authenticated app: investigation screens have maps
 * and nested scroll panes that must behave exactly like native scrolling.
 *
 * Lenis is driven by GSAP's ticker so ScrollTrigger scrubs stay locked to the
 * smoothed position, and in-page `#anchor` links are routed through it so they
 * glide instead of jumping. Under reduced motion none of this runs and the page
 * scrolls natively.
 */
export function SmoothScroll({ children }: { children: ReactNode }) {
  useEffect(() => {
    if (prefersReducedMotion()) return;

    const lenis = new Lenis({ duration: 1.15, smoothWheel: true, anchors: false });
    lenis.on('scroll', ScrollTrigger.update);
    const tick = (time: number) => lenis.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);

    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey) return;
      const anchor = (event.target as Element | null)?.closest?.('a[href^="#"]');
      if (!anchor) return;
      const hash = anchor.getAttribute('href');
      if (!hash || hash === '#') return;
      const target = document.querySelector(hash);
      if (!target) return;
      event.preventDefault();
      lenis.scrollTo(target as HTMLElement, { offset: -72 });
      history.replaceState(null, '', hash);
    };
    document.addEventListener('click', onClick);

    return () => {
      document.removeEventListener('click', onClick);
      gsap.ticker.remove(tick);
      gsap.ticker.lagSmoothing(500, 33);
      lenis.destroy();
    };
  }, []);

  return <>{children}</>;
}
