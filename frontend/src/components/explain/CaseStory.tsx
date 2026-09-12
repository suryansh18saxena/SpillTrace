'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';
import { Disclaimer } from '@/components/attribution/Disclaimer';
import { ProvenanceBadge } from '@/components/common/ProvenanceBadge';
import { IconArrowRight } from '@/components/ui/Icons';
import { LinkButton } from '@/components/ui/LinkButton';
import { Skeleton } from '@/components/ui/Skeleton';
import {
  useAttributions,
  useCase,
  useDetections,
  useDriftRuns,
  useEnvironment,
  useVerification,
  useVessels,
} from '@/lib/api/hooks';
import { cx } from '@/lib/cx';
import { WHAT_IS_SPILLTRACE } from '@/lib/explain';
import {
  EMPTY_VALUE,
  formatAreaKm2,
  formatDateTimeCompact,
  formatInteger,
  formatNumber,
  formatScore,
  formatTimeRange,
  pluralize,
} from '@/lib/format';
import { ExplainTip } from './ExplainTip';
import styles from './explain.module.css';

export interface CaseStoryProps {
  caseId: string;
}

interface Figure {
  label: ReactNode;
  value: ReactNode;
}

interface Step {
  /** Everyday heading for this part of the story. */
  title: string;
  /** The machine stage names this step covers, shown small for traceability. */
  machine: string;
  /** Two or three plain sentences. */
  body: ReactNode;
  /** What this step actually produced in this case. Empty while it has not run. */
  figures: Figure[];
  /** A note printed under the figures, e.g. how a number was arrived at. */
  note?: ReactNode;
  /** The limit of what this step established. */
  caution?: string;
  /** Where to go to see this step in full. */
  href?: string;
  hrefLabel?: string;
  /** True once this step has produced something. */
  done: boolean;
  /** Why there is nothing to show yet. */
  pending?: string;
}

/**
 * One investigation, told as a story.
 *
 * Everything numeric on this screen comes from the same endpoints the other case
 * screens use — this is a different way of reading the case, never a different
 * set of facts. A step that has not run says so in words and shows no figures at
 * all, because an empty step and a step that found nothing are different claims.
 */
export function CaseStory({ caseId }: CaseStoryProps) {
  const caseQuery = useCase(caseId);
  const detections = useDetections(caseId);
  const drifts = useDriftRuns(caseId);
  const attributions = useAttributions(caseId);
  const vessels = useVessels(caseId);
  const environment = useEnvironment(caseId);

  const detection = detections.data?.items[0];
  const verification = useVerification(detection?.id);

  const loading =
    caseQuery.isPending ||
    detections.isPending ||
    drifts.isPending ||
    attributions.isPending ||
    vessels.isPending;

  if (loading) {
    return (
      <div className={styles.story} aria-busy="true">
        <span className="sr-only">Building the walkthrough for this investigation</span>
        <Skeleton height="9rem" />
        <Skeleton height="12rem" />
        <Skeleton height="12rem" />
      </div>
    );
  }

  const record = caseQuery.data;
  // `counts` is optional on the API type. Falling back to zero is honest here:
  // these are only used to decide whether a step ran at all, and zero renders the
  // "has not run yet" message rather than a fabricated figure.
  const sceneCount = record?.counts?.scenes ?? 0;
  const trajectoryCount = record?.counts?.trajectories ?? 0;
  const artifactCount = record?.counts?.artifacts ?? 0;
  const jobCount = record?.counts?.jobs ?? 0;
  const drift = drifts.data?.items[0];
  const candidates = attributions.data?.items ?? [];
  const top = candidates[0];
  const rules = verification.data?.rules ?? [];
  const rulesPassed = rules.filter((rule) => rule.passed && rule.applicable !== false).length;
  const rulesFailed = rules.filter((rule) => !rule.passed && rule.applicable !== false).length;

  // The wind that the look-alike checks were evaluated against, if it was fetched.
  const environmentSummary = environment.data?.items[0]?.summary ?? {};
  const windEntry = Object.entries(environmentSummary).find(([key]) =>
    /wind.*speed|speed.*wind/i.test(key),
  )?.[1];
  const windMean = typeof windEntry?.mean === 'number' ? windEntry.mean : null;

  const base = `/cases/${caseId}`;

  const steps: Step[] = [
    {
      title: 'Someone drew a box on the sea',
      machine: 'case created',
      body: (
        <>
          An investigation always starts with a place and a stretch of time. Everything that
          follows is limited to this{' '}
          <ExplainTip term="aoi">
            <span>area of interest</span>
          </ExplainTip>{' '}
          and this window — nothing outside either is considered.
        </>
      ),
      figures: record
        ? [
            { label: 'Area of sea', value: formatAreaKm2(record.aoi_area_km2) },
            {
              label: 'Time window',
              value: formatTimeRange(record.start_time, record.end_time),
            },
          ]
        : [],
      done: Boolean(record),
      href: base,
      hrefLabel: 'See the area on the map',
    },
    {
      title: 'A radar satellite photographed that water',
      machine: 'scene.search → scene.download → sar.preprocess',
      body: (
        <>
          An ordinary camera cannot see the sea at night or through cloud, so the system uses{' '}
          <ExplainTip term="sar">
            <span>radar</span>
          </ExplainTip>{' '}
          from the free European{' '}
          <ExplainTip term="sentinel-1">
            <span>Sentinel-1</span>
          </ExplainTip>{' '}
          satellites. A rough, windy sea scatters radar and comes back bright. A smooth sea
          reflects it away and comes back dark. The raw image is then cleaned so that dark means
          the same thing everywhere in it.
        </>
      ),
      figures:
        record && sceneCount > 0
          ? [
              {
                label: 'Images covering the area',
                value: formatInteger(sceneCount),
              },
              ...(detection
                ? [{ label: 'Image taken at', value: formatDateTimeCompact(detection.detected_at) }]
                : []),
            ]
          : [],
      caution:
        'A satellite only sees this water when it passes over it. Anything that happened between two passes leaves no image at all.',
      done: Boolean(record && sceneCount > 0),
      pending: 'No satellite image has been attached to this case yet.',
    },
    {
      title: 'The model found a dark patch',
      machine: 'ml.detect',
      body: (
        <>
          Oil flattens the small ripples that radar bounces off, so a{' '}
          <ExplainTip term="slick">
            <span>slick</span>
          </ExplainTip>{' '}
          appears as a dark shape on a bright sea. A trained neural network scores every pixel from
          0 to 1 for how oil-like it looks, and the dark shapes are traced into an outline.
        </>
      ),
      figures: detection
        ? [
            { label: 'Size of the patch', value: formatAreaKm2(detection.area_km2) },
            {
              label: 'How oil-like',
              value: formatScore(detection.detection_confidence),
            },
            {
              label: 'Strongest pixel',
              value:
                typeof detection.max_probability === 'number'
                  ? formatScore(detection.max_probability)
                  : EMPTY_VALUE,
            },
          ]
        : [],
      note: detection ? (
        <>
          Both numbers run from 0 to 1 and describe appearance in a radar image only. You can see
          the model&rsquo;s raw output for yourself by turning on the{' '}
          <ExplainTip term="probability-raster">
            <span>oil probability layer</span>
          </ExplainTip>{' '}
          on the map.
        </>
      ) : undefined,
      caution:
        'A dark patch is only a dark patch. Several completely harmless things look identical at this point, which is exactly why the next step exists.',
      done: Boolean(detection),
      pending: 'The detection step has not produced an outline for this case yet.',
      href: `${base}/spill`,
      hrefLabel: 'See what the model saw',
    },
    {
      title: 'Seven checks asked whether it could be something else',
      machine: 'env.fetch → detect.verify',
      body: (
        <>
          Low wind, algae, rain cells and river water all flatten the sea and look like oil on
          radar — these are called{' '}
          <ExplainTip term="look-alike">
            <span>look-alikes</span>
          </ExplainTip>
          . The measured wind and current for that exact hour are fetched, then seven physical
          checks are run on the patch: how dark it is, how ragged its edge is, how sharp its
          boundary is, how long and thin it is. Each check reports what it found, separately.
        </>
      ),
      figures:
        rules.length > 0
          ? [
              { label: 'Checks passed', value: formatInteger(rulesPassed) },
              { label: 'Checks failed', value: formatInteger(rulesFailed) },
              {
                label: 'Survived the checks',
                value:
                  typeof verification.data?.verification_confidence === 'number'
                    ? formatScore(verification.data.verification_confidence)
                    : EMPTY_VALUE,
              },
              ...(windMean !== null
                ? [
                    {
                      label: 'Wind at the time',
                      value: `${formatNumber(windMean, { maximumFractionDigits: 1 })} m/s`,
                    },
                  ]
                : []),
            ]
          : [],
      note:
        rules.length > 0 ? (
          <>
            This score is kept deliberately separate from the detection score above, and the two are
            never multiplied together — they answer two different questions.
          </>
        ) : undefined,
      caution:
        'These checks cut down false alarms. They cannot prove the patch is oil, and a natural film can still pass them.',
      done: rules.length > 0,
      pending: 'The look-alike checks have not run for this case yet.',
      href: `${base}/spill`,
      hrefLabel: 'Read all seven checks',
    },
    {
      title: 'The sea was run backwards to find where the oil started',
      machine: 'drift.hindcast',
      body: (
        <>
          Oil does not stay where it was spilled — wind and current carry it. Thousands of
          imaginary particles are dropped into the slick and pushed{' '}
          <ExplainTip term="drift-hindcast">
            <span>backwards</span>
          </ExplainTip>{' '}
          through the real measured weather, hour by hour. Where they bunch together is the{' '}
          <ExplainTip term="origin-region">
            <span>origin region</span>
          </ExplainTip>
          .
        </>
      ),
      figures: drift
        ? [
            {
              label: 'Region it points to',
              value:
                typeof drift.origin_area_km2 === 'number'
                  ? formatAreaKm2(drift.origin_area_km2)
                  : EMPTY_VALUE,
            },
            { label: 'How concentrated', value: formatScore(drift.origin_confidence) },
            { label: 'Particles used', value: formatInteger(drift.number_of_particles) },
            {
              label: 'Started within',
              value:
                drift.inferred_start && drift.inferred_end
                  ? formatTimeRange(drift.inferred_start, drift.inferred_end)
                  : EMPTY_VALUE,
            },
          ]
        : [],
      note: drift ? (
        <>
          Run backwards over {formatInteger(drift.duration_hours)} hours with{' '}
          {pluralize(drift.ensemble_members, 'ensemble member')}
          {drift.seed !== null ? `, seed ${drift.seed}` : ''} — the same inputs reproduce the same
          region exactly.
        </>
      ) : undefined,
      caution:
        'This is a region, never an exact discharge point, and it is not a claim that a discharge happened. Small errors in wind grow the further back you run, which is why the answer is a spread.',
      done: Boolean(drift),
      pending: 'The drift simulation has not run for this case yet.',
      href: `${base}/drift`,
      hrefLabel: 'See the origin region',
    },
    {
      title: 'Ships that were in that region at that time were listed',
      machine: 'ais.ingest → ais.clean → traj.build → correlate',
      body: (
        <>
          Most large ships continuously broadcast their identity, position and speed over a public
          radio system called{' '}
          <ExplainTip term="ais">
            <span>AIS</span>
          </ExplainTip>
          . Those broadcasts are collected, obviously bad ones are thrown out with the reason
          recorded, the rest are joined into a track per ship, and then the tracks are checked
          against the origin region and the window above.
        </>
      ),
      figures:
        record && trajectoryCount > 0
          ? [
              {
                label: 'Ships seen in the area',
                value: formatInteger(vessels.data?.total ?? trajectoryCount),
              },
              {
                label: 'Still in the region and window',
                value: formatInteger(candidates.length),
              },
            ]
          : [],
      note:
        record && trajectoryCount > 0 ? (
          <>
            Ships that were far away, or there on the wrong day, drop out at this point. The list is
            never padded to reach a target length.
          </>
        ) : undefined,
      caution:
        'Public AIS coverage is incomplete, and is thinner far from shore. A ship missing from this list was not necessarily absent from the sea.',
      done: Boolean(record && trajectoryCount > 0),
      pending: 'No ship tracks have been built for this case yet.',
    },
    {
      title: 'Each remaining ship was scored on six separate things',
      machine: 'score',
      body: (
        <>
          Every{' '}
          <ExplainTip term="candidate">
            <span>candidate</span>
          </ExplainTip>{' '}
          is scored on six factors kept apart from one another: how close it came to the origin
          region, how well its timing matches, how well its path matches, its heading, its speed,
          and how complete its own AIS reporting was. Each is scored alone, then combined using
          fixed published weights.
        </>
      ),
      figures: top
        ? [
            { label: 'Ships ranked', value: formatInteger(candidates.length) },
            {
              label: 'Highest score',
              value: (
                <>
                  {formatScore(top.final_score)}
                  <ExplainTip term="investigative-score" />
                </>
              ),
            },
            {
              label: 'Its evidence band',
              value: (
                <>
                  {top.confidence_label}
                  <ExplainTip term="band" />
                </>
              ),
            },
          ]
        : [],
      note: top ? (
        <>
          Scored with {top.scoring_version}. Open any row on the ranking screen to see all six
          factors, their weights and the arithmetic that produced the total — every rank can be
          argued with.
        </>
      ) : undefined,
      caution:
        'This sorts who is worth asking about first. It is a prototype engineering weighting, not a calibrated statistic, and the nearest ship is not automatically the source.',
      done: Boolean(top),
      pending: 'Scoring has not run for this case yet.',
      href: `${base}/ranking`,
      hrefLabel: 'Read the full ranking',
    },
    {
      title: 'Everything above was written down',
      machine: 'report.build',
      body: (
        <>
          The evidence report gathers every source, timestamp, model version, check result and
          caveat into one document, so that whoever reads it later can see exactly what was used and
          what its limits were.
        </>
      ),
      figures:
        record && artifactCount > 0
          ? [
              { label: 'Files kept as evidence', value: formatInteger(artifactCount) },
              { label: 'Steps that ran', value: formatInteger(jobCount) },
            ]
          : [],
      done: Boolean(record && artifactCount > 0),
      pending: 'The report has not been built for this case yet.',
      href: `${base}/report`,
      hrefLabel: 'Open the evidence report',
    },
  ];

  return (
    <div className={styles.story}>
      <section className={styles.storyIntro}>
        <h2 className={styles.storyIntroTitle}>{WHAT_IS_SPILLTRACE.title}</h2>
        <p className={styles.storyIntroBody}>{WHAT_IS_SPILLTRACE.body}</p>
        {WHAT_IS_SPILLTRACE.caution ? (
          <p className={styles.storyIntroCaution}>{WHAT_IS_SPILLTRACE.caution}</p>
        ) : null}
        {record ? (
          <p className={styles.storyIntroCaution} style={{ borderLeftColor: 'var(--color-accent)' }}>
            Below is what happened in this particular investigation,{' '}
            <strong>{record.title}</strong>, step by step, with the real number each step produced.
            Its data is labelled <ProvenanceBadge provenance={record.data_provenance} />.
          </p>
        ) : null}
      </section>

      <ol className={styles.steps}>
        {steps.map((step, index) => (
          <li
            key={step.title}
            className={styles.step}
            data-enter=""
            aria-label={`Step ${index + 1}: ${step.title}`}
          >
            <span
              className={cx(
                styles.stepMarker,
                step.done ? styles.stepMarkerDone : styles.stepMarkerSkipped,
              )}
              aria-hidden="true"
            >
              {index + 1}
            </span>

            <div className={styles.stepHead}>
              <h3 className={styles.stepTitle}>{step.title}</h3>
              <code className={styles.stepMachine}>{step.machine}</code>
            </div>

            <p className={styles.stepBody}>{step.body}</p>

            {step.done && step.figures.length > 0 ? (
              <div className={styles.stepResult}>
                {step.figures.map((figure, figureIndex) => (
                  <div key={figureIndex} className={styles.stepResultItem}>
                    <span className={styles.stepResultLabel}>{figure.label}</span>
                    <span className={styles.stepResultValue}>{figure.value}</span>
                  </div>
                ))}
                {step.note ? <p className={styles.stepResultNote}>{step.note}</p> : null}
              </div>
            ) : null}

            {!step.done && step.pending ? (
              <p className={styles.stepPending}>{step.pending}</p>
            ) : null}

            {step.caution ? (
              <p className={styles.stepCaution}>
                <span className={styles.stepCautionLabel}>Careful:</span>
                <span>{step.caution}</span>
              </p>
            ) : null}

            {step.href && step.done ? (
              <Link className={styles.stepLink} href={step.href}>
                {step.hrefLabel ?? 'Open'}
                <IconArrowRight size={14} />
              </Link>
            ) : null}
          </li>
        ))}
      </ol>

      <section className={styles.storyEnd}>
        <h2 className={styles.storyEndTitle}>So what does this actually tell you?</h2>
        <p className={styles.storyEndBody}>
          That a slick was seen at a place and a time, that it did not look like the natural things
          that imitate oil, that the weather points back to a region it plausibly came from, and
          that a handful of ships were in that region then. That is a starting point for an
          enquiry — somebody now has to go and check.
        </p>
        {attributions.data?.disclaimer ? (
          <div style={{ marginTop: 'var(--space-4)' }}>
            <Disclaimer text={attributions.data.disclaimer} />
          </div>
        ) : null}
        <div className={styles.storyEndActions}>
          <LinkButton href={`${base}/ranking`} variant="primary">
            See the ranked ships
          </LinkButton>
          <LinkButton href={`${base}/report`} variant="secondary">
            Open the evidence report
          </LinkButton>
          <LinkButton href="/help" variant="ghost">
            What every number means
          </LinkButton>
        </div>
      </section>
    </div>
  );
}
