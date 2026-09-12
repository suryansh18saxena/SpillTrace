'use client';

import { createElement, useRef, type CSSProperties, type ElementType, type ReactNode } from 'react';
import { gsap, prefersReducedMotion, useGSAP } from '@/lib/motion/gsap';

export interface RevealProps {
  as?: ElementType;
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  id?: string;
  /** Distance travelled on the way in, in px. */
  y?: number;
  delay?: number;
  duration?: number;
  /**
   * Stagger the direct children (or `selector` matches) instead of moving the
   * container as one block. Seconds between each.
   */
  stagger?: number;
  selector?: string;
  /** Animate on mount rather than when scrolled into view. */
  immediate?: boolean;
  /** ScrollTrigger start position. */
  start?: string;
  /** Extra props for the rendered element (aria-*, role, data-*). */
  [key: `aria-${string}` | `data-${string}`]: string | number | boolean | undefined;
  role?: string;
}

/**
 * Fades and lifts content into place the first time it scrolls into view.
 *
 * The element carries `data-reveal`, which `globals.css` pre-hides before first
 * paint — but only when motion is allowed and scripting ran — so there is no
 * flash of content that then vanishes and re-animates. Under reduced motion the
 * content is simply there.
 */
export function Reveal({
  as: Tag = 'div',
  children,
  className,
  style,
  id,
  y = 28,
  delay = 0,
  duration = 1,
  stagger = 0,
  selector,
  immediate = false,
  start = 'top 88%',
  role,
  ...rest
}: RevealProps) {
  const ref = useRef<HTMLElement | null>(null);

  useGSAP(
    () => {
      const el = ref.current;
      if (!el) return;
      el.setAttribute('data-reveal-ready', '');
      if (prefersReducedMotion()) return;

      const targets: gsap.TweenTarget = stagger
        ? selector
          ? el.querySelectorAll(selector)
          : Array.from(el.children)
        : el;

      gsap.fromTo(
        targets,
        { autoAlpha: 0, y },
        {
          autoAlpha: 1,
          y: 0,
          duration,
          delay,
          stagger,
          ease: 'expo.out',
          clearProps: 'transform',
          ...(immediate ? {} : { scrollTrigger: { trigger: el, start, once: true } }),
        },
      );
    },
    { scope: ref },
  );

  // createElement rather than <Tag>: with a bare `ElementType` tag, React 19.3's
  // types collapse the JSX props to `never`.
  return createElement(
    Tag,
    { ref, id, className, style, role, 'data-reveal': '', ...rest },
    children,
  );
}
