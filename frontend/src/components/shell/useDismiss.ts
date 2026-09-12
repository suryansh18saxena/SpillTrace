'use client';

import { useEffect, type RefObject } from 'react';

/**
 * Closes a non-modal popover on an outside pointer press or on Escape.
 *
 * On Escape, focus returns to the trigger so a keyboard user is never left on
 * an element that just disappeared.
 */
export function useDismiss(
  open: boolean,
  onClose: () => void,
  root: RefObject<HTMLElement | null>,
  trigger?: RefObject<HTMLElement | null>,
): void {
  useEffect(() => {
    if (!open) return;

    const onPointer = (event: PointerEvent) => {
      const node = root.current;
      if (node && !node.contains(event.target as Node)) onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      onClose();
      trigger?.current?.focus();
    };

    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, onClose, root, trigger]);
}
