import type { CaseBundle } from '@/lib/api/aggregate';

export type NotificationKind = 'created' | 'running' | 'completed' | 'failed' | 'signal';

export interface AppNotification {
  id: string;
  kind: NotificationKind;
  title: string;
  body: string;
  /** Epoch milliseconds. */
  at: number;
  href: string;
}

function epoch(value: string | null | undefined): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : 0;
}

/**
 * Turns the current state of recent cases into a notification feed.
 *
 * There is no server-side notification store, so this is *derived*, not
 * recorded: it describes what is true of each case now (created, running,
 * completed, failed, has candidates in the HIGH band). Wording follows the
 * product vocabulary — "candidate", "investigative signal", "lead" — and never
 * describes a vessel as anything more than a candidate for enquiry (CON-001).
 */
export function deriveNotifications(bundles: readonly CaseBundle[], limit = 25): AppNotification[] {
  const items: AppNotification[] = [];

  for (const bundle of bundles) {
    const item = bundle.case;
    const title = item.title || 'Untitled case';
    const updated = epoch(item.updated_at) || epoch(item.created_at);
    const base = `/cases/${item.id}`;

    items.push({
      id: `${item.id}:created`,
      kind: 'created',
      title: 'New case opened',
      body: title,
      at: epoch(item.created_at),
      href: base,
    });

    switch (item.status) {
      case 'QUEUED':
      case 'RUNNING':
        items.push({
          id: `${item.id}:running:${updated}`,
          kind: 'running',
          title: 'Investigation chain running',
          body: `${title} — stages are executing now.`,
          at: updated,
          href: base,
        });
        break;
      case 'COMPLETED': {
        const count = bundle.attributions?.items.length;
        items.push({
          id: `${item.id}:completed:${updated}`,
          kind: 'completed',
          title: 'Investigation chain completed',
          body:
            count === undefined
              ? title
              : `${title} — ${count} candidate vessel${count === 1 ? '' : 's'} ranked.`,
          at: updated,
          href: base,
        });
        break;
      }
      case 'FAILED':
        items.push({
          id: `${item.id}:failed:${updated}`,
          kind: 'failed',
          title: 'A pipeline stage failed',
          body: `${title} — open the pipeline tab to see the stated reason.`,
          at: updated,
          href: base,
        });
        break;
      default:
        break;
    }

    const high =
      bundle.attributions?.items.filter((a) => a.confidence_label === 'HIGH').length ?? 0;
    if (high > 0) {
      items.push({
        id: `${item.id}:signal:${high}:${updated}`,
        kind: 'signal',
        title: 'HIGH investigative signal',
        body: `${high} candidate${high === 1 ? '' : 's'} in ${title} reached the HIGH evidence-strength band — a lead for enquiry, not a finding.`,
        // Just after the completion so it sorts above it.
        at: updated + 1,
        href: `${base}/ranking`,
      });
    }
  }

  return items
    .filter((n) => n.at > 0)
    .sort((a, b) => b.at - a.at)
    .slice(0, limit);
}
