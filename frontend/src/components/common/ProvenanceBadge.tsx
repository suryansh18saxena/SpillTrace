import { Badge, type BadgeTone } from '@/components/ui/Badge';
import type { DataProvenance } from '@/lib/api/types';

export interface ProvenanceBadgeProps {
  provenance: DataProvenance | null | undefined;
  className?: string;
}

const TONE: Record<string, BadgeTone> = {
  REAL: 'info',
  SYNTHETIC: 'synthetic',
  MIXED: 'warning',
};

const TITLE: Record<string, string> = {
  REAL: 'Derived from real observations.',
  SYNTHETIC: 'Deterministic synthetic data. Not a real-world observation.',
  MIXED: 'Combines real observations with synthetic or fallback-generated inputs.',
};

/**
 * CON-009: synthetic and demo data is *always* visibly labelled and can never be
 * mistaken for a real observation. This badge is the mechanism, and it is
 * rendered next to every artifact that carries a `data_provenance` field.
 */
export function ProvenanceBadge({ provenance, className }: ProvenanceBadgeProps) {
  if (!provenance) return null;
  return (
    <Badge tone={TONE[provenance] ?? 'neutral'} className={className} title={TITLE[provenance]}>
      {provenance}
    </Badge>
  );
}
