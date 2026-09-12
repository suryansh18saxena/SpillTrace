import styles from '../landing.module.css';
import { SOURCES } from './content';

/**
 * Two counter-scrolling rows of the data sources and building blocks.
 *
 * Pure CSS (a translate loop on a doubled list), paused on hover and stopped
 * entirely under reduced motion by the global rule. The duplicate half is
 * `aria-hidden` so a screen reader reads each name once.
 */
export function Marquee() {
  const half = Math.ceil(SOURCES.length / 2);
  const rows = [SOURCES.slice(0, half), SOURCES.slice(half)];

  return (
    <section className={styles.marquee} aria-label="Data sources and building blocks">
      {rows.map((row, rowIndex) => (
        <div
          key={rowIndex}
          className={`${styles.marqueeRow} ${rowIndex === 1 ? styles.marqueeReverse : ''}`}
        >
          {[...row, ...row].map((item, index) => (
            <span
              key={`${item}-${index}`}
              className={styles.marqueeItem}
              aria-hidden={index >= row.length ? true : undefined}
            >
              <span className={styles.marqueeDot} />
              {item}
            </span>
          ))}
        </div>
      ))}
    </section>
  );
}
