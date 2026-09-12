'use client';

import { useRef, type ReactNode } from 'react';
import { gsap, prefersReducedMotion, useGSAP } from '@/lib/motion/gsap';
import styles from '@/components/layout/layout.module.css';

/**
 * Route transition for the authenticated app (v3).
 *
 * A template (unlike a layout) remounts on every navigation, which is exactly
 * the hook a page entrance needs. The frame is revealed by a clip-path wipe
 * that opens from the top-left like a shutter, the page header's children rise
 * in a beat later, and the first few cards on the screen follow with a soft
 * stagger. Everything is transform/opacity/clip-path, ends inside ~700 ms, and
 * `clearProps` removes the inline styles so no lingering transform becomes the
 * containing block for a `position: fixed` descendant. Under reduced motion the
 * page is simply there.
 */
export default function AppTemplate({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement | null>(null);

  useGSAP(
    () => {
      const el = ref.current;
      if (!el || prefersReducedMotion()) return;

      const timeline = gsap.timeline({ defaults: { ease: 'expo.out' } });
      timeline.fromTo(
        el,
        { autoAlpha: 0, y: 10, clipPath: 'inset(0 0 12% 0 round 16px)' },
        {
          autoAlpha: 1,
          y: 0,
          clipPath: 'inset(0 0 0% 0 round 0px)',
          duration: 0.6,
          clearProps: 'transform,opacity,visibility,clipPath',
        },
      );

      const header = el.querySelector('[data-page-header]');
      if (header) {
        timeline.fromTo(
          header.children,
          { autoAlpha: 0, y: 16 },
          {
            autoAlpha: 1,
            y: 0,
            duration: 0.8,
            stagger: 0.06,
            clearProps: 'transform,opacity,visibility',
          },
          0.08,
        );
      }

      // The first screenful of panels: anything the page marks, else its cards.
      const panels = Array.from(
        el.querySelectorAll<HTMLElement>('[data-enter], section[class*="card"]'),
      )
        .filter((node) => node.getBoundingClientRect().top < window.innerHeight * 1.1)
        .slice(0, 8);
      if (panels.length) {
        timeline.fromTo(
          panels,
          { autoAlpha: 0, y: 18, scale: 0.985 },
          {
            autoAlpha: 1,
            y: 0,
            scale: 1,
            duration: 0.7,
            stagger: 0.045,
            clearProps: 'transform,opacity,visibility',
          },
          0.14,
        );
      }
    },
    { scope: ref },
  );

  return (
    <div ref={ref} className={styles.routeFrame}>
      {children}
    </div>
  );
}
