import Link from 'next/link';
import type { ComponentProps, ReactNode } from 'react';
import { cx } from '@/lib/cx';
import type { ButtonSize, ButtonVariant } from './Button';
import styles from './ui.module.css';

export interface LinkButtonProps extends Omit<ComponentProps<typeof Link>, 'className'> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  fullWidth?: boolean;
  leadingIcon?: ReactNode;
  className?: string;
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
 * A navigation link that *looks* like a button.
 *
 * Kept separate from `<Button>` on purpose: a thing that navigates must be an
 * `<a>` so it works with middle-click, "open in new tab", and the screen-reader
 * links list. Wrapping a `<Link>` inside a `<button>` would be invalid HTML and
 * break all three.
 */
export function LinkButton({
  variant = 'secondary',
  size = 'md',
  fullWidth = false,
  leadingIcon,
  className,
  children,
  ...rest
}: LinkButtonProps) {
  return (
    <Link
      {...rest}
      className={cx(
        styles.button,
        VARIANT_CLASS[variant],
        SIZE_CLASS[size],
        fullWidth && styles.buttonFullWidth,
        className,
      )}
    >
      <span className={styles.buttonInner}>
        {leadingIcon}
        {children}
      </span>
    </Link>
  );
}
