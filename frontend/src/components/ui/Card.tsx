'use client';

import { createElement, type ElementType, type ReactNode } from 'react';
import { useSpotlight } from '@/components/motion/useSpotlight';
import { cx } from '@/lib/cx';
import styles from './ui.module.css';

export type CardVariant = 'glass' | 'solid' | 'neo';

export interface CardProps {
  title?: ReactNode;
  description?: ReactNode;
  /** Toolbar shown on the right of the header. */
  actions?: ReactNode;
  footer?: ReactNode;
  /** Removes body padding — use when the body is a full-bleed table or map. */
  flush?: boolean;
  /** Heading level for the card title; keep the document outline sane. */
  titleAs?: ElementType;
  as?: ElementType;
  /**
   * `glass` (default) is a frosted panel over the aurora; `solid` is opaque for
   * dense data (tables, reports); `neo` is a soft machined block for controls.
   */
  variant?: CardVariant;
  /** Lifts on hover and lights up under the cursor — for cards that are links. */
  interactive?: boolean;
  className?: string;
  bodyClassName?: string;
  children?: ReactNode;
}

const VARIANT_CLASS: Record<CardVariant, string | undefined> = {
  glass: undefined,
  solid: styles.cardSolid,
  neo: styles.cardNeo,
};

export function Card({
  title,
  description,
  actions,
  footer,
  flush = false,
  titleAs: TitleTag = 'h2',
  as: Tag = 'section',
  variant = 'glass',
  interactive = false,
  className,
  bodyClassName,
  children,
}: CardProps) {
  const spot = useSpotlight<HTMLElement>();
  // createElement rather than <Tag>/<TitleTag>: with a bare `ElementType` tag,
  // React 19.3's types collapse the JSX props to `never`.
  return createElement(
    Tag,
    {
      ref: interactive ? spot : undefined,
      className: cx(
        styles.card,
        VARIANT_CLASS[variant],
        interactive && styles.cardInteractive,
        interactive && styles.cardSpot,
        className,
      ),
    },
    title || actions || description ? (
      <header className={styles.cardHeader}>
        <div className={styles.cardHeaderText}>
          {title ? createElement(TitleTag, { className: styles.cardTitle }, title) : null}
          {description ? <p className={styles.cardDescription}>{description}</p> : null}
        </div>
        {actions ? <div className={styles.cardActions}>{actions}</div> : null}
      </header>
    ) : null,
    children !== undefined ? (
      <div className={cx(styles.cardBody, flush && styles.cardBodyFlush, bodyClassName)}>
        {children}
      </div>
    ) : null,
    footer ? <footer className={styles.cardFooter}>{footer}</footer> : null,
  );
}
