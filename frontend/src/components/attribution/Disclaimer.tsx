import { IconAlert } from '@/components/ui/Icons';
import { INVESTIGATIVE_DISCLAIMER } from '@/lib/config';
import { cx } from '@/lib/cx';
import styles from './attribution.module.css';

export interface DisclaimerProps {
  /**
   * The `disclaimer` string from the API response. API.md §10 makes it mandatory
   * and non-empty on every attribution, and it is what actually gets shown —
   * this component never rewrites or shortens it.
   */
  text?: string | null;
  label?: string;
  className?: string;
}

/**
 * The standing investigative-evidence notice (CON-001, CON-003, MVP-11, AC-13).
 *
 * It must accompany every score, ranking and candidate vessel in the product.
 * When the server supplied a `disclaimer` that text is authoritative; the local
 * constant is only a floor for the case where a response predates the field, so
 * that a missing string can never result in an unlabelled score.
 */
export function Disclaimer({ text, label = 'Investigative evidence', className }: DisclaimerProps) {
  const body = text && text.trim() ? text : INVESTIGATIVE_DISCLAIMER;
  return (
    <p className={cx(styles.disclaimer, className)} data-testid="attribution-disclaimer">
      <span className={styles.disclaimerIcon}>
        <IconAlert size={15} />
      </span>
      <span className={styles.disclaimerText}>
        <span className={styles.disclaimerLabel}>{label}</span>
        {body}
      </span>
    </p>
  );
}
