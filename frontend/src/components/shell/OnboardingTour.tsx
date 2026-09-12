'use client';

import { usePathname } from 'next/navigation';
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/Button';
import { cx } from '@/lib/cx';
import { gsap, prefersReducedMotion } from '@/lib/motion/gsap';
import {
  PREF_TOUR_DONE,
  readBooleanPreference,
  START_TOUR_EVENT,
  writeBooleanPreference,
} from '@/lib/preferences';
import styles from './shell.module.css';

interface TourStep {
  target: string;
  title: string;
  body: string;
}

const STEPS: TourStep[] = [
  {
    target: '[data-tour="sidebar"]',
    title: 'Everything has a place',
    body: 'Overview screens, your investigations, cross-case intelligence and system status. Collapse the sidebar to an icon rail with the button at its foot.',
  },
  {
    target: '[data-tour="search"]',
    title: 'Jump anywhere with Ctrl K',
    body: 'Search cases by title, open any screen or run a quick action — from every page, without reaching for the mouse.',
  },
  {
    target: '[data-tour="notifications"]',
    title: 'The chain reports back',
    body: 'Completed and failed pipelines, and candidates that reach the HIGH investigative-signal band, surface here as they happen.',
  },
  {
    target: '[data-tour="data-mode"]',
    title: 'Always know what is real',
    body: 'This chip says whether any data source is synthetic. Every synthetic result is labelled SYNTHETIC wherever it appears — it can never pass as a real observation.',
  },
  {
    target: '[data-tour="help"]',
    title: 'When in doubt, read this',
    body: 'What every score, band, contour and badge means — and, just as important, what each one does not mean.',
  },
];

const PAD = 8;

function visibleRect(selector: string): DOMRect | null {
  const node = document.querySelector<HTMLElement>(selector);
  if (!node) return null;
  const rect = node.getBoundingClientRect();
  if (rect.width < 2 || rect.height < 2) return null;
  if (rect.right < 0 || rect.left > window.innerWidth) return null;
  return rect;
}

/**
 * A five-step first-run walkthrough.
 *
 * Starts once, automatically, on the first visit to the dashboard; it can be
 * replayed from the account menu, the command palette or the help page. It is
 * a modal dialog while open (Escape closes it, focus moves into the card) and
 * the spotlight is purely decorative.
 */
export function OnboardingTour() {
  const pathname = usePathname();
  const [step, setStep] = useState<number | null>(null);
  const spotRef = useRef<HTMLDivElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  const firstPlacement = useRef(true);

  const finish = useCallback(() => {
    writeBooleanPreference(PREF_TOUR_DONE, true);
    setStep(null);
  }, []);

  // First-run auto start on the dashboard.
  useEffect(() => {
    if (pathname !== '/dashboard' || readBooleanPreference(PREF_TOUR_DONE)) return;
    const timer = setTimeout(() => setStep(0), 1400);
    return () => clearTimeout(timer);
  }, [pathname]);

  useEffect(() => {
    const onStart = () => {
      firstPlacement.current = true;
      setStep(0);
    };
    window.addEventListener(START_TOUR_EVENT, onStart);
    return () => window.removeEventListener(START_TOUR_EVENT, onStart);
  }, []);

  // Position the spotlight and the card for the current step.
  useLayoutEffect(() => {
    if (step === null) return;
    const current = STEPS[step];
    const spot = spotRef.current;
    const card = cardRef.current;
    if (!current || !spot || !card) return;

    const place = () => {
      const rect = visibleRect(current.target);
      const cardWidth = card.offsetWidth;
      const cardHeight = card.offsetHeight;
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const instant = firstPlacement.current || prefersReducedMotion();
      const duration = instant ? 0 : 0.6;

      if (!rect) {
        gsap.to(spot, { autoAlpha: 0, duration: 0.2 });
        gsap.to(card, {
          x: (vw - cardWidth) / 2,
          y: (vh - cardHeight) / 2,
          duration,
          ease: 'expo.out',
        });
      } else {
        const box = {
          x: rect.left - PAD,
          y: rect.top - PAD,
          width: rect.width + PAD * 2,
          height: Math.min(rect.height + PAD * 2, vh - 16),
        };
        gsap.to(spot, { ...box, autoAlpha: 1, duration, ease: 'expo.out' });

        // Card: to the right of the target if it fits, else below, else above.
        let x = box.x + box.width + 16;
        let y = box.y;
        if (x + cardWidth > vw - 16) {
          x = Math.min(Math.max(16, box.x), vw - cardWidth - 16);
          y = box.y + box.height + 16;
          if (y + cardHeight > vh - 16) y = Math.max(16, box.y - cardHeight - 16);
        }
        y = Math.min(Math.max(16, y), vh - cardHeight - 16);
        gsap.to(card, { x, y, duration, ease: 'expo.out' });
      }

      if (firstPlacement.current) {
        firstPlacement.current = false;
        if (!prefersReducedMotion()) {
          gsap.fromTo(
            card,
            { autoAlpha: 0, scale: 0.96 },
            { autoAlpha: 1, scale: 1, duration: 0.5 },
          );
        }
      }
    };

    place();
    card.focus();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [step]);

  useEffect(() => {
    if (step === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') finish();
      if (event.key === 'ArrowRight')
        setStep((s) => (s === null ? s : Math.min(s + 1, STEPS.length - 1)));
      if (event.key === 'ArrowLeft') setStep((s) => (s === null ? s : Math.max(s - 1, 0)));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [step, finish]);

  if (step === null) return null;
  const current = STEPS[step];
  if (!current) return null;
  const last = step === STEPS.length - 1;

  return (
    <div className={styles.tour}>
      <div className={styles.tourSpot} ref={spotRef} aria-hidden="true" />
      <div
        className={styles.tourCard}
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <p className={styles.tourStep}>
          Step {step + 1} of {STEPS.length}
        </p>
        <h2 className={styles.tourTitle} id={titleId}>
          {current.title}
        </h2>
        <p className={styles.tourBody}>{current.body}</p>
        <div className={styles.tourFooter}>
          <div className={styles.tourDots} aria-hidden="true">
            {STEPS.map((item, index) => (
              <span
                key={item.target}
                className={cx(styles.tourDot, index === step && styles.tourDotActive)}
              />
            ))}
          </div>
          <div className={styles.tourActions}>
            {step === 0 ? (
              <Button variant="ghost" size="sm" onClick={finish}>
                Skip
              </Button>
            ) : (
              <Button variant="ghost" size="sm" onClick={() => setStep(step - 1)}>
                Back
              </Button>
            )}
            <Button
              variant="primary"
              size="sm"
              onClick={() => (last ? finish() : setStep(step + 1))}
            >
              {last ? 'Finish' : 'Next'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
