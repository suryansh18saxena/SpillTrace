'use client';

import Link from 'next/link';
import { useRef, useState } from 'react';
import { RadarMark } from '@/components/brand/RadarMark';
import { ThemeToggle } from '@/components/layout/ThemeToggle';
import { Magnetic } from '@/components/motion/Magnetic';
import { LinkButton } from '@/components/ui/LinkButton';
import { APP_NAME } from '@/lib/config';
import { cx } from '@/lib/cx';
import { gsap, prefersReducedMotion, ScrollTrigger, useGSAP } from '@/lib/motion/gsap';
import styles from '../landing.module.css';

const LINKS = [
  { href: '#chain', label: 'The chain' },
  { href: '#stages', label: 'Stages' },
  { href: '#evidence', label: 'Evidence' },
  { href: '#safeguards', label: 'Safeguards' },
];

/**
 * Transparent over the hero; glass once the page scrolls; slides away while
 * reading downward and returns on the first upward scroll.
 */
export function LandingNav() {
  const ref = useRef<HTMLElement | null>(null);
  const [scrolled, setScrolled] = useState(false);

  useGSAP(
    () => {
      const el = ref.current;
      if (!el) return;
      const reduced = prefersReducedMotion();
      const hide = reduced
        ? null
        : gsap.to(el, { yPercent: -110, duration: 0.45, ease: 'power3.out', paused: true });

      ScrollTrigger.create({
        start: 0,
        end: 'max',
        onUpdate: (self) => {
          const y = self.scroll();
          setScrolled(y > 24);
          if (!hide) return;
          if (self.direction === 1 && y > 480) hide.play();
          else if (self.direction === -1) hide.reverse();
        },
      });
    },
    { scope: ref },
  );

  return (
    <header ref={ref} className={cx(styles.nav, scrolled && styles.navScrolled)}>
      <div className={cx(styles.container, styles.navInner)}>
        <Link href="/" className={styles.brand} aria-label={`${APP_NAME} home`}>
          <RadarMark size={30} />
          {APP_NAME}
        </Link>

        <nav className={styles.navLinks} aria-label="Page sections">
          {LINKS.map((link) => (
            <a key={link.href} className={styles.navLink} href={link.href}>
              {link.label}
            </a>
          ))}
          <Link className={styles.navLink} href="/transparency">
            Transparency
          </Link>
        </nav>

        <div className={styles.navActions}>
          <ThemeToggle />
          <Magnetic strength={0.25}>
            <LinkButton href="/login" variant="primary" size="sm">
              Sign in
            </LinkButton>
          </Magnetic>
        </div>
      </div>
    </header>
  );
}
