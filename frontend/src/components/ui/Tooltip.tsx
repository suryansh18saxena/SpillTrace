'use client';

import {
  cloneElement,
  useCallback,
  useId,
  useState,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
} from 'react';
import { cx } from '@/lib/cx';
import styles from './ui.module.css';

type TriggerProps = {
  'aria-describedby'?: string;
};

export interface TooltipProps {
  /** Supplementary detail only. Never put information here that is required. */
  content: ReactNode;
  children: ReactElement<TriggerProps>;
  className?: string;
}

/**
 * Hover **and** focus triggered tooltip wired with `aria-describedby`, dismissed
 * with Escape (WCAG 1.4.13). It carries supplementary detail only — anything an
 * analyst must read to act is rendered in the page, not in a tooltip.
 */
export function Tooltip({ content, children, className }: TooltipProps) {
  const id = useId();
  const [open, setOpen] = useState(false);

  const show = useCallback(() => setOpen(true), []);
  const hide = useCallback(() => setOpen(false), []);
  const handleKeyDown = useCallback((event: KeyboardEvent<HTMLSpanElement>) => {
    if (event.key === 'Escape') setOpen(false);
  }, []);

  return (
    <span
      className={cx(styles.tooltipRoot, className)}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocusCapture={show}
      onBlurCapture={hide}
      onKeyDown={handleKeyDown}
    >
      {cloneElement(children, { 'aria-describedby': open ? id : undefined })}
      {open ? (
        <span role="tooltip" id={id} className={styles.tooltipBubble}>
          {content}
        </span>
      ) : null}
    </span>
  );
}
