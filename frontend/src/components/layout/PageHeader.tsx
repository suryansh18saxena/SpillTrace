import type { ReactNode } from 'react';
import { ScreenGuide } from '@/components/explain/ScreenGuide';
import { cx } from '@/lib/cx';
import type { Explainer } from '@/lib/explain';
import styles from './layout.module.css';

export interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  /** Small mono label above the title, e.g. the section of the product. */
  eyebrow?: ReactNode;
  /** Override the automatic "What am I looking at?" copy for this screen. */
  explainer?: Explainer;
  /** Suppress the plain-language strip (a screen that is already an explanation). */
  hideGuide?: boolean;
  className?: string;
}

/**
 * The single `<h1>` of a page, plus its toolbar.
 *
 * `data-page-header` is the hook the route transition in `(app)/template.tsx`
 * uses to stagger the title block and the actions in after the page itself.
 *
 * It also carries the screen's plain-language explanation. Putting it here means
 * every screen that has a title gets a "What am I looking at?" strip without the
 * page having to remember to ask for one, and a screen can never quietly ship
 * without an explanation.
 */
export function PageHeader({
  title,
  subtitle,
  actions,
  eyebrow,
  explainer,
  hideGuide = false,
  className,
}: PageHeaderProps) {
  return (
    <>
      <div className={cx(styles.pageHeader, className)} data-page-header="">
        <div className={styles.pageHeaderText}>
          {eyebrow ? <p className={styles.pageEyebrow}>{eyebrow}</p> : null}
          <h1 className={styles.pageTitle}>{title}</h1>
          {subtitle ? <p className={styles.pageSubtitle}>{subtitle}</p> : null}
        </div>
        {actions ? <div className={styles.pageActions}>{actions}</div> : null}
      </div>
      {hideGuide ? null : <ScreenGuide {...(explainer ? { explainer } : {})} />}
    </>
  );
}
