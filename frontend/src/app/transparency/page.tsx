import type { Metadata } from 'next';
import Link from 'next/link';
import type { ReactNode } from 'react';
import { ConfidenceBadge } from '@/components/attribution/ConfidenceBadge';
import { RadarMark } from '@/components/brand/RadarMark';
import { Notice } from '@/components/common/Notice';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { Parallax } from '@/components/motion/Parallax';
import { Reveal } from '@/components/motion/Reveal';
import { SmoothScroll } from '@/components/motion/SmoothScroll';
import { SplitReveal } from '@/components/motion/SplitReveal';
import {
  IconArrowRight,
  IconCheck,
  IconDatabase,
  IconGlobe,
  IconHistory,
  IconSatellite,
  IconShield,
  IconShip,
  IconWind,
} from '@/components/ui/Icons';
import { LinkButton } from '@/components/ui/LinkButton';
import { formatScore } from '@/lib/format';
import {
  BAND_HIGH_MIN,
  BAND_MEANINGS,
  BAND_MODERATE_MIN,
  CMEMS_ATTRIBUTION,
  DISCLAIMERS,
  NO_TIME_OVERLAP_CEILING,
  PRD_CALIBRATION_QUOTE,
  REPORT_LIMITATIONS,
  SAFEGUARDS,
  SCORE_FACTORS,
  SCORING_VERSION,
  type Band,
} from './content';
import styles from './transparency.module.css';

export const metadata: Metadata = {
  title: 'Transparency',
  description:
    'How SPILLTRACE reaches a ranking, the nine things it will never claim, how its score is built, the limits it states up front, and what a person must still do before anyone acts on its output.',
};

/*
 * Public transparency page — for citizens, journalists and courts.
 *
 * Server-rendered and static on purpose: it calls no API, shows no live
 * statistics and invents no numbers. The only figures on it are rules the
 * system is built on (weights, band edges, thresholds), each quoted from the
 * source named in `./content.ts` or in the comment beside it. Motion comes from
 * small client islands (SmoothScroll, Reveal, SplitReveal, Parallax), all of
 * which stand down under reduced motion.
 */

const CONTENTS: ReadonlyArray<{ id: string; label: string }> = [
  { id: 'does', label: 'What SPILLTRACE does' },
  { id: 'never', label: 'What it will never do' },
  { id: 'score', label: 'How a score is built' },
  { id: 'limits', label: 'Limitations, stated up front' },
  { id: 'sources', label: 'Data sources and credits' },
  { id: 'reproducibility', label: 'Reproducibility' },
  { id: 'security', label: 'Privacy and security' },
  { id: 'before-acting', label: 'Before anyone acts on a ranking' },
];

/**
 * The chain in seven plain steps — docs/REQUIREMENTS.md FR-001…FR-018, in the
 * order the pipeline actually executes (wind is loaded before verification;
 * docs/DECISIONS.md AD-30).
 */
const STEPS: ReadonlyArray<{ title: string; text: string; tag: string }> = [
  {
    title: 'An investigator opens a case',
    text: 'They draw an area of sea on a map and pin it to a window of time. Nothing outside that area and window is looked at.',
    tag: 'Area + time window',
  },
  {
    title: 'The radar image is found',
    text: 'The Copernicus catalogue is searched for Sentinel-1 radar scenes of that area and window. The chosen scene is downloaded and its checksum recorded.',
    tag: 'Sentinel-1 radar',
  },
  {
    title: 'Oil-like slicks are marked',
    text: 'The image is calibrated and tiled, a model marks the pixels that look like an oil film, and they are outlined as a slick with its measured area.',
    tag: 'Detection',
  },
  {
    title: 'Look-alikes are ruled out',
    text: 'Calm water, natural films and rain can look exactly like oil to a radar. Wind at the time of the image, and the slick’s shape and contrast, are checked against published physical rules — and every rule’s result is shown.',
    tag: 'Verified · uncertain · false positive',
  },
  {
    title: 'The drift is run backwards',
    text: 'Thousands of simulated particles are carried back in time through recorded wind and currents, to estimate the area — and the window of time — in which the oil most likely entered the sea.',
    tag: 'Origin region, never a point',
  },
  {
    title: 'Vessel tracks are compared',
    text: 'Vessel position reports (AIS) for that area and time are cleaned, joined into tracks and compared with the origin region in both space and time. Every vessel kept carries a sentence saying why.',
    tag: 'Candidates, never padded',
  },
  {
    title: 'Leads are ranked and packaged',
    text: 'Each candidate is scored on six published factors and ranked with its reasons. Everything is packaged into an evidence report with its sources, versions, checksums and limitations.',
    tag: 'Leads for enquiry',
  },
];

const BAND_ROWS: ReadonlyArray<{ band: Band; range: string }> = [
  { band: 'LOW', range: `below ${formatScore(BAND_MODERATE_MIN)}` },
  {
    band: 'MODERATE',
    range: `${formatScore(BAND_MODERATE_MIN)} to below ${formatScore(BAND_HIGH_MIN)}`,
  },
  { band: 'HIGH', range: `${formatScore(BAND_HIGH_MIN)} and above` },
];

const MAX_WEIGHT = Math.max(...SCORE_FACTORS.map((factor) => factor.weight));

/** Further limits recorded in the specifications — each with its source. */
const ALSO_STATED: ReadonlyArray<{ title: string; text: string }> = [
  {
    title: 'Detection is weaker outside its training waters',
    // docs/ML_PIPELINE.md §7, docs/DECISIONS.md AD-13
    text: 'Public oil-spill benchmarks come overwhelmingly from European waters, and models trained on them are documented to perform worse elsewhere — including the Indian waters this system targets. The evidence report says so.',
  },
  {
    title: 'No number is published that was not measured',
    // docs/ML_PIPELINE.md (opening rule), docs/FINAL_AUDIT.md
    text: 'Where a model has no recorded evaluation, the product shows “no evaluation recorded” rather than a figure. A fabricated benchmark would make the whole evidence chain worthless.',
  },
  {
    title: 'Biogenic films remain the hard case',
    // core/lookalike/explain.py, docs/DECISIONS.md AD-16
    text: 'Look-alike checks reduce false positives, but natural films produced by marine life remain difficult to separate from mineral oil in radar imagery.',
  },
  {
    title: 'AIS identity can be wrong',
    // docs/DECISIONS.md AD-25
    text: 'AIS can be spoofed and MMSI numbers are reassigned over time. A position that matches a slick is consistent with a vessel’s presence, not proof of it; the report states which identifier was used.',
  },
  {
    title: 'Data sources have their own gaps',
    // docs/DECISIONS.md AD-17, adapters/environmental/cmems.py
    text: 'The near-real-time Copernicus Marine wind product begins in June 2024, so older events need a fallback source. Any unavailable source produces a clearly failed step, never a silent substitute.',
  },
  {
    title: 'Fallbacks always say so',
    // docs/ML_PIPELINE.md §9, docs/DECISIONS.md AD-18
    text: 'With no trained model, a deterministic analytical detector runs and its output is labelled SYNTHETIC. Without the full drift engine, the drift run records that an analytical engine produced it.',
  },
];

/** `RunManifest` in backend/src/spilltrace/core/provenance.py — field names verbatim. */
const MANIFEST_FIELDS: ReadonlyArray<{ field: string; means: string }> = [
  { field: 'stage', means: 'which pipeline step produced it' },
  { field: 'software_version', means: 'the SPILLTRACE release' },
  { field: 'git_sha', means: 'the exact source revision' },
  { field: 'created_at', means: 'when, in UTC' },
  { field: 'provider', means: 'which data source adapter ran' },
  { field: 'provider_parameters', means: 'exactly what was asked of it' },
  { field: 'model_name / model_version', means: 'the model, when one was used' },
  { field: 'parameters', means: 'every tunable setting' },
  { field: 'seed', means: 'the random seed, for stochastic steps' },
  { field: 'inputs', means: 'each input and its checksum' },
  { field: 'data_provenance', means: 'REAL, SYNTHETIC or MIXED' },
  { field: 'notes', means: 'anything done differently, stated' },
];

/** docs/SECURITY.md §2 (checklist) — what is in place. */
const IN_PLACE: readonly string[] = [
  'Your browser only ever talks to the SPILLTRACE API. Copernicus and AIS credentials stay on the server, a content-security policy pins where the page may connect, and the built client bundle is scanned for credential-shaped names.',
  'No third-party requests: the map and the fonts are self-hosted, so viewing a case tells no outside service what is being looked at.',
  'Passwords are hashed with Argon2id, and sign-in takes the same time whether or not an account exists, so accounts cannot be discovered by timing.',
  'A short-lived access token is held only in memory; the refresh token sits in an httpOnly cookie, rotates on every use, and only its hash is stored.',
  'Cases are visible only to their owner and to administrators. A request for someone else’s case is answered “not found”, so case identifiers cannot be probed.',
  'Sign-in, token refresh and job creation are rate-limited. Secrets are redacted from logs and never returned in error messages.',
  'The evidence report escapes every value it prints and makes no external request.',
];

/** docs/SECURITY.md §4 — "Known gaps, stated plainly". */
const KNOWN_GAPS: readonly string[] = [
  'Dependency vulnerability scanning is not yet wired into continuous integration.',
  'The content-security policy still allows inline scripts, a documented trade-off of static rendering.',
  'The live job-progress stream accepts the access token as a URL parameter, so it can appear in proxy logs.',
  'There is no audit log yet of who read which case.',
  'There is no account lockout or multi-factor authentication.',
];

/** Human-in-the-loop — each step tied to the rule or mechanism it relies on. */
const BEFORE_ACTING: ReadonlyArray<{ title: string; text: string; ref: string }> = [
  {
    title: 'Confirm the slick is oil-like',
    text: 'Read the look-alike verdict and every rule behind it. An UNCERTAIN or FALSE_POSITIVE verdict leads the report; a rule marked “not evaluated” means an input was missing.',
    ref: 'FR-007',
  },
  {
    title: 'Check what is real',
    text: 'Look at the provenance label on every artifact. Anything SYNTHETIC or MIXED is not, or not wholly, an observation of the real sea.',
    ref: 'CON-009',
  },
  {
    title: 'Treat the origin as a search area',
    text: 'Use the probability contours, the origin confidence and the inferred window as an area and a period to search — never as a location or a time of discharge.',
    ref: 'CON-008',
  },
  {
    title: 'Read every factor, not the total',
    text: 'A score is six separate measurements. See which of them carry it, and whether a note says the labels were capped because candidates could not be told apart.',
    ref: 'SCORE-007',
  },
  {
    title: 'Treat AIS with care',
    text: 'A gap lowers confidence and proves nothing. A vessel absent from AIS may still have been there. Confirm identity by IMO number where it exists.',
    ref: 'CON-002 · CON-007',
  },
  {
    title: 'Corroborate independently',
    text: 'A ranking only says where to look first. Any action needs evidence gathered independently of SPILLTRACE, through the authority’s own lawful procedures.',
    ref: 'CON-001',
  },
  {
    title: 'Reproduce before relying',
    text: 'Re-run the stage from its recorded manifest and compare checksums. The scoring version says exactly which weights produced the number.',
    ref: 'NFR-005 · SCORE-008',
  },
  {
    title: 'Calibrate before any legal use',
    text: 'The weights are prototype defaults. Until they are calibrated on validated cases, a score may be used only to prioritise enquiry — never quoted as a probability.',
    ref: 'CON-003',
  },
];

// ------------------------------------------------------------------ pieces

function HeroArt() {
  // Decorative: nested contours and a drifting particle cloud, in the map's
  // own origin-region colour. aria-hidden via the Parallax wrapper.
  return (
    <svg className={styles.heroSvg} viewBox="0 0 520 520" fill="none">
      <g className={styles.heroContours}>
        <path d="M70 286 C58 196 118 104 214 82 C300 62 402 92 446 168 C486 238 470 330 414 392 C356 456 262 470 186 444 C114 420 78 360 70 286 Z" />
        <path d="M136 290 C128 222 170 160 238 146 C300 134 372 158 398 214 C424 270 406 332 362 368 C316 404 250 410 202 388 C160 368 140 334 136 290 Z" />
        <path d="M204 292 C200 250 226 216 266 210 C306 204 344 222 354 258 C364 294 346 330 314 344 C282 358 244 352 224 332 C210 318 206 306 204 292 Z" />
      </g>
      <g className={styles.heroRings}>
        <circle cx="270" cy="266" r="240" />
        <circle cx="270" cy="266" r="170" />
      </g>
    </svg>
  );
}

function SectionHead({
  id,
  index,
  eyebrow,
  title,
  lede,
}: {
  id: string;
  index: number;
  eyebrow: string;
  title: ReactNode;
  lede?: ReactNode;
}) {
  return (
    <header className={styles.sectionHead}>
      <p className={styles.sectionEyebrow}>
        <span className={styles.sectionNum}>{String(index).padStart(2, '0')}</span>
        {eyebrow}
      </p>
      <SplitReveal as="h2" className={styles.sectionTitle} id={`${id}-title`}>
        {title}
      </SplitReveal>
      {lede ? (
        <Reveal as="p" className={styles.sectionLede} y={16} delay={0.1}>
          {lede}
        </Reveal>
      ) : null}
    </header>
  );
}

// -------------------------------------------------------------------- page

export default function TransparencyPage() {
  return (
    <SmoothScroll>
      <div className={styles.page}>
        <header className={styles.header}>
          <div className={`${styles.container} ${styles.headerInner}`}>
            <Link href="/" className={styles.brand}>
              <RadarMark size={26} />
              <span>SPILLTRACE</span>
            </Link>
            <nav className={styles.nav} aria-label="Site">
              <Link href="/" className={styles.navLink}>
                Overview
              </Link>
              <LinkButton href="/login" variant="primary" size="sm">
                Sign in
              </LinkButton>
            </nav>
          </div>
        </header>

        <main id="main-content">
          {/* ------------------------------------------------------ hero */}
          <section className={`${styles.hero} grain`} aria-labelledby="transparency-title">
            <Parallax className={styles.heroArt} speed={-0.3} aria-hidden>
              <HeroArt />
            </Parallax>
            <div className={styles.heroVeil} aria-hidden="true" />

            <div className={`${styles.container} ${styles.heroGrid}`}>
              <div className={styles.heroCopy}>
                <p className={styles.heroEyebrow}>
                  <span className={styles.heroDot} aria-hidden="true" />
                  Public accountability · SIH26143
                </p>
                <SplitReveal as="h1" className={styles.heroTitle} id="transparency-title" immediate>
                  What SPILLTRACE does, what it refuses to do — <em>and how to hold it to that.</em>
                </SplitReveal>
                <Reveal as="p" className={styles.heroLede} immediate delay={0.25} y={18}>
                  SPILLTRACE helps an investigating authority decide which vessels to look at first
                  after an oil slick is seen from space. It produces leads for enquiry, not
                  findings, and it never establishes responsibility. This page sets out — for
                  citizens, journalists and courts — how it reaches a ranking, the safeguards
                  written into it, the limits it states up front, and what a person must still do
                  before anyone acts on its output.
                </Reveal>
                {/* Plain in-page anchors (not <Link>) so SmoothScroll can glide to them. */}
                <Reveal className={styles.heroActions} immediate delay={0.35} y={14}>
                  <a href="#never" className={`${styles.heroCta} ${styles.heroCtaPrimary}`}>
                    Read the nine safeguards
                    <IconArrowRight size={16} />
                  </a>
                  <a href="#before-acting" className={styles.heroCta}>
                    Before anyone acts on a ranking
                  </a>
                </Reveal>
              </div>

              <Reveal
                as="nav"
                className={styles.contents}
                aria-label="On this page"
                immediate
                delay={0.4}
              >
                <p className={styles.contentsTitle}>On this page</p>
                <ol className={styles.contentsList}>
                  {CONTENTS.map((item, index) => (
                    <li key={item.id}>
                      <a href={`#${item.id}`} className={styles.contentsLink}>
                        <span className={styles.contentsNum}>
                          {String(index + 1).padStart(2, '0')}
                        </span>
                        <span>{item.label}</span>
                        <IconArrowRight size={14} className={styles.contentsArrow} />
                      </a>
                    </li>
                  ))}
                </ol>
              </Reveal>
            </div>

            <div className={styles.container}>
              <Reveal className={styles.pillars} stagger={0.08} immediate delay={0.5}>
                <div className={styles.pillar}>
                  <strong>Evidence, not proof</strong>
                  <span>{DISCLAIMERS.attribution}</span>
                </div>
                <div className={styles.pillar}>
                  <strong>Six published factors</strong>
                  <span>Fixed weights, versioned and stored with every result.</span>
                </div>
                <div className={styles.pillar}>
                  <strong>Nine safeguards</strong>
                  <span>Quoted from the requirement register, held in code and report.</span>
                </div>
                <div className={styles.pillar}>
                  <strong>Reproducible</strong>
                  <span>Every artifact carries the manifest needed to re-run it.</span>
                </div>
              </Reveal>
            </div>
          </section>

          {/* ----------------------------------------------- what it does */}
          <section id="does" className={styles.section} aria-labelledby="does-title">
            <div className={styles.container}>
              <SectionHead
                id="does"
                index={1}
                eyebrow="What SPILLTRACE does"
                title={
                  <>
                    From a dark patch on a radar image to a <em>short list of leads.</em>
                  </>
                }
                lede="Seven steps. Each runs as a tracked background job, writes an artifact that can be opened and checked, and records what is needed to reproduce it."
              />
              <Reveal as="ol" className={styles.steps} stagger={0.07} y={22}>
                {STEPS.map((step, index) => (
                  <li key={step.title} className={styles.step}>
                    <span className={styles.stepNum} aria-hidden="true">
                      {index + 1}
                    </span>
                    <div className={styles.stepBody}>
                      <div className={styles.stepHead}>
                        <h3 className={styles.stepTitle}>{step.title}</h3>
                        <span className={styles.stepTag}>{step.tag}</span>
                      </div>
                      <p className={styles.stepText}>{step.text}</p>
                    </div>
                  </li>
                ))}
              </Reveal>
            </div>
          </section>

          {/* ------------------------------------------------ never do */}
          <section
            id="never"
            className={`${styles.section} ${styles.sectionAlt}`}
            aria-labelledby="never-title"
          >
            <div className={styles.container}>
              <SectionHead
                id="never"
                index={2}
                eyebrow="What it will never do"
                title={
                  <>
                    Nine things this system <em>refuses to claim.</em>
                  </>
                }
                lede="These are constraints CON-001 to CON-009 from the problem statement, in the requirement register’s own words. Beneath each: what it means in plain language, and how it is actually held."
              />
              <Reveal className={styles.guards} stagger={0.05} y={20}>
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
            </div>
          </section>

          {/* --------------------------------------------------- score */}
          <section id="score" className={styles.section} aria-labelledby="score-title">
            <div className={styles.container}>
              <SectionHead
                id="score"
                index={3}
                eyebrow="How a score is built"
                title={
                  <>
                    Six factors, fixed weights — <em>and no probability.</em>
                  </>
                }
                lede="Each candidate vessel is measured six separate ways. Each measurement is between 0 and 1, is stored, and is explained in a sentence. The score is their weighted sum: a way to decide where to look first."
              />

              <div className={styles.scoreGrid}>
                <Reveal className={styles.card}>
                  <div className={styles.cardHead}>
                    <h3 className={styles.cardTitle}>The weights</h3>
                    <span className={styles.versionChip}>scoring {SCORING_VERSION}</span>
                  </div>
                  <ul className={styles.weights} aria-label="The six factors and their weights">
                    {SCORE_FACTORS.map((factor) => (
                      <li key={factor.key} className={styles.weightRow}>
                        <span className={styles.weightHead}>
                          <span className={styles.weightName}>{factor.label}</span>
                          <span className={styles.weightValue}>{formatScore(factor.weight)}</span>
                        </span>
                        <span className={styles.weightTrack} aria-hidden="true">
                          <span
                            className={styles.weightFill}
                            style={{ width: `${(factor.weight / MAX_WEIGHT) * 100}%` }}
                          />
                        </span>
                        <span className={styles.weightMeaning}>{factor.meaning}</span>
                      </li>
                    ))}
                  </ul>
                  <p className={styles.cardFoot}>
                    The six weights sum to 1.00, so the score sits on the same 0–1 scale as its
                    factors. They travel with every result under a version string, so an old score
                    is always read in the terms it was produced under — and a re-score under a new
                    version never overwrites it.
                  </p>
                </Reveal>

                <div className={styles.scoreSide}>
                  <Reveal className={styles.card}>
                    <h3 className={styles.cardTitle}>Evidence-strength bands</h3>
                    <p className={styles.cardText}>
                      Each score also carries a label for how much corroborating evidence the
                      candidate has. It is a reading aid, not a likelihood of anything.
                    </p>
                    <ul className={styles.bandList}>
                      {BAND_ROWS.map((row) => (
                        <li key={row.band} className={styles.bandRow} data-band={row.band}>
                          <span className={styles.bandBadge}>
                            <ConfidenceBadge label={row.band} />
                          </span>
                          <span className={styles.bandRange}>{row.range}</span>
                          <span className={styles.bandMeaning}>{BAND_MEANINGS[row.band]}</span>
                        </li>
                      ))}
                    </ul>
                  </Reveal>

                  <Reveal className={styles.facts} stagger={0.06}>
                    <div className={styles.fact}>
                      <span className={styles.factValue}>
                        {formatScore(NO_TIME_OVERLAP_CEILING)}
                      </span>
                      <span className={styles.factText}>
                        The most a vessel can score with no overlap in time — just under the HIGH
                        edge. Being nearby is never enough on its own.
                      </span>
                    </div>
                    <div className={styles.fact}>
                      <span className={styles.factValue}>0–1</span>
                      <span className={styles.factText}>
                        Scores are shown on a 0–1 scale with two decimals — never as a percentage.
                      </span>
                    </div>
                    <div className={styles.fact}>
                      <span className={styles.factValue}>Capped</span>
                      <span className={styles.factText}>
                        When candidates cannot be told apart, every label is held at MODERATE with a
                        note saying why. The score itself is never changed.
                      </span>
                    </div>
                  </Reveal>
                </div>
              </div>

              <Reveal className={styles.calibration}>
                <p className={styles.calibrationLabel}>From the problem statement, verbatim</p>
                <blockquote className={styles.calibrationQuote}>
                  “{PRD_CALIBRATION_QUOTE}”
                </blockquote>
                <Notice text={DISCLAIMERS.score} label="Printed with every score" />
              </Reveal>
            </div>
          </section>

          {/* -------------------------------------------------- limits */}
          <section
            id="limits"
            className={`${styles.section} ${styles.sectionAlt}`}
            aria-labelledby="limits-title"
          >
            <div className={styles.container}>
              <SectionHead
                id="limits"
                index={4}
                eyebrow="Limitations, stated up front"
                title={
                  <>
                    What every evidence report <em>says before anything else.</em>
                  </>
                }
                lede="These seven statements are required in every evidence report. They are reproduced here word for word, in the order the report prints them."
              />
              <Reveal as="ol" className={styles.limits} stagger={0.05} y={16}>
                {REPORT_LIMITATIONS.map((text, index) => (
                  <li key={text} className={styles.limit}>
                    <span className={styles.limitNum} aria-hidden="true">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <p>{text}</p>
                  </li>
                ))}
              </Reveal>

              <Reveal>
                <Notice
                  text={DISCLAIMERS.synthetic}
                  tone="synthetic"
                  label="Printed on anything that is not real data"
                />
              </Reveal>

              <h3 className={styles.subhead}>Also stated plainly</h3>
              <Reveal className={styles.alsoGrid} stagger={0.05} y={16}>
                {ALSO_STATED.map((item) => (
                  <div key={item.title} className={styles.also}>
                    <h4 className={styles.alsoTitle}>{item.title}</h4>
                    <p>{item.text}</p>
                  </div>
                ))}
              </Reveal>
            </div>
          </section>

          {/* ------------------------------------------------- sources */}
          <section id="sources" className={styles.section} aria-labelledby="sources-title">
            <div className={styles.container}>
              <SectionHead
                id="sources"
                index={5}
                eyebrow="Data sources and credits"
                title={
                  <>
                    Where the data comes from — <em>and who to credit.</em>
                  </>
                }
                lede="Each source sits behind a swappable adapter with a deterministic fallback. Whichever one produced a result is recorded with it, and anything a fallback produced is labelled."
              />
              <Reveal className={styles.sources} stagger={0.06} y={20}>
                <article className={styles.source}>
                  <span className={styles.sourceIcon} aria-hidden="true">
                    <IconSatellite size={18} />
                  </span>
                  <h3 className={styles.sourceTitle}>Copernicus Sentinel-1</h3>
                  <p className={styles.sourceText}>
                    Radar imagery from the European Union’s Copernicus programme, searched and
                    downloaded through the Copernicus Data Space Ecosystem. Products derived from it
                    contain modified Copernicus Sentinel data.
                  </p>
                  <p className={styles.sourceFallback}>
                    Without credentials, a local fixture scene is used — and labelled.
                  </p>
                </article>

                <article className={`${styles.source} ${styles.sourceFeatured}`}>
                  <span className={styles.sourceIcon} aria-hidden="true">
                    <IconWind size={18} />
                  </span>
                  <h3 className={styles.sourceTitle}>Copernicus Marine Service</h3>
                  <p className={styles.sourceText}>
                    Hourly sea-surface wind and ocean-current fields, used by the look-alike checks
                    and to run the drift backwards. Dataset identifiers are recorded in each run’s
                    manifest and in the evidence report.
                  </p>
                  <p className={styles.attribution}>
                    <span className={styles.attributionLabel}>Required attribution</span>
                    {CMEMS_ATTRIBUTION}
                  </p>
                  <p className={styles.sourceFallback}>
                    When unavailable, a deterministic synthetic field is used — and labelled.
                  </p>
                </article>

                <article className={styles.source}>
                  <span className={styles.sourceIcon} aria-hidden="true">
                    <IconShip size={18} />
                  </span>
                  <h3 className={styles.sourceTitle}>AIS via AISStream</h3>
                  <p className={styles.sourceText}>
                    Vessel position and identity messages, received on the server for the case’s
                    area only. A free, public feed whose coverage is incomplete; production use
                    would need an authorised or contracted source.
                  </p>
                  <p className={styles.sourceFallback}>
                    A deterministic synthetic AIS generator stands in when needed — and is labelled.
                  </p>
                </article>

                <article className={styles.source}>
                  <span className={styles.sourceIcon} aria-hidden="true">
                    <IconDatabase size={18} />
                  </span>
                  <h3 className={styles.sourceTitle}>Training imagery</h3>
                  <p className={styles.sourceText}>
                    The public Sentinel-1 oil-spill, look-alike and no-oil dataset of
                    Trujillo-Acatitla et al., published on Zenodo under CC BY 4.0 (Marine Pollution
                    Bulletin, doi:10.1016/j.marpolbul.2024.116549). Any split made from it is ours,
                    and our numbers are never presented as comparable to published benchmarks.
                  </p>
                </article>

                <article className={styles.source}>
                  <span className={styles.sourceIcon} aria-hidden="true">
                    <IconGlobe size={18} />
                  </span>
                  <h3 className={styles.sourceTitle}>Drift modelling</h3>
                  <p className={styles.sourceText}>
                    The open-source OpenDrift / OpenOil framework when it is installed; otherwise a
                    deterministic analytical advection–diffusion engine. Every drift run records
                    which one produced it, and its random seed.
                  </p>
                </article>

                <article className={styles.source}>
                  <span className={styles.sourceIcon} aria-hidden="true">
                    <IconHistory size={18} />
                  </span>
                  <h3 className={styles.sourceTitle}>
                    Demonstration data <ProvenanceBadge provenance="SYNTHETIC" />
                  </h3>
                  <p className={styles.sourceText}>
                    Generated deterministically by SPILLTRACE so the whole chain can be shown with
                    no external account. Always labelled SYNTHETIC; synthetic vessel names end in
                    “(SYNTHETIC)”. It never represents a real vessel, spill or observation.
                  </p>
                </article>
              </Reveal>
            </div>
          </section>

          {/* ----------------------------------------- reproducibility */}
          <section
            id="reproducibility"
            className={`${styles.section} ${styles.sectionAlt}`}
            aria-labelledby="reproducibility-title"
          >
            <div className={styles.container}>
              <SectionHead
                id="reproducibility"
                index={6}
                eyebrow="Reproducibility"
                title={
                  <>
                    Every result carries <em>the recipe that made it.</em>
                  </>
                }
                lede="An altered score, outline or timestamp would destroy the value of everything built on it. So every artifact the pipeline writes carries a run manifest, and anyone with the same inputs and software can re-run the step and compare."
              />
              <div className={styles.reproGrid}>
                <Reveal
                  className={styles.manifest}
                  aria-label="The fields of a run manifest"
                  role="figure"
                >
                  <p className={styles.manifestHead}>
                    <span className={styles.manifestDot} aria-hidden="true" />
                    run_manifest
                  </p>
                  <dl className={styles.manifestList}>
                    {MANIFEST_FIELDS.map((item) => (
                      <div key={item.field} className={styles.manifestRow}>
                        <dt>{item.field}</dt>
                        <dd>{item.means}</dd>
                      </div>
                    ))}
                  </dl>
                </Reveal>
                <Reveal className={styles.reproFacts} stagger={0.08}>
                  <div className={styles.reproFact}>
                    <h3 className={styles.reproTitle}>Seeded simulations</h3>
                    <p>
                      The drift ensemble’s random seed is stored with the run. The same seed
                      reproduces the identical particle set — a property checked by test.
                    </p>
                  </div>
                  <div className={styles.reproFact}>
                    <h3 className={styles.reproTitle}>Versioned scoring</h3>
                    <p>
                      Weights are stored with every candidate under scoring version{' '}
                      <code>{SCORING_VERSION}</code>. A re-score under a new version adds a new
                      result; it never silently replaces the old one.
                    </p>
                  </div>
                  <div className={styles.reproFact}>
                    <h3 className={styles.reproTitle}>Checksummed artifacts</h3>
                    <p>
                      Imagery, environmental fields and reports are kept in object storage with
                      SHA-256 checksums, and the evidence report records the sources, timestamps and
                      model versions behind its figures.
                    </p>
                  </div>
                </Reveal>
              </div>
            </div>
          </section>

          {/* ------------------------------------------------ security */}
          <section id="security" className={styles.section} aria-labelledby="security-title">
            <div className={styles.container}>
              <SectionHead
                id="security"
                index={7}
                eyebrow="Privacy and security"
                title={
                  <>
                    Investigation material names vessels. <em>It is guarded accordingly.</em>
                  </>
                }
                lede="An unfinished, uncertain attribution that leaked could damage an operator who did nothing wrong. So access is restricted, secrets never leave the server, and the gaps that remain are published rather than hidden."
              />
              <div className={styles.securityGrid}>
                <Reveal className={styles.card}>
                  <h3 className={styles.cardTitle}>In place</h3>
                  <ul className={styles.checkList}>
                    {IN_PLACE.map((item) => (
                      <li key={item}>
                        <IconCheck size={15} className={styles.checkIcon} />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                </Reveal>
                <Reveal className={`${styles.card} ${styles.gapsCard}`}>
                  <h3 className={styles.cardTitle}>Known gaps, stated plainly</h3>
                  <p className={styles.cardText}>
                    From the project’s own security review. None is hidden; each is a named
                    follow-up.
                  </p>
                  <ol className={styles.gapList}>
                    {KNOWN_GAPS.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ol>
                </Reveal>
              </div>
            </div>
          </section>

          {/* ------------------------------------------- before acting */}
          <section
            id="before-acting"
            className={`${styles.section} ${styles.sectionAlt} ${styles.sectionFinal}`}
            aria-labelledby="before-acting-title"
          >
            <div className={styles.container}>
              <SectionHead
                id="before-acting"
                index={8}
                eyebrow="Before anyone acts on a ranking"
                title={
                  <>
                    SPILLTRACE decides nothing. <em>A person must.</em>
                  </>
                }
                lede="A ranking is where an enquiry starts, not where it ends. These are the steps a competent authority must take — every time — before a lead becomes an action."
              />
              <Reveal as="ol" className={styles.checklist} stagger={0.06} y={20}>
                {BEFORE_ACTING.map((step, index) => (
                  <li key={step.title} className={styles.checkItem}>
                    <span className={styles.checkNum} aria-hidden="true">
                      {index + 1}
                    </span>
                    <div>
                      <h3 className={styles.checkTitle}>{step.title}</h3>
                      <p className={styles.checkText}>{step.text}</p>
                      <span className={styles.checkRef}>{step.ref}</span>
                    </div>
                  </li>
                ))}
              </Reveal>
              <Reveal>
                <Notice
                  text={DISCLAIMERS.proximity}
                  label="Printed wherever candidates are listed"
                />
              </Reveal>
            </div>
          </section>
        </main>

        <footer className={styles.footer}>
          <div className={styles.container}>
            <div className={styles.footerTop}>
              <Link href="/" className={styles.brand}>
                <RadarMark size={22} animated={false} />
                <span>SPILLTRACE</span>
              </Link>
              <nav className={styles.footerNav} aria-label="Footer">
                <Link href="/">Overview</Link>
                <a href="#never">Safeguards</a>
                <a href="#sources">Credits</a>
                <Link href="/login">Sign in</Link>
              </nav>
            </div>
            <p className={styles.footerMeta}>
              Smart India Hackathon 2026 · Problem statement SIH26143 · Team OnlyBans
            </p>
            <p className={styles.footerFine}>
              SPILLTRACE produces investigative, probabilistic evidence to help an authority decide
              which vessels to examine next. It does not establish responsibility, a gap in AIS
              reporting is not evidence of wrongdoing, and a score is not a calibrated probability.
              Wind and ocean-current data: {CMEMS_ATTRIBUTION}.
            </p>
          </div>
        </footer>
      </div>
    </SmoothScroll>
  );
}
