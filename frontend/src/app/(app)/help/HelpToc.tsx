'use client';

import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { cx } from '@/lib/cx';
import { prefersReducedMotion } from '@/lib/motion/gsap';
import styles from './help.module.css';

export interface TocItem {
  id: string;
  label: string;
}

/** Matches the `64rem` breakpoint in help.module.css where the TOC becomes a sidebar. */
const DESKTOP_QUERY = '(min-width: 64rem)';

/** How long a click-initiated scroll owns the highlight before the spy takes over again. */
const CLICK_LOCK_MS = 1100;

function remToPx(value: string): number {
  const rem = Number.parseFloat(value);
  const root = Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  return Number.isFinite(rem) ? rem * root : 60;
}

/**
 * "On this page" — a sticky sidebar on desktop, a sticky horizontal chip row on
 * narrow screens. One list, restyled, so assistive technology meets a single
 * navigation landmark rather than two copies of it.
 *
 * Scroll-spy is IntersectionObserver-based: each section reports when it enters
 * a band running from just under the sticky chrome to 40 % down the viewport,
 * and the last section in document order that is inside the band is current.
 * A second observer notices when the final (short) section is fully on screen,
 * because at the foot of the page its heading may never reach the band.
 */
export function HelpToc({ items }: { items: readonly TocItem[] }) {
  const [active, setActive] = useState<string>(items[0]?.id ?? '');
  const navRef = useRef<HTMLElement | null>(null);
  const listRef = useRef<HTMLOListElement | null>(null);
  const lockUntil = useRef(0);

  // Deep link: honour an incoming #hash as the initial highlight.
  useEffect(() => {
    const hash = window.location.hash.slice(1);
    if (hash && items.some((item) => item.id === hash)) setActive(hash);
  }, [items]);

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return;
    const sections = items
      .map((item) => document.getElementById(item.id))
      .filter((node): node is HTMLElement => node !== null);
    if (sections.length === 0) return;

    const desktop = window.matchMedia(DESKTOP_QUERY);
    const lastId = items[items.length - 1]?.id ?? null;
    let observers: IntersectionObserver[] = [];

    const setup = () => {
      observers.forEach((observer) => observer.disconnect());
      const header = remToPx(
        getComputedStyle(document.documentElement).getPropertyValue('--layout-header-height'),
      );
      // On narrow screens the chip row is stuck under the header too.
      const chrome = header + (desktop.matches ? 0 : (navRef.current?.offsetHeight ?? 0)) + 8;

      const inBand = new Set<string>();
      let atEnd = false;
      const update = () => {
        if (performance.now() < lockUntil.current) return;
        if (atEnd && lastId) {
          setActive(lastId);
          return;
        }
        let current: string | null = null;
        for (const item of items) if (inBand.has(item.id)) current = item.id;
        if (current) setActive(current);
      };

      const band = new IntersectionObserver(
        (entries) => {
          for (const entry of entries) {
            if (entry.isIntersecting) inBand.add(entry.target.id);
            else inBand.delete(entry.target.id);
          }
          update();
        },
        { rootMargin: `-${Math.round(chrome)}px 0px -60% 0px` },
      );
      sections.forEach((section) => band.observe(section));

      const last = sections[sections.length - 1];
      const end = new IntersectionObserver(
        ([entry]) => {
          atEnd = Boolean(entry && entry.intersectionRatio >= 0.95);
          update();
        },
        { threshold: [0, 0.95, 1] },
      );
      if (last) end.observe(last);

      observers = [band, end];
    };

    setup();
    desktop.addEventListener('change', setup);
    return () => {
      desktop.removeEventListener('change', setup);
      observers.forEach((observer) => observer.disconnect());
    };
  }, [items]);

  // Keep the current chip visible in the horizontal row. `scrollTo` on the list
  // (not `scrollIntoView`) so the page itself never moves.
  useEffect(() => {
    const list = listRef.current;
    if (!list || list.scrollWidth <= list.clientWidth + 1) return;
    const link = list.querySelector<HTMLElement>(`[data-toc-id="${active}"]`);
    if (!link) return;
    list.scrollTo({
      left: link.offsetLeft - (list.clientWidth - link.offsetWidth) / 2,
      behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    });
  }, [active]);

  const onNavigate = (event: MouseEvent<HTMLAnchorElement>, id: string) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const target = document.getElementById(id);
    if (!target) return;
    event.preventDefault();

    setActive(id);
    lockUntil.current = performance.now() + CLICK_LOCK_MS;
    const release = () => {
      lockUntil.current = 0;
    };
    window.addEventListener('scrollend', release, { once: true });

    // `scroll-margin-top` on each section keeps its heading clear of the header.
    target.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' });
    window.history.replaceState(null, '', `#${id}`);
    // Move focus with the reader, so the next Tab continues from the section.
    target.querySelector<HTMLElement>('h2')?.focus({ preventScroll: true });
  };

  return (
    <nav ref={navRef} className={styles.toc} aria-label="On this page">
      <p className={styles.tocTitle}>On this page</p>
      <ol ref={listRef} className={styles.tocList}>
        {items.map((item, index) => {
          const current = item.id === active;
          return (
            <li key={item.id} className={styles.tocItem}>
              <a
                href={`#${item.id}`}
                data-toc-id={item.id}
                aria-current={current ? 'location' : undefined}
                className={cx(styles.tocLink, current && styles.tocLinkActive)}
                onClick={(event) => onNavigate(event, item.id)}
              >
                <span className={styles.tocNum} aria-hidden="true">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <span className={styles.tocLabel}>{item.label}</span>
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
