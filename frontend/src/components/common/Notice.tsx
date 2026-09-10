import type { ReactNode } from 'react';
import { IconAlert, IconInfo } from '@/components/ui/Icons';
import { cx } from '@/lib/cx';
import styles from './common.module.css';

export type NoticeTone = 'neutral' | 'caution' | 'info' | 'synthetic';

export interface NoticeProps {
  /**
   * The server's own `notice` / `disclaimer` string. Rendered verbatim — never
   * paraphrased, shortened or summarised. When it is null the component renders
   * nothing, so a caller can pass an optional field straight through.
   */
  text?: string | null;
  label?: string;
  tone?: NoticeTone;
  children?: ReactNode;
  className?: string;
}

const TONE_CLASS: Record<NoticeTone, string | undefined> = {
  neutral: undefined,
  caution: styles.noticeCaution,
  info: styles.noticeInfo,
  synthetic: styles.noticeSynthetic,
};

/**
 * The API's standing caveats (CON-001, CON-003, CON-008, CON-009).
 *
 * Detections, origin regions, vessel absence, AIS gaps and attribution scores
 * each carry a `notice` explaining what the number does *not* mean. Those
 * strings are part of the product's honesty guarantee, so this component is
 * deliberately dumb: it lays the text out and never touches it.
 */
export function Notice({ text, label, tone = 'caution', children, className }: NoticeProps) {
  const body = text?.trim();
  if (!body && !children) return null;

  return (
    <p className={cx(styles.notice, TONE_CLASS[tone], className)} data-testid="api-notice">
      <span className={styles.noticeIcon}>
        {tone === 'info' ? <IconInfo size={15} /> : <IconAlert size={15} />}
      </span>
      <span className={styles.noticeBody}>
        {label ? <span className={styles.noticeLabel}>{label}</span> : null}
        {body}
        {children}
      </span>
    </p>
  );
}

export interface NoticeStackProps {
  /** Duplicates and blanks are dropped, so several sources can be passed in. */
  notices: ReadonlyArray<string | null | undefined>;
  label?: string;
  tone?: NoticeTone;
  className?: string;
}

/** Several server notices at once, de-duplicated. */
export function NoticeStack({ notices, label, tone = 'caution', className }: NoticeStackProps) {
  const unique = Array.from(
    new Set(
      notices.map((notice) => notice?.trim()).filter((notice): notice is string => Boolean(notice)),
    ),
  );
  if (unique.length === 0) return null;
  return (
    <div className={cx(styles.noticeStack, className)}>
      {unique.map((notice) => (
        <Notice key={notice} text={notice} label={label} tone={tone} />
      ))}
    </div>
  );
}
