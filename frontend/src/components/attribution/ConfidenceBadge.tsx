import { Badge, type BadgeTone } from '@/components/ui/Badge';
import type { ConfidenceLabel } from '@/lib/api/types';

export interface ConfidenceBadgeProps {
  label: ConfidenceLabel;
  className?: string;
}

/**
 * The 3-step investigative-confidence ramp.
 *
 * The wording is deliberate and fixed: "HIGH investigative signal", never "high
 * probability of responsibility". An 88 is not an 88% legal probability
 * (CON-003), and the colour ramp avoids red for the same reason.
 */
const TONE: Record<string, BadgeTone> = {
  LOW: 'confidence-1',
  // The server's enum is LOW / MODERATE / HIGH; `MEDIUM` is accepted too so a
  // deployment on an older scoring version still lands on the middle step
  // rather than falling through to neutral grey.
  MODERATE: 'confidence-2',
  MEDIUM: 'confidence-2',
  HIGH: 'confidence-3',
};

const DESCRIPTION: Record<string, string> = {
  LOW: 'Weak investigative signal — this candidate needs corroborating evidence.',
  MODERATE: 'Moderate investigative signal — worth further enquiry.',
  MEDIUM: 'Moderate investigative signal — worth further enquiry.',
  HIGH: 'Strong investigative signal — prioritise for further enquiry. Not proof of responsibility.',
};

export function ConfidenceBadge({ label, className }: ConfidenceBadgeProps) {
  const tone = TONE[label] ?? 'neutral';
  return (
    <Badge tone={tone} className={className} title={DESCRIPTION[label] ?? undefined}>
      {label} investigative signal
    </Badge>
  );
}
