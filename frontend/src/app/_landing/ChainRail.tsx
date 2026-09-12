'use client';

import { useRef } from 'react';
import { useSpotlight } from '@/components/motion/useSpotlight';
import { gsap, prefersReducedMotion, useGSAP } from '@/lib/motion/gsap';
import styles from '../landing.module.css';
import { STAGES, type Stage } from './content';

function RailCard({ stage, index }: { stage: Stage; index: number }) {
  const ref = useSpotlight<HTMLLIElement>();
  return (
    <li ref={ref} className={styles.railCard} data-rail-card="">
      <span className={styles.railIndex} aria-hidden="true">
        {String(index + 1).padStart(2, '0')}
      </span>
      <h3 className={styles.railName}>{stage.name}</h3>
      <code className={styles.railJob}>{stage.job}</code>
      <p className={styles.railText}>{stage.text}</p>
    </li>
  );
}

/**
 * The thirteen stages as one horizontal rail.
 *
 * On wide screens the section pins and vertical scroll drives the rail
 * sideways; on narrow screens, and under reduced motion, it is simply a
 * vertical list. `gsap.matchMedia` reverts the pin cleanly when the viewport
 * crosses the breakpoint.
 */
export function ChainRail() {
  const root = useRef<HTMLElement | null>(null);

  useGSAP(
    () => {
      const el = root.current;
      if (!el || prefersReducedMotion()) return;
      const mm = gsap.matchMedia();
      mm.add('(min-width: 48.01rem)', () => {
        const pin = el.querySelector<HTMLElement>('[data-rail-pin]');
        const track = el.querySelector<HTMLElement>('[data-rail-track]');
        const progress = el.querySelector<HTMLElement>('[data-rail-progress]');
        if (!pin || !track) return;
        // Switch the CSS from "wrapping grid" to "one long row" only now that
        // the pin is really going to drive it; `mm.revert()` undoes it.
        pin.setAttribute('data-rail-active', '');
        const distance = () => Math.max(0, track.scrollWidth - window.innerWidth);

        const tl = gsap.timeline({
          scrollTrigger: {
            trigger: pin,
            start: 'top top',
            end: () => `+=${distance()}`,
            pin: true,
            scrub: 0.8,
            invalidateOnRefresh: true,
            anticipatePin: 1,
          },
        });
        tl.to(track, { x: () => -distance(), ease: 'none' }, 0);
        if (progress) tl.fromTo(progress, { scaleX: 0 }, { scaleX: 1, ease: 'none' }, 0);

        gsap.from(el.querySelectorAll('[data-rail-card]'), {
          autoAlpha: 0,
          y: 40,
          duration: 1,
          stagger: 0.06,
          ease: 'expo.out',
          scrollTrigger: { trigger: pin, start: 'top 75%', once: true },
        });
        return () => pin.removeAttribute('data-rail-active');
      });
      return () => mm.revert();
    },
    { scope: root },
  );

  return (
    <section ref={root} className={styles.railSection} id="stages" aria-labelledby="stages-title">
      <div className={styles.container}>
        <div className={styles.sectionHead} style={{ marginBottom: 0 }}>
          <span className="eyebrow">The reasoning chain</span>
          <h2 className={styles.sectionTitle} id="stages-title">
            Thirteen stages, <em>each one inspectable</em>
          </h2>
          <p className={styles.sectionLede}>
            Every stage runs as a tracked background job, writes an artifact you can open, and
            records the software version, provider parameters, random seed and input checksums
            needed to reproduce it. Any stage can be re-run with different parameters.
          </p>
        </div>
      </div>
      <div className={styles.railPin} data-rail-pin="">
        <div className={styles.railProgress} aria-hidden="true">
          <span data-rail-progress="" />
        </div>
        <ol className={styles.railTrack} data-rail-track="">
          {STAGES.map((stage, index) => (
            <RailCard key={stage.job} stage={stage} index={index} />
          ))}
        </ol>
      </div>
    </section>
  );
}
