'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { cx } from '@/lib/cx';
import { IconClose } from './Icons';
import styles from './ui.module.css';

export type ToastTone = 'info' | 'success' | 'warning' | 'error';

export interface ToastOptions {
  title: string;
  description?: string;
  tone?: ToastTone;
  /** Milliseconds before auto-dismiss. Errors default to staying put. */
  duration?: number;
}

interface ToastRecord extends ToastOptions {
  id: string;
  tone: ToastTone;
}

interface ToastContextValue {
  toast: (options: ToastOptions) => string;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const TONE_CLASS: Record<ToastTone, string | undefined> = {
  info: styles.toastInfo,
  success: styles.toastSuccess,
  warning: styles.toastWarning,
  error: styles.toastError,
};

const DEFAULT_DURATION: Record<ToastTone, number> = {
  info: 5_000,
  success: 4_000,
  warning: 8_000,
  // Errors stay until dismissed: an analyst who looked away must not miss one.
  error: 0,
};

let counter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback(
    (options: ToastOptions) => {
      counter += 1;
      const id = `toast-${counter}`;
      const tone = options.tone ?? 'info';
      const record: ToastRecord = { ...options, id, tone };
      setToasts((current) => [...current, record]);

      const duration = options.duration ?? DEFAULT_DURATION[tone];
      if (duration > 0) {
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), duration),
        );
      }
      return id;
    },
    [dismiss],
  );

  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const timer of pending.values()) clearTimeout(timer);
      pending.clear();
    };
  }, []);

  const value = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/*
        Two live regions: errors and warnings interrupt (assertive), everything
        else waits for a pause (polite). One region for both would either shout
        successes or swallow failures.
      */}
      <div className={styles.toastViewport}>
        <div aria-live="assertive" aria-atomic="false" className={styles.toastStack}>
          {toasts
            .filter((item) => item.tone === 'error' || item.tone === 'warning')
            .map((item) => (
              <ToastItem key={item.id} toast={item} onDismiss={dismiss} />
            ))}
        </div>
        <div aria-live="polite" aria-atomic="false" className={styles.toastStack}>
          {toasts
            .filter((item) => item.tone !== 'error' && item.tone !== 'warning')
            .map((item) => (
              <ToastItem key={item.id} toast={item} onDismiss={dismiss} />
            ))}
        </div>
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: ToastRecord; onDismiss: (id: string) => void }) {
  return (
    <div className={cx(styles.toast, TONE_CLASS[toast.tone])} data-testid="toast">
      <div className={styles.toastText}>
        <p className={styles.toastTitle}>{toast.title}</p>
        {toast.description ? <p className={styles.toastDescription}>{toast.description}</p> : null}
      </div>
      <button
        type="button"
        className={styles.toastClose}
        aria-label={`Dismiss notification: ${toast.title}`}
        onClick={() => onDismiss(toast.id)}
      >
        <IconClose size={14} />
      </button>
    </div>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used inside a <ToastProvider>.');
  }
  return context;
}
