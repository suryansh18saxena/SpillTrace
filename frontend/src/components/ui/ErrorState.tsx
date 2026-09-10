'use client';

import type { ReactNode } from 'react';
import { ApiError } from '@/lib/api/client';
import { cx } from '@/lib/cx';
import { Button } from './Button';
import { IconAlert, IconRefresh } from './Icons';
import styles from './ui.module.css';

export interface ErrorStateProps {
  /** Defaults to a title derived from the error's HTTP status. */
  title?: string;
  error?: unknown;
  /** Overrides the message extracted from `error`. */
  description?: ReactNode;
  onRetry?: () => void;
  retryLabel?: string;
  action?: ReactNode;
  compact?: boolean;
  className?: string;
}

function titleFor(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.isNotFound) return 'Not found';
    if (error.isForbidden) return 'Not permitted';
    if (error.isUnauthenticated) return 'Session expired';
    if (error.status === 409) return 'Conflicting state';
    if (error.status === 422) return 'Validation failed';
    if (error.status === 429) return 'Rate limited';
    if (error.status === 503) return 'Service unavailable';
    if (error.code === 'NETWORK_ERROR') return 'Cannot reach the API';
    if (error.code === 'TIMEOUT') return 'The request timed out';
  }
  return 'Something went wrong';
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === 'string' && error) return error;
  return 'The request could not be completed.';
}

/**
 * The single error presentation.
 *
 * It always shows the server's `request_id` when there is one: that string is
 * what turns "it broke" into a line an engineer can find in the structured logs
 * (NFR-004), and it costs the analyst nothing to quote it.
 */
export function ErrorState({
  title,
  error,
  description,
  onRetry,
  retryLabel = 'Try again',
  action,
  compact = false,
  className,
}: ErrorStateProps) {
  const requestId = error instanceof ApiError ? error.requestId : null;
  const code = error instanceof ApiError ? error.code : null;

  return (
    <div
      role="alert"
      data-testid="error-state"
      className={cx(styles.placeholder, compact && styles.placeholderCompact, className)}
    >
      <span className={cx(styles.placeholderIcon, styles.placeholderIconDanger)}>
        <IconAlert size={18} />
      </span>
      <p className={styles.placeholderTitle}>{title ?? titleFor(error)}</p>
      <p className={styles.placeholderBody}>{description ?? messageFor(error)}</p>
      {code || requestId ? (
        <p className={styles.placeholderMeta}>
          {code ? <span>{code}</span> : null}
          {code && requestId ? <span> · </span> : null}
          {requestId ? <span>request {requestId}</span> : null}
        </p>
      ) : null}
      {onRetry || action ? (
        <div className={styles.placeholderActions}>
          {onRetry ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={onRetry}
              leadingIcon={<IconRefresh size={14} />}
            >
              {retryLabel}
            </Button>
          ) : null}
          {action}
        </div>
      ) : null}
    </div>
  );
}
