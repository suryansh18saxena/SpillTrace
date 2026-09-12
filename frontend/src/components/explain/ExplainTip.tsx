'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { cx } from '@/lib/cx';
import { termExplainer, type Explainer } from '@/lib/explain';
import styles from './explain.module.css';

export interface ExplainTipProps {
  /** Key into `TERMS` in `lib/explain.ts`, e.g. `"ais"` or `"origin-region"`. */
  term?: string;
  /** Supply the text directly instead of looking a term up. */
  explainer?: Explainer;
  /** The word being explained, rendered before the "?". Omit for a bare marker. */
  children?: React.ReactNode;
  className?: string;
}

/**
 * A small "?" beside a piece of jargon that opens its plain-English meaning.
 *
 * It is a real `<button>` with `aria-expanded`, so the explanation is reachable
 * by keyboard and announced by a screen reader — a `title` attribute would be
 * neither. Hover opens it for mouse users, focus and click for everyone else,
 * and Escape closes it.
 *
 * The bubble flips below the marker when there is no room above, which is what
 * happens to any term sitting in a page header.
 */
export function ExplainTip({ term, explainer, children, className }: ExplainTipProps) {
  const resolved = explainer ?? (term ? termExplainer(term) : undefined);
  const [open, setOpen] = useState(false);
  const [below, setBelow] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    const onPointer = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);

  if (!resolved) return <>{children}</>;

  const show = () => {
    // Roughly 12 rem of bubble; if that would run off the top, flip it down.
    const rect = rootRef.current?.getBoundingClientRect();
    setBelow(Boolean(rect && rect.top < 220));
    setOpen(true);
  };

  return (
    <span
      ref={rootRef}
      className={cx(styles.tipRoot, className)}
      onMouseEnter={show}
      onMouseLeave={() => setOpen(false)}
    >
      {children}
      <button
        type="button"
        className={cx(styles.tipButton, open && styles.tipButtonOpen)}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={`What is ${resolved.title}?`}
        onClick={() => (open ? setOpen(false) : show())}
        onFocus={show}
        onBlur={() => setOpen(false)}
      >
        ?
      </button>
      {open ? (
        <span id={id} role="tooltip" className={cx(styles.tipBubble, below && styles.tipBubbleBelow)}>
          <span className={styles.tipTitle}>{resolved.title}</span>
          <span className={styles.tipBody}>{resolved.body}</span>
          {resolved.caution ? <span className={styles.tipCaution}>{resolved.caution}</span> : null}
        </span>
      ) : null}
    </span>
  );
}
