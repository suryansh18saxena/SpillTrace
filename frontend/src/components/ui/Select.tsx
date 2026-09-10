'use client';

import { forwardRef, type ReactNode, type SelectHTMLAttributes } from 'react';
import { cx } from '@/lib/cx';
import { FieldShell, useFieldA11y } from './Field';
import styles from './ui.module.css';

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id'> {
  label: ReactNode;
  id?: string;
  options: readonly SelectOption[];
  hint?: ReactNode;
  error?: ReactNode;
  labelHidden?: boolean;
  optional?: boolean;
  /** Placeholder entry rendered as a disabled first option. */
  placeholder?: string;
  containerClassName?: string;
}

/**
 * A native `<select>`. Custom listboxes are where keyboard and screen-reader
 * support usually goes to die; the native control is already correct on every
 * platform including mobile, so it is only restyled, never replaced.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  {
    label,
    id,
    options,
    hint,
    error,
    labelHidden = false,
    optional = false,
    placeholder,
    required,
    className,
    containerClassName,
    ...rest
  },
  ref,
) {
  const a11y = useFieldA11y(id, Boolean(hint), Boolean(error));
  return (
    <FieldShell
      a11y={a11y}
      label={label}
      hint={hint}
      error={error}
      required={required}
      optional={optional}
      labelHidden={labelHidden}
      className={containerClassName}
    >
      <span className={styles.selectWrap}>
        <select
          {...rest}
          ref={ref}
          id={a11y.id}
          required={required}
          aria-invalid={error ? true : undefined}
          aria-describedby={a11y.describedBy}
          className={cx(styles.control, styles.select, className)}
        >
          {placeholder ? (
            <option value="" disabled>
              {placeholder}
            </option>
          ) : null}
          {options.map((option) => (
            <option key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </option>
          ))}
        </select>
        <span className={styles.selectArrow} aria-hidden="true">
          ▼
        </span>
      </span>
    </FieldShell>
  );
});
