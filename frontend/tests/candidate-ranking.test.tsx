import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CandidateRanking } from '@/components/attribution/CandidateRanking';
import { Disclaimer } from '@/components/attribution/Disclaimer';
import { INVESTIGATIVE_DISCLAIMER } from '@/lib/config';
import type { Attribution } from '@/lib/api/types';

/** Verbatim from the attribution example in docs/API.md §10. */
const DISCLAIMER = 'Investigative/probabilistic evidence — not automatic legal proof.';

const WEIGHTS = {
  origin_proximity: 0.35,
  time_match: 0.2,
  trajectory_match: 0.15,
  heading_match: 0.1,
  speed_match: 0.1,
  ais_reliability: 0.1,
};

function attribution(overrides: Partial<Attribution> = {}): Attribution {
  return {
    id: 'attr-1',
    rank: 1,
    vessel: { id: 'v1', mmsi: 419001234, name: 'DEMO CARRIER (SYNTHETIC)' },
    final_score: 0.81,
    confidence_label: 'HIGH',
    factors: [
      {
        key: 'origin_proximity',
        label: 'Origin proximity',
        weight: 0.35,
        score: 0.92,
        contribution: 0.322,
        explanation:
          'Closest approach to the origin probability region was 1.4 km at 2026-08-01T18:20Z, inside the 80th-percentile contour.',
        evidence: { closest_approach_km: 1.4, contour_percentile: 80 },
      },
      {
        key: 'time_match',
        label: 'Time match',
        weight: 0.2,
        score: 0.74,
        contribution: 0.148,
        explanation: 'Present for 4h 10m of the inferred discharge window.',
      },
      {
        key: 'ais_reliability',
        label: 'AIS reliability',
        weight: 0.1,
        score: 0.55,
        contribution: 0.055,
        explanation:
          'One 38-minute reporting gap. A gap lowers confidence in the track; it is not itself an indicator of activity.',
      },
    ],
    weights: WEIGHTS,
    scoring_version: 'prd-j-v1',
    disclaimer: DISCLAIMER,
    data_provenance: 'SYNTHETIC',
    ...overrides,
  };
}

/**
 * AC-13 / CON-001 / CON-003 / MVP-11.
 *
 * The product must label attribution as investigative and probabilistic wherever
 * a score, ranking or candidate vessel appears. These tests are the client-side
 * half of the guarantee that `backend/tests/unit/test_disclaimers.py` makes on
 * the server side.
 */
describe('CandidateRanking — the disclaimer is not optional', () => {
  it('renders the disclaimer text supplied by the API alongside the ranking', () => {
    render(<CandidateRanking attributions={[attribution()]} />);

    const disclaimers = screen.getAllByTestId('attribution-disclaimer');
    expect(disclaimers.length).toBeGreaterThan(0);
    expect(disclaimers[0]).toHaveTextContent(DISCLAIMER);
  });

  it('shows the server disclaimer verbatim rather than a paraphrase', () => {
    const custom = 'Probabilistic investigative output. Requires corroboration before any action.';
    render(<CandidateRanking attributions={[attribution({ disclaimer: custom })]} />);
    expect(screen.getAllByTestId('attribution-disclaimer')[0]).toHaveTextContent(custom);
  });

  it('still labels the score when a response arrives without a disclaimer', () => {
    // Defence in depth: a missing field must never yield an unlabelled score.
    render(<CandidateRanking attributions={[attribution({ disclaimer: '' })]} />);
    expect(screen.getAllByTestId('attribution-disclaimer')[0]).toHaveTextContent(
      INVESTIGATIVE_DISCLAIMER,
    );
  });

  it('repeats the disclaimer inside each candidate breakdown', () => {
    render(<CandidateRanking attributions={[attribution()]} />);
    // Panel-level notice + the one attached to the single candidate.
    expect(screen.getAllByTestId('attribution-disclaimer')).toHaveLength(2);
    expect(screen.getByText('Applies to this candidate')).toBeInTheDocument();
  });

  it('never uses accusatory language anywhere in the ranking', () => {
    render(
      <CandidateRanking
        attributions={[attribution(), attribution({ id: 'attr-2', rank: 2, final_score: 0.44 })]}
      />,
    );

    const text = (document.body.textContent ?? '').toLowerCase();
    for (const banned of [
      'guilty',
      'culprit',
      'responsible',
      'proven',
      'perpetrator',
      'offender',
    ]) {
      expect(text).not.toContain(banned);
    }
    expect(text).toContain('investigative');
    expect(text).toContain('candidate');
  });
});

describe('CandidateRanking — score presentation', () => {
  it('shows the score at two decimals, captioned as investigative', () => {
    render(<CandidateRanking attributions={[attribution()]} />);
    expect(screen.getByText('0.81')).toBeInTheDocument();
    expect(screen.getByText('investigative score')).toBeInTheDocument();
  });

  it('labels confidence as a signal, not a probability of responsibility', () => {
    render(<CandidateRanking attributions={[attribution()]} />);
    expect(screen.getByText('HIGH investigative signal')).toBeInTheDocument();
  });

  it('explains every factor with its weight and contribution (SCORE-007)', () => {
    render(<CandidateRanking attributions={[attribution()]} />);

    expect(screen.getByText('Origin proximity')).toBeInTheDocument();
    expect(screen.getByText(/weight 0\.35 · contributes 0\.32/)).toBeInTheDocument();
    expect(
      screen.getByText(/closest approach to the origin probability region/i),
    ).toBeInTheDocument();

    // Each factor carries its own labelled progress bar.
    expect(
      screen.getByRole('progressbar', { name: 'Origin proximity factor score' }),
    ).toBeInTheDocument();
  });

  it('states that the weights are engineering defaults, not calibrated probabilities', () => {
    render(<CandidateRanking attributions={[attribution()]} />);
    expect(
      screen.getByText(/not scientifically validated legal probabilities/i),
    ).toBeInTheDocument();
  });

  it('marks synthetic vessels so they cannot be read as real observations (CON-009)', () => {
    render(<CandidateRanking attributions={[attribution()]} />);
    const candidate = screen.getByText('DEMO CARRIER (SYNTHETIC)').closest('details');
    expect(candidate).not.toBeNull();
    expect(within(candidate as HTMLElement).getByText('Synthetic')).toBeInTheDocument();
  });

  it('says so plainly when fewer than three candidates exist, and never pads (A-10)', () => {
    render(<CandidateRanking attributions={[attribution()]} />);
    expect(screen.getByText(/only 1 candidate vessel was found/i)).toBeInTheDocument();
    expect(screen.getByText(/never padded/i)).toBeInTheDocument();
  });
});

describe('CandidateRanking — non-success states', () => {
  it('empty: explains what has to run before candidates exist', () => {
    render(<CandidateRanking attributions={[]} />);
    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByText('No candidate vessels yet')).toBeInTheDocument();
    expect(screen.getByText(/correlate and score stages/i)).toBeInTheDocument();
    expect(screen.queryByTestId('attribution-disclaimer')).not.toBeInTheDocument();
  });

  it('loading: announces busy without inventing rows', () => {
    const { container } = render(<CandidateRanking attributions={[]} loading />);
    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(screen.getByText('Loading candidate ranking')).toBeInTheDocument();
  });

  it('error: surfaces the failure instead of an empty ranking', () => {
    render(<CandidateRanking attributions={[]} error={new Error('nope')} />);
    expect(screen.getByTestId('error-state')).toBeInTheDocument();
    expect(screen.getByText('Ranking unavailable')).toBeInTheDocument();
  });
});

describe('Disclaimer', () => {
  it('prefers the server text over the built-in floor', () => {
    render(<Disclaimer text="Server-supplied notice." />);
    expect(screen.getByTestId('attribution-disclaimer')).toHaveTextContent(
      'Server-supplied notice.',
    );
  });

  it('falls back to the product-level notice for blank input', () => {
    render(<Disclaimer text="   " />);
    expect(screen.getByTestId('attribution-disclaimer')).toHaveTextContent(
      INVESTIGATIVE_DISCLAIMER,
    );
  });
});
