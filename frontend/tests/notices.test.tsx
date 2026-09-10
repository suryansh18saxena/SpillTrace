import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Notice, NoticeStack } from '@/components/common/Notice';
import { Unmeasured } from '@/components/common/MetaList';
import { hasMetrics, type ModelVersion } from '@/lib/api/types';

/** Verbatim from a live `GET /cases/{id}/vessels`. */
const AIS_NOTICE =
  'AIS coverage is not complete. Vessels may be absent from this dataset because they were ' +
  'outside receiver coverage, because their transmissions collided with others, or because they ' +
  'do not carry AIS. Absence of a vessel is not evidence of absence.';

const ORIGIN_NOTICE =
  'The origin region is a probability region derived from reverse drift simulation. It indicates ' +
  'where a discharge was more likely to have occurred; it is not an exact discharge coordinate.';

/**
 * CON-008 / CON-009.
 *
 * The API attaches a `notice` to the responses whose numbers are easiest to
 * over-read. Those strings are part of the product's honesty guarantee, so the
 * component that renders them must never paraphrase, truncate or drop one.
 */
describe('Notice', () => {
  it('renders the server string verbatim', () => {
    render(<Notice text={ORIGIN_NOTICE} />);
    expect(screen.getByTestId('api-notice')).toHaveTextContent(ORIGIN_NOTICE);
  });

  it('renders nothing at all when the server sent no notice', () => {
    const { container } = render(<Notice text={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing for a blank notice rather than an empty box', () => {
    const { container } = render(<Notice text="   " />);
    expect(container).toBeEmptyDOMElement();
  });

  it('keeps the label separate from the server text', () => {
    render(<Notice text={AIS_NOTICE} label="About AIS coverage" />);
    expect(screen.getByText('About AIS coverage')).toBeInTheDocument();
    expect(screen.getByTestId('api-notice')).toHaveTextContent(AIS_NOTICE);
  });
});

describe('NoticeStack', () => {
  it('shows every distinct notice it is given', () => {
    render(<NoticeStack notices={[AIS_NOTICE, ORIGIN_NOTICE]} />);
    expect(screen.getAllByTestId('api-notice')).toHaveLength(2);
  });

  it('de-duplicates the same caveat arriving from two endpoints', () => {
    render(<NoticeStack notices={[AIS_NOTICE, AIS_NOTICE, null, undefined, '']} />);
    expect(screen.getAllByTestId('api-notice')).toHaveLength(1);
  });

  it('renders nothing when every source is empty', () => {
    const { container } = render(<NoticeStack notices={[null, undefined, '  ']} />);
    expect(container).toBeEmptyDOMElement();
  });
});

/**
 * A-06.
 *
 * `metrics: {}` on a model version means **no evaluation has been recorded**.
 * Rendering that as `0%` would assert a measured failure nobody measured, which
 * is the single most misleading thing this screen could do.
 */
describe('unmeasured model metrics', () => {
  const model = (metrics: ModelVersion['metrics']): ModelVersion => ({
    name: 'synthetic-generator',
    version: '1.0.0',
    is_active: false,
    metrics,
  });

  it('treats an empty metrics object as unmeasured', () => {
    expect(hasMetrics(model({}))).toBe(false);
  });

  it('treats a recorded metric as measured', () => {
    expect(hasMetrics(model({ iou: 0.71 }))).toBe(true);
  });

  it('renders unmeasured evaluation as words, never as a number', () => {
    render(<Unmeasured />);
    const text = screen.getByText(/no evaluation recorded/i);
    expect(text).toBeInTheDocument();
    expect(text.textContent).not.toMatch(/\d/);
  });
});
