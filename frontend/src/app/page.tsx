import type { Metadata } from 'next';
import { Reveal } from '@/components/motion/Reveal';
import { ScrollProgress } from '@/components/motion/ScrollProgress';
import { SmoothScroll } from '@/components/motion/SmoothScroll';
import { SplitReveal } from '@/components/motion/SplitReveal';
import { APP_NAME } from '@/lib/config';
import { ChainRail } from './_landing/ChainRail';
import { ChainStory } from './_landing/ChainStory';
import { FinalCta, LandingFooter, SafeguardGrid } from './_landing/Closing';
import { FeatureBento } from './_landing/FeatureBento';
import { Hero } from './_landing/Hero';
import { LandingNav } from './_landing/LandingNav';
import { Manifesto } from './_landing/Manifesto';
import { Marquee } from './_landing/Marquee';
import { ProofNumbers } from './_landing/ProofNumbers';
import { RankingPreview } from './_landing/RankingPreview';
import styles from './landing.module.css';

export const metadata: Metadata = {
  title: {
    absolute: `${APP_NAME} — Maritime oil-spill attribution, with its reasoning on show`,
  },
  description:
    'SPILLTRACE detects oil slicks in Sentinel-1 radar imagery, rules out the natural phenomena that look identical, back-tracks the oil to an origin probability region, and ranks candidate vessels with a score that can be read factor by factor.',
};

/**
 * Public landing page.
 *
 * A server component: the copy is rendered on the server and readable with
 * scripting off; each animated section is a small client island. Inertial
 * scrolling (Lenis) is scoped to this page only.
 */
export default function LandingPage() {
  return (
    <SmoothScroll>
      <div className={styles.page}>
        <ScrollProgress />
        <LandingNav />
        <main id="main-content">
          <Hero />
          <Marquee />
          <Manifesto />
          <ChainStory />
          <ChainRail />
          <ProofNumbers />
          <FeatureBento />

          <section className={styles.section} id="evidence" aria-labelledby="evidence-title">
            <div className={styles.container}>
              <div className={styles.evidence}>
                <div>
                  <span className="eyebrow">A real result</span>
                  <SplitReveal as="h2" className={styles.sectionTitle} id="evidence-title">
                    The third-ranked vessel is the whole point
                  </SplitReveal>
                  <p className={styles.sectionLede}>
                    This is the output of the seeded demonstration case — the same algorithms that
                    run on live Copernicus and AIS data, applied to synthetic observations so the
                    chain can be shown end to end with no external account.
                  </p>
                  <Reveal as="ul" className={styles.evidenceList} stagger={0.12}>
                    <li className={styles.evidenceItem}>
                      <span className={styles.evidenceNum}>01</span>
                      <span>
                        <strong>
                          MATSYA VII sits 0.0 km from the origin region with a perfect time and
                          trajectory match — and still ranks third.
                        </strong>{' '}
                        Nearest is not a verdict, so the system does not treat it as one.
                      </span>
                    </li>
                    <li className={styles.evidenceItem}>
                      <span className={styles.evidenceNum}>02</span>
                      <span>
                        <strong>
                          A 14.1-hour reporting gap drops its AIS reliability to 0.448.
                        </strong>{' '}
                        Nobody wrote a rule that punishes dark vessels; the system simply becomes
                        less confident about what it cannot see — and a gap can never raise a score.
                      </span>
                    </li>
                    <li className={styles.evidenceItem}>
                      <span className={styles.evidenceNum}>03</span>
                      <span>
                        <strong>Of six vessels considered, two were correctly excluded</strong> —
                        one three days early, one 80 km away. The list is never padded to reach a
                        target number of candidates.
                      </span>
                    </li>
                    <li className={styles.evidenceItem}>
                      <span className={styles.evidenceNum}>04</span>
                      <span>
                        <strong>
                          When the evidence cannot separate candidates, labels are capped.
                        </strong>{' '}
                        If more than three share the top origin score, every band stops at MODERATE
                        and the reason is stated — instead of naming a wall of suspects.
                      </span>
                    </li>
                  </Reveal>
                </div>
                <Reveal y={48}>
                  <RankingPreview />
                </Reveal>
              </div>
            </div>
          </section>

          <SafeguardGrid />
          <FinalCta />
        </main>
        <LandingFooter />
      </div>
    </SmoothScroll>
  );
}
