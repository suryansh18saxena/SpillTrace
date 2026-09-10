'use client';

import { useEffect, useId, useRef, type ReactNode } from 'react';
import { cx } from '@/lib/cx';
import { Button } from './Button';
import { IconClose } from './Icons';
import styles from './ui.module.css';

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  footer?: ReactNode;
  /** Hide the close button when the dialog demands an explicit decision. */
  dismissible?: boolean;
  className?: string;
  children: ReactNode;
}

/**
 * Modal built on the native `<dialog>` element.
 *
 * `showModal()` gives us the top layer, the `::backdrop`, focus containment,
 * inertness of the page behind, and Escape-to-close from the platform. Every
 * hand-rolled focus trap is a bug waiting to happen, so we use the one that
 * ships with the browser and only add the `cancel` handler that routes Escape
 * back through React state.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  footer,
  dismissible = true,
  className,
  children,
}: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof node.showModal !== 'function') return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const handleCancel = (event: Event) => {
      event.preventDefault();
      if (dismissible) onClose();
    };
    const handleClose = () => {
      if (open) onClose();
    };

    node.addEventListener('cancel', handleCancel);
    node.addEventListener('close', handleClose);
    return () => {
      node.removeEventListener('cancel', handleCancel);
      node.removeEventListener('close', handleClose);
    };
  }, [dismissible, onClose, open]);

  return (
    <dialog
      ref={ref}
      className={cx(styles.dialog, className)}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
    >
      <div className={styles.dialogInner}>
        <header className={styles.dialogHeader}>
          <div>
            <h2 id={titleId} className={styles.dialogTitle}>
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className={styles.dialogDescription}>
                {description}
              </p>
            ) : null}
          </div>
          {dismissible ? (
            <Button variant="ghost" size="sm" iconOnly aria-label="Close dialog" onClick={onClose}>
              <IconClose size={16} />
            </Button>
          ) : null}
        </header>
        <div className={styles.dialogBody}>{children}</div>
        {footer ? <footer className={styles.dialogFooter}>{footer}</footer> : null}
      </div>
    </dialog>
  );
}
