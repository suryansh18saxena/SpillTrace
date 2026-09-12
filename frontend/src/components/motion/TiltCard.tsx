'use client';

import {
  createElement,
  useCallback,
  useEffect,
  useRef,
  type CSSProperties,
  type ElementType,
  type ReactNode,
} from 'react';
import { hasFinePointer, prefersReducedMotion } from '@/lib/motion/gsap';
import { cx } from '@/lib/cx';
import styles from './motion.module.css';

export interface TiltCardProps {
  as?: ElementType;
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
  /** Maximum lean in degrees. */
  max?: number;
  /** Draw a moving light where the pointer is. */
  glare?: boolean;
  id?: string;
}

/**
 * A card that leans towards the pointer and springs back — the "physical
 * object" feeling of glass panels.
 *
 * Only transforms and custom properties change (no layout, no React state), and
 * the effect is skipped entirely on touch devices and under reduced motion so
 * those visitors get a perfectly ordinary, still card.
 */
export function TiltCard({
  as: Tag = 'div',
  children,
  className,
  style,
  max = 6,
  glare = true,
  id,
}: TiltCardProps) {
  const ref = useRef<HTMLElement | null>(null);
  const frame = useRef(0);
  const last = useRef<PointerEvent | null>(null);

  const flush = useCallback(() => {
    frame.current = 0;
    const el = ref.current;
    const event = last.current;
    if (!el || !event) return;
    const rect = el.getBoundingClientRect();
    const px = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const py = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    el.style.setProperty('--tilt-x', `${((0.5 - py) * max).toFixed(2)}deg`);
    el.style.setProperty('--tilt-y', `${((px - 0.5) * max).toFixed(2)}deg`);
    el.style.setProperty('--glare-x', `${(px * 100).toFixed(1)}%`);
    el.style.setProperty('--glare-y', `${(py * 100).toFixed(1)}%`);
    el.style.setProperty('--glare-o', '1');
  }, [max]);

  useEffect(() => {
    const el = ref.current;
    if (!el || !hasFinePointer() || prefersReducedMotion()) return;

    const onMove = (event: PointerEvent) => {
      last.current = event;
      el.classList.add(styles.tiltActive ?? '');
      if (!frame.current) frame.current = requestAnimationFrame(flush);
    };
    const onLeave = () => {
      last.current = null;
      el.classList.remove(styles.tiltActive ?? '');
      el.style.setProperty('--tilt-x', '0deg');
      el.style.setProperty('--tilt-y', '0deg');
      el.style.setProperty('--glare-o', '0');
    };
    el.addEventListener('pointermove', onMove);
    el.addEventListener('pointerleave', onLeave);
    return () => {
      el.removeEventListener('pointermove', onMove);
      el.removeEventListener('pointerleave', onLeave);
      if (frame.current) cancelAnimationFrame(frame.current);
    };
  }, [flush]);

  // createElement rather than <Tag>: see Reveal.tsx.
  return createElement(
    Tag,
    { ref, id, className: cx(styles.tilt, className), style },
    children,
    glare ? <span className={styles.glare} aria-hidden="true" /> : null,
  );
}
