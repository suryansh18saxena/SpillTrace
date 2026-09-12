'use client';

import type { CSSProperties, ReactNode } from 'react';
import { Reveal } from '@/components/motion/Reveal';
import { BorderBeam } from '@/components/motion/BorderBeam';
import { TiltCard } from '@/components/motion/TiltCard';
import { Badge } from '@/components/ui/Badge';
import { useGrowIn } from '@/components/charts/useGrowIn';
import { cx } from '@/lib/cx';
import styles from '../landing.module.css';

function BentoCard({
  className,
  tint,
  visual,
  title,
  children,
}: {
  className?: string;
  tint: string;
  visual: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <TiltCard
      as="article"
      max={5}
      className={cx(styles.bentoCard, className)}
      style={{ '--tint': tint } as CSSProperties}
    >
      <div className={styles.bentoVisual} aria-hidden="true">
        {visual}
      </div>
      <h3 className={styles.bentoTitle}>{title}</h3>
      <p className={styles.bentoText}>{children}</p>
      <BorderBeam duration={11} />
    </TiltCard>
  );
}

/**
 * SAGAR PRABHA (SYNTHETIC), rank 1 in the demo case: weight × factor score.
 * 0.35×0.96 + 0.20×1.00 + 0.15×1.00 + 0.10×0.877 + 0.10×0.989 + 0.10×0.82 = 0.9546.
 */
const DEMO_FACTORS = [
  { label: 'Origin proximity', weight: 0.35, contribution: 0.336 },
  { label: 'Time match', weight: 0.2, contribution: 0.2 },
  { label: 'Trajectory match', weight: 0.15, contribution: 0.15 },
  { label: 'Heading match', weight: 0.1, contribution: 0.0877 },
  { label: 'Speed match', weight: 0.1, contribution: 0.0989 },
  { label: 'AIS reliability', weight: 0.1, contribution: 0.082 },
];

function FactorVisual() {
  const ref = useGrowIn<HTMLDivElement>();
  return (
    <div className={styles.miniBars} ref={ref}>
      {DEMO_FACTORS.map((f) => (
        <div key={f.label} className={styles.miniBar}>
          <span>{f.label}</span>
          <span className={styles.miniTrack}>
            <span className={styles.miniCap} style={{ width: `${(f.weight / 0.35) * 100}%` }} />
            <span
              className={styles.miniFill}
              data-grow="x"
              style={{ width: `${(f.contribution / 0.35) * 100}%` }}
            />
          </span>
          <span className={styles.miniValue}>{f.contribution.toFixed(2)}</span>
        </div>
      ))}
      <p className={styles.miniCaption}>
        SAGAR PRABHA (SYNTHETIC), demo case — contribution of a possible weight. Sum 0.95.
      </p>
    </div>
  );
}

function ContourVisual() {
  return (
    <svg viewBox="0 0 400 180">
      <defs>
        <radialGradient id="bn-origin" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="var(--map-origin)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--map-origin)" stopOpacity="0.04" />
        </radialGradient>
      </defs>
      <g className={styles.breathe} style={{ transformOrigin: '200px 90px' }}>
        <ellipse
          cx="200"
          cy="90"
          rx="170"
          ry="78"
          fill="url(#bn-origin)"
          stroke="var(--map-origin)"
          strokeOpacity="0.45"
          strokeDasharray="5 6"
        />
        <ellipse
          cx="200"
          cy="90"
          rx="112"
          ry="52"
          fill="none"
          stroke="var(--map-origin)"
          strokeOpacity="0.7"
        />
        <ellipse
          cx="200"
          cy="90"
          rx="58"
          ry="27"
          fill="var(--map-origin)"
          fillOpacity="0.2"
          stroke="var(--map-origin)"
        />
      </g>
      <text x="370" y="24" textAnchor="end" className={styles.svgLabel}>
        90 %
      </text>
      <text x="316" y="50" textAnchor="end" className={styles.svgLabel}>
        75 %
      </text>
      <text x="262" y="76" textAnchor="end" className={styles.svgLabel}>
        50 %
      </text>
    </svg>
  );
}

function GapVisual() {
  return (
    <svg viewBox="0 0 400 180">
      <path
        d="M20 130 C80 120 120 100 170 92"
        fill="none"
        stroke="var(--map-vessel)"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M170 92 C200 88 230 84 250 82"
        fill="none"
        stroke="var(--map-vessel)"
        strokeOpacity="0.6"
        strokeWidth="2"
        strokeDasharray="2 7"
        strokeLinecap="round"
      />
      <path
        d="M250 82 C300 76 340 60 385 40"
        fill="none"
        stroke="var(--map-vessel)"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      {[20, 60, 100, 140, 170, 250, 290, 330, 385].map((x, i) => (
        <circle
          key={x}
          cx={x}
          cy={[130, 124, 110, 97, 92, 82, 74, 60, 40][i]}
          r="3.5"
          fill="var(--map-vessel)"
        />
      ))}
      <text x="210" y="116" textAnchor="middle" className={styles.svgLabel}>
        14.1 h without a report
      </text>
      <text x="60" y="152" className={styles.svgLabel}>
        AIS reliability
      </text>
      <text x="340" y="152" textAnchor="end" className={styles.svgLabel} fill="var(--color-text)">
        0.448
      </text>
      <rect x="60" y="162" width="280" height="8" rx="4" fill="var(--color-surface-hover)" />
      <rect x="60" y="162" width={280 * 0.448} height="8" rx="4" fill="var(--chart-series-1)" />
    </svg>
  );
}

function ProvenanceVisual() {
  return (
    <div className={styles.badgeStack}>
      <div className={styles.badgeLine}>
        Real observation <Badge tone="info">Real</Badge>
      </div>
      <div className={styles.badgeLine}>
        Demo / fallback <Badge tone="synthetic">Synthetic</Badge>
      </div>
      <div className={styles.badgeLine}>
        Combined inputs <Badge tone="warning">Mixed</Badge>
      </div>
    </div>
  );
}

/** The four claims that separate this from "an AI that spots oil". */
export function FeatureBento() {
  return (
    <section className={styles.section} aria-labelledby="bento-title">
      <div className={styles.container}>
        <div className={styles.sectionHead}>
          <span className="eyebrow">What makes it different</span>
          <h2 className={styles.sectionTitle} id="bento-title">
            Detection is stage four of thirteen. <em>The product is the attribution.</em>
          </h2>
          <p className={styles.sectionLede}>
            Spotting a dark patch on radar is close to useless on its own. The hard part is
            everything after it — and doing that honestly.
          </p>
        </div>

        <Reveal className={styles.bento} stagger={0.09} y={40}>
          <BentoCard
            className={styles.bentoWide}
            tint="var(--color-accent)"
            visual={<FactorVisual />}
            title="Every number shows its work"
          >
            Six independent factors — proximity, time, trajectory, heading, speed, AIS reliability —
            each stored, weighted and explained in a sentence with the evidence behind it. The
            weights travel with every result under a <strong>version string</strong>, so an old
            ranking can always be re-read in its own terms.
          </BentoCard>
          <BentoCard
            className={styles.bentoNarrow}
            tint="var(--map-origin)"
            visual={<ContourVisual />}
            title="An area, not a pin"
          >
            Reversing drift is uncertain, so the answer is an{' '}
            <strong>origin probability region</strong> — nested contours and an inferred window,
            never a coordinate we cannot defend.
          </BentoCard>
          <BentoCard
            className={styles.bentoNarrow}
            tint="var(--map-vessel)"
            visual={<ProvenanceVisual />}
            title="Synthetic can never pass as real"
          >
            Provenance travels on every row and response, demo vessels are suffixed
            &ldquo;(SYNTHETIC)&rdquo;, and the report leads its limitations with it.
          </BentoCard>
          <BentoCard
            className={styles.bentoWide}
            tint="var(--confidence-3)"
            visual={<GapVisual />}
            title="A dark vessel becomes less certain, not more suspect"
          >
            AIS gaps are normal — satellite revisits, receiver coverage, message collisions. A gap
            only ever lowers the <strong>AIS reliability</strong> factor, which can never raise a
            score. In the demo case a vessel 0.0 km from the region, with perfect time and track
            matches, ranks third for exactly this reason.
          </BentoCard>
        </Reveal>
      </div>
    </section>
  );
}
