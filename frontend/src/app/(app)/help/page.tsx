import type { Metadata } from 'next';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { ConfidenceBadge } from '@/components/attribution/ConfidenceBadge';
import { ContributionBars } from '@/components/charts';
import { Notice } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { PageHeader } from '@/components/layout/PageHeader';
import { Reveal } from '@/components/motion/Reveal';
import { SplitReveal } from '@/components/motion/SplitReveal';
import { Badge } from '@/components/ui/Badge';
import {
  IconActivity,
  IconArrowRight,
  IconArrowUpRight,
  IconCheck,
  IconDroplet,
  IconMinus,
  IconShield,
  IconWind,
} from '@/components/ui/Icons';
import { LinkButton } from '@/components/ui/LinkButton';
import layout from '@/components/layout/layout.module.css';
import type { AttributionFactor } from '@/lib/api/types';
import { cx } from '@/lib/cx';
import { formatScore } from '@/lib/format';
import {
  BAND_HIGH_MIN,
  BAND_MEANINGS,
  BAND_MODERATE_MIN,
  DISCLAIMERS,
  NO_TIME_OVERLAP_CEILING,
  PRD_CALIBRATION_QUOTE,
  SAFEGUARDS,
  SCORE_FACTORS,
  SCORING_VERSION,
  bandFor,
  type Band,
} from '@/app/transparency/content';
import { BandExplorer } from './BandExplorer';
import { BandMeter } from './BandMeter';
import { Glossary } from './Glossary';
import { HelpToc, type TocItem } from './HelpToc';
import { DischargeWindowFigure, OriginFigure } from './OriginFigure';
import { TourButton } from './TourButton';
import styles from './help.module.css';

export const metadata: Metadata = {
  title: 'How to read this',
  description:
    'What every score, band, contour and badge in SPILLTRACE means — and what each one does not mean.',
};

/*
 * "How to read this" — the analyst's guide.
 *
 * A static page by design: nothing here is fetched, so nothing here can be
 * mistaken for a live result. Every rule, weight, edge and notice is quoted
 * from its source (see `app/transparency/content.ts`, which the public
 * transparency page shares), and every picture that uses numbers is captioned
 * as an illustration. Interactive parts — the table of contents, the band
 * explorer, the glossary filter and the tour button — are small client islands.
 */

const SECTIONS: readonly TocItem[] = [
  { id: 'score', label: 'The investigative score' },
  { id: 'bands', label: 'Evidence-strength bands' },
  { id: 'origin', label: 'The origin region' },
  { id: 'look-alikes', label: 'Look-alike checks' },
  { id: 'ais', label: 'AIS gaps & coverage' },
  { id: 'provenance', label: 'Data provenance' },
  { id: 'safeguards', label: 'The nine safeguards' },
  { id: 'glossary', label: 'Glossary' },
  { id: 'shortcuts', label: 'Keyboard shortcuts' },
];

/**
 * Invented factor scores for the worked example — clearly captioned as such.
 * The weights are the real ones; contributions and the total are computed from
 * them, so the arithmetic on screen is the model's own.
 */
const EXAMPLE_SCORES: Record<string, number> = {
  origin_proximity: 0.8,
  time_match: 0.75,
  trajectory_match: 0.6,
  heading_match: 0.8,
  speed_match: 0.7,
  ais_reliability: 0.5,
};

const EXAMPLE_FACTORS: AttributionFactor[] = SCORE_FACTORS.map((factor) => {
  const score = EXAMPLE_SCORES[factor.key] ?? 0;
  return {
    key: factor.key,
    label: factor.label,
    weight: factor.weight,
    score,
    contribution: factor.weight * score,
    explanation: 'Illustrative value — not measured.',
  };
});

const EXAMPLE_TOTAL = EXAMPLE_FACTORS.reduce((sum, factor) => sum + factor.contribution, 0);
const MAX_WEIGHT = Math.max(...SCORE_FACTORS.map((factor) => factor.weight));

const BAND_CARDS: ReadonlyArray<{ band: Band; range: string; why: string }> = [
  {
    band: 'LOW',
    range: `score < ${formatScore(BAND_MODERATE_MIN)}`,
    why: 'A well-tracked vessel moving at a plausible speed collects roughly 0.25 from heading, speed and AIS reliability no matter where or when it was. Below about 0.45 there is no real link to the place or the time.',
  },
  {
    band: 'MODERATE',
    range: `${formatScore(BAND_MODERATE_MIN)} ≤ score < ${formatScore(BAND_HIGH_MIN)}`,
    why: 'A genuine link to the origin region or the discharge window, short of the HIGH edge. Labels are also held here when the evidence cannot separate candidates — see below.',
  },
  {
    band: 'HIGH',
    range: `score ≥ ${formatScore(BAND_HIGH_MIN)}`,
    why: `Placed so that a candidate with no overlap in time can never reach it: the most such a candidate can score is ${formatScore(NO_TIME_OVERLAP_CEILING)}.`,
  },
];

/** Weights and one-line purposes from `core/lookalike/rules.py`. */
const LOOKALIKE_RULES: ReadonlyArray<{
  label: string;
  weight: number;
  checks: string;
  veto?: string;
}> = [
  {
    label: 'Wind conditions',
    weight: 0.3,
    checks: 'Wind speed at the time of the image — the single most useful physical discriminator.',
    veto: 'below 2 m/s or above 12 m/s',
  },
  {
    label: 'Backscatter contrast',
    weight: 0.25,
    checks:
      'How much darker the feature is than the surrounding sea. 6 dB or more is strong damping.',
    veto: 'less than 2 dB',
  },
  {
    label: 'Boundary irregularity',
    weight: 0.13,
    checks:
      'How complex the outline is (a circle scores 1.0). Oil tends to exceed 1.6; low-wind patches are smooth.',
  },
  {
    label: 'Elongation',
    weight: 0.1,
    checks:
      'Length against width. Two or more is typical of a discharge trailing behind a moving vessel.',
  },
  {
    label: 'Relative backscatter variance',
    weight: 0.1,
    checks:
      'Power-to-mean ratio against the background. Oil damps uniformly, so it varies less than the sea.',
  },
  {
    label: 'Detected area',
    weight: 0.07,
    checks: 'Size. Between 0.5 and 1,500 km² is plausible for a single operational discharge.',
  },
  {
    label: 'Edge sharpness',
    weight: 0.05,
    checks:
      'How sharply the boundary changes. Oil films have defined edges; wind shadows fade out.',
  },
];

/** The wind gate — docs/DECISIONS.md AD-15, as scored by `rule_wind_window`. */
const WIND_ZONES: ReadonlyArray<{
  from: number;
  to: number;
  range: string;
  verdict: string;
  tone: string;
}> = [
  { from: 0, to: 2, range: '< 2 m/s', verdict: 'Veto — glassy sea, nothing to damp', tone: 'veto' },
  {
    from: 2,
    to: 4,
    range: '2–4',
    verdict: 'Counts against — look-alikes peak here',
    tone: 'against',
  },
  { from: 4, to: 10, range: '4–10', verdict: 'Supports — the reliable window', tone: 'support' },
  { from: 10, to: 12, range: '10–12', verdict: 'Weak support — thin films disperse', tone: 'weak' },
  { from: 12, to: 15, range: '> 12', verdict: 'Veto — slicks dispersed', tone: 'veto' },
];

/** `_HEADLINE` in core/lookalike/explain.py, verbatim. */
const OUTCOMES: ReadonlyArray<{ status: string; headline: string }> = [
  {
    status: 'VERIFIED',
    headline: 'The detected feature is consistent with an oil-like surface film.',
  },
  {
    status: 'UNCERTAIN',
    headline:
      'The evidence is mixed: the detected feature may be an oil-like film, but a natural look-alike cannot be ruled out.',
  },
  {
    status: 'FALSE_POSITIVE',
    headline: 'The detected feature is more consistent with a natural look-alike than with oil.',
  },
];

/** docs/AIS_PIPELINE.md §4 and `core/ais/constants.py`. */
const GAP_THRESHOLDS: ReadonlyArray<{ value: string; name: string; use: string; note: string }> = [
  {
    value: '30 min',
    name: 'Segment gap',
    use: 'The track is split into a new segment.',
    note: 'Bookkeeping only — it says nothing about the vessel.',
  },
  {
    value: '2 h',
    name: 'Review gap',
    use: 'Flagged for an analyst to look at.',
    note: 'Never surfaced as a signal.',
  },
  {
    value: '12 h',
    name: 'Dark period',
    use: 'Only when the gap begins more than 50 nautical miles from shore, where reception is adequate.',
    note: 'The only gap that may be surfaced — and it still lowers confidence rather than counting against the vessel.',
  },
];

/** `RELIABILITY_WEIGHT_*` in core/ais/constants.py — docs/AIS_PIPELINE.md §6. */
const RELIABILITY_PARTS: ReadonlyArray<{ name: string; weight: number; what: string }> = [
  { name: 'Coverage', weight: 0.3, what: 'Positions received against the number expected.' },
  { name: 'Continuity', weight: 0.25, what: 'How long the longest gap was, against 12 hours.' },
  { name: 'Density', weight: 0.2, what: 'How many positions fall inside the case window.' },
  { name: 'Cleanliness', weight: 0.15, what: 'The share of positions not rejected by cleaning.' },
  { name: 'Identity', weight: 0.1, what: 'IMO, name, call sign, type and dimensions present.' },
];

const PROVENANCE_CARDS: ReadonlyArray<{
  value: 'REAL' | 'SYNTHETIC' | 'MIXED';
  meaning: string;
  detail: string;
}> = [
  {
    value: 'REAL',
    meaning: 'Derived from real observations.',
    detail: 'A result is REAL only when every input that contributed to it was real.',
  },
  {
    value: 'SYNTHETIC',
    meaning: 'Deterministic synthetic data. Not a real-world observation.',
    detail:
      'Produced by the built-in generators and fallbacks — for example the analytical detector used when no trained model is registered. Synthetic vessel names end in “(SYNTHETIC)”.',
  },
  {
    value: 'MIXED',
    meaning: 'Combines real observations with synthetic or fallback-generated inputs.',
    detail: 'Any synthetic input makes a result MIXED at best. Treat it as partly demonstration.',
  },
];

const SHORTCUTS: ReadonlyArray<{ keys: string[][]; where: string; what: string }> = [
  {
    keys: [
      ['Ctrl', 'K'],
      ['⌘', 'K'],
    ],
    where: 'Anywhere in the app',
    what: 'Open or close the command palette — jump to a screen, a case or an action.',
  },
  { keys: [['↑'], ['↓']], where: 'Command palette', what: 'Move the selection.' },
  {
    keys: [['Enter']],
    where: 'Command palette',
    what: 'Open the selected screen, case or action.',
  },
  { keys: [['Esc']], where: 'Command palette', what: 'Close the palette.' },
  { keys: [['←'], ['→']], where: 'Product tour', what: 'Previous or next step.' },
  { keys: [['Esc']], where: 'Product tour', what: 'End the tour.' },
  {
    keys: [['Tab']],
    where: 'First key press on any page',
    what: 'Reveals “Skip to main content”, which jumps past the navigation.',
  },
];

// ----------------------------------------------------------------- helpers

function Section({
  id,
  index,
  title,
  lede,
  children,
}: {
  id: string;
  index: number;
  title: ReactNode;
  lede?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section id={id} className={styles.section} aria-labelledby={`${id}-title`}>
      <Reveal className={styles.sectionHead} y={18}>
        <span className={styles.sectionIndex} aria-hidden="true">
          {String(index).padStart(2, '0')}
        </span>
        <div className={styles.sectionHeadText}>
          <h2 id={`${id}-title`} className={styles.sectionTitle} tabIndex={-1}>
            {title}
          </h2>
          {lede ? <p className={styles.sectionLede}>{lede}</p> : null}
        </div>
      </Reveal>
      <div className={styles.sectionBody}>{children}</div>
    </section>
  );
}

function Kbd({ keys }: { keys: string[] }) {
  return (
    <span className={styles.keyCombo}>
      {keys.map((key, index) => (
        <span key={key} className={styles.keyCombo}>
          {index > 0 ? (
            <span className={styles.keyPlus} aria-hidden="true">
              +
            </span>
          ) : null}
          <kbd>{key}</kbd>
        </span>
      ))}
    </span>
  );
}

// -------------------------------------------------------------------- page

export default function HelpPage() {
  const exampleBand = bandFor(EXAMPLE_TOTAL);

  return (
    <main className={layout.content} id="main-content">
      <PageHeader
        eyebrow="Guide"
        title="How to read this"
        subtitle="What every score, band, contour and badge means — and, just as important, what each one does not."
        actions={
          <>
            <LinkButton
              href="/transparency"
              variant="secondary"
              leadingIcon={<IconArrowUpRight size={15} />}
            >
              Public transparency page
            </LinkButton>
            <TourButton />
          </>
        }
      />

      {/* ------------------------------------------------------------ hero */}
      <div className={`${styles.hero} grain`}>
        <svg className={styles.heroRings} viewBox="0 0 400 400" aria-hidden="true">
          <circle cx="200" cy="200" r="190" />
          <circle cx="200" cy="200" r="130" />
          <circle cx="200" cy="200" r="72" />
        </svg>
        <SplitReveal as="p" className={styles.heroLine} immediate>
          Every number in SPILLTRACE is a lead for enquiry — <em>never a verdict.</em>
        </SplitReveal>
        <p className={styles.heroLede}>
          Read this once before acting on a ranking. Each section says what a figure means, where it
          comes from, and the reading it is most often mistaken for. Nothing on this page is live
          data: pictures that use numbers are marked as illustrations.
        </p>
        <ul className={styles.heroPrinciples}>
          <li>
            <a href="#score" className={styles.principle}>
              A score is not a probability <IconArrowRight size={13} />
            </a>
          </li>
          <li>
            <a href="#ais" className={styles.principle}>
              An AIS gap is not evidence of wrongdoing <IconArrowRight size={13} />
            </a>
          </li>
          <li>
            <a href="#origin" className={styles.principle}>
              An origin is an area, not a point <IconArrowRight size={13} />
            </a>
          </li>
        </ul>
      </div>

      <div className={styles.layout}>
        <HelpToc items={SECTIONS} />

        <div className={styles.content}>
          {/* -------------------------------------------------- 1. score */}
          <Section
            id="score"
            index={1}
            title="The investigative score"
            lede="A single number on a 0–1 scale that says which candidate vessel to look at first. It is the weighted sum of six separately measured factors — and each one can, and should, be read on its own."
          >
            <Reveal className={styles.split} stagger={0.08}>
              <div className={styles.panel}>
                <p className={styles.panelKicker}>What it is</p>
                <ul className={styles.checkList}>
                  <li>
                    <IconCheck size={15} className={styles.checkIcon} />
                    <span>
                      A weighted sum of six factors, each normalised to 0–1, stored and explained on
                      its own.
                    </span>
                  </li>
                  <li>
                    <IconCheck size={15} className={styles.checkIcon} />
                    <span>A way to put leads in order so enquiry starts in the right place.</span>
                  </li>
                  <li>
                    <IconCheck size={15} className={styles.checkIcon} />
                    <span>
                      Reproducible: the exact weights travel with every result under scoring version{' '}
                      <code className={styles.inlineCode}>{SCORING_VERSION}</code>.
                    </span>
                  </li>
                </ul>
              </div>
              <div className={cx(styles.panel, styles.isNotPanel)}>
                <p className={styles.panelKicker}>What it is not</p>
                <ul className={styles.checkList}>
                  <li>
                    <IconMinus size={15} className={styles.minusIcon} />
                    <span>
                      Not a probability. Reading 0.72 as a percentage is exactly the mistake CON-003
                      forbids.
                    </span>
                  </li>
                  <li>
                    <IconMinus size={15} className={styles.minusIcon} />
                    <span>
                      Not a finding about any vessel. A score never establishes responsibility; it
                      says where to look.
                    </span>
                  </li>
                  <li>
                    <IconMinus size={15} className={styles.minusIcon} />
                    <span>
                      Not calibrated. The weights are prototype engineering defaults chosen by
                      judgement, not fitted to validated cases.
                    </span>
                  </li>
                </ul>
              </div>
            </Reveal>

            <Reveal className={styles.panel}>
              <div className={styles.panelHead}>
                <div>
                  <p className={styles.panelKicker}>The formula</p>
                  <h3 className={styles.panelTitle}>Six factors, fixed weights, summing to 1.00</h3>
                </div>
                {/* The version string is an identifier: shown exactly, never upper-cased. */}
                <span className={styles.versionChip}>scoring {SCORING_VERSION}</span>
              </div>
              <p
                className={styles.formula}
                aria-label="Final score equals 0.35 times origin proximity, plus 0.20 times time match, plus 0.15 times trajectory match, plus 0.10 times heading match, plus 0.10 times speed match, plus 0.10 times AIS reliability."
              >
                <span className={styles.formulaLead}>score =</span>
                {SCORE_FACTORS.map((factor, index) => (
                  <span key={factor.key} className={styles.formulaTerm}>
                    {index > 0 ? <span className={styles.formulaPlus}>+</span> : null}
                    <span className={styles.formulaChip}>
                      <span className={styles.formulaWeight}>{formatScore(factor.weight)}</span>×{' '}
                      {factor.label.toLowerCase()}
                    </span>
                  </span>
                ))}
              </p>

              <ul className={styles.weights} aria-label="The six factors and their weights">
                {SCORE_FACTORS.map((factor) => (
                  <li key={factor.key} className={styles.weightRow}>
                    <span className={styles.weightText}>
                      <span className={styles.weightName}>{factor.label}</span>
                      <span className={styles.weightMeaning}>{factor.meaning}</span>
                    </span>
                    <span className={styles.weightTrack} aria-hidden="true">
                      <span
                        className={styles.weightFill}
                        style={{ width: `${(factor.weight / MAX_WEIGHT) * 100}%` }}
                      />
                    </span>
                    <span className={styles.weightValue}>{formatScore(factor.weight)}</span>
                  </li>
                ))}
              </ul>
              <blockquote className={styles.quote}>
                <p>“{PRD_CALIBRATION_QUOTE}”</p>
                <footer>— Problem statement SIH26143, Part J</footer>
              </blockquote>
            </Reveal>

            <Reveal className={styles.panel}>
              <div className={styles.panelHead}>
                <div>
                  <p className={styles.panelKicker}>Worked example</p>
                  <h3 className={styles.panelTitle}>How one candidate’s score is built</h3>
                </div>
                <span className={styles.illustrationTag}>Illustration</span>
              </div>
              <p className={styles.panelText}>
                The pale track is each factor’s weight — the most it can add. The solid bar is what
                it actually added: weight × factor score. The six contributions sum to the score.
              </p>
              <ContributionBars
                factors={EXAMPLE_FACTORS}
                candidateLabel="an illustrative candidate"
              />
              <div className={styles.exampleTotal}>
                <div className={styles.exampleSum}>
                  <span className={styles.exampleSumLabel}>Sum of contributions</span>
                  <span className={styles.exampleSumValue}>{formatScore(EXAMPLE_TOTAL)}</span>
                  <ConfidenceBadge label={exampleBand} />
                </div>
                <div className={styles.exampleMeter}>
                  <BandMeter value={EXAMPLE_TOTAL} label="Illustrative score" />
                </div>
              </div>
              <p className={styles.caption}>
                <span className={styles.illustrationTag}>Illustration — not a real vessel</span>
                The factor scores are invented to show the arithmetic. The weights and band edges
                are the real ones.
              </p>
            </Reveal>

            <Reveal className={styles.panel}>
              <BandExplorer />
            </Reveal>

            <Notice text={DISCLAIMERS.score} label="Shown with every score" />
          </Section>

          {/* -------------------------------------------------- 2. bands */}
          <Section
            id="bands"
            index={2}
            title="Evidence-strength bands"
            lede="Each score also carries a label — LOW, MODERATE or HIGH — for how much corroborating evidence the candidate has. A band is a reading aid, not a likelihood of anything."
          >
            <Reveal className={styles.bandGrid} stagger={0.08}>
              {BAND_CARDS.map((card) => (
                <article key={card.band} className={styles.bandCard} data-band={card.band}>
                  <ConfidenceBadge label={card.band} />
                  <p className={styles.bandRange}>{card.range}</p>
                  <p className={styles.bandMeaning}>{BAND_MEANINGS[card.band]}</p>
                  <p className={styles.bandWhy}>
                    <span className={styles.bandWhyLabel}>Why this edge</span>
                    {card.why}
                  </p>
                </article>
              ))}
            </Reveal>

            <Reveal className={cx(styles.panel, styles.callout)}>
              <IconShield size={18} className={styles.calloutIcon} />
              <div>
                <h3 className={styles.panelTitle}>Labels can be capped. Scores never are.</h3>
                <p className={styles.panelText}>
                  A weighted sum scores each candidate on its own, so it cannot notice when a whole
                  field is indistinguishable. Before labels are attached the field is checked: if
                  more than three candidates sit within 0.02 of the top origin-proximity score, or
                  the origin confidence is below 0.60, every label is held at MODERATE and a note
                  saying why travels with each candidate. The score itself is left exactly as
                  computed — capping a label is a judgement about presentation; changing a score
                  would be a claim about evidence.
                </p>
              </div>
            </Reveal>

            <p className={styles.bodyText}>
              The edges themselves are presentation choices on uncalibrated weights, not thresholds
              derived from data. Colour follows a single warm ramp that deliberately never uses red:
              a strong signal is a lead for enquiry, not an accusation.
            </p>

            <Notice text={DISCLAIMERS.proximity} label="Shown wherever candidates are listed" />
          </Section>

          {/* ------------------------------------------------- 3. origin */}
          <Section
            id="origin"
            index={3}
            title="The origin probability region"
            lede="Where the oil most likely entered the sea — drawn as an area with its uncertainty, never as a point (CON-008)."
          >
            <Reveal className={cx(styles.panel, styles.originPanel)}>
              <div className={styles.originFigure}>
                <OriginFigure />
              </div>
              <ul className={styles.legend}>
                <li>
                  <span className={cx(styles.swatch, styles.swatchSlick)} aria-hidden="true" />
                  <span>
                    <strong>Detected slick</strong> — the only thing in this picture the radar saw.
                  </span>
                </li>
                <li>
                  <span className={cx(styles.swatch, styles.swatch50)} aria-hidden="true" />
                  <span>
                    <strong>50% contour</strong> — the smallest area holding half of the
                    back-tracked particles.
                  </span>
                </li>
                <li>
                  <span className={cx(styles.swatch, styles.swatch75)} aria-hidden="true" />
                  <span>
                    <strong>75% contour</strong> — three quarters of them.
                  </span>
                </li>
                <li>
                  <span className={cx(styles.swatch, styles.swatch90)} aria-hidden="true" />
                  <span>
                    <strong>90% contour</strong> — the widest, and the practical search area.
                  </span>
                </li>
                <li>
                  <span className={cx(styles.swatch, styles.swatchDot)} aria-hidden="true" />
                  <span>
                    <strong>Particles</strong> — one ensemble, each drifting slightly differently.
                  </span>
                </li>
                <li className={styles.legendNever}>
                  <IconMinus size={14} aria-hidden="true" />
                  <span>
                    <strong>Never drawn:</strong> a single discharge point.
                  </span>
                </li>
              </ul>
              <p className={cx(styles.caption, styles.originCaption)}>
                <span className={styles.illustrationTag}>Illustration</span>
                Schematic shapes, not a real case.
              </p>
            </Reveal>

            <Reveal className={styles.explainGrid} stagger={0.07}>
              <div className={styles.explainItem}>
                <h3 className={styles.explainTitle}>How the contours are made</h3>
                <p>
                  The drift is run backwards from the slick as an ensemble of particles. Where they
                  end up at the start of the back-track becomes a smoothed density, and each contour
                  is the smallest set of cells holding 50, 75 or 90% of it — so a contour and its
                  number always describe the same cells.
                </p>
              </div>
              <div className={styles.explainItem}>
                <h3 className={styles.explainTitle}>What “50%” does not mean</h3>
                <p>
                  It is not a 50% chance that a discharge happened inside the line. It describes the
                  simulation, which depends on interpolated wind and current fields and an uncertain
                  wind-drift factor — not a measurement of where oil entered the water.
                </p>
              </div>
              <div className={styles.explainItem}>
                <h3 className={styles.explainTitle}>Origin confidence</h3>
                <p>
                  How concentrated the back-tracked density is. It is not a probability that a
                  discharge occurred, and it is never multiplied with the detection or verification
                  confidence into one number.
                </p>
              </div>
              <div className={styles.explainItem}>
                <h3 className={styles.explainTitle}>Which engine drew it</h3>
                <p>
                  OpenDrift / OpenOil when it is installed; otherwise a deterministic analytical
                  advection–diffusion engine. Every drift run records which one produced it, and the
                  random seed, so the region can be reproduced exactly.
                </p>
              </div>
            </Reveal>

            <Reveal className={styles.panel}>
              <div className={styles.panelHead}>
                <div>
                  <p className={styles.panelKicker}>The inferred discharge window</p>
                  <h3 className={styles.panelTitle}>A period, not a timestamp</h3>
                </div>
              </div>
              <p className={styles.panelText}>
                Every time a back-tracked particle is inside the origin region, its timestamp is
                kept. The window is the middle half of those times — the 25th to the 75th percentile
                — so it narrows when wind and current constrain the problem well and widens honestly
                when they do not. If too few particles reach the region, the whole back-track span
                is used. Candidates are then looked for inside the region (with a 5 km buffer by
                default) and inside the window (with a 2-hour tolerance by default).
              </p>
              <DischargeWindowFigure />
            </Reveal>

            <Notice text={DISCLAIMERS.originRegion} label="Shown on every origin region" />
          </Section>

          {/* --------------------------------------------- 4. look-alikes */}
          <Section
            id="look-alikes"
            index={4}
            title="Look-alike verification"
            lede="Radar sees roughness, not oil. Anything that smooths the sea’s short waves makes the same dark patch — so every detection is checked against published physical rules before a single vessel is considered."
          >
            <Reveal className={styles.mimicGrid} stagger={0.07}>
              <article className={styles.mimic}>
                <span className={styles.mimicIcon} aria-hidden="true">
                  <IconWind size={17} />
                </span>
                <h3 className={styles.explainTitle}>Low wind</h3>
                <p>
                  Below about 2 m/s the sea is glassy: there are no short waves for oil to damp, so
                  a dark patch there cannot be attributed to oil at all. The wind rule treats this
                  as a veto.
                </p>
              </article>
              <article className={styles.mimic}>
                <span className={styles.mimicIcon} aria-hidden="true">
                  <IconActivity size={17} />
                </span>
                <h3 className={styles.explainTitle}>Biogenic films</h3>
                <p>
                  Natural surface films produced by marine life damp the same waves oil does. They
                  are the acknowledged hard case: no feature set separates them from mineral oil
                  reliably, and the report says so.
                </p>
              </article>
              <article className={styles.mimic}>
                <span className={styles.mimicIcon} aria-hidden="true">
                  <IconDroplet size={17} />
                </span>
                <h3 className={styles.explainTitle}>Rain cells</h3>
                <p>
                  A passing rain cell can damp the short waves beneath it and leave a dark patch of
                  its own. Internal waves, upwelling and current shear do the same — all of them
                  look like a slick to a radar.
                </p>
              </article>
            </Reveal>

            <Reveal className={styles.panel}>
              <div className={styles.panelHead}>
                <div>
                  <p className={styles.panelKicker}>The wind gate</p>
                  <h3 className={styles.panelTitle}>
                    How wind speed at the time of the image is read
                  </h3>
                </div>
              </div>
              <ol className={styles.windStrip} aria-label="Wind rule by wind speed">
                {WIND_ZONES.map((zone) => (
                  <li
                    key={zone.range}
                    className={styles.windZone}
                    data-tone={zone.tone}
                    style={{ flexGrow: zone.to - zone.from }}
                  >
                    <span className={styles.windRange}>{zone.range}</span>
                    <span className={styles.windVerdict}>{zone.verdict}</span>
                  </li>
                ))}
              </ol>
              <p className={styles.caption}>
                Widths are proportional to wind speed from 0 to 15 m/s. Thresholds from the SAR
                oil-spill literature recorded in the decision log: 95% of slicks in one large study
                were detected between 2.09 and 8.33 m/s.
              </p>
            </Reveal>

            <Reveal className={styles.panel}>
              <div className={styles.panelHead}>
                <div>
                  <p className={styles.panelKicker}>Seven rules</p>
                  <h3 className={styles.panelTitle}>
                    What each check looks at, and how much it counts
                  </h3>
                </div>
              </div>
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <caption className="sr-only">
                    Look-alike verification rules, their weights and veto conditions
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Rule</th>
                      <th scope="col">What it checks</th>
                      <th scope="col" className={styles.numCol}>
                        Weight
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {LOOKALIKE_RULES.map((rule) => (
                      <tr key={rule.label}>
                        <th scope="row">
                          {rule.label}
                          {rule.veto ? (
                            <span className={styles.vetoTag}>
                              <Badge tone="warning">veto</Badge>
                              <span className={styles.vetoWhen}>{rule.veto}</span>
                            </span>
                          ) : null}
                        </th>
                        <td>{rule.checks}</td>
                        <td className={styles.numCol} data-label="Weight">
                          {formatScore(rule.weight)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Reveal>

            <Reveal className={styles.twoUp} stagger={0.08}>
              <div className={cx(styles.panel, styles.callout)}>
                <span className={styles.notEvaluatedPill} aria-hidden="true">
                  Not evaluated
                </span>
                <div>
                  <h3 className={styles.panelTitle}>“Not evaluated” is not a failure</h3>
                  <p className={styles.panelText}>
                    A rule whose input was missing — no wind measurement, no source imagery, no
                    probability raster — says so. It is left out of the weighted evidence instead of
                    being counted against the detection. It does lower the evidence coverage, and
                    when less than 45% of the rule weight could be evaluated the verdict is
                    UNCERTAIN, whichever way the rest points.
                  </p>
                </div>
              </div>
              <div className={cx(styles.panel, styles.callout)}>
                <Badge tone="warning">veto</Badge>
                <div>
                  <h3 className={styles.panelTitle}>Vetoes are not out-voted</h3>
                  <p className={styles.panelText}>
                    Wind below 2 m/s or above 12 m/s, or contrast under 2 dB, is a physical
                    precondition that was not met. The verdict is FALSE_POSITIVE however convincing
                    the shape looks — five weak positives cannot override a physical impossibility.
                  </p>
                </div>
              </div>
            </Reveal>

            <Reveal className={styles.outcomes} stagger={0.06}>
              {OUTCOMES.map((outcome) => (
                <div key={outcome.status} className={styles.outcome}>
                  <code className={styles.outcomeStatus}>{outcome.status}</code>
                  <p>{outcome.headline}</p>
                </div>
              ))}
            </Reveal>

            <p className={styles.bodyText}>
              A FALSE_POSITIVE does not stop the chain, but the case leads with the rejection and
              candidates are kept out of the ranking headline. And verification only reduces false
              positives: it does not by itself establish that a discharge occurred.
            </p>

            <Notice text={DISCLAIMERS.detection} label="Shown on every detection" />
          </Section>

          {/* ---------------------------------------------------- 5. AIS */}
          <Section
            id="ais"
            index={5}
            title="AIS gaps and coverage"
            lede="AIS is the radio beacon vessels use to report who and where they are. It is invaluable and it is incomplete — and the system is built so that what it cannot see never counts against anyone."
          >
            <Reveal className={styles.twoUp} stagger={0.08}>
              <div className={styles.panel}>
                <p className={styles.panelKicker}>CON-002 · Gaps</p>
                <h3 className={styles.panelTitle}>
                  A gap lowers confidence. It is never evidence.
                </h3>
                <p className={styles.panelText}>
                  Vessels drop out of AIS for ordinary reasons: satellite revisit intervals, holes
                  in coastal receiver coverage, interference in busy waters, faulty equipment. So a
                  gap lowers the <em>AIS reliability</em> factor — which can only pull a score down.
                  The system cannot reward absence of evidence, and “it went dark, so it did it” is
                  exactly the inference it refuses to make.
                </p>
              </div>
              <div className={styles.panel}>
                <p className={styles.panelKicker}>CON-007 · Coverage</p>
                <h3 className={styles.panelTitle}>“No vessel seen” is not “no vessel there”.</h3>
                <p className={styles.panelText}>
                  A vessel can be missing because it was outside receiver range, because its
                  messages collided with others, or because it carries no AIS. The observed
                  reception density is recorded for each case, so an empty sea can be told apart
                  from a blind spot.
                </p>
              </div>
            </Reveal>

            <Reveal className={styles.panel}>
              <div className={styles.panelHead}>
                <div>
                  <p className={styles.panelKicker}>Three thresholds, named apart</p>
                  <h3 className={styles.panelTitle}>
                    How long a silence has to be before it means anything
                  </h3>
                </div>
              </div>
              <ol className={styles.ladder}>
                {GAP_THRESHOLDS.map((gap) => (
                  <li key={gap.name} className={styles.ladderRow}>
                    <span className={styles.ladderValue}>{gap.value}</span>
                    <span className={styles.ladderText}>
                      <strong>{gap.name}.</strong> {gap.use}
                      <span className={styles.ladderNote}>{gap.note}</span>
                    </span>
                  </li>
                ))}
              </ol>
              <p className={styles.caption}>
                Below 12 hours a gap is unreliable — a single sun-synchronous AIS satellite takes
                about that long to pass over the same place again — and near shore, coverage
                differences dominate. These are Global Fishing Watch’s published criteria.
              </p>
            </Reveal>

            <Reveal className={styles.panel}>
              <div className={styles.panelHead}>
                <div>
                  <p className={styles.panelKicker}>Inside the AIS-reliability factor</p>
                  <h3 className={styles.panelTitle}>Five parts, each 0–1</h3>
                </div>
              </div>
              <ul
                className={styles.weights}
                aria-label="AIS reliability sub-scores and their weights"
              >
                {RELIABILITY_PARTS.map((part) => (
                  <li key={part.name} className={styles.weightRow}>
                    <span className={styles.weightText}>
                      <span className={styles.weightName}>{part.name}</span>
                      <span className={styles.weightMeaning}>{part.what}</span>
                    </span>
                    <span className={styles.weightTrack} aria-hidden="true">
                      <span
                        className={styles.weightFill}
                        style={{ width: `${(part.weight / 0.3) * 100}%` }}
                      />
                    </span>
                    <span className={styles.weightValue}>{formatScore(part.weight)}</span>
                  </li>
                ))}
              </ul>
              <p className={styles.panelText}>
                Identity is worth checking by hand too: an MMSI is a radio number that gets
                reassigned, the IMO number is the durable key, and AIS can be spoofed. A position
                that matches a slick is <em>consistent with</em> a vessel’s presence, not proof of
                it.
              </p>
            </Reveal>

            <div className={styles.noticePair}>
              <Notice text={DISCLAIMERS.aisGap} label="Shown wherever a gap is displayed" />
              <Notice
                text={DISCLAIMERS.aisCoverage}
                label="Shown wherever coverage is summarised"
              />
            </div>
          </Section>

          {/* --------------------------------------------- 6. provenance */}
          <Section
            id="provenance"
            index={6}
            title="Data provenance"
            lede="Every artifact says where its data came from. The label is always text, never colour alone, so it survives a greyscale printout and every kind of colour vision."
          >
            <Reveal className={styles.provGrid} stagger={0.08}>
              {PROVENANCE_CARDS.map((card) => (
                <article key={card.value} className={styles.provCard}>
                  <ProvenanceBadge provenance={card.value} />
                  <p className={styles.provMeaning}>{card.meaning}</p>
                  <p className={styles.provDetail}>{card.detail}</p>
                </article>
              ))}
            </Reveal>
            <p className={styles.bodyText}>
              Fallbacks are labelled too. When no trained detection model is registered, a
              deterministic analytical detector runs and its output is SYNTHETIC; when the full
              drift engine is not installed, the drift run records that the analytical engine
              produced it. The chain keeps working, and nobody is misled about what produced a
              result.
            </p>
            <Notice
              text={DISCLAIMERS.synthetic}
              tone="synthetic"
              label="Shown on anything not REAL"
            />
          </Section>

          {/* --------------------------------------------- 7. safeguards */}
          <Section
            id="safeguards"
            index={7}
            title="The nine safeguards"
            lede="Constraints CON-001 to CON-009 from the problem statement, in the requirement register’s own words — with what each means in practice and how it is held."
          >
            <Reveal className={styles.guardGrid} stagger={0.05}>
              {SAFEGUARDS.map((guard) => (
                <article key={guard.id} className={styles.guard}>
                  <header className={styles.guardHead}>
                    <span className={styles.guardId}>{guard.id}</span>
                    <IconShield size={15} className={styles.guardIcon} />
                  </header>
                  <blockquote className={styles.guardRule}>{guard.rule}</blockquote>
                  <p className={styles.guardPlain}>{guard.plain}</p>
                  <p className={styles.guardHow}>
                    <span className={styles.guardHowLabel}>How it is held</span>
                    {guard.enforcement}
                  </p>
                </article>
              ))}
            </Reveal>
          </Section>

          {/* ----------------------------------------------- 8. glossary */}
          <Section
            id="glossary"
            index={8}
            title="Glossary"
            lede="The terms you will meet across the product, defined the way SPILLTRACE uses them."
          >
            <Glossary />
          </Section>

          {/* ---------------------------------------------- 9. shortcuts */}
          <Section
            id="shortcuts"
            index={9}
            title="Keyboard shortcuts"
            lede="Everything is reachable from the keyboard. These are the shortcuts worth knowing."
          >
            <Reveal className={styles.panel}>
              <div className={styles.tableWrap}>
                <table className={cx(styles.table, styles.shortcutTable)}>
                  <caption className="sr-only">Keyboard shortcuts</caption>
                  <thead>
                    <tr>
                      <th scope="col">Keys</th>
                      <th scope="col">Where</th>
                      <th scope="col">What it does</th>
                    </tr>
                  </thead>
                  <tbody>
                    {SHORTCUTS.map((shortcut) => (
                      <tr key={`${shortcut.where}-${shortcut.what}`}>
                        <td className={styles.keysCell}>
                          {shortcut.keys.map((combo, index) => (
                            <span key={combo.join('+')} className={styles.keyCombo}>
                              {index > 0 ? <span className={styles.keyOr}>or</span> : null}
                              <Kbd keys={combo} />
                            </span>
                          ))}
                        </td>
                        <td className={styles.whereCell} data-label="Where">
                          {shortcut.where}
                        </td>
                        <td>{shortcut.what}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Reveal>

            <div className={styles.outro}>
              <p>
                The same rules, written for people outside the investigation team — citizens,
                journalists and courts — are on the{' '}
                <Link href="/transparency">public transparency page</Link>.
              </p>
            </div>
          </Section>
        </div>
      </div>
    </main>
  );
}
