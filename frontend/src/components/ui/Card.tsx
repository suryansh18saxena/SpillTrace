import type { ElementType, ReactNode } from 'react';
import { cx } from '@/lib/cx';
import styles from './ui.module.css';

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
  className?: string;
  bodyClassName?: string;
  children?: ReactNode;
}

export function Card({
  title,
  description,
  actions,
  footer,
  flush = false,
  titleAs: TitleTag = 'h2',
  as: Tag = 'section',
  className,
  bodyClassName,
  children,
}: CardProps) {
  return (
    <Tag className={cx(styles.card, className)}>
      {title || actions || description ? (
        <header className={styles.cardHeader}>
          <div className={styles.cardHeaderText}>
            {title ? <TitleTag className={styles.cardTitle}>{title}</TitleTag> : null}
            {description ? <p className={styles.cardDescription}>{description}</p> : null}
          </div>
          {actions ? <div className={styles.cardActions}>{actions}</div> : null}
        </header>
      ) : null}
      {children !== undefined ? (
        <div className={cx(styles.cardBody, flush && styles.cardBodyFlush, bodyClassName)}>
          {children}
        </div>
      ) : null}
      {footer ? <footer className={styles.cardFooter}>{footer}</footer> : null}
    </Tag>
  );
}
