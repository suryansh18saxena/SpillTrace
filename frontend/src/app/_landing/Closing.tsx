import Link from 'next/link';
import { RadarMark } from '@/components/brand/RadarMark';
import { Magnetic } from '@/components/motion/Magnetic';
import { Parallax } from '@/components/motion/Parallax';
import { Reveal } from '@/components/motion/Reveal';
import { SplitReveal } from '@/components/motion/SplitReveal';
import { IconArrowRight, IconShield } from '@/components/ui/Icons';
import { LinkButton } from '@/components/ui/LinkButton';
import { APP_NAME } from '@/lib/config';
import styles from '../landing.module.css';
import { SAFEGUARDS } from './content';

/** The nine constraints from `docs/REQUIREMENTS.md` §7. */
export function SafeguardGrid() {
  return (
    <section className={styles.section} id="safeguards" aria-labelledby="guards-title">
      <div className={styles.container}>
        <div className={styles.sectionHead}>
          <span className="eyebrow">Safeguards</span>
          <SplitReveal as="h2" className={styles.sectionTitle} id="guards-title">
            Nine things this system refuses to do
          </SplitReveal>
          <p className={styles.sectionLede}>
            An uncertain attribution that leaks can damage an operator who did nothing wrong. These
            are not disclaimers stapled on at the end: they live in the code, are covered by tests,
            a repository lint and schema review, and generated prose is checked against a list of
            forbidden phrases.
          </p>
        </div>

        <Reveal as="ul" className={styles.guards} stagger={0.06}>
          {SAFEGUARDS.map((guard) => (
            <li key={guard.id} className={styles.guard}>
              <span className={styles.guardId}>
                <IconShield size={14} />
                {guard.id}
              </span>
              <h3 className={styles.guardTitle}>{guard.title}</h3>
              <p className={styles.guardText}>{guard.body}</p>
            </li>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

export function FinalCta() {
  return (
    <section className={styles.section} aria-labelledby="cta-title">
      <div className={styles.container}>
        <Reveal className={`${styles.cta} grain`} y={40}>
          <Parallax className={styles.ctaRings} speed={-0.25} aria-hidden>
            <svg viewBox="0 0 960 960" width="100%" height="100%">
              {[120, 220, 320, 420].map((r) => (
                <circle key={r} cx="480" cy="480" r={r} />
              ))}
            </svg>
          </Parallax>
          <RadarMark size={56} />
          <h2 className={styles.ctaTitle} id="cta-title" style={{ marginTop: 'var(--space-6)' }}>
            Open a case and <em>watch the chain run</em>
          </h2>
          <p className={styles.ctaLede}>
            The demonstration scenario runs the complete pipeline on deterministic synthetic
            observations — no accounts, no keys, nothing to configure. Every result it produces is
            labelled SYNTHETIC.
          </p>
          <div className={styles.ctaActions}>
            <Magnetic>
              <LinkButton
                href="/login"
                variant="primary"
                size="lg"
                leadingIcon={<IconArrowRight size={16} />}
              >
                Sign in to SPILLTRACE
              </LinkButton>
            </Magnetic>
            <LinkButton href="/transparency" variant="secondary" size="lg">
              Read the transparency note
            </LinkButton>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

export function LandingFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.container}>
        <div className={styles.footerGrid}>
          <span className={styles.brand}>
            <RadarMark size={26} animated={false} />
            {APP_NAME}
          </span>
          <nav className={styles.footerLinks} aria-label="Footer">
            <a href="#chain">The chain</a>
            <a href="#safeguards">Safeguards</a>
            <Link href="/transparency">Transparency</Link>
            <Link href="/login">Sign in</Link>
          </nav>
        </div>
        <p className={styles.footerMeta}>
          Smart India Hackathon 2026 · Problem statement SIH26143 · Team OnlyBans
        </p>
        <p className={styles.footerDisclaimer}>
          SPILLTRACE produces investigative, probabilistic evidence to help an analyst decide which
          vessels to examine next. It does not establish responsibility, a gap in AIS reporting is
          not evidence of wrongdoing, and a score is not a calibrated legal probability. When real
          providers are configured, environmental data is generated using E.U. Copernicus Marine
          Service Information and derived radar products contain modified Copernicus Sentinel data.
          Demonstration data is synthetic and labelled as such.
        </p>
      </div>
    </footer>
  );
}
