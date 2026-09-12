import type { Metadata } from 'next';
import { APP_NAME } from '@/lib/config';
import { CinematicLanding } from './_cinematic/CinematicLanding';

export const metadata: Metadata = {
  title: {
    absolute: `${APP_NAME} — Trace the spill. Find the source.`,
  },
  description:
    'SPILLTRACE detects oil slicks in Sentinel-1 radar imagery, rules out the natural phenomena that look identical, back-tracks the oil to an origin probability region, and ranks candidate vessels with a score that can be read factor by factor.',
};

/**
 * Public landing page: one continuous, scroll-driven investigation.
 *
 * The copy is server-rendered and readable with scripting off; the 3D scene
 * beneath it loads on the client only, and only where the device can run it.
 */
export default function LandingPage() {
  return <CinematicLanding />;
}
