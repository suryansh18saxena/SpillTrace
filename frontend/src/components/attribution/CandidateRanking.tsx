'use client';

import { Notice } from '@/components/common/Notice';
import { Badge } from '@/components/ui/Badge';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { Skeleton } from '@/components/ui/Skeleton';
import { IconChevronRight, IconTarget } from '@/components/ui/Icons';
import { cx } from '@/lib/cx';
import { formatMmsi, formatOrdinal, formatPercent, formatScore } from '@/lib/format';
import type { Attribution } from '@/lib/api/types';
import { ConfidenceBadge } from './ConfidenceBadge';
import { Disclaimer } from './Disclaimer';
import styles from './attribution.module.css';

export interface CandidateRankingProps {
  attributions: readonly Attribution[];
  /**
   * `shortfall_note` from the list response — set when the engine produced fewer
   * candidates than it would normally rank. Rendered verbatim: the list is never
   * padded to reach a target count (A-10).
   */
  shortfallNote?: string | null;
  /** List-level `disclaimer`; falls back to the per-candidate one. */
  disclaimer?: string | null;
  /** What the combined score is and is not (`score_disclaimer`). */
  scoreDisclaimer?: string | null;
  /** What proximity to the origin region does not mean (`proximity_disclaimer`). */
  proximityDisclaimer?: string | null;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  className?: string;
}

/** Colour step for a factor's own bar, on the same 3-step ramp. */
function toneForScore(score: number): 'neutral' | 'accent' {
  return score >= 0.5 ? 'accent' : 'neutral';
}

/**
 * The ranked candidate list (FR-016, SCORE-007, UI-007 surface).
 *
 * Three rules govern this component and none of them are negotiable:
 *
 *  1. The API's `disclaimer` is rendered with the ranking, and again inside each
 *     expanded breakdown. A score is never shown without it (CON-003, AC-13).
 *  2. The vocabulary is "candidate", "investigative", "signal". The words
 *     "responsible", "guilty", "proven" and "culprit" do not appear anywhere in
 *     this product's copy (CON-001).
 *  3. Every one of the six factors is displayed with its weight, its normalised
 *     score, its contribution and its explanation — the ranking is auditable, not
 *     an oracle (SCORE-007, MVP-09).
 */
export function CandidateRanking({
  attributions,
  shortfallNote,
  disclaimer,
  scoreDisclaimer,
  proximityDisclaimer,
  loading = false,
  error,
  onRetry,
  className,
}: CandidateRankingProps) {
  if (error) {
    return (
      <ErrorState
        title="Ranking unavailable"
        error={error}
        onRetry={onRetry}
        description="The candidate ranking could not be loaded."
      />
    );
  }

  if (loading && attributions.length === 0) {
    return (
      <div className={cx(styles.rankingRoot, className)} aria-busy="true">
        <span className="sr-only">Loading candidate ranking</span>
        {Array.from({ length: 3 }, (_, index) => (
          <div key={index} className={styles.candidate} style={{ padding: 'var(--space-3)' }}>
            <Skeleton height="1.25rem" width="45%" />
          </div>
        ))}
      </div>
    );
  }

  if (attributions.length === 0) {
    return (
      <EmptyState
        icon={<IconTarget size={18} />}
        title="No candidate vessels yet"
        description="Correlation and scoring have not produced any candidates for this case. Run the correlate and score stages once AIS trajectories and an origin probability region exist."
      />
    );
  }

  const serverDisclaimer =
    disclaimer?.trim() ||
    (attributions.find((item) => item.disclaimer?.trim())?.disclaimer ?? null);
  const scoringVersion = attributions[0]?.scoring_version;

  return (
    <div className={cx(styles.rankingRoot, className)}>
      <Disclaimer text={serverDisclaimer} />
      <Notice text={scoreDisclaimer} label="What this score is" />
      <Notice text={proximityDisclaimer} label="What proximity means" />
      <Notice text={shortfallNote} label="Fewer candidates than usual" tone="info" />

      {attributions.length < 3 ? (
        <p className={styles.footnote}>
          Only {attributions.length} candidate{' '}
          {attributions.length === 1 ? 'vessel was' : 'vessels were'} found in the origin region and
          time window. The list is never padded to reach a target count.
        </p>
      ) : null}

      {attributions.map((attribution) => {
        const vesselName = attribution.vessel.name?.trim() || 'Unnamed vessel';
        const isSynthetic = attribution.data_provenance === 'SYNTHETIC';
        return (
          <details key={attribution.id} className={styles.candidate}>
            <summary className={styles.candidateSummary}>
              <span className={styles.rank} aria-hidden="true">
                {attribution.rank}
              </span>
              <span className={styles.candidateIdentity}>
                <span className={styles.vesselName}>
                  <span className="sr-only">
                    {formatOrdinal(attribution.rank)} ranked candidate vessel:{' '}
                  </span>
                  {vesselName}
                </span>
                <span className={styles.vesselIds}>
                  <span>MMSI {formatMmsi(attribution.vessel.mmsi)}</span>
                  {isSynthetic ? <Badge tone="synthetic">Synthetic</Badge> : null}
                </span>
              </span>
              <span className={styles.scoreBlock}>
                <span className={styles.scoreValue}>
                  {formatScore(attribution.final_score)}
                  <span className={styles.scoreCaption}>investigative score</span>
                </span>
                <ConfidenceBadge label={attribution.confidence_label} />
                <span className={styles.chevron}>
                  <IconChevronRight size={16} />
                </span>
              </span>
            </summary>

            <div className={styles.candidateBody}>
              {attribution.factors.map((factor) => (
                <div key={factor.key} className={styles.factor}>
                  <div>
                    <p className={styles.factorLabel}>{factor.label}</p>
                    <p className={styles.factorWeight}>
                      weight {formatScore(factor.weight)} · contributes{' '}
                      {formatScore(factor.contribution)}
                    </p>
                  </div>
                  <ProgressBar
                    label={`${factor.label} factor score`}
                    value={factor.score * 100}
                    tone={toneForScore(factor.score)}
                    valueText={`${formatPercent(factor.score)} of this factor`}
                  />
                  <p className={styles.factorExplanation}>{factor.explanation}</p>
                </div>
              ))}

              <div className={styles.weightsRow}>
                {Object.entries(attribution.weights).map(([key, weight]) => (
                  <span key={key}>
                    {key}={formatScore(weight)}
                  </span>
                ))}
                {scoringVersion ? <span>scoring={scoringVersion}</span> : null}
              </div>

              <p className={styles.footnote}>
                Weights are versioned engineering defaults for this prototype, not scientifically
                validated legal probabilities; they must be calibrated on labelled cases before any
                score is treated as a measured likelihood.
              </p>

              <Disclaimer text={attribution.disclaimer} label="Applies to this candidate" />
            </div>
          </details>
        );
      })}
    </div>
  );
}
