'use client';

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cx } from '@/lib/cx';
import { Spinner } from './Spinner';
import styles from './ui.module.css';

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner, sets `aria-busy` and blocks further clicks. */
  loading?: boolean;
  /** What assistive technology announces while `loading`. */
  loadingLabel?: string;
  fullWidth?: boolean;
  /** Square button with no visible text — `aria-label` then becomes mandatory. */
  iconOnly?: boolean;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
}

const VARIANT_CLASS: Record<ButtonVariant, string | undefined> = {
  primary: styles.buttonPrimary,
  secondary: styles.buttonSecondary,
  ghost: styles.buttonGhost,
  danger: styles.buttonDanger,
};

const SIZE_CLASS: Record<ButtonSize, string | undefined> = {
  sm: styles.buttonSm,
  md: styles.buttonMd,
  lg: styles.buttonLg,
};

/**
 * The one button in the application.
 *
 * While `loading`, the label stays in the DOM but invisible so the button does
 * not change width and the layout does not jump — a small thing that matters a
 * lot on a dense screen where a button sits inside a toolbar.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'secondary',
    size = 'md',
    loading = false,
    loadingLabel = 'Working',
    fullWidth = false,
    iconOnly = false,
    leadingIcon,
    trailingIcon,
    disabled,
    className,
    children,
    type = 'button',
    ...rest
  },
  ref,
) {
  const isDisabled = disabled || loading;
  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      className={cx(
        styles.button,
        VARIANT_CLASS[variant],
        SIZE_CLASS[size],
        fullWidth && styles.buttonFullWidth,
        iconOnly && styles.buttonIconOnly,
        className,
      )}
    >
      <span className={styles.buttonInner}>
        {loading ? (
          <span className={styles.buttonSpinnerSlot}>
            <Spinner size={size === 'lg' ? 'sm' : 'xs'} label={loadingLabel} />
          </span>
        ) : null}
        <span className={cx(styles.buttonInner, loading && styles.buttonLabelHidden)}>
          {leadingIcon}
          {children}
          {trailingIcon}
        </span>
      </span>
    </button>
  );
});
