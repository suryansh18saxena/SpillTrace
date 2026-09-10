'use client';

import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react';
import { cx } from '@/lib/cx';
import { FieldShell, useFieldA11y } from './Field';
import styles from './ui.module.css';

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: ReactNode;
  id?: string;
  hint?: ReactNode;
  /** A non-empty value renders the message, sets `aria-invalid` and reddens the control. */
  error?: ReactNode;
  labelHidden?: boolean;
  optional?: boolean;
  /** Use the monospace face — for MMSI, IMO, product ids and checksums. */
  mono?: boolean;
  containerClassName?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    label,
    id,
    hint,
    error,
    labelHidden = false,
    optional = false,
    mono = false,
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
      <input
        {...rest}
        ref={ref}
        id={a11y.id}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={a11y.describedBy}
        className={cx(styles.control, mono && styles.controlMono, className)}
      />
    </FieldShell>
  );
});
