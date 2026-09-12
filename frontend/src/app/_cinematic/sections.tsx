'use client';

import Link from 'next/link';
import { useRef, type ReactNode } from 'react';
import { Magnetic } from '@/components/motion/Magnetic';
import { Reveal } from '@/components/motion/Reveal';
import { SplitReveal } from '@/components/motion/SplitReveal';
import { IconArrowRight } from '@/components/ui/Icons';
import { LinkButton } from '@/components/ui/LinkButton';
import { cx } from '@/lib/cx';
import { gsap, prefersReducedMotion, ScrollTrigger, useGSAP } from '@/lib/motion/gsap';
import {
  CANDIDATES,
  CASE,
  DETECTION,
  DISCLAIMER,
  DRIFT,
  ENVIRONMENT,
  EXPLAINED_TOTAL,
  EXPLAINED_VESSEL,
  FACTORS,
  FINAL,
  HERO,
  SAFEGUARDS,
  TECH_LABELS,
  VESSELS,
} from './content';
import styles from './cinematic.module.css';
import { SECTIONS, type SectionId } from './timeline';

/* ------------------------------------------------------------------ frame */

interface StoryProps {
  id: SectionId;
  index: number;
  children: ReactNode;
  align?: 'left' | 'right' | 'center';
  wide?: boolean;
}

/**
 * One chapter of the scroll story: a tall section with a sticky, full-height
 * frame in which the copy fades and lifts in over the first fifth of the
 * scroll and out over the last fifth, so the scene beneath is never hidden
 * behind a wall of text. The section's own progress is exposed as `--p` for
 * CSS-driven instruments.
 */
function Story({ id, index, children, align = 'left', wide = false }: StoryProps) {
  const ref = useRef<HTMLElement>(null);
  const copy = useRef<HTMLDivElement>(null);
  const vh = SECTIONS.find((s) => s.id === id)!.vh;

  useGSAP(
    () => {
      const el = ref.current;
      const c = copy.current;
      if (!el || !c) return;
      if (prefersReducedMotion()) {
        el.style.setProperty('--p', '1');
        return;
      }
      ScrollTrigger.create({
        trigger: el,
        start: 'top top',
        end: 'bottom bottom',
        onUpdate: (self) => {
          const p = self.progress;
          el.style.setProperty('--p', p.toFixed(4));
          const fadeIn = Math.min(1, p / 0.16);
          const fadeOut = Math.min(1, (1 - p) / 0.16);
          const a = Math.min(fadeIn, fadeOut);
          const eased = a * a * (3 - 2 * a);
          gsap.set(c, { opacity: eased, y: (1 - fadeIn) * 48 - (1 - fadeOut) * 36 });
        },
      });
    },
    { scope: ref },
  );

  return (
    <section
      ref={ref}
      id={id}
      className={styles.story}
      style={{ minHeight: `${vh}vh` }}
      aria-labelledby={`${id}-title`}
      data-align={align}
    >
      <div className={styles.sticky}>
        <div ref={copy} className={cx(styles.copy, wide && styles.copyWide)}>
          <span className={cx('eyebrow', styles.index)}>
            {String(index).padStart(2, '0')} — {SECTIONS[index]!.label}
          </span>
          {children}
        </div>
      </div>
    </section>
  );
}

function Readouts({ items }: { items: { label: string; value: string; unit?: string }[] }) {
  return (
    <Reveal as="dl" className={styles.readouts} stagger={0.05}>
      {items.map((r) => (
        <div key={r.label} className={styles.readout}>
          <dt className={styles.readoutLabel}>{r.label}</dt>
          <dd className={styles.readoutValue}>
            {r.value}
            {r.unit ? <span className={styles.readoutUnit}> {r.unit}</span> : null}
          </dd>
        </div>
      ))}
    </Reveal>
  );
}

/* ------------------------------------------------------------------- hero */

export function Hero() {
  const ref = useRef<HTMLElement>(null);
  const copy = useRef<HTMLDivElement>(null);
  const vh = SECTIONS[0]!.vh;

  useGSAP(
    () => {
      const el = ref.current;
      const c = copy.current;
      if (!el || !c || prefersReducedMotion()) return;
      ScrollTrigger.create({
        trigger: el,
        start: 'top top',
        end: 'bottom bottom',
        onUpdate: (self) => {
          const p = self.progress;
          el.style.setProperty('--p', p.toFixed(4));
          const out = Math.min(1, Math.max(0, (p - 0.45) / 0.35));
          gsap.set(c, { opacity: 1 - out * out, y: -out * 60 });
        },
      });
    },
    { scope: ref },
  );

  return (
    <section
      ref={ref}
      id="hero"
      className={cx(styles.story, styles.hero)}
      style={{ minHeight: `${vh}vh` }}
      aria-labelledby="hero-title"
    >
      <div className={styles.sticky}>
        <div ref={copy} className={styles.heroCopy}>
          <Reveal className={styles.heroTag} immediate delay={0.2}>
            <span className={styles.heroTagDot} />
            {CASE.sensor} · {CASE.region}
          </Reveal>
          {/* A plain fade, not a masked split: the mask clips the glyph tops and
              breaks the gradient fill on the wordmark. */}
          <Reveal
            as="h1"
            className={styles.heroTitle}
            id="hero-title"
            immediate
            delay={0.35}
            y={40}
          >
            <span className={styles.heroWord}>{HERO.title}</span>
          </Reveal>
          <SplitReveal as="p" className={styles.heroLine} by="lines" immediate delay={0.7}>
            {HERO.line1} <em>{HERO.line2}</em>
          </SplitReveal>
          <Reveal as="p" className={styles.heroLede} immediate delay={1.05}>
            {HERO.lede}
          </Reveal>
          <Reveal className={styles.actions} immediate delay={1.2}>
            <Magnetic>
              <LinkButton
                href="/login"
                variant="primary"
                size="lg"
                leadingIcon={<IconArrowRight size={16} />}
              >
                {HERO.primary}
              </LinkButton>
            </Magnetic>
            <LinkButton href="#detect" variant="secondary" size="lg">
              {HERO.secondary}
            </LinkButton>
          </Reveal>
          <Reveal className={styles.techLabels} immediate delay={1.5} stagger={0.06}>
            {TECH_LABELS.map((label, i) => (
              <span key={label} className={styles.techLabel}>
                {i > 0 ? <span className={styles.techSep}>/</span> : null}
                {label}
              </span>
            ))}
          </Reveal>
        </div>
        <div className={styles.scrollCue} aria-hidden="true">
          <span className={styles.scrollCueLine} />
          <span>Scroll to rise</span>
        </div>
      </div>
    </section>
  );
}

/* --------------------------------------------------------------- chapters */

export function Detect() {
  return (
    <Story id="detect" index={1}>
      <SplitReveal as="h2" className={styles.headline} id="detect-title">
        The ocean leaves evidence.
      </SplitReveal>
      <Reveal as="p" className={styles.lede}>
        A Sentinel-1 radar pass sees the sea surface in any weather, day or night. Oil damps the
        capillary waves that scatter the signal back, so a slick appears as a dark, unnaturally
        smooth region against the speckle of open water.
      </Reveal>
      <Readouts
        items={[
          { label: 'SAR analysis', value: CASE.sensor },
          { label: 'Acquired', value: CASE.acquisition },
          { label: 'Anomaly', value: 'DETECTED' },
          { label: 'Max probability', value: DETECTION.maxProbability.toFixed(3) },
          { label: 'Area', value: DETECTION.areaKm2.toFixed(1), unit: 'km²' },
          { label: 'Threshold', value: DETECTION.threshold.toFixed(2) },
        ]}
      />
    </Story>
  );
}

export function Segment() {
  return (
    <Story id="segment" index={2} align="right">
      <SplitReveal as="h2" className={styles.headline} id="segment-title">
        From signal to spill.
      </SplitReveal>
      <Reveal as="p" className={styles.lede}>
        A U-Net turns the raw backscatter into a per-pixel oil probability, then seven physical
        rules ask whether it could be anything else — a calm patch, a biogenic film, a rain cell.
        Wind is the decisive test, and here it sits inside the window where radar detection is most
        reliable.
      </Reveal>
      <Reveal className={styles.morph} stagger={0.08}>
        <span>RAW SAR</span>
        <span className={styles.morphArrow}>→</span>
        <span>PROBABILITY</span>
        <span className={styles.morphArrow}>→</span>
        <span className={styles.morphOn}>SEGMENTED SLICK</span>
      </Reveal>
      <Readouts
        items={[
          { label: 'Verification', value: DETECTION.verification },
          { label: 'Confidence', value: DETECTION.verificationConfidence.toFixed(2) },
          { label: 'Contrast', value: DETECTION.contrastDb.toFixed(1), unit: 'dB' },
          { label: 'Elongation', value: `${DETECTION.elongation.toFixed(1)} : 1` },
          { label: 'Wind', value: DETECTION.windMs.toFixed(1), unit: 'm/s' },
          { label: 'Rules', value: `${DETECTION.rulesPassed} / ${DETECTION.rulesTotal} passed` },
        ]}
      />
    </Story>
  );
}

export function Match() {
  return (
    <Story id="match" index={3} wide>
      <SplitReveal as="h2" className={styles.headline} id="match-title">
        Who was there?
      </SplitReveal>
      <Reveal as="p" className={styles.lede}>
        Every vessel broadcasting AIS in the area and window is pulled in, cleaned and rebuilt into
        a time-ordered track. Nothing is deleted: a bad fix or a silent hour is flagged and kept,
        because the gaps are evidence about the data — not about the ship.
      </Reveal>
      <Reveal className={styles.panel}>
        <div className={styles.panelHead}>
          <span>VESSEL</span>
          <span>MMSI</span>
          <span>TYPE</span>
          <span>FLAG</span>
          <span>LOA</span>
        </div>
        {VESSELS.map((v) => (
          <div key={v.key} className={styles.row}>
            <span className={styles.rowName}>{v.name}</span>
            <span className={styles.mono}>{v.mmsi}</span>
            <span>{v.type}</span>
            <span>{v.flag}</span>
            <span className={styles.mono}>{v.lengthM} m</span>
          </div>
        ))}
        <p className={styles.panelNote}>
          {VESSELS.length} vessels seeded in scenario {CASE.scenario} · positions, speed and heading
          are read from the track as the scene plays.
        </p>
      </Reveal>
    </Story>
  );
}

export function Backtrack() {
  return (
    <Story id="backtrack" index={4} align="right">
      <SplitReveal as="h2" className={styles.headline} id="backtrack-title">
        Follow the trajectory back.
      </SplitReveal>
      <Reveal as="p" className={styles.lede}>
        Not the ship&rsquo;s trajectory — the oil&rsquo;s. Thousands of particles are released on
        the slick and integrated <strong>backwards</strong> under the wind and current of the day,
        each with its own wind-drift factor. Where they land is not a point but a probability
        region, with a stated confidence and an inferred discharge window.
      </Reveal>
      <Readouts
        items={[
          { label: 'Engine', value: DRIFT.engine },
          { label: 'Particles', value: `${DRIFT.particles.toLocaleString()} × ${DRIFT.ensembles}` },
          { label: 'Window', value: `${DRIFT.hours} h · ${DRIFT.stepSeconds} s step` },
          { label: 'Wind drift α', value: `${DRIFT.windDriftFactor} ± ${DRIFT.windDriftSigma}` },
          { label: 'Diffusivity K', value: `${DRIFT.diffusivity}`, unit: 'm²/s' },
          {
            label: 'Forcing',
            value: `${ENVIRONMENT.windMs} m/s wind · ${ENVIRONMENT.currentMs} m/s current`,
          },
          { label: 'Origin region', value: DRIFT.originAreaKm2.toFixed(0), unit: 'km²' },
          { label: 'Origin confidence', value: DRIFT.originConfidence.toFixed(2) },
          {
            label: 'Discharge window',
            value: `${DRIFT.windowStart} → ${DRIFT.windowEnd.replace('13 Aug ', '')}`,
          },
        ]}
      />
    </Story>
  );
}

export function Attribution() {
  return (
    <Story id="attribution" index={5} wide>
      <SplitReveal as="h2" className={styles.headline} id="attribution-title">
        From many vessels. To one probable source.
      </SplitReveal>
      <Reveal as="p" className={styles.lede}>
        A vessel becomes a candidate only if it was inside the origin region during the inferred
        window. Two of six are excluded on that test alone. The rest are scored on six independent
        factors and ranked — as evidence-weighted attribution, never as a verdict.
      </Reveal>
      <Reveal className={styles.verdict}>
        <span className="eyebrow">Most probable source</span>
        <span className={styles.verdictName}>{CANDIDATES[0]!.name}</span>
        <span className={styles.verdictScore}>
          <span className={styles.mono}>{CANDIDATES[0]!.score?.toFixed(3)}</span>
          <span className={styles.band} data-band="HIGH">
            HIGH
          </span>
          <span className={styles.verdictNote}>
            evidence-weighted attribution · {CASE.provenance}
          </span>
        </span>
      </Reveal>
      <Reveal className={styles.ranking} stagger={0.1}>
        {CANDIDATES.map((c) => (
          <div
            key={c.key}
            className={styles.rankRow}
            data-band={c.band ?? ''}
            data-rank={c.rank ?? ''}
          >
            <span className={styles.rank}>{String(c.rank).padStart(2, '0')}</span>
            <span className={styles.rankName}>
              {c.name}
              <span className={styles.rankMeta}>
                closest {c.closestKm?.toFixed(1)} km · {c.closestAt}
              </span>
            </span>
            <span className={styles.bar} aria-hidden="true">
              <span
                className={styles.barFill}
                style={{ '--w': c.score ?? 0 } as React.CSSProperties}
              />
            </span>
            <span className={cx(styles.mono, styles.score)}>{c.score?.toFixed(3)}</span>
            <span className={styles.band} data-band={c.band ?? ''}>
              {c.band}
            </span>
          </div>
        ))}
        <div className={styles.excluded}>
          {VESSELS.filter((v) => v.rank === null).map((v) => (
            <span key={v.key}>
              <span className={styles.excludedTag}>EXCLUDED</span> {v.name} — {v.note}
            </span>
          ))}
        </div>
      </Reveal>
    </Story>
  );
}

export function Explain() {
  return (
    <Story id="explain" index={6} wide>
      <SplitReveal as="h2" className={styles.headline} id="explain-title">
        Every conclusion has a trail of evidence.
      </SplitReveal>
      <Reveal as="p" className={styles.lede}>
        The system does not only say <em>who</em>; it shows <em>why</em>. Take the third-ranked
        vessel: a perfect time and track match, ranked below two others — because a 14.1-hour
        reporting gap lowers the one factor that measures what the system could not see.
      </Reveal>
      <Reveal className={styles.evidence}>
        <div className={styles.evidenceHead}>
          <span className={styles.rowName}>{EXPLAINED_VESSEL.name}</span>
          <span className={styles.mono}>
            score = Σ weight × factor = {EXPLAINED_TOTAL.toFixed(4)}
          </span>
        </div>
        {FACTORS.map((f, i) => (
          <div
            key={f.key}
            className={styles.factor}
            style={{ '--v': f.value, '--w': f.weight, '--i': i } as React.CSSProperties}
            data-weak={f.value < 0.6 ? '' : undefined}
          >
            <span className={styles.factorLabel}>
              {f.label}
              <span className={styles.factorPlain}>{f.plain}</span>
            </span>
            <span className={styles.factorBar} aria-hidden="true">
              <span className={styles.factorFill} />
            </span>
            <span className={cx(styles.mono, styles.factorNum)}>{f.value.toFixed(3)}</span>
            <span className={cx(styles.mono, styles.factorWeight)}>× {f.weight.toFixed(2)}</span>
            <span className={cx(styles.mono, styles.factorContrib)}>
              = {(f.value * f.weight).toFixed(3)}
            </span>
          </div>
        ))}
        <div className={styles.total}>
          <span>Evidence-weighted score</span>
          <span className={styles.mono}>{EXPLAINED_TOTAL.toFixed(4)}</span>
          <span className={styles.band} data-band="HIGH">
            HIGH
          </span>
        </div>
        <p className={styles.panelNote}>
          Weights are versioned prototype defaults (scoring{' '}
          <span className={styles.mono}>prd-j-v1</span>), stored with every result. Missing evidence
          scores 0.10, never 0 — absence can neither accuse nor excuse.
        </p>
      </Reveal>
    </Story>
  );
}

export function Final() {
  const vh = SECTIONS[SECTIONS.length - 1]!.vh;
  return (
    <section
      id="final"
      className={cx(styles.story, styles.final)}
      style={{ minHeight: `${vh}vh` }}
      aria-labelledby="final-title"
    >
      <div className={styles.sticky}>
        <div className={cx(styles.copy, styles.copyCenter)}>
          <SplitReveal as="h2" className={cx(styles.headline, styles.headlineXL)} id="final-title">
            {FINAL.line1} {FINAL.line2}
          </SplitReveal>
          <Reveal as="p" className={styles.lede}>
            {FINAL.lede}
          </Reveal>
          <Reveal className={styles.actions}>
            <Magnetic>
              <LinkButton
                href="/login"
                variant="primary"
                size="lg"
                leadingIcon={<IconArrowRight size={16} />}
              >
                {FINAL.primary}
              </LinkButton>
            </Magnetic>
            <LinkButton href="/transparency" variant="secondary" size="lg">
              {FINAL.secondary}
            </LinkButton>
          </Reveal>
          <Reveal as="p" className={styles.disclaimer}>
            {DISCLAIMER}
          </Reveal>
          <Reveal className={styles.safeguards} stagger={0.03}>
            {SAFEGUARDS.map((g) => (
              <Link key={g.id} href="/transparency" className={styles.safeguard} title={g.title}>
                {g.id}
              </Link>
            ))}
          </Reveal>
        </div>
      </div>
    </section>
  );
}
