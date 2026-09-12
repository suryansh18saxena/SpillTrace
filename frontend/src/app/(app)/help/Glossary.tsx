'use client';

import { useDeferredValue, useMemo, useState, type ReactNode } from 'react';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { IconSearch } from '@/components/ui/Icons';
import { Input } from '@/components/ui/Input';
import { cx } from '@/lib/cx';
import styles from './help.module.css';

type Topic = 'imagery' | 'drift' | 'ais' | 'scoring' | 'records';

interface Term {
  term: string;
  /** Expansion or alternative name, searched as well as shown. */
  aka?: string;
  topic: Topic;
  definition: string;
}

const TOPICS: ReadonlyArray<{ key: Topic | 'all'; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'imagery', label: 'Imagery & detection' },
  { key: 'drift', label: 'Drift & origin' },
  { key: 'ais', label: 'Vessels & AIS' },
  { key: 'scoring', label: 'Scoring' },
  { key: 'records', label: 'Records & data' },
];

/**
 * Definitions are written from the specifications (docs/ML_PIPELINE.md,
 * docs/GIS_PIPELINE.md, docs/AIS_PIPELINE.md, docs/DECISIONS.md) and the
 * scoring, look-alike, drift and provenance modules — never from general
 * knowledge where the system does something more specific.
 */
const TERMS: readonly Term[] = [
  // ------------------------------------------------------- imagery & detection
  {
    term: 'SAR',
    aka: 'Synthetic-aperture radar',
    topic: 'imagery',
    definition:
      'A radar that images the sea from orbit by day or night and through cloud. Over water it measures surface roughness, so an oil film — which smooths the surface — shows up as a dark patch.',
  },
  {
    term: 'Sentinel-1',
    topic: 'imagery',
    definition:
      'The European Union’s Copernicus radar-satellite mission. SPILLTRACE searches its catalogue, through the Copernicus Data Space Ecosystem, for scenes covering a case’s area and time window.',
  },
  {
    term: 'GRD',
    aka: 'Ground Range Detected',
    topic: 'imagery',
    definition:
      'The Sentinel-1 product level SPILLTRACE reads (IW GRDH). Each polarisation band is fetched as a Cloud-Optimised GeoTIFF, so it can be read in windows rather than downloaded whole.',
  },
  {
    term: 'VV / VH',
    aka: 'Polarisation',
    topic: 'imagery',
    definition:
      'Radar channels: transmitted vertically, received vertically (VV) or horizontally (VH). When only VV exists it is duplicated into the second channel, and the run records that it was.',
  },
  {
    term: 'Backscatter',
    aka: 'σ⁰, sigma nought, dB',
    topic: 'imagery',
    definition:
      'The share of the radar pulse the surface returns to the satellite, expressed in decibels (10·log₁₀ σ⁰). Rough water returns more; a smooth, damped film returns less.',
  },
  {
    term: 'Bragg waves',
    aka: 'Capillary waves',
    topic: 'imagery',
    definition:
      'The short, wind-raised ripples that return most of the radar signal from the sea. Oil damps them — and so do calm air, natural films and rain, which is why look-alikes exist.',
  },
  {
    term: 'U-Net',
    topic: 'imagery',
    definition:
      'The segmentation neural network specified for detection: it gives each pixel a probability of belonging to an oil-like film. When no trained model is registered, a deterministic analytical detector runs instead and its output is labelled SYNTHETIC.',
  },
  {
    term: 'Detection confidence',
    topic: 'imagery',
    definition:
      'The area-weighted mean predicted probability over the retained slick polygons. A model-internal quantity — never multiplied with verification or origin confidence.',
  },
  {
    term: 'Look-alike',
    topic: 'imagery',
    definition:
      'A dark radar feature that is not oil: low wind, biogenic films, rain cells, internal waves, upwelling or current shear all damp the same short waves.',
  },
  {
    term: 'Biogenic film',
    topic: 'imagery',
    definition:
      'A thin natural surface film produced by marine life. It damps the same waves oil does, and no feature set separates it from mineral oil reliably — the acknowledged hard case.',
  },
  {
    term: 'Veto rule',
    topic: 'imagery',
    definition:
      'A look-alike rule reporting a physical impossibility — wind below 2 m/s or above 12 m/s, or less than 2 dB of contrast. It rejects the detection whatever the other rules say.',
  },
  {
    term: 'Evidence coverage',
    topic: 'imagery',
    definition:
      'The share of look-alike rule weight that could actually be evaluated. A rule without its input is left out rather than failed; below 45% coverage the verdict is UNCERTAIN.',
  },
  // ----------------------------------------------------------- drift & origin
  {
    term: 'Drift hindcast',
    aka: 'Reverse drift, back-tracking',
    topic: 'drift',
    definition:
      'Running a drift simulation backwards in time from the observed slick, under recorded wind and currents, to estimate where and when the oil entered the sea.',
  },
  {
    term: 'Particle ensemble',
    topic: 'drift',
    definition:
      'The many simulated particles a hindcast releases, each responding slightly differently to wind and current, so that their spread expresses the uncertainty instead of hiding it.',
  },
  {
    term: 'Forcing',
    topic: 'drift',
    definition:
      'The wind and ocean-current fields that drive a drift simulation — from the Copernicus Marine Service, or a labelled synthetic field when that source is unavailable.',
  },
  {
    term: 'Origin probability region',
    topic: 'drift',
    definition:
      'Nested contours enclosing 50%, 75% and 90% of the back-tracked particle mass. An area with its uncertainty drawn in — never a coordinate (CON-008).',
  },
  {
    term: 'Inferred discharge window',
    topic: 'drift',
    definition:
      'The middle half (25th to 75th percentile) of the times at which back-tracked particles were inside the origin region. If too few particles reach it, the whole back-track span is used.',
  },
  {
    term: 'Origin confidence',
    topic: 'drift',
    definition:
      'How concentrated the back-tracked particle density is. Not a probability that a discharge occurred, and never combined with detection or verification confidence.',
  },
  {
    term: 'OpenDrift / OpenOil',
    topic: 'drift',
    definition:
      'The open-source trajectory framework used for drift when it is installed. Otherwise a deterministic analytical advection–diffusion engine runs, and the drift run records which engine produced it.',
  },
  // ------------------------------------------------------------ vessels & AIS
  {
    term: 'AIS',
    aka: 'Automatic Identification System',
    topic: 'ais',
    definition:
      'Radio messages in which vessels broadcast identity, position, speed and course. Received by coastal stations and satellites with gaps — and not every vessel carries it.',
  },
  {
    term: 'MMSI',
    aka: 'Maritime Mobile Service Identity',
    topic: 'ais',
    definition:
      'The nine-digit radio identifier in every AIS message. It is reassigned over time, so on its own it is not a durable identity for a vessel.',
  },
  {
    term: 'IMO number',
    topic: 'ais',
    definition:
      'The ship’s durable identifier, carried in AIS static-data messages. Both it and the MMSI are stored, and the evidence report states which one was used.',
  },
  {
    term: 'SOG / COG',
    aka: 'Speed / course over ground',
    topic: 'ais',
    definition:
      'Speed over ground in knots and course over ground in degrees, as reported in AIS position messages. Values outside physical limits are flagged, not trusted.',
  },
  {
    term: 'Trajectory',
    topic: 'ais',
    definition:
      'A vessel’s cleaned, time-ordered track, split into a new segment wherever reporting stops for 30 minutes or more. Flagged positions are kept with a reason, never deleted.',
  },
  {
    term: 'Dark period',
    topic: 'ais',
    definition:
      'An AIS gap of 12 hours or more that begins over 50 nautical miles from shore where reception is adequate — the only kind of gap that may be surfaced, and even then not evidence of wrongdoing.',
  },
  {
    term: 'Coverage ratio',
    topic: 'ais',
    definition:
      'Observed AIS positions divided by the number expected at a conservative reporting rate, clamped to 0–1. One of five inputs to the AIS-reliability factor.',
  },
  {
    term: 'Candidate vessel',
    topic: 'ais',
    definition:
      'A vessel whose track is compatible with the origin region in space and time — by default within 5 km of the region and 2 hours of the window. A lead for enquiry, with a sentence saying why it was included.',
  },
  // ----------------------------------------------------------------- scoring
  {
    term: 'Investigative score',
    topic: 'scoring',
    definition:
      'The weighted sum of six factor scores, on a 0–1 scale. A way to decide which lead to look at first — not a probability, and not a finding.',
  },
  {
    term: 'Factor',
    topic: 'scoring',
    definition:
      'One of the six independent measurements behind a score — origin proximity, time match, trajectory match, heading match, speed match and AIS reliability — each stored and explained on its own.',
  },
  {
    term: 'Contribution',
    topic: 'scoring',
    definition:
      'A factor’s weight multiplied by its score: the part of the final score that factor delivered. The six contributions add up to the score.',
  },
  {
    term: 'Evidence-strength band',
    aka: 'LOW / MODERATE / HIGH',
    topic: 'scoring',
    definition:
      'The label from where a score sits against the edges 0.45 and 0.80. It describes how much corroborating evidence a candidate has — not how likely anything is.',
  },
  {
    term: 'Discrimination note',
    topic: 'scoring',
    definition:
      'The explanation attached when labels are capped at MODERATE — because the evidence could not tell candidates apart, or the origin region itself was weak. Scores are never altered.',
  },
  {
    term: 'Scoring version',
    topic: 'scoring',
    definition:
      'The identifier of the factor formulas and weights that produced a score — prd-j-v1 — stored with every result, so an old score is always read in the terms it was produced under.',
  },
  // ----------------------------------------------------------- records & data
  {
    term: 'Case',
    topic: 'records',
    definition:
      'One investigation: an area of interest pinned to a time window, together with every job and artifact produced for it.',
  },
  {
    term: 'AOI',
    aka: 'Area of interest',
    topic: 'records',
    definition:
      'The polygon drawn when a case is opened. It is validated and size-capped, and data is fetched for this area and the case’s time window only.',
  },
  {
    term: 'Job',
    topic: 'records',
    definition:
      'A tracked background task that runs one pipeline stage, with its status, progress and any error recorded — heavy work never runs inside a web request.',
  },
  {
    term: 'Provenance',
    aka: 'REAL / SYNTHETIC / MIXED',
    topic: 'records',
    definition:
      'Where the data behind an artifact came from: real observations, deterministic synthetic data, or a mixture. Carried on every artifact and always shown as a text label.',
  },
  {
    term: 'Run manifest',
    topic: 'records',
    definition:
      'The reproducibility record stored with every artifact: pipeline stage, software version and commit, provider and its parameters, model and version, random seed, input checksums and notes.',
  },
  {
    term: 'Checksum',
    aka: 'SHA-256',
    topic: 'records',
    definition:
      'A fingerprint of a file’s exact bytes. Change one byte and the fingerprint changes — which is how an artifact is shown to be the one that was produced.',
  },
  {
    term: 'Seed',
    topic: 'records',
    definition:
      'The starting value of the random-number generator, recorded so a stochastic step such as a drift ensemble can be reproduced exactly.',
  },
  {
    term: 'Evidence report',
    topic: 'records',
    definition:
      'The packaged output of a case — sources, timestamps, model versions, parameters, checksums and limitations — as HTML with a PDF export, stored with its own checksum.',
  },
  {
    term: 'CDSE',
    aka: 'Copernicus Data Space Ecosystem',
    topic: 'records',
    definition: 'The Copernicus service used to search for and download Sentinel-1 scenes.',
  },
  {
    term: 'CMEMS',
    aka: 'Copernicus Marine Service',
    topic: 'records',
    definition:
      'The EU service that supplies the wind and ocean-current fields used by the look-alike checks and the drift simulation.',
  },
];

const TOTAL = TERMS.length;

function matches(term: Term, query: string): boolean {
  if (!query) return true;
  const haystack = `${term.term} ${term.aka ?? ''} ${term.definition}`.toLowerCase();
  return query
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => haystack.includes(word));
}

/** Wraps the matched part of a term name in <mark>, case-insensitively. */
function highlight(text: string, query: string): ReactNode {
  const needle = query.trim().toLowerCase();
  if (!needle) return text;
  const at = text.toLowerCase().indexOf(needle);
  if (at < 0) return text;
  return (
    <>
      {text.slice(0, at)}
      <mark className={styles.mark}>{text.slice(at, at + needle.length)}</mark>
      {text.slice(at + needle.length)}
    </>
  );
}

/** A searchable, topic-filterable glossary. Purely local — no data is fetched. */
export function Glossary() {
  const [query, setQuery] = useState('');
  const [topic, setTopic] = useState<Topic | 'all'>('all');
  const deferred = useDeferredValue(query.trim());

  const results = useMemo(
    () =>
      TERMS.filter((term) => (topic === 'all' || term.topic === topic) && matches(term, deferred)),
    [deferred, topic],
  );

  const reset = () => {
    setQuery('');
    setTopic('all');
  };

  return (
    <div className={styles.glossary}>
      <div className={styles.glossaryControls}>
        <div className={styles.glossarySearch}>
          <IconSearch size={16} className={styles.glossarySearchIcon} />
          <Input
            label="Search the glossary"
            labelHidden
            type="search"
            value={query}
            placeholder="Search terms — e.g. MMSI, hindcast, provenance"
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setQuery(event.target.value)}
            className={styles.glossaryInput}
          />
        </div>
        <div className={styles.filterRow} role="group" aria-label="Filter by topic">
          {TOPICS.map((item) => (
            <button
              key={item.key}
              type="button"
              aria-pressed={topic === item.key}
              className={cx(styles.filterChip, topic === item.key && styles.filterChipActive)}
              onClick={() => setTopic(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <p className={styles.glossaryCount} role="status">
        {results.length === TOTAL ? `${TOTAL} terms` : `${results.length} of ${TOTAL} terms`}
      </p>

      {results.length === 0 ? (
        <EmptyState
          compact
          icon={<IconSearch size={18} />}
          title="No term matches"
          description={`Nothing in the glossary mentions “${query.trim()}”${topic === 'all' ? '' : ' under this topic'}. Try a shorter word, or clear the filters.`}
          action={
            <Button size="sm" variant="secondary" onClick={reset}>
              Clear search and filters
            </Button>
          }
        />
      ) : (
        <dl className={styles.glossaryList}>
          {results.map((term) => (
            <div key={term.term} className={styles.term}>
              <dt className={styles.termName}>
                {highlight(term.term, deferred)}
                {term.aka ? <span className={styles.termAka}>{term.aka}</span> : null}
              </dt>
              <dd className={styles.termDefinition}>{term.definition}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
