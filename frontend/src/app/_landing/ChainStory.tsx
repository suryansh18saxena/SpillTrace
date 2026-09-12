'use client';

import { useMemo, useRef } from 'react';
import { IconCheck } from '@/components/ui/Icons';
import { cx } from '@/lib/cx';
import { gsap, prefersReducedMotion, ScrollTrigger, useGSAP } from '@/lib/motion/gsap';
import styles from '../landing.module.css';
import { DEMO_CANDIDATES, LOOKALIKE_RULES } from './content';

interface StoryStep {
  jobs: string;
  title: string;
  body: React.ReactNode;
}

const STEPS: StoryStep[] = [
  {
    jobs: 'scene.search · scene.download · sar.preprocess',
    title: 'A satellite looks down',
    body: (
      <>
        Sentinel-1’s radar sees through cloud and darkness. Oil damps the small waves that scatter
        radar back to the satellite, so a slick shows up as a <strong>dark patch</strong> in the
        backscatter.
      </>
    ),
  },
  {
    jobs: 'ml.detect',
    title: 'A U-Net finds an oil-like slick',
    body: (
      <>
        A per-pixel probability field, blended across tile seams and turned into outlines. At this
        point it is only a dark patch — <strong>not yet oil</strong>.
      </>
    ),
  },
  {
    jobs: 'env.fetch · detect.verify',
    title: 'Seven rules rule out look-alikes',
    body: (
      <>
        Low wind, biogenic films and rain cells darken the sea too. Wind, contrast, shape,
        elongation, power ratio, area and border are each tested — and a rule that cannot be
        evaluated <strong>says so</strong> instead of quietly passing.
      </>
    ),
  },
  {
    jobs: 'drift.hindcast',
    title: 'The oil is run backwards',
    body: (
      <>
        Thousands of particles are integrated in reverse under hourly wind and current as a{' '}
        <strong>seeded ensemble</strong> — the same inputs always give the same answer.
      </>
    ),
  },
  {
    jobs: 'drift.hindcast',
    title: 'An area, never a pin',
    body: (
      <>
        Where the particles concentrate becomes nested <strong>90 / 75 / 50 %</strong> probability
        contours with an inferred discharge window. No code path emits a single coordinate.
      </>
    ),
  },
  {
    jobs: 'ais.ingest · ais.clean · traj.build · correlate',
    title: 'Vessels that could have been there',
    body: (
      <>
        AIS tracks are cleaned (flagged, never deleted), split at reporting gaps and tested against
        the region in space and time. In the demo case <strong>6 vessels</strong> were considered;{' '}
        <strong>4</strong> were compatible and 2 were correctly excluded.
      </>
    ),
  },
  {
    jobs: 'score · report.build',
    title: 'Six factors, one auditable rank',
    body: (
      <>
        Proximity, time, trajectory, heading, speed and AIS reliability — weighted 0.35 / 0.20 /
        0.15 / 0.10 / 0.10 / 0.10 and explained one sentence each. The vessel sitting{' '}
        <strong>0.0 km from the region ranks third</strong>: a reporting gap lowered confidence in
        its track.
      </>
    ),
  },
];

function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const SLICK =
  'M292 278c26-20 70-27 112-15 36 10 62 27 96 32 27 4 47 18 38 34-11 18-41 20-66 16-46-6-86-25-132-27-36-2-62 6-82-10-16-12-9-27 34-30z';

/**
 * Schematic, but the counts are the demo's: 6 vessels considered — 4 candidate
 * tracks (three below plus MATSYA VII's, drawn with its gap) and 2 excluded.
 */
const CANDIDATE_TRACKS = [
  'M18 520 C110 482 160 452 214 426 S370 360 470 326',
  'M36 356 C108 388 160 418 206 438 S330 500 422 566',
  'M140 624 C168 546 188 486 202 434 S238 300 282 196',
];

/** MATSYA VII: a perfect match with a 14.1 h reporting gap — drawn as two segments. */
const GAP_TRACK_A = 'M8 446 C70 440 130 434 190 430';
const GAP_TRACK_GAP = 'M190 430 C220 428 244 426 262 424';
const GAP_TRACK_B = 'M262 424 C330 418 410 404 488 372';

/** The two excluded vessels (one three days too early, one ~80 km away). */
const OTHER_TRACKS = ['M440 60 C500 120 560 160 632 190', 'M520 640 C540 560 570 500 632 470'];

export function ChainStory() {
  const root = useRef<HTMLElement | null>(null);

  const particles = useMemo(() => {
    const rand = mulberry32(42);
    return Array.from({ length: 44 }, (_, i) => {
      const sx = 330 + (rand() - 0.5) * 190;
      const sy = 298 + (rand() - 0.5) * 50;
      const angle = rand() * Math.PI * 2;
      const radius = Math.sqrt(rand());
      const ex = 206 + Math.cos(angle) * radius * 78;
      const ey = 432 + Math.sin(angle) * radius * 46;
      const bend = (rand() - 0.5) * 90;
      return {
        key: i,
        sx,
        sy,
        mx: (sx + ex) / 2 + bend,
        my: (sy + ey) / 2 - Math.abs(bend) * 0.4,
        ex,
        ey,
      };
    });
  }, []);

  useGSAP(
    () => {
      const el = root.current;
      if (!el) return;
      const q = gsap.utils.selector(el);

      // Particles start on the slick.
      q('[data-particle]').forEach((dot, i) => {
        const p = particles[i];
        if (p) gsap.set(dot, { x: p.sx, y: p.sy });
      });

      const tl = gsap.timeline({ defaults: { ease: 'power2.inOut' } });

      // 1 — satellite pass
      tl.addLabel('s1', 0)
        .fromTo(
          q('[data-swath-clip]'),
          { attr: { height: 0 } },
          { attr: { height: 640 }, duration: 1, ease: 'none' },
          's1',
        )
        .fromTo(
          q('[data-sat-story]'),
          { x: 240, y: -20 },
          { x: 400, y: 660, duration: 1, ease: 'none' },
          's1',
        )
        .fromTo(q('[data-coast]'), { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.5 }, 's1');

      // 2 — slick detected
      tl.addLabel('s2', 1)
        .fromTo(q('[data-slick-line]'), { drawSVG: '0%' }, { drawSVG: '100%', duration: 0.7 }, 's2')
        .fromTo(
          q('[data-slick-fill]'),
          { autoAlpha: 0 },
          { autoAlpha: 1, duration: 0.6 },
          's2+=0.3',
        )
        .to(q('[data-swath]'), { autoAlpha: 0.25, duration: 0.6 }, 's2+=0.2');

      // 3 — look-alike rules
      tl.addLabel('s3', 2)
        .fromTo(
          q('[data-rules]'),
          { autoAlpha: 0, y: 16 },
          { autoAlpha: 1, y: 0, duration: 0.3 },
          's3',
        )
        .fromTo(
          q('[data-rule]'),
          { autoAlpha: 0, x: -8 },
          { autoAlpha: 1, x: 0, stagger: 0.07, duration: 0.2 },
          's3+=0.15',
        )
        .to(q('[data-rules]'), { autoAlpha: 0, y: -10, duration: 0.25 }, 's3+=0.8');

      // 4 — reverse drift
      tl.addLabel('s4', 3)
        .fromTo(q('[data-arrows]'), { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.3 }, 's4')
        .fromTo(
          q('[data-particle]'),
          { autoAlpha: 0 },
          { autoAlpha: 1, duration: 0.15, stagger: 0.004 },
          's4',
        );
      q('[data-particle]').forEach((dot, i) => {
        const p = particles[i];
        if (!p) return;
        tl.to(
          dot,
          {
            motionPath: {
              path: [
                { x: p.sx, y: p.sy },
                { x: p.mx, y: p.my },
                { x: p.ex, y: p.ey },
              ],
              curviness: 1.4,
            },
            duration: 0.8,
            ease: 'power1.inOut',
          },
          `s4+=${0.1 + (i % 11) * 0.012}`,
        );
      });

      // 5 — origin region
      tl.addLabel('s5', 4)
        .fromTo(
          q('[data-contour]'),
          { scale: 0, autoAlpha: 0, transformOrigin: '50% 50%' },
          { scale: 1, autoAlpha: 1, duration: 0.6, stagger: 0.12, ease: 'expo.out' },
          's5',
        )
        .fromTo(
          q('[data-contour-label]'),
          { autoAlpha: 0 },
          { autoAlpha: 1, duration: 0.3, stagger: 0.08 },
          's5+=0.4',
        )
        .to(q('[data-particle]'), { autoAlpha: 0.25, duration: 0.4 }, 's5+=0.3')
        .to(q('[data-arrows]'), { autoAlpha: 0, duration: 0.3 }, 's5+=0.3');

      // 6 — AIS tracks
      tl.addLabel('s6', 5)
        .fromTo(
          q('[data-other]'),
          { drawSVG: '0%' },
          { drawSVG: '100%', duration: 0.6, stagger: 0.05 },
          's6',
        )
        .fromTo(
          q('[data-cand]'),
          { drawSVG: '0%' },
          { drawSVG: '100%', duration: 0.7, stagger: 0.07 },
          's6+=0.1',
        )
        .fromTo(q('[data-gap]'), { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.3 }, 's6+=0.6')
        .fromTo(q('[data-ais-label]'), { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.3 }, 's6+=0.6')
        .to(q('[data-particle]'), { autoAlpha: 0, duration: 0.3 }, 's6');

      // 7 — ranking
      tl.addLabel('s7', 6)
        .to(q('[data-dim-on-rank]'), { autoAlpha: 0.35, duration: 0.4 }, 's7')
        .fromTo(
          q('[data-rank]'),
          { autoAlpha: 0, y: 30 },
          { autoAlpha: 1, y: 0, duration: 0.4, ease: 'expo.out' },
          's7',
        )
        .fromTo(
          q('[data-rank-bar]'),
          { scaleX: 0 },
          { scaleX: 1, duration: 0.5, stagger: 0.06, ease: 'expo.out' },
          's7+=0.15',
        )
        .to({}, { duration: 0.3 });

      if (prefersReducedMotion()) {
        // The finished picture, no scroll choreography.
        tl.progress(1).pause();
        return;
      }

      // Steps are equal height and the timeline has one unit per step, so a
      // window starting when the steps' top crosses 85% of the viewport puts
      // each visual stage just over half-way through by the time its text is
      // centred — the picture leads the words slightly, never lags them.
      const steps = q('[data-step]');
      const range = { start: 'top 85%', end: 'bottom 85%' };
      ScrollTrigger.create({
        trigger: q('[data-steps]')[0],
        ...range,
        scrub: 1,
        animation: tl,
      });
      gsap.fromTo(
        q('[data-progress]'),
        { scaleX: 0 },
        {
          scaleX: 1,
          ease: 'none',
          scrollTrigger: { trigger: q('[data-steps]')[0], ...range, scrub: true },
        },
      );
      steps.forEach((step) => {
        ScrollTrigger.create({
          trigger: step,
          start: 'top 62%',
          end: 'bottom 62%',
          toggleClass: { targets: step, className: styles.storyStepActive ?? '' },
        });
      });
    },
    { scope: root },
  );

  return (
    <section
      ref={root}
      className={cx(styles.section, styles.story)}
      id="chain"
      aria-labelledby="chain-title"
    >
      <div className={styles.container}>
        <div className={styles.sectionHead}>
          <span className="eyebrow">From radar to ranking</span>
          <h2 className={styles.sectionTitle} id="chain-title">
            Watch one slick become <em>a list of leads</em>
          </h2>
          <p className={styles.sectionLede}>
            Scroll through the investigation chain as it runs on the seeded demonstration case — the
            same algorithms that run on live Copernicus and AIS data, applied to synthetic
            observations so every step can be shown end to end.
          </p>
        </div>

        <div className={styles.storyGrid}>
          <ol className={styles.storySteps} data-steps="">
            {STEPS.map((step, index) => (
              <li key={step.title} className={styles.storyStep} data-step="">
                <span className={styles.stepIndex}>
                  <span>{String(index + 1).padStart(2, '0')}</span>
                  <code>{step.jobs}</code>
                </span>
                <h3 className={styles.stepTitle}>{step.title}</h3>
                <p className={styles.stepText}>{step.body}</p>
              </li>
            ))}
          </ol>

          <div className={styles.storyVisual}>
            <div className={styles.storyFrame}>
              <svg
                className={styles.storySvg}
                viewBox="0 0 640 640"
                preserveAspectRatio="xMidYMid slice"
                aria-hidden="true"
              >
                <defs>
                  <pattern id="st-grid" width="40" height="40" patternUnits="userSpaceOnUse">
                    <path
                      d="M40 0H0V40"
                      fill="none"
                      stroke="var(--map-graticule)"
                      strokeWidth="1"
                    />
                  </pattern>
                  <pattern id="st-speckle" width="18" height="18" patternUnits="userSpaceOnUse">
                    <rect
                      x="1"
                      y="2"
                      width="2"
                      height="2"
                      fill="var(--color-text)"
                      opacity="0.14"
                    />
                    <rect
                      x="9"
                      y="6"
                      width="2"
                      height="2"
                      fill="var(--color-text)"
                      opacity="0.08"
                    />
                    <rect
                      x="4"
                      y="12"
                      width="2"
                      height="2"
                      fill="var(--color-text)"
                      opacity="0.12"
                    />
                    <rect
                      x="13"
                      y="14"
                      width="2"
                      height="2"
                      fill="var(--color-text)"
                      opacity="0.06"
                    />
                  </pattern>
                  <clipPath id="st-swath-clip">
                    <rect data-swath-clip="" x="0" y="0" width="640" height="640" />
                  </clipPath>
                  <radialGradient id="st-heat" cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stopColor="var(--map-spill)" stopOpacity="0.55" />
                    <stop offset="100%" stopColor="var(--map-spill)" stopOpacity="0" />
                  </radialGradient>
                  <radialGradient id="st-origin" cx="50%" cy="50%" r="50%">
                    <stop offset="0%" stopColor="var(--map-origin)" stopOpacity="0.45" />
                    <stop offset="100%" stopColor="var(--map-origin)" stopOpacity="0.05" />
                  </radialGradient>
                  <marker
                    id="st-arrow"
                    viewBox="0 0 10 10"
                    refX="8"
                    refY="5"
                    markerWidth="6"
                    markerHeight="6"
                    orient="auto-start-reverse"
                  >
                    <path d="M0 0L10 5L0 10z" fill="var(--color-accent-2)" />
                  </marker>
                </defs>

                <rect width="640" height="640" fill="url(#st-grid)" opacity="0.6" />
                <path
                  data-coast=""
                  d="M470 0 C500 40 540 60 600 70 C620 74 640 90 640 90 L640 0 Z"
                  fill="var(--color-surface-raised)"
                  stroke="var(--color-border-strong)"
                />

                {/* 1 — SAR swath */}
                <g data-swath="" clipPath="url(#st-swath-clip)">
                  <polygon points="150,0 360,0 520,640 300,640" fill="url(#st-speckle)" />
                  <polygon
                    points="150,0 360,0 520,640 300,640"
                    fill="var(--color-accent)"
                    opacity="0.07"
                  />
                  <polygon
                    points="150,0 360,0 520,640 300,640"
                    fill="none"
                    stroke="var(--color-accent)"
                    strokeOpacity="0.35"
                    strokeDasharray="4 6"
                  />
                </g>
                <g data-sat-story="">
                  <rect x="-18" y="-3" width="12" height="6" rx="1" fill="var(--color-accent)" />
                  <rect x="6" y="-3" width="12" height="6" rx="1" fill="var(--color-accent)" />
                  <rect x="-5" y="-6" width="10" height="12" rx="2" fill="var(--color-text)" />
                </g>

                {/* 2 — slick */}
                <g data-dim-on-rank="">
                  <g data-slick-fill="">
                    <ellipse cx="330" cy="300" rx="130" ry="46" fill="url(#st-heat)" />
                    <path d={SLICK} fill="var(--map-spill)" opacity="0.45" />
                  </g>
                  <path
                    data-slick-line=""
                    d={SLICK}
                    fill="none"
                    stroke="var(--map-spill)"
                    strokeWidth="2"
                  />
                </g>

                {/* 4 — wind & current (forward direction), then particles run backwards */}
                <g
                  data-arrows=""
                  stroke="var(--color-accent-2)"
                  strokeWidth="1.6"
                  fill="none"
                  markerEnd="url(#st-arrow)"
                >
                  <path d="M150 470 C200 420 250 380 300 340" markerEnd="url(#st-arrow)" />
                  <path d="M120 400 C170 370 220 345 270 318" markerEnd="url(#st-arrow)" />
                  <path d="M200 520 C250 470 300 420 350 360" markerEnd="url(#st-arrow)" />
                  <text
                    x="96"
                    y="536"
                    className={styles.svgLabel}
                    stroke="none"
                    fill="var(--color-text-secondary)"
                  >
                    wind + current, hourly
                  </text>
                </g>
                <g fill="var(--color-accent-2)">
                  {particles.map((p) => (
                    <circle key={p.key} data-particle="" cx="0" cy="0" r="2.4" opacity="0" />
                  ))}
                </g>

                {/* 5 — origin probability region */}
                <g data-dim-on-rank="">
                  <ellipse
                    data-contour=""
                    cx="206"
                    cy="432"
                    rx="104"
                    ry="64"
                    fill="url(#st-origin)"
                    stroke="var(--map-origin)"
                    strokeOpacity="0.5"
                    strokeDasharray="5 5"
                  />
                  <ellipse
                    data-contour=""
                    cx="206"
                    cy="432"
                    rx="70"
                    ry="43"
                    fill="none"
                    stroke="var(--map-origin)"
                    strokeOpacity="0.7"
                  />
                  <ellipse
                    data-contour=""
                    cx="206"
                    cy="432"
                    rx="38"
                    ry="23"
                    fill="var(--map-origin)"
                    fillOpacity="0.18"
                    stroke="var(--map-origin)"
                  />
                  <text data-contour-label="" x="306" y="400" className={styles.svgLabel}>
                    90 %
                  </text>
                  <text data-contour-label="" x="272" y="428" className={styles.svgLabel}>
                    75 %
                  </text>
                  <text data-contour-label="" x="238" y="452" className={styles.svgLabel}>
                    50 %
                  </text>
                </g>

                {/* 6 — AIS tracks */}
                <g fill="none" strokeLinecap="round">
                  {OTHER_TRACKS.map((d) => (
                    <path
                      key={d}
                      data-other=""
                      d={d}
                      stroke="var(--map-track)"
                      strokeOpacity="0.45"
                      strokeWidth="1.3"
                    />
                  ))}
                  {CANDIDATE_TRACKS.map((d) => (
                    <path key={d} data-cand="" d={d} stroke="var(--map-vessel)" strokeWidth="1.8" />
                  ))}
                  <path data-cand="" d={GAP_TRACK_A} stroke="var(--map-vessel)" strokeWidth="1.8" />
                  <path
                    data-gap=""
                    d={GAP_TRACK_GAP}
                    stroke="var(--map-vessel)"
                    strokeOpacity="0.6"
                    strokeWidth="1.4"
                    strokeDasharray="2 5"
                  />
                  <path data-cand="" d={GAP_TRACK_B} stroke="var(--map-vessel)" strokeWidth="1.8" />
                </g>
                <text data-ais-label="" x="232" y="410" className={styles.svgLabel}>
                  14.1 h gap
                </text>
              </svg>

              <div className={styles.storyLabel}>
                <span className={styles.storyChip}>Case kutch-01</span>
                <span className={cx(styles.storyChip, styles.storyChipSynthetic)}>Synthetic</span>
              </div>

              <div
                className={cx(styles.overlayCard, styles.rulesCard)}
                data-rules=""
                aria-hidden="true"
                style={{ opacity: 0 }}
              >
                <p className={styles.overlayTitle}>detect.verify · 7 rules</p>
                {LOOKALIKE_RULES.map((rule) => (
                  <div key={rule} className={styles.ruleRow} data-rule="">
                    <IconCheck size={13} />
                    {rule}
                  </div>
                ))}
              </div>

              <div
                className={cx(styles.overlayCard, styles.rankOverlay)}
                data-rank=""
                aria-hidden="true"
                style={{ opacity: 0 }}
              >
                <p className={styles.overlayTitle}>score · candidate ranking</p>
                {DEMO_CANDIDATES.map((c) => (
                  <div
                    key={c.rank}
                    className={cx(styles.rankLine, c.highlight && styles.rankLineHighlight)}
                  >
                    <span className={styles.hudRank}>#{c.rank}</span>
                    <span className={styles.rankLineName}>
                      <span>{c.name}</span>
                      <span className={styles.rankLineBar}>
                        <i data-rank-bar="" style={{ width: `${c.score * 100}%` }} />
                      </span>
                    </span>
                    <span className={styles.rankLineScore}>{c.score.toFixed(2)}</span>
                  </div>
                ))}
                <p className={styles.capNote}>
                  Investigative scores on a 0–1 scale — leads for enquiry, never a finding.
                </p>
              </div>

              <div className={styles.storyProgress} aria-hidden="true">
                <span data-progress="" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
