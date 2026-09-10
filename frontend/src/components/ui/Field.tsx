'use client';

import { useId, type ReactNode } from 'react';
import { cx } from '@/lib/cx';
import styles from './ui.module.css';

export interface FieldA11y {
  id: string;
  hintId?: string;
  errorId?: string;
  describedBy?: string;
}

/**
 * Generates the ids that wire a label, a hint and an error message to a control
 * via `aria-describedby`. Every form control in the app goes through this, so no
 * control can accidentally ship without a programmatic label.
 */
export function useFieldA11y(
  idProp: string | undefined,
  hasHint: boolean,
  hasError: boolean,
): FieldA11y {
  const generated = useId();
  const id = idProp ?? generated;
  const hintId = hasHint ? `${id}-hint` : undefined;
  const errorId = hasError ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;
  return { id, hintId, errorId, describedBy };
}

export interface FieldShellProps {
  a11y: FieldA11y;
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  /** Marks the field explicitly optional instead of implicitly. */
  optional?: boolean;
  labelHidden?: boolean;
  className?: string;
  children: ReactNode;
}

export function FieldShell({
  a11y,
  label,
  hint,
  error,
  required = false,
  optional = false,
  labelHidden = false,
  className,
  children,
}: FieldShellProps) {
  return (
    <div className={cx(styles.field, className)}>
      <label htmlFor={a11y.id} className={cx(styles.label, labelHidden && 'sr-only')}>
        {label}
        {required ? (
          <span className={styles.required} aria-hidden="true">
            *
          </span>
        ) : null}
        {optional && !required ? <span className={styles.optional}>(optional)</span> : null}
        {required ? <span className="sr-only">(required)</span> : null}
      </label>
      {children}
      {hint && a11y.hintId ? (
        <p id={a11y.hintId} className={styles.hint}>
          {hint}
        </p>
      ) : null}
      {error && a11y.errorId ? (
        <p id={a11y.errorId} className={styles.errorText} role="alert">
          <span aria-hidden="true">▲</span>
          <span>{error}</span>
        </p>
      ) : null}
    </div>
  );
}
