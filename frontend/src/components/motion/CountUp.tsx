'use client';

import { useRef } from 'react';
import { gsap, prefersReducedMotion, ScrollTrigger, useGSAP } from '@/lib/motion/gsap';

export interface CountUpProps {
  value: number;
  /** Digits after the decimal point in the final value. */
  decimals?: number;
  duration?: number;
  prefix?: string;
  suffix?: string;
  className?: string;
  /** Start when scrolled into view (default) or immediately. */
  immediate?: boolean;
  /** Locale grouping, e.g. 1,284. On by default. */
  grouping?: boolean;
}

function formatter(decimals: number, grouping: boolean) {
  const nf = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    useGrouping: grouping,
  });
  return (value: number) => nf.format(value);
}

/**
 * A number that counts up to its value when it first scrolls into view.
 *
 * The server render and every non-animated path show the *final* value, and a
 * visually-hidden copy of it is what assistive technology reads — the ticking
 * digits are `aria-hidden`, so a screen reader never announces "0.4…0.7…".
 * The animated span is keyed on the value so a new value remounts it cleanly
 * instead of React reconciling a text node GSAP has been writing to.
 */
export function CountUp({
  value,
  decimals = 0,
  duration = 1.6,
  prefix = '',
  suffix = '',
  className,
  immediate = false,
  grouping = true,
}: CountUpProps) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const format = formatter(decimals, grouping);
  const finalText = `${prefix}${format(value)}${suffix}`;

  useGSAP(
    () => {
      const el = ref.current;
      if (!el || prefersReducedMotion() || !Number.isFinite(value)) return;
      const state = { v: 0 };
      el.textContent = `${prefix}${format(0)}${suffix}`;
      const tween = gsap.to(state, {
        v: value,
        duration,
        ease: 'power3.out',
        paused: !immediate,
        onUpdate: () => {
          el.textContent = `${prefix}${format(state.v)}${suffix}`;
        },
      });
      if (!immediate) {
        ScrollTrigger.create({
          trigger: el,
          start: 'top 92%',
          once: true,
          onEnter: () => tween.play(),
        });
      }
    },
    { dependencies: [value, decimals, prefix, suffix, immediate] },
  );

  return (
    <span className={className}>
      <span className="sr-only">{finalText}</span>
      <span ref={ref} key={finalText} aria-hidden="true">
        {finalText}
      </span>
    </span>
  );
}
