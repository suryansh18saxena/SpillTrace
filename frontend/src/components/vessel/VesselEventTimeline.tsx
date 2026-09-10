'use client';

import { useMemo } from 'react';
import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { EmptyState } from '@/components/ui/EmptyState';
import { Notice } from '@/components/common/Notice';
import { formatDateTime, formatDistanceKm, formatDuration, formatPercent } from '@/lib/format';
import type { TrajectorySegment } from '@/lib/api/types';
import styles from '@/styles/pages.module.css';

export interface VesselEventTimelineProps {
  segments: readonly TrajectorySegment[];
  firstSeen?: string | null;
  lastSeen?: string | null;
  /**
   * The API's gap notice. Rendered wherever a gap is shown — a reporting gap is
   * not evidence of wrongdoing, and this product never lets one imply that.
   */
  gapNotice?: string | null;
  className?: string;
}

interface TimelineEvent {
  id: string;
  at: string;
  title: string;
  detail?: string;
  tone?: BadgeTone;
  badge?: string;
  isGap?: boolean;
}

/**
 * What AIS actually recorded for this vessel, in order (UI-008).
 *
 * Segment boundaries are shown as what they are — the receiver stopped hearing
 * the vessel, then heard it again. The API's own wording about why that happens
 * is rendered next to every gap, because a silent break in a track is the single
 * easiest thing in this product to misread as intent.
 */
export function VesselEventTimeline({
  segments,
  firstSeen,
  lastSeen,
  gapNotice,
  className,
}: VesselEventTimelineProps) {
  const events = useMemo<TimelineEvent[]>(() => {
    const ordered = [...segments].sort(
      (a, b) => Date.parse(a.time_start) - Date.parse(b.time_start),
    );
    const out: TimelineEvent[] = [];

    if (firstSeen) {
      out.push({
        id: 'first-seen',
        at: firstSeen,
        title: 'First AIS report in the case window',
        tone: 'neutral',
        badge: 'Start',
      });
    }

    ordered.forEach((segment, index) => {
      out.push({
        id: `${segment.trajectory_id}-start`,
        at: segment.time_start,
        title: `Track segment ${index + 1} begins`,
        detail: [
          `${segment.position_count} positions`,
          segment.distance_km === null ? null : formatDistanceKm(segment.distance_km),
          segment.coverage_ratio === null
            ? null
            : `${formatPercent(segment.coverage_ratio)} coverage`,
          segment.quality_score === null ? null : `quality ${segment.quality_score.toFixed(2)}`,
        ]
          .filter(Boolean)
          .join(' · '),
        tone: 'accent',
        badge: 'Segment',
      });

      out.push({
        id: `${segment.trajectory_id}-end`,
        at: segment.time_end,
        title: `Track segment ${index + 1} ends`,
        detail:
          segment.gap_count > 0
            ? `${segment.gap_count} internal reporting gap${segment.gap_count === 1 ? '' : 's'}, longest ${formatDuration((segment.max_gap_minutes ?? 0) * 60)}`
            : 'No internal reporting gaps',
        tone: 'neutral',
        isGap: segment.gap_count > 0,
      });

      const next = ordered[index + 1];
      if (next) {
        const gapSeconds = (Date.parse(next.time_start) - Date.parse(segment.time_end)) / 1000;
        if (gapSeconds > 0) {
          out.push({
            id: `${segment.trajectory_id}-gap`,
            at: segment.time_end,
            title: `No AIS reports for ${formatDuration(gapSeconds)}`,
            detail:
              'The receiver heard nothing from this vessel during this interval. That is a property of the reporting, not of the vessel.',
            tone: 'warning',
            badge: 'Gap',
            isGap: true,
          });
        }
      }
    });

    if (lastSeen) {
      out.push({
        id: 'last-seen',
        at: lastSeen,
        title: 'Last AIS report in the case window',
        tone: 'neutral',
        badge: 'End',
      });
    }

    return out.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  }, [segments, firstSeen, lastSeen]);

  const hasGap = events.some((event) => event.isGap);

  if (events.length === 0) {
    return (
      <EmptyState
        compact
        title="No AIS timeline"
        description="No trajectory segments were built for this vessel, so there is nothing to place on a timeline. That may simply mean the vessel was never heard inside the case window."
      />
    );
  }

  return (
    <div className={className}>
      <ol className={styles.eventTimeline}>
        {events.map((event) => (
          <li key={event.id} className={styles.eventRow}>
            <span className={styles.eventTime}>{formatDateTime(event.at)}</span>
            <span className={styles.eventBody}>
              {event.badge ? (
                <>
                  <Badge tone={event.tone ?? 'neutral'}>{event.badge}</Badge>{' '}
                </>
              ) : null}
              {event.title}
              {event.detail ? <span className={styles.eventDetail}>{event.detail}</span> : null}
            </span>
          </li>
        ))}
      </ol>

      {hasGap ? (
        <Notice
          className={styles.panelNotices}
          text={gapNotice}
          label="About reporting gaps"
          tone="caution"
        />
      ) : null}
    </div>
  );
}
