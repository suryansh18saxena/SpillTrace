'use client';

import Link from 'next/link';
import { useRef, useState } from 'react';
import { RadarMark } from '@/components/brand/RadarMark';
import { Magnetic } from '@/components/motion/Magnetic';
import { LinkButton } from '@/components/ui/LinkButton';
import { APP_NAME } from '@/lib/config';
import { cx } from '@/lib/cx';
import { gsap, prefersReducedMotion, ScrollTrigger, useGSAP } from '@/lib/motion/gsap';
import nav from '../landing.module.css';
import styles from './cinematic.module.css';

const LINKS = [
  { href: '#detect', label: 'Detect' },
  { href: '#match', label: 'Match' },
  { href: '#backtrack', label: 'Backtrack' },
  { href: '#attribution', label: 'Attribute' },
];

/** Transparent over the water; glass once the page moves; hides while reading down. */
export function CinematicNav() {
  const ref = useRef<HTMLElement | null>(null);
  const [scrolled, setScrolled] = useState(false);

  useGSAP(
    () => {
      const el = ref.current;
      if (!el) return;
      const hide = prefersReducedMotion()
        ? null
        : gsap.to(el, { yPercent: -110, duration: 0.45, ease: 'power3.out', paused: true });
      ScrollTrigger.create({
        start: 0,
        end: 'max',
        onUpdate: (self) => {
          const y = self.scroll();
          setScrolled(y > 24);
          if (!hide) return;
          if (self.direction === 1 && y > 600) hide.play();
          else if (self.direction === -1) hide.reverse();
        },
      });
    },
    { scope: ref },
  );

  return (
    <header ref={ref} className={cx(nav.nav, scrolled && nav.navScrolled, styles.nav)}>
      <div className={cx(nav.container, nav.navInner)}>
        <Link href="/" className={nav.brand} aria-label={`${APP_NAME} home`}>
          <RadarMark size={30} />
          {APP_NAME}
        </Link>
        <nav className={nav.navLinks} aria-label="Page sections">
          {LINKS.map((link) => (
            <a key={link.href} className={nav.navLink} href={link.href}>
              {link.label}
            </a>
          ))}
          <Link className={nav.navLink} href="/transparency">
            Transparency
          </Link>
        </nav>
        <div className={nav.navActions}>
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
