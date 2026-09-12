'use client';

import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import { IconInfo } from '@/components/ui/Icons';
import { cx } from '@/lib/cx';
import { screenExplainer, type Explainer } from '@/lib/explain';
import { readPreference, writePreference } from '@/lib/preferences';
import styles from './explain.module.css';

export const PREF_SCREEN_GUIDE = 'screen-guide-hidden';

export interface ScreenGuideProps {
  /** Override the automatic lookup, for a screen the pathname cannot describe. */
  explainer?: Explainer;
  className?: string;
}

/**
 * The "What am I looking at?" strip that sits under a page's title.
 *
 * Shown **expanded by default**, because someone seeing this product for the
 * first time should not have to discover the help — they should have to dismiss
 * it. Hiding it is one click and is remembered across screens and reloads, so a
 * daily analyst switches it off once and never sees it again.
 *
 * The copy lives in `lib/explain.ts`, which keeps every screen's explanation in
 * one reviewable place and stops two screens describing the same idea in two
 * different ways.
 */
export function ScreenGuide({ explainer, className }: ScreenGuideProps) {
  const pathname = usePathname() ?? '';
  const resolved = explainer ?? screenExplainer(pathname);

  // `null` until the stored preference has been read, so the server render and
  // the first client render agree and nothing flickers.
  const [hidden, setHidden] = useState<boolean | null>(null);

  useEffect(() => {
    setHidden(readPreference(PREF_SCREEN_GUIDE) === '1');
  }, []);

  if (!resolved || hidden === null) return null;

  if (hidden) {
    return (
      <button
        type="button"
        className={cx(styles.guideCollapsed, className)}
        onClick={() => {
          setHidden(false);
          writePreference(PREF_SCREEN_GUIDE, '0');
        }}
      >
        <IconInfo size={13} />
        What am I looking at?
      </button>
    );
  }

  return (
    <aside className={cx(styles.guide, className)} aria-label="What this screen shows">
      <span className={styles.guideIcon} aria-hidden="true">
        <IconInfo size={16} />
      </span>
      <div className={styles.guideText}>
        <span className={styles.guideTitle}>{resolved.title}</span>
        <p className={styles.guideBody}>{resolved.body}</p>
        {resolved.caution ? (
          <p className={styles.guideCaution}>
            <span className={styles.guideCautionLabel}>Careful:</span>
            <span>{resolved.caution}</span>
          </p>
        ) : null}
      </div>
      <button
        type="button"
        className={styles.guideToggle}
        onClick={() => {
          setHidden(true);
          writePreference(PREF_SCREEN_GUIDE, '1');
        }}
      >
        Hide
      </button>
    </aside>
  );
}
