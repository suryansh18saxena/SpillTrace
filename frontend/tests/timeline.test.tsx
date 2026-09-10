import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Timeline } from '@/components/map/Timeline';
import { VesselEventTimeline } from '@/components/vessel/VesselEventTimeline';
import type { TrajectorySegment } from '@/lib/api/types';

const START = '2026-08-12T14:12:00Z';
const END = '2026-08-14T07:12:00Z';

function renderTimeline(props: Partial<React.ComponentProps<typeof Timeline>> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <Timeline
      start={START}
      end={END}
      value={null}
      onChange={onChange}
      spans={[
        {
          id: 'window',
          label: 'Inferred discharge window',
          start: '2026-08-13T08:57:00Z',
          end: '2026-08-13T13:42:00Z',
          kind: 'window',
        },
        {
          id: 'coverage',
          label: 'AIS coverage (6 vessels)',
          start: START,
          end: END,
          kind: 'coverage',
        },
      ]}
      markers={[{ id: 'scene', label: 'Scene acquisition', time: '2026-08-14T01:12:00Z' }]}
      {...props}
    />,
  );
  return { onChange, ...utils };
}

/**
 * UI-004 — the map's time axis.
 *
 * A native range input carries the interaction so the whole control is keyboard
 * operable for free, and `aria-valuetext` reads a UTC timestamp instead of an
 * epoch number. "Show every time" always exists: a scrubbed map that cannot be
 * un-scrubbed is a trap.
 */
describe('Timeline', () => {
  it('success: labels the window, the marker and the current cursor', () => {
    renderTimeline({ value: Date.parse('2026-08-13T10:42:00Z') });

    expect(screen.getByRole('region', { name: 'Investigation timeline' })).toBeInTheDocument();
    // Shown twice on purpose: once as the readout, once as the slider's own output.
    expect(screen.getAllByText('2026-08-13 10:42Z').length).toBeGreaterThan(0);
    expect(screen.getByText(/Inferred discharge window/)).toBeInTheDocument();
    expect(screen.getByText(/Scene acquisition/)).toBeInTheDocument();
  });

  it('shows every time until the analyst scrubs', () => {
    renderTimeline();
    expect(screen.getByText('All times')).toBeInTheDocument();
    expect(screen.getByRole('slider')).toHaveAttribute(
      'aria-valuetext',
      'Every time in the window',
    );
  });

  it('disabled: the reset control is inert while nothing is filtered', () => {
    renderTimeline();
    expect(screen.getByRole('button', { name: /show every time/i })).toBeDisabled();
  });

  it('clears the filter when the analyst asks for every time', async () => {
    const user = userEvent.setup();
    const { onChange } = renderTimeline({ value: Date.parse('2026-08-13T10:42:00Z') });

    await user.click(screen.getByRole('button', { name: /show every time/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('is a native range input, so it is focusable and reports its bounds', () => {
    const { onChange } = renderTimeline({ value: Date.parse('2026-08-13T10:42:00Z') });

    const slider = screen.getByRole('slider');
    slider.focus();
    expect(slider).toHaveFocus();
    expect(slider).toHaveAttribute('min', String(Date.parse(START)));
    expect(slider).toHaveAttribute('max', String(Date.parse(END)));

    // jsdom does not implement arrow-key stepping on a range input, so the
    // change itself is driven directly; the binding is what is under test.
    fireEvent.change(slider, { target: { value: String(Date.parse('2026-08-13T11:00:00Z')) } });
    expect(onChange).toHaveBeenCalledWith(Date.parse('2026-08-13T11:00:00Z'));
  });

  it('exposes play state so the control reads correctly to assistive technology', () => {
    renderTimeline({ playing: true, onTogglePlay: vi.fn() });
    expect(screen.getByRole('button', { name: /pause/i })).toHaveAttribute('aria-pressed', 'true');
  });

  it('renders nothing for an impossible window rather than an unusable slider', () => {
    const { container } = render(
      <Timeline start={END} end={START} value={null} onChange={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

const GAP_NOTICE =
  'A gap in AIS reporting is not evidence of wrongdoing. Gaps are commonly caused by satellite ' +
  'revisit intervals, terrestrial receiver coverage, signal interference in busy waters, and ' +
  'equipment faults.';

const SEGMENTS: TrajectorySegment[] = [
  {
    trajectory_id: 't1',
    time_start: '2026-08-12T14:12:00Z',
    time_end: '2026-08-13T07:51:00Z',
    position_count: 354,
    distance_km: 134.1,
    gap_count: 0,
    max_gap_minutes: 0,
    coverage_ratio: 1,
    quality_score: 1,
  },
  {
    trajectory_id: 't2',
    time_start: '2026-08-13T12:30:00Z',
    time_end: '2026-08-14T07:12:00Z',
    position_count: 187,
    distance_km: 88.4,
    gap_count: 1,
    max_gap_minutes: 38,
    coverage_ratio: 0.82,
    quality_score: 0.76,
  },
];

/**
 * UI-008 / CON-001.
 *
 * A break in an AIS track is the easiest thing in this product to misread as
 * intent. Wherever one is shown, the API's own wording about why gaps happen is
 * shown with it.
 */
describe('VesselEventTimeline', () => {
  it('places the gap between two segments on the timeline', () => {
    render(
      <VesselEventTimeline
        segments={SEGMENTS}
        firstSeen="2026-08-12T14:12:00Z"
        lastSeen="2026-08-14T07:12:00Z"
        gapNotice={GAP_NOTICE}
      />,
    );

    expect(screen.getByText(/No AIS reports for/)).toBeInTheDocument();
    expect(screen.getByText('First AIS report in the case window')).toBeInTheDocument();
    expect(screen.getByText('Last AIS report in the case window')).toBeInTheDocument();
  });

  it("renders the API's gap notice whenever a gap is shown", () => {
    render(<VesselEventTimeline segments={SEGMENTS} gapNotice={GAP_NOTICE} />);
    expect(screen.getByTestId('api-notice')).toHaveTextContent(GAP_NOTICE);
  });

  it('never implies a gap means anything about the vessel', () => {
    render(<VesselEventTimeline segments={SEGMENTS} gapNotice={GAP_NOTICE} />);
    const text = (document.body.textContent ?? '').toLowerCase();
    for (const banned of ['guilty', 'culprit', 'responsible', 'proven', 'went dark', 'concealed']) {
      expect(text).not.toContain(banned);
    }
  });

  it('shows no gap notice when the track has no gaps', () => {
    render(<VesselEventTimeline segments={[SEGMENTS[0]!]} gapNotice={GAP_NOTICE} />);
    expect(screen.queryByTestId('api-notice')).not.toBeInTheDocument();
  });

  it('empty: explains that no segments were built', () => {
    render(<VesselEventTimeline segments={[]} />);
    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByText('No AIS timeline')).toBeInTheDocument();
  });
});
