import type { ReactNode } from 'react';
import { cx } from '@/lib/cx';
import styles from './layout.module.css';

export interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  /** Small mono label above the title, e.g. the section of the product. */
  eyebrow?: ReactNode;
  className?: string;
}

/**
 * The single `<h1>` of a page, plus its toolbar.
 *
 * `data-page-header` is the hook the route transition in `(app)/template.tsx`
 * uses to stagger the title block and the actions in after the page itself.
 */
export function PageHeader({ title, subtitle, actions, eyebrow, className }: PageHeaderProps) {
  return (
    <div className={cx(styles.pageHeader, className)} data-page-header="">
      <div className={styles.pageHeaderText}>
        {eyebrow ? <p className={styles.pageEyebrow}>{eyebrow}</p> : null}
        <h1 className={styles.pageTitle}>{title}</h1>
        {subtitle ? <p className={styles.pageSubtitle}>{subtitle}</p> : null}
      </div>
      {actions ? <div className={styles.pageActions}>{actions}</div> : null}
    </div>
  );
}
