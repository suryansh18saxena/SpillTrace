'use client';

import { Button } from '@/components/ui/Button';
import { IconSparkle } from '@/components/ui/Icons';
import { requestTour } from '@/lib/preferences';

/**
 * Replays the five-step walkthrough. The tour itself lives in the app shell
 * (`OnboardingTour`), which listens for the event `requestTour()` dispatches —
 * so this page never needs to know how the tour works.
 */
export function TourButton() {
  return (
    <Button variant="primary" leadingIcon={<IconSparkle size={16} />} onClick={() => requestTour()}>
      Take the product tour
    </Button>
  );
}
