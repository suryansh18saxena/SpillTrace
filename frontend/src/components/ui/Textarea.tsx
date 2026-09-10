'use client';

import { forwardRef, type ReactNode, type TextareaHTMLAttributes } from 'react';
import { cx } from '@/lib/cx';
import { FieldShell, useFieldA11y } from './Field';
import styles from './ui.module.css';

export interface TextareaProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'id'> {
  label: ReactNode;
  id?: string;
  hint?: ReactNode;
  error?: ReactNode;
  labelHidden?: boolean;
  optional?: boolean;
  containerClassName?: string;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  {
    label,
    id,
    hint,
    error,
    labelHidden = false,
    optional = false,
    required,
    rows = 4,
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
      <textarea
        {...rest}
        ref={ref}
        id={a11y.id}
        rows={rows}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={a11y.describedBy}
        className={cx(styles.control, styles.textarea, className)}
      />
    </FieldShell>
  );
});
