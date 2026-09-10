'use client';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { EmptyState } from '@/components/ui/EmptyState';
import { Table, type Column } from '@/components/ui/Table';
import { Tooltip } from '@/components/ui/Tooltip';
import { EMPTY_VALUE, formatNumber, formatPercent } from '@/lib/format';
import type { VerificationRule } from '@/lib/api/types';

export interface RulesTableProps {
  rules: readonly VerificationRule[];
  loading?: boolean;
  error?: React.ReactNode;
  className?: string;
}

/** Three outcomes, not two: a rule that did not apply was never a failure. */
export type RuleOutcome = 'pass' | 'fail' | 'not-evaluated';

export function ruleOutcome(rule: VerificationRule): RuleOutcome {
  if (rule.applicable === false) return 'not-evaluated';
  return rule.passed ? 'pass' : 'fail';
}

const OUTCOME_TONE: Record<RuleOutcome, BadgeTone> = {
  pass: 'success',
  fail: 'warning',
  'not-evaluated': 'neutral',
};

const OUTCOME_LABEL: Record<RuleOutcome, string> = {
  pass: 'Pass',
  fail: 'Fail',
  'not-evaluated': 'Not evaluated',
};

const OUTCOME_TITLE: Record<RuleOutcome, string> = {
  pass: 'The observation is consistent with an oil-like surface film for this rule.',
  fail: 'The observation is not consistent with an oil-like film for this rule.',
  'not-evaluated':
    'This rule could not be evaluated — the input it needs was not available. It is not a failure and it did not lower the confidence.',
};

function formatScalar(value: number): string {
  const digits = Math.abs(value) >= 100 ? 1 : Math.abs(value) >= 1 ? 2 : 4;
  return formatNumber(value, { maximumFractionDigits: digits });
}

/**
 * Render a threshold, whichever of the four shapes the rule uses.
 *
 * Thresholds are genuinely heterogeneous: a scalar floor (`6.0`), an inclusive
 * range (`[0.5, 1500]`), or a named set of bounds (`{optimal_ms: [4,10],
 * glassy_below_ms: 2, …}`). Flattening all of that to one number would misstate
 * the rule, so each shape is rendered as what it is.
 */
export function formatThreshold(threshold: VerificationRule['threshold']): string {
  if (threshold === null || threshold === undefined) return EMPTY_VALUE;
  if (typeof threshold === 'number') return formatScalar(threshold);
  if (typeof threshold === 'string') return threshold;
  if (Array.isArray(threshold)) {
    const parts = threshold.map((entry) =>
      typeof entry === 'number' ? formatScalar(entry) : String(entry),
    );
    return parts.length === 2 ? `${parts[0]} – ${parts[1]}` : parts.join(', ');
  }
  return Object.entries(threshold)
    .map(([key, value]) => {
      const label = key.replace(/_/g, ' ');
      if (Array.isArray(value)) {
        const parts = value.map((entry) =>
          typeof entry === 'number' ? formatScalar(entry) : String(entry),
        );
        return `${label} ${parts.join(' – ')}`;
      }
      if (typeof value === 'number') return `${label} ${formatScalar(value)}`;
      return `${label} ${String(value)}`;
    })
    .join(' · ');
}

export function formatObserved(observed: VerificationRule['observed']): string {
  if (observed === null || observed === undefined) return EMPTY_VALUE;
  if (typeof observed === 'number') return formatScalar(observed);
  return observed;
}

/**
 * The look-alike verification rules (UI-005, FR-008).
 *
 * A SAR dark patch is not automatically oil: low wind, biogenic films and rain
 * cells all produce one. This table is how the product shows its working —
 * every rule with what was observed, what the threshold was, and which of the
 * three outcomes it reached. A rule that could not be evaluated says so rather
 * than being silently counted as a pass or a failure.
 */
export function RulesTable({ rules, loading = false, error, className }: RulesTableProps) {
  const columns: Column<VerificationRule>[] = [
    {
      key: 'label',
      header: 'Rule',
      render: (rule) => (
        <span>
          {rule.label}
          {rule.veto ? (
            <>
              {' '}
              <Badge
                tone="warning"
                title="A veto rule can reject a detection on its own, whatever the other rules say."
              >
                veto
              </Badge>
            </>
          ) : null}
        </span>
      ),
    },
    {
      key: 'outcome',
      header: 'Outcome',
      width: '9rem',
      render: (rule) => {
        const outcome = ruleOutcome(rule);
        return (
          <Badge tone={OUTCOME_TONE[outcome]} dot title={OUTCOME_TITLE[outcome]}>
            {OUTCOME_LABEL[outcome]}
          </Badge>
        );
      },
    },
    {
      key: 'observed',
      header: 'Observed',
      numeric: true,
      mono: true,
      width: '7rem',
      render: (rule) =>
        rule.applicable === false ? EMPTY_VALUE : formatObserved(rule.observed ?? null),
    },
    {
      key: 'threshold',
      header: 'Threshold',
      mono: true,
      width: '14rem',
      render: (rule) => formatThreshold(rule.threshold ?? null),
    },
    {
      key: 'weight',
      header: 'Weight',
      numeric: true,
      mono: true,
      width: '6rem',
      render: (rule) =>
        typeof rule.weight === 'number' ? (
          <Tooltip content="How much this rule contributes to the overall verification confidence.">
            <span tabIndex={0}>{formatPercent(rule.weight)}</span>
          </Tooltip>
        ) : (
          EMPTY_VALUE
        ),
    },
    {
      key: 'message',
      header: 'What it means',
      render: (rule) => rule.message ?? EMPTY_VALUE,
    },
  ];

  return (
    <Table
      className={className}
      caption="Look-alike verification rules"
      columns={columns}
      rows={rules}
      getRowKey={(rule, index) => rule.rule_id || `rule-${index}`}
      loading={loading}
      error={error}
      empty={
        <EmptyState
          compact
          title="No rules were recorded"
          description="Verification has not run for this detection, so no look-alike rule was evaluated. Run the detect.verify stage to produce them."
        />
      }
    />
  );
}
