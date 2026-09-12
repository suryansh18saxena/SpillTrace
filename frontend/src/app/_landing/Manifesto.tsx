'use client';

import { useRef } from 'react';
import { cx } from '@/lib/cx';
import { gsap, prefersReducedMotion, useGSAP } from '@/lib/motion/gsap';
import styles from '../landing.module.css';

/** `*word*` marks an editorial serif accent. */
const TEXT =
  'A dark patch on radar is the easy part. Low wind, algal films and rain cells look *identical.* The hard part is everything after it — tracing the oil back, finding who was there, and doing it *honestly.*';

/**
 * The problem statement, lit word by word as it scrolls through the viewport.
 *
 * The words are real text in one paragraph, so it reads normally with
 * assistive technology and without scripting; only their opacity is scrubbed.
 */
export function Manifesto() {
  const ref = useRef<HTMLParagraphElement | null>(null);
  const words = TEXT.split(' ');

  useGSAP(
    () => {
      const el = ref.current;
      if (!el || prefersReducedMotion()) return;
      gsap.fromTo(
        el.querySelectorAll('[data-word]'),
        { opacity: 0.14 },
        {
          opacity: 1,
          ease: 'none',
          stagger: 0.08,
          scrollTrigger: { trigger: el, start: 'top 80%', end: 'bottom 45%', scrub: 0.8 },
        },
      );
    },
    { scope: ref },
  );

  return (
    <section className={styles.section}>
      <div className={styles.container}>
        <p className="eyebrow" style={{ marginBottom: 'var(--space-6)' }}>
          The problem
        </p>
        <p ref={ref} className={styles.manifesto}>
          {words.map((word, index) => {
            const accent = word.startsWith('*');
            const clean = word.replace(/\*/g, '');
            return (
              <span
                key={index}
                data-word=""
                className={cx(styles.word, accent && styles.wordSerif)}
              >
                {clean}
              </span>
            );
          })}
        </p>
      </div>
    </section>
  );
}
