'use client';

import { useRef, type ElementType, type ReactNode } from 'react';
import { gsap, prefersReducedMotion, SplitText, useGSAP } from '@/lib/motion/gsap';

export interface SplitRevealProps {
  as?: ElementType;
  children: ReactNode;
  className?: string;
  id?: string;
  /** Split into masked lines (headlines) or words (short phrases). */
  by?: 'lines' | 'words';
  delay?: number;
  stagger?: number;
  /** Play on mount instead of on scroll-into-view. */
  immediate?: boolean;
}

/**
 * A headline whose lines rise out of a mask, one after another.
 *
 * SplitText keeps the element accessible: it puts the full text on the parent
 * as `aria-label` and hides the generated fragments, so a screen reader reads
 * the sentence once. `autoSplit` re-splits after the web fonts load and on
 * resize, so line breaks are always computed with the real typeface.
 */
export function SplitReveal({
  as: Tag = 'h2',
  children,
  className,
  id,
  by = 'lines',
  delay = 0,
  stagger = 0.09,
  immediate = false,
}: SplitRevealProps) {
  const ref = useRef<HTMLElement | null>(null);

  useGSAP(
    () => {
      const el = ref.current;
      if (!el) return;
      el.setAttribute('data-reveal-ready', '');
      if (prefersReducedMotion()) return;

      let played = false;
      const split = SplitText.create(el, {
        type: by === 'lines' ? 'lines' : 'words',
        mask: by === 'lines' ? 'lines' : 'words',
        autoSplit: true,
        onSplit(self) {
          const targets = by === 'lines' ? self.lines : self.words;
          // A re-split after the first reveal (fonts loading, resize) must not
          // replay the entrance — it just lays the text out again.
          if (played) return undefined;
          played = true;
          return gsap.from(targets, {
            yPercent: 115,
            duration: 1.15,
            ease: 'expo.out',
            stagger,
            delay,
            ...(immediate ? {} : { scrollTrigger: { trigger: el, start: 'top 88%', once: true } }),
          });
        },
      });
      return () => split.revert();
    },
    { scope: ref },
  );

  return (
    <Tag ref={ref} id={id} className={className} data-reveal="">
      {children}
    </Tag>
  );
}
