import { CountUp } from '@/components/motion/CountUp';
import { Reveal } from '@/components/motion/Reveal';
import styles from '../landing.module.css';
import { PROOF } from './content';

/** Four verified counts — see `content.ts` for where each one comes from. */
export function ProofNumbers() {
  return (
    <section
      className={styles.section}
      aria-label="The system in numbers"
      style={{ paddingBlock: 'clamp(3rem, 7vw, 5rem)' }}
    >
      <div className={styles.container}>
        <Reveal as="dl" className={styles.proofGrid} stagger={0.1}>
          {PROOF.map((item) => (
            <div key={item.label} className={styles.proofItem}>
              {/* Term first in the DOM (dt → dd); the number is lifted above it visually. */}
              <dt className={styles.proofLabel}>{item.label}</dt>
              <dd className={styles.proofValue}>
                <CountUp value={item.value} duration={2} />
              </dd>
              <dd className={styles.proofSource}>{item.source}</dd>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}
