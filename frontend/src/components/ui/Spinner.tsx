import { cx } from '@/lib/cx';
import styles from './ui.module.css';

export type SpinnerSize = 'xs' | 'sm' | 'md' | 'lg';

export interface SpinnerProps {
  size?: SpinnerSize;
  /**
   * Announced to assistive technology. Pass `null` when the spinner sits inside
   * an element that already announces the busy state (e.g. a loading Button),
   * so the same thing is not read out twice.
   */
  label?: string | null;
  className?: string;
}

const SIZE_CLASS: Record<SpinnerSize, string | undefined> = {
  xs: styles.spinnerXs,
  sm: styles.spinnerSm,
  md: styles.spinnerMd,
  lg: styles.spinnerLg,
};

export function Spinner({ size = 'sm', label = 'Loading', className }: SpinnerProps) {
  return (
    <>
      <span
        className={cx(styles.spinner, SIZE_CLASS[size], className)}
        aria-hidden="true"
        data-testid="spinner"
      />
      {label ? <span className="sr-only">{label}</span> : null}
    </>
  );
}
