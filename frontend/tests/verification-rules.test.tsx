import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
  RulesTable,
  formatObserved,
  formatThreshold,
  ruleOutcome,
} from '@/components/detection/RulesTable';
import type { VerificationRule } from '@/lib/api/types';

/** Verbatim shapes taken from a live `GET /detections/{id}/verification`. */
const WIND: VerificationRule = {
  rule_id: 'wind_window',
  label: 'Wind conditions',
  passed: true,
  applicable: true,
  veto: false,
  weight: 0.3,
  evidence: 1,
  observed: 5.3993,
  threshold: { optimal_ms: [4, 10], glassy_below_ms: 2, dispersed_above_ms: 12 },
  message: 'Wind was 5.4 m/s, inside the 4-10 m/s window in which SAR oil detection is reliable.',
};

const AREA: VerificationRule = {
  rule_id: 'area',
  label: 'Detected area',
  passed: true,
  applicable: true,
  weight: 0.07,
  observed: 85.346,
  threshold: [0.5, 1500],
  message: 'The feature covers 85.3 km², a plausible size for an operational discharge.',
};

const CONTRAST: VerificationRule = {
  rule_id: 'contrast',
  label: 'Backscatter contrast',
  passed: false,
  applicable: true,
  weight: 0.25,
  observed: 2.1,
  threshold: 6,
  message: 'The feature is only 2.1 dB darker than the surrounding sea.',
};

const CLASSIFIER: VerificationRule = {
  rule_id: 'classifier',
  label: 'Look-alike classifier',
  passed: false,
  applicable: false,
  veto: true,
  weight: 0.2,
  observed: null,
  threshold: null,
  message: 'No trained look-alike classifier is registered, so this rule was not evaluated.',
};

/**
 * FR-008 / A-06.
 *
 * A dark SAR patch is not automatically oil, and the product's claim to honesty
 * rests on showing the rules rather than a single verdict. The case that matters
 * most is the third outcome: a rule that could not be evaluated is neither a
 * pass nor a failure, and rendering it as either would be a lie about how much
 * evidence there is.
 */
describe('ruleOutcome — three outcomes, not two', () => {
  it('reports a pass', () => {
    expect(ruleOutcome(WIND)).toBe('pass');
  });

  it('reports a failure', () => {
    expect(ruleOutcome(CONTRAST)).toBe('fail');
  });

  it('reports an inapplicable rule as not evaluated, never as a failure', () => {
    expect(ruleOutcome(CLASSIFIER)).toBe('not-evaluated');
    expect(ruleOutcome({ ...CLASSIFIER, passed: true })).toBe('not-evaluated');
  });
});

describe('formatThreshold — every shape the API actually sends', () => {
  it('renders a scalar floor', () => {
    expect(formatThreshold(6)).toBe('6');
  });

  it('renders an inclusive range as a range', () => {
    expect(formatThreshold([0.5, 1500])).toBe('0.5 – 1,500');
  });

  it('renders a named set of bounds without collapsing it to one number', () => {
    const rendered = formatThreshold(WIND.threshold ?? null);
    expect(rendered).toContain('optimal ms 4 – 10');
    expect(rendered).toContain('glassy below ms 2');
    expect(rendered).toContain('dispersed above ms 12');
  });

  it('renders a missing threshold as an explicit blank', () => {
    expect(formatThreshold(null)).toBe('—');
    expect(formatObserved(null)).toBe('—');
  });
});

describe('RulesTable', () => {
  const rules = [WIND, AREA, CONTRAST, CLASSIFIER];

  it('success: shows every rule with its outcome, observation and threshold', () => {
    render(<RulesTable rules={rules} />);

    const table = screen.getByRole('table', { name: 'Look-alike verification rules' });
    expect(within(table).getAllByRole('row')).toHaveLength(rules.length + 1);
    expect(screen.getByText('Wind conditions')).toBeInTheDocument();
    expect(screen.getAllByText('Pass')).toHaveLength(2);
    expect(screen.getByText('Fail')).toBeInTheDocument();
    expect(screen.getByText('Not evaluated')).toBeInTheDocument();
  });

  it('blanks the observation for a rule that was never evaluated', () => {
    render(<RulesTable rules={[CLASSIFIER]} />);
    const row = screen.getByText('Look-alike classifier').closest('tr');
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getAllByText('—').length).toBeGreaterThan(0);
  });

  it('marks a veto rule, because it can reject a detection on its own', () => {
    render(<RulesTable rules={[CLASSIFIER]} />);
    expect(screen.getByText('veto')).toBeInTheDocument();
  });

  it('loading: announces busy without inventing rows', () => {
    render(<RulesTable rules={[]} loading />);
    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getAllByTestId('skeleton').length).toBeGreaterThan(0);
  });

  it('empty: says what has to run before rules exist', () => {
    render(<RulesTable rules={[]} />);
    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByText(/detect\.verify stage/i)).toBeInTheDocument();
  });

  it('error: surfaces the failure instead of an empty rule set', () => {
    render(<RulesTable rules={[]} error={<span>Verification unavailable</span>} />);
    expect(screen.getByText('Verification unavailable')).toBeInTheDocument();
  });
});
