'use client';

import { EmptyState } from '@/components/ui/EmptyState';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { Table, type Column } from '@/components/ui/Table';
import { formatPercent, formatScore } from '@/lib/format';
import type { AttributionFactor } from '@/lib/api/types';

export interface FactorTableProps {
  factors: readonly AttributionFactor[];
  /** The candidate this breakdown belongs to — used for accessible names. */
  candidateLabel: string;
  className?: string;
}

/**
 * The six weighted evidence factors behind one candidate's score (SCORE-007).
 *
 * All six are always shown, including the ones that scored badly: a ranking you
 * cannot audit is an oracle, and an oracle is exactly what this product must not
 * be. Weight × score = contribution is displayed as three separate columns so
 * the arithmetic is checkable by eye.
 */
export function FactorTable({ factors, candidateLabel, className }: FactorTableProps) {
  const columns: Column<AttributionFactor>[] = [
    { key: 'label', header: 'Factor', render: (factor) => factor.label },
    {
      key: 'weight',
      header: 'Weight',
      numeric: true,
      mono: true,
      width: '6rem',
      render: (factor) => formatScore(factor.weight),
    },
    {
      key: 'score',
      header: 'Score',
      numeric: true,
      mono: true,
      width: '6rem',
      render: (factor) => formatScore(factor.score),
    },
    {
      key: 'bar',
      header: 'Strength',
      width: '9rem',
      render: (factor) => (
        <ProgressBar
          label={`${factor.label} factor score for ${candidateLabel}`}
          value={factor.score * 100}
          tone={factor.score >= 0.5 ? 'accent' : 'neutral'}
          showValue={false}
          valueText={`${formatPercent(factor.score)} of this factor`}
        />
      ),
    },
    {
      key: 'contribution',
      header: 'Contribution',
      numeric: true,
      mono: true,
      width: '8rem',
      render: (factor) => formatScore(factor.contribution),
    },
    {
      key: 'explanation',
      header: 'Why',
      render: (factor) => factor.explanation,
    },
  ];

  return (
    <Table
      className={className}
      caption={`Evidence factors for ${candidateLabel}`}
      columns={columns}
      rows={factors}
      getRowKey={(factor) => factor.key}
      empty={
        <EmptyState
          compact
          title="No factors recorded"
          description="This candidate has a score but no factor breakdown, which means the scoring stage stored an incomplete result. Treat the score as unusable until the stage is re-run."
        />
      }
    />
  );
}
