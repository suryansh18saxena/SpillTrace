'use client';

import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { prefersReducedMotion } from '@/lib/motion/gsap';
import { cx } from '@/lib/cx';
import styles from './motion.module.css';

export interface NumberTickerProps {
  /** The formatted value to show, e.g. "1,014" or "0.78". `null` renders "—". */
  value: string | null | undefined;
  className?: string;
  /** Milliseconds for the digit roll. */
  duration?: number;
  /** Accessible label read instead of the individual digits. */
  label?: string;
}

const DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'];

/**
 * Odometer-style digits that roll into place when the value changes.
 *
 * It only ever displays the string it is given — it never counts up to a
 * number, interpolates or rounds, so what the analyst sees is exactly the
 * server's figure at every instant. Unknown stays "—". Under reduced motion the
 * digits are simply set.
 */
export function NumberTicker({ value, className, duration = 900, label }: NumberTickerProps) {
  const [ready, setReady] = useState(false);
  const mounted = useRef(false);

  // Start from zero on first paint so the digits roll in once, then track
  // every later change directly.
  useEffect(() => {
    if (prefersReducedMotion()) {
      setReady(true);
      return;
    }
    const frame = requestAnimationFrame(() => setReady(true));
    mounted.current = true;
    return () => cancelAnimationFrame(frame);
  }, []);

  if (value === null || value === undefined || value === '') {
    return (
      <span className={cx(styles.ticker, className)} aria-label={label}>
        —
      </span>
    );
  }

  const characters = Array.from(value);
  return (
    <span
      className={cx(styles.ticker, className)}
      role="text"
      aria-label={label ?? value}
      style={{ '--ticker-duration': `${duration}ms` } as CSSProperties}
    >
      {characters.map((char, index) => {
        const digit = DIGITS.indexOf(char);
        if (digit === -1) {
          return (
            <span key={index} className={styles.tickerStatic} aria-hidden="true">
              {char}
            </span>
          );
        }
        return (
          <span key={index} className={styles.tickerDigit} aria-hidden="true">
            <span
              className={styles.tickerColumn}
              style={{ '--digit': ready ? digit : 0 } as CSSProperties}
            >
              {DIGITS.map((d) => (
                <span key={d}>{d}</span>
              ))}
            </span>
          </span>
        );
      })}
    </span>
  );
}
