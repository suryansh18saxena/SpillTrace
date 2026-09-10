import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CandidateRanking } from '@/components/attribution/CandidateRanking';
import { FactorTable } from '@/components/attribution/FactorTable';
import type { Attribution, AttributionFactor } from '@/lib/api/types';

/** The six factors, verbatim in shape from a live `GET /cases/{id}/attributions`. */
const FACTORS: AttributionFactor[] = [
  {
    key: 'origin_proximity',
    label: 'Origin proximity',
    weight: 0.35,
    score: 0.96,
    contribution: 0.336,
    explanation:
      'Closest approach to the origin probability region was 0.0 km at 2026-08-13T10:42Z, inside the 90th-percentile contour.',
  },
  {
    key: 'time_match',
    label: 'Time match',
    weight: 0.2,
    score: 0.91,
    contribution: 0.182,
    explanation: 'Present for 147 minutes of the inferred discharge window.',
  },
  {
    key: 'trajectory_match',
    label: 'Trajectory match',
    weight: 0.15,
    score: 0.88,
    contribution: 0.132,
    explanation: 'The track runs along the long axis of the slick.',
  },
  {
    key: 'heading_match',
    label: 'Heading match',
    weight: 0.1,
    score: 0.94,
    contribution: 0.094,
    explanation: 'Course was within 12° of the slick axis.',
  },
  {
    key: 'speed_match',
    label: 'Speed match',
    weight: 0.1,
    score: 0.99,
    contribution: 0.099,
    explanation: '11.2 knots is a typical operational-discharge transit speed.',
  },
  {
    key: 'ais_reliability',
    label: 'AIS reliability',
    weight: 0.1,
    score: 1,
    contribution: 0.1,
    explanation:
      'Continuous reporting with no gaps. Reliability describes the data, not the vessel.',
  },
];

const ATTRIBUTION: Attribution = {
  id: 'attr-1',
  rank: 1,
  vessel: { id: 'v1', mmsi: 419008412, name: 'SAGAR PRABHA (SYNTHETIC)' },
  final_score: 0.9546,
  confidence_label: 'HIGH',
  factors: FACTORS,
  weights: {
    origin_proximity: 0.35,
    time_match: 0.2,
    trajectory_match: 0.15,
    heading_match: 0.1,
    speed_match: 0.1,
    ais_reliability: 0.1,
  },
  scoring_version: 'prd-j-v1',
  disclaimer:
    'Attribution is investigative/probabilistic evidence and is not automatic legal proof.',
  data_provenance: 'SYNTHETIC',
};

/**
 * SCORE-007 / MVP-09.
 *
 * A ranking nobody can audit is an oracle. All six factors are always shown,
 * including the ones that scored badly, and weight × score = contribution is
 * three separate columns so the arithmetic is checkable by eye.
 */
describe('FactorTable', () => {
  it('shows all six factors with weight, score and contribution', () => {
    render(<FactorTable factors={FACTORS} candidateLabel="SAGAR PRABHA (SYNTHETIC)" />);

    const table = screen.getByRole('table', {
      name: 'Evidence factors for SAGAR PRABHA (SYNTHETIC)',
    });
    expect(within(table).getAllByRole('row')).toHaveLength(FACTORS.length + 1);

    const row = screen.getByText('Origin proximity').closest('tr') as HTMLElement;
    expect(within(row).getByText('0.35')).toBeInTheDocument();
    expect(within(row).getByText('0.96')).toBeInTheDocument();
    expect(within(row).getByText('0.34')).toBeInTheDocument();
  });

  it('gives every factor bar its own accessible name', () => {
    render(<FactorTable factors={FACTORS} candidateLabel="SAGAR PRABHA (SYNTHETIC)" />);
    expect(
      screen.getByRole('progressbar', {
        name: 'AIS reliability factor score for SAGAR PRABHA (SYNTHETIC)',
      }),
    ).toBeInTheDocument();
  });

  it('explains every factor in words as well as numbers', () => {
    render(<FactorTable factors={FACTORS} candidateLabel="SAGAR PRABHA (SYNTHETIC)" />);
    for (const factor of FACTORS) {
      expect(screen.getByText(factor.explanation)).toBeInTheDocument();
    }
  });

  it('empty: says the score is unusable rather than showing a blank breakdown', () => {
    render(<FactorTable factors={[]} candidateLabel="SAGAR PRABHA (SYNTHETIC)" />);
    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByText(/treat the score as unusable/i)).toBeInTheDocument();
  });
});

/**
 * CON-003 / A-10.
 *
 * The list response carries three separate caveats plus an optional shortfall
 * note. Each one is a different claim about what the numbers mean, so each is
 * rendered — none is folded into the others.
 */
describe('CandidateRanking — the list-level caveats from the API', () => {
  it('renders the score and proximity disclaimers the server sent', () => {
    render(
      <CandidateRanking
        attributions={[ATTRIBUTION]}
        disclaimer="List-level disclaimer."
        scoreDisclaimer="This score combines six weighted evidence factors using prototype weights."
        proximityDisclaimer="Proximity to the origin region does not by itself indicate involvement."
      />,
    );

    expect(screen.getByText(/six weighted evidence factors/i)).toBeInTheDocument();
    expect(screen.getByText(/does not by itself indicate involvement/i)).toBeInTheDocument();
    expect(screen.getAllByTestId('attribution-disclaimer')[0]).toHaveTextContent(
      'List-level disclaimer.',
    );
  });

  it('renders the shortfall note verbatim when the engine found fewer candidates', () => {
    render(
      <CandidateRanking
        attributions={[ATTRIBUTION]}
        shortfallNote="Only 1 vessel met the correlation criteria; the list was not padded."
      />,
    );
    expect(screen.getByText(/the list was not padded/i)).toBeInTheDocument();
  });

  it('renders no caveat boxes at all when the server sent none', () => {
    render(<CandidateRanking attributions={[ATTRIBUTION]} />);
    expect(screen.queryByTestId('api-notice')).not.toBeInTheDocument();
  });
});
