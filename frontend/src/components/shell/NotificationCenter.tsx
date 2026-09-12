'use client';

import Link from 'next/link';
import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from 'react';
import {
  IconActivity,
  IconAlert,
  IconBell,
  IconCheck,
  IconPlus,
  IconTarget,
} from '@/components/ui/Icons';
import { useCaseUniverse } from '@/lib/api/aggregate';
import { cx } from '@/lib/cx';
import { formatRelativeTime } from '@/lib/format';
import { deriveNotifications, type NotificationKind } from '@/lib/notifications';
import { PREF_NOTIFICATIONS_SEEN, readPreference, writePreference } from '@/lib/preferences';
import styles from './shell.module.css';
import { useDismiss } from './useDismiss';

const KIND_CLASS: Record<NotificationKind, string | undefined> = {
  created: styles.nCreated,
  running: styles.nRunning,
  completed: styles.nCompleted,
  failed: styles.nFailed,
  signal: styles.nSignal,
};

const KIND_ICON: Record<NotificationKind, ReactNode> = {
  created: <IconPlus size={15} />,
  running: <IconActivity size={15} />,
  completed: <IconCheck size={15} />,
  failed: <IconAlert size={15} />,
  signal: <IconTarget size={15} />,
};

/**
 * The bell: pipeline completions and failures, and candidates that reach the
 * HIGH investigative-signal band, across the analyst's recent cases.
 *
 * Derived from live case state and polled every 30 s. "Read" is a display
 * preference (the time the panel was last closed), kept in local storage.
 */
export function NotificationCenter() {
  const universe = useCaseUniverse({ attributions: true, refetchInterval: 30_000 });
  const notifications = deriveNotifications(universe.bundles);

  const [open, setOpen] = useState(false);
  const [seenAt, setSeenAt] = useState<number>(0);
  const [ringing, setRinging] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelId = useId();
  const previousUnread = useRef(0);

  useEffect(() => {
    setSeenAt(Number(readPreference(PREF_NOTIFICATIONS_SEEN) ?? 0) || 0);
  }, []);

  const unread = notifications.filter((item) => item.at > seenAt).length;

  // A small ring when something new arrives while the analyst is looking.
  useEffect(() => {
    if (unread > previousUnread.current && previousUnread.current !== 0) {
      setRinging(true);
      const timer = setTimeout(() => setRinging(false), 1200);
      previousUnread.current = unread;
      return () => clearTimeout(timer);
    }
    previousUnread.current = unread;
    return undefined;
  }, [unread]);

  const markAllRead = useCallback(() => {
    const now = Date.now();
    setSeenAt(now);
    writePreference(PREF_NOTIFICATIONS_SEEN, String(now));
  }, []);

  const close = useCallback(() => {
    setOpen(false);
    markAllRead();
  }, [markAllRead]);

  useDismiss(open, close, rootRef, triggerRef);

  return (
    <div className={styles.popoverRoot} ref={rootRef} data-tour="notifications">
      <button
        ref={triggerRef}
        type="button"
        className={cx(styles.bellButton, ringing && styles.bellRinging)}
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : 'Notifications'}
        aria-expanded={open}
        aria-controls={open ? panelId : undefined}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <IconBell size={17} />
        {unread > 0 ? (
          <span className={styles.bellCount} aria-hidden="true">
            {unread > 9 ? '9+' : unread}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className={styles.popover} id={panelId} role="dialog" aria-label="Notifications">
          <div className={styles.popoverHeader}>
            <span className={styles.popoverTitle}>Notifications</span>
            {unread > 0 ? (
              <button type="button" className={styles.textButton} onClick={markAllRead}>
                Mark all read
              </button>
            ) : null}
          </div>

          {universe.isPending ? (
            <p className={styles.popoverEmpty}>Loading recent activity…</p>
          ) : notifications.length === 0 ? (
            <p className={styles.popoverEmpty}>
              Nothing yet. Case activity and HIGH-band candidates will appear here.
            </p>
          ) : (
            <ul className={styles.notificationList}>
              {notifications.map((item) => (
                <li key={item.id}>
                  <Link href={item.href} className={styles.notification} onClick={close}>
                    <span className={cx(styles.notificationIcon, KIND_CLASS[item.kind])}>
                      {KIND_ICON[item.kind]}
                    </span>
                    <span>
                      <span className={styles.notificationTitle}>
                        {item.title}
                        {item.at > seenAt ? (
                          <>
                            <span className={styles.unreadDot} aria-hidden="true" />
                            <span className="sr-only">(unread)</span>
                          </>
                        ) : null}
                      </span>
                      <span className={styles.notificationBody}>{item.body}</span>
                      <span className={styles.notificationTime}>{formatRelativeTime(item.at)}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}

          <div className={styles.popoverFooter}>
            <Link href="/activity" onClick={close}>
              Open the activity feed →
            </Link>
          </div>
        </div>
      ) : null}
    </div>
  );
}
