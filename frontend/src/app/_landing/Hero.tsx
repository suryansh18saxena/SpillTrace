'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Magnetic } from '@/components/motion/Magnetic';
import { IconArrowRight, IconCheck, IconInfo } from '@/components/ui/Icons';
import { LinkButton } from '@/components/ui/LinkButton';
import { BorderBeam } from '@/components/motion/BorderBeam';
import { cx } from '@/lib/cx';
import {
  gsap,
  hasFinePointer,
  prefersReducedMotion,
  ScrollTrigger,
  useGSAP,
} from '@/lib/motion/gsap';
import styles from '../landing.module.css';
import { DEMO_CANDIDATES } from './content';

/** Small deterministic PRNG so the star field is identical on server and client. */
function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const HUD_STAGES = ['sar.preprocess', 'ml.detect', 'detect.verify', 'drift.hindcast', 'score'];

const TRACKS = [
  'M40 610 C200 560 300 520 400 470 S620 380 780 330',
  'M60 300 C200 330 300 390 420 420 S640 450 790 420',
  'M250 790 C300 680 360 600 460 540 S640 450 760 250',
];

/**
 * Degree ticks around the scope's outer ring.
 *
 * Rounded to two decimals on purpose: `Math.cos`/`Math.sin` may differ in the
 * last bits between the server's V8 and the browser's, and an unrounded
 * coordinate would then be a hydration mismatch on every tick.
 */
const round = (value: number) => Math.round(value * 100) / 100;
const TICKS = Array.from({ length: 72 }, (_, i) => {
  const angle = (i * 5 * Math.PI) / 180;
  const inner = i % 6 === 0 ? 350 : 358;
  return {
    key: i,
    x1: round(400 + Math.cos(angle) * inner),
    y1: round(400 + Math.sin(angle) * inner),
    x2: round(400 + Math.cos(angle) * 366),
    y2: round(400 + Math.sin(angle) * 366),
    major: i % 6 === 0,
  };
});

export function Hero() {
  const root = useRef<HTMLElement | null>(null);
  const [live, setLive] = useState(HUD_STAGES.length);

  const stars = useMemo(() => {
    const rand = mulberry32(26143);
    return Array.from({ length: 90 }, (_, i) => ({
      key: i,
      cx: rand() * 1440,
      cy: rand() * 620,
      r: rand() * 1.3 + 0.35,
      o: rand() * 0.55 + 0.15,
      twinkle: rand() > 0.62,
      delay: `${(rand() * 4).toFixed(2)}s`,
    }));
  }, []);

  // Cycle the "live" stage in the pipeline card. Illustrative of the process,
  // not a claim about any particular run — hence no numbers in that card.
  useEffect(() => {
    if (prefersReducedMotion()) return;
    setLive(0);
    const timer = setInterval(() => setLive((i) => (i + 1) % (HUD_STAGES.length + 2)), 1500);
    return () => clearInterval(timer);
  }, []);

  useGSAP(
    () => {
      const el = root.current;
      if (!el) return;
      const q = gsap.utils.selector(el);
      const content = q('[data-hero-content]')[0];
      content?.setAttribute('data-reveal-ready', '');
      if (prefersReducedMotion()) return;

      // Three independent motion channels, each owning its own properties so
      // they never fight: the intro animates the inner elements, the scroll
      // scrub animates `y`/scale/rotate on the layer wrappers, and the pointer
      // animates `x`/`yPercent` on the same wrappers.

      // ------------------------------------------------------ intro
      const intro = gsap.timeline({ defaults: { ease: 'expo.out' } });
      intro
        .from(
          q('[data-hero-scope]'),
          { autoAlpha: 0, scale: 0.86, rotate: -12, duration: 2.2, transformOrigin: '50% 50%' },
          0,
        )
        .from(q('[data-hero-badge]'), { autoAlpha: 0, y: 18, duration: 1 }, 0.15)
        .from(q('[data-line]'), { yPercent: 115, duration: 1.3, stagger: 0.1 }, 0.25)
        .from(q('[data-hero-fade]'), { autoAlpha: 0, y: 24, duration: 1.1, stagger: 0.09 }, 0.7)
        .from(q('[data-hud]'), { autoAlpha: 0, xPercent: 18, duration: 1.2, stagger: 0.15 }, 0.9)
        .from(q('[data-cue]'), { autoAlpha: 0, duration: 1 }, 1.4);

      // ------------------------------------------------ ambient loops
      const ambient: gsap.core.Tween[] = [];
      q('[data-ship]').forEach((ship, index) => {
        const path = q(`[data-track="${index}"]`)[0] as SVGPathElement | undefined;
        if (!path) return;
        ambient.push(
          gsap.to(ship, {
            motionPath: { path, align: path, alignOrigin: [0.5, 0.5], autoRotate: true },
            duration: 16 + index * 5,
            ease: 'none',
            repeat: -1,
            delay: -index * 4,
          }),
        );
      });
      const sat = q('[data-sat]')[0];
      const orbit = q('[data-orbit]')[0] as SVGPathElement | undefined;
      if (sat && orbit) {
        ambient.push(
          gsap.to(sat, {
            motionPath: { path: orbit, align: orbit, alignOrigin: [0.5, 0.5] },
            duration: 26,
            ease: 'none',
            repeat: -1,
          }),
        );
      }

      // ------------------------------------------- scroll-linked depth
      const scroll = gsap.timeline({
        scrollTrigger: { trigger: el, start: 'top top', end: 'bottom top', scrub: 0.6 },
      });
      scroll
        .to(q('[data-depth="stars"]'), { y: 90, ease: 'none' }, 0)
        .to(q('[data-depth="grid"]'), { y: 60, ease: 'none' }, 0)
        .to(q('[data-depth="scope"]'), { y: 180, scale: 1.14, rotate: 10, ease: 'none' }, 0)
        .to(q('[data-depth="sat"]'), { y: 70, ease: 'none' }, 0)
        .to(content ?? [], { y: -140, autoAlpha: 0.1, ease: 'none' }, 0)
        .to(q('[data-hud]'), { y: -220, ease: 'none' }, 0);

      // Pause the ambient loops while the hero is off-screen — no point
      // spending frames on ships nobody can see.
      ScrollTrigger.create({
        trigger: el,
        start: 'top bottom',
        end: 'bottom top',
        onToggle: (self) =>
          ambient.forEach((tween) => (self.isActive ? tween.resume() : tween.pause())),
      });

      // ------------------------------------------------ pointer depth
      if (!hasFinePointer()) return;
      const layers = [
        { targets: q('[data-depth="stars"]'), depth: 10 },
        { targets: q('[data-depth="grid"]'), depth: 14 },
        { targets: q('[data-depth="scope"]'), depth: 26 },
        { targets: q('[data-depth="sat"]'), depth: 18 },
        { targets: q('[data-hud]'), depth: -22 },
      ].map(({ targets, depth }) => ({
        x: gsap.quickTo(targets, 'x', { duration: 1.2, ease: 'power3.out' }),
        yTo: gsap.quickTo(targets, 'yPercent', { duration: 1.2, ease: 'power3.out' }),
        depth,
      }));
      const onMove = (event: PointerEvent) => {
        const nx = event.clientX / window.innerWidth - 0.5;
        const ny = event.clientY / window.innerHeight - 0.5;
        for (const layer of layers) {
          layer.x(-nx * layer.depth);
          layer.yTo(-ny * layer.depth * 0.08);
        }
      };
      el.addEventListener('pointermove', onMove);
      return () => el.removeEventListener('pointermove', onMove);
    },
    { scope: root },
  );

  return (
    <section ref={root} className={styles.hero} aria-labelledby="hero-title">
      <div className={styles.heroBase} aria-hidden="true" />

      {/* Layer 1 — plankton / stars */}
      <div
        className={cx(styles.heroLayer, styles.layerStars)}
        data-depth="stars"
        aria-hidden="true"
      >
        <svg viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice">
          {stars.map((s) => (
            <circle
              key={s.key}
              className={cx(styles.star, s.twinkle && styles.twinkle)}
              cx={s.cx}
              cy={s.cy}
              r={s.r}
              opacity={s.o}
              style={s.twinkle ? { animationDelay: s.delay } : undefined}
            />
          ))}
        </svg>
      </div>

      {/* Layer 2 — perspective radar floor */}
      <div className={cx(styles.heroLayer, styles.layerGrid)} data-depth="grid" aria-hidden="true">
        <div className={styles.gridPlane} />
      </div>
      <div className={styles.horizon} aria-hidden="true" />

      {/* Layer 3 — the scope: slick, origin region, vessel tracks */}
      <div
        className={cx(styles.heroLayer, styles.layerScope)}
        data-depth="scope"
        aria-hidden="true"
      >
        <svg viewBox="0 0 800 800" data-hero-scope="">
          <defs>
            <radialGradient id="hs-glow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.16" />
              <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
            </radialGradient>
            <linearGradient id="hs-sweep" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%" stopColor="var(--color-accent-2)" stopOpacity="0.38" />
              <stop offset="100%" stopColor="var(--color-accent-2)" stopOpacity="0" />
            </linearGradient>
            <radialGradient id="hs-slick" cx="45%" cy="42%" r="62%">
              <stop offset="0%" stopColor="var(--map-spill)" stopOpacity="0.9" />
              <stop offset="60%" stopColor="var(--map-spill)" stopOpacity="0.42" />
              <stop offset="100%" stopColor="var(--map-spill)" stopOpacity="0.06" />
            </radialGradient>
            <radialGradient id="hs-origin" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="var(--map-origin)" stopOpacity="0.4" />
              <stop offset="100%" stopColor="var(--map-origin)" stopOpacity="0" />
            </radialGradient>
            <clipPath id="hs-disc">
              <circle cx="400" cy="400" r="366" />
            </clipPath>
          </defs>

          <circle cx="400" cy="400" r="380" fill="url(#hs-glow)" />
          <g clipPath="url(#hs-disc)">
            <g fill="none" stroke="var(--color-accent)" strokeOpacity="0.22">
              <circle cx="400" cy="400" r="120" />
              <circle cx="400" cy="400" r="240" />
              <circle cx="400" cy="400" r="366" strokeOpacity="0.4" />
              <path d="M34 400H766M400 34V766" strokeDasharray="2 6" />
            </g>
            <g fill="none" stroke="var(--color-accent-2)" strokeOpacity="0.5">
              <circle className={styles.ring} cx="400" cy="400" r="200" />
              <circle className={cx(styles.ring, styles.ring2)} cx="400" cy="400" r="200" />
              <circle className={cx(styles.ring, styles.ring3)} cx="400" cy="400" r="200" />
            </g>

            {/* Origin probability region: nested contours, never a point (CON-008). */}
            <g className={styles.breathe}>
              <ellipse cx="330" cy="470" rx="160" ry="104" fill="url(#hs-origin)" />
              <ellipse
                cx="330"
                cy="470"
                rx="140"
                ry="90"
                fill="none"
                stroke="var(--map-origin)"
                strokeOpacity="0.45"
                strokeDasharray="5 6"
              />
              <ellipse
                cx="330"
                cy="470"
                rx="96"
                ry="60"
                fill="none"
                stroke="var(--map-origin)"
                strokeOpacity="0.6"
              />
              <ellipse
                cx="330"
                cy="470"
                rx="52"
                ry="32"
                fill="none"
                stroke="var(--map-origin)"
                strokeOpacity="0.85"
              />
            </g>

            {/* Detected slick */}
            <path
              d="M380 350c42-26 96-33 150-19 47 12 86 39 132 45 38 5 74-6 108 9 26 11 38 36 27 56-13 24-49 28-79 24-59-8-112-36-172-40-52-4-104 12-153-5-34-12-56-45-47-69 7-19 22-25 34-1z"
              fill="url(#hs-slick)"
              stroke="var(--map-spill)"
              strokeOpacity="0.6"
              strokeWidth="1.5"
              transform="translate(-60 20) scale(0.92)"
            />

            {/* Vessel tracks + moving vessels */}
            <g fill="none" stroke="var(--map-vessel)" strokeWidth="1.6" strokeOpacity="0.7">
              {TRACKS.map((d, index) => (
                <path
                  key={d}
                  d={d}
                  data-track={index}
                  className={styles.trackFlow}
                  style={{ animationDuration: `${3 + index}s` }}
                />
              ))}
            </g>
            <g fill="var(--map-vessel)">
              {TRACKS.map((d) => (
                <g key={d} data-ship="">
                  <path d="M-5 5 L0 -8 L5 5 Z" />
                </g>
              ))}
            </g>

            {/* Sweep */}
            <g className={styles.sweep}>
              <path d="M400 400 L780 260 A404 404 0 0 1 780 540 Z" fill="url(#hs-sweep)" />
              <line
                x1="400"
                y1="400"
                x2="790"
                y2="400"
                stroke="var(--color-accent-2)"
                strokeOpacity="0.7"
                strokeWidth="1.5"
              />
            </g>
          </g>

          <g stroke="var(--color-accent)" strokeOpacity="0.5">
            {TICKS.map((t) => (
              <line
                key={t.key}
                x1={t.x1}
                y1={t.y1}
                x2={t.x2}
                y2={t.y2}
                strokeWidth={t.major ? 1.5 : 0.8}
              />
            ))}
          </g>
          <circle cx="400" cy="400" r="4" fill="var(--color-accent-2)" />
        </svg>
      </div>

      {/* Layer 4 — Sentinel-1 pass with its SAR swath */}
      <div className={cx(styles.heroLayer, styles.layerSat)} data-depth="sat" aria-hidden="true">
        <svg viewBox="0 0 1440 900" preserveAspectRatio="xMidYMid slice">
          <defs>
            <linearGradient id="hs-beam" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--color-accent-2)" stopOpacity="0.28" />
              <stop offset="100%" stopColor="var(--color-accent-2)" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path
            data-orbit=""
            d="M-120 190 C 360 60, 1080 60, 1560 170"
            fill="none"
            stroke="var(--color-accent)"
            strokeOpacity="0.14"
            strokeDasharray="2 8"
          />
          <g data-sat="">
            <polygon points="-10,10 10,10 70,420 -70,420" fill="url(#hs-beam)" />
            <rect
              x="-26"
              y="-4"
              width="18"
              height="8"
              rx="1"
              fill="var(--color-accent)"
              opacity="0.8"
            />
            <rect
              x="8"
              y="-4"
              width="18"
              height="8"
              rx="1"
              fill="var(--color-accent)"
              opacity="0.8"
            />
            <rect x="-6" y="-7" width="12" height="14" rx="2" fill="var(--color-text)" />
          </g>
        </svg>
      </div>

      {/* Instrument cards */}
      <div className={cx(styles.hud, styles.hudTop)} data-hud="" aria-hidden="true">
        <BorderBeam duration={8} />
        <div className={styles.hudHead}>
          <span>The chain</span>
          <span>13 stages</span>
        </div>
        {HUD_STAGES.map((stage, index) => {
          const done = index < live;
          const active = index === live;
          return (
            <div
              key={stage}
              className={styles.hudStage}
              style={{ opacity: done || active ? 1 : 0.4 }}
            >
              <span className={cx(styles.hudTick, active && styles.hudTickLive)}>
                {done ? <IconCheck size={10} /> : null}
              </span>
              <code>{stage}</code>
              <span style={{ fontSize: '0.625rem' }}>
                {done ? 'done' : active ? 'running' : ''}
              </span>
            </div>
          );
        })}
      </div>

      <div className={cx(styles.hud, styles.hudBottom)} data-hud="" aria-hidden="true">
        <BorderBeam duration={13} />
        <div className={styles.hudHead}>
          <span>Candidates · kutch-01</span>
          <span className={styles.hudTag}>Synthetic</span>
        </div>
        {DEMO_CANDIDATES.slice(0, 4).map((c) => (
          <div key={c.rank} className={styles.hudRow}>
            <span className={styles.hudRank}>#{c.rank}</span>
            <span className={styles.hudName}>{c.name.replace(' (SYNTHETIC)', '')}</span>
            <span className={styles.hudScore}>{c.score.toFixed(2)}</span>
            <span className={styles.hudBar}>
              <span style={{ width: `${c.score * 100}%` }} />
            </span>
          </div>
        ))}
        <p className={styles.hudFoot}>
          Rank 3 sits 0.0 km from the origin region — a 14.1 h reporting gap lowered its AIS
          reliability.
        </p>
      </div>

      {/* Copy */}
      <div className={styles.container}>
        <div className={styles.heroContent} data-hero-content="" data-reveal="">
          <span className={styles.heroBadge} data-hero-badge="">
            <span className={styles.heroBadgePill}>SIH 2026</span>
            Problem statement SIH26143
          </span>

          <h1 className={styles.heroTitle} id="hero-title">
            <span className={styles.line}>
              <span className={styles.lineInner} data-line="">
                Find the slick.
              </span>
            </span>
            <span className={styles.line}>
              <span className={cx(styles.lineInner, styles.heroAccent)} data-line="">
                Trace it back.
              </span>
            </span>
            <span className={styles.line}>
              <span className={styles.lineInner} data-line="">
                Show your working.
              </span>
            </span>
          </h1>

          <p className={styles.heroLede} data-hero-fade="">
            SPILLTRACE detects oil-like slicks in Sentinel-1 radar imagery, rules out the natural
            phenomena that look identical, runs the oil backwards through wind and current to the
            region where it plausibly began, and ranks the vessels that were there — with a score an
            analyst can read one factor at a time.
          </p>

          <div className={styles.heroActions} data-hero-fade="">
            <Magnetic>
              <LinkButton
                href="/login"
                variant="primary"
                size="lg"
                leadingIcon={<IconArrowRight size={16} />}
              >
                Launch the console
              </LinkButton>
            </Magnetic>
            <Magnetic strength={0.2}>
              <LinkButton href="#chain" variant="secondary" size="lg">
                Watch the chain
              </LinkButton>
            </Magnetic>
          </div>

          <p className={styles.heroNote} data-hero-fade="">
            <IconInfo size={15} />
            <span>
              Attribution produced by this system is investigative, probabilistic evidence — not
              automatic legal proof. The product says so on every screen that shows a score.
            </span>
          </p>
        </div>
      </div>

      <div className={styles.scrollCue} data-cue="" aria-hidden="true">
        Scroll to trace
        <span className={styles.scrollLine} />
      </div>
    </section>
  );
}
