'use client';

import { useRef } from 'react';
import { ScrollProgress } from '@/components/motion/ScrollProgress';
import { SmoothScroll } from '@/components/motion/SmoothScroll';
import { ScrollTrigger, useGSAP } from '@/lib/motion/gsap';
import { LandingFooter } from '../_landing/Closing';
import { CinematicNav } from './CinematicNav';
import styles from './cinematic.module.css';
import { Attribution, Backtrack, Detect, Explain, Final, Hero, Match, Segment } from './sections';
import { Stage } from './Stage';
import { scrollStore } from './timeline';

/**
 * The landing page as one continuous investigation.
 *
 * A single ScrollTrigger over the story writes the page's progress into
 * `scrollStore`; the fixed stage beneath reads it every frame to move the
 * camera and blend the scene, and each chapter's copy fades through its own
 * sticky frame on top. Inertial scrolling is scoped to this page.
 */
export function CinematicLanding() {
  const main = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      const el = main.current;
      if (!el) return;
      ScrollTrigger.create({
        trigger: el,
        start: 'top top',
        end: 'bottom bottom',
        onUpdate: (self) => {
          scrollStore.progress = self.progress;
        },
      });
      // The stage is fixed and the sections are tall; make sure the first
      // measurement happens after fonts and the 3D layer have had a frame.
      requestAnimationFrame(() => ScrollTrigger.refresh());
    },
    { scope: main },
  );

  return (
    <SmoothScroll>
      <div className={styles.page}>
        <ScrollProgress />
        <CinematicNav />
        <Stage />
        <main ref={main} id="main-content" className={styles.main}>
          <Hero />
          <Detect />
          <Segment />
          <Match />
          <Backtrack />
          <Attribution />
          <Explain />
          <Final />
        </main>
        <div className={styles.footer}>
          <LandingFooter />
        </div>
      </div>
    </SmoothScroll>
  );
}
