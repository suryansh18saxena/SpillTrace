import { describe, expect, it } from 'vitest';
import {
  CASE_SCREENS,
  SCREENS,
  STAGES,
  TERMS,
  WHAT_IS_SPILLTRACE,
  screenExplainer,
  stageExplainer,
  stagePlainName,
  type Explainer,
} from '@/lib/explain';

/**
 * The plain-language layer is the part of the product a non-specialist actually
 * reads, which makes it the easiest place for an over-claim to slip in
 * unnoticed. These tests hold it to the same rules as the rest of the UI
 * (`docs/DESIGN_SYSTEM.md` §1).
 */

/** Words that must never describe a candidate vessel or a score. */
const BANNED = [
  'guilty',
  'culprit',
  'proven',
  'perpetrator',
  'offender',
  'polluter',
  'suspect',
  'legal probability',
];

function everyExplainer(): Array<[string, Explainer]> {
  return [
    ['WHAT_IS_SPILLTRACE', WHAT_IS_SPILLTRACE],
    ...STAGES.map((stage) => [`STAGES.${stage.id}`, stage] as [string, Explainer]),
    ...Object.entries(TERMS).map(([key, value]) => [`TERMS.${key}`, value] as [string, Explainer]),
    ...Object.entries(SCREENS).map(
      ([key, value]) => [`SCREENS.${key}`, value] as [string, Explainer],
    ),
    ...Object.entries(CASE_SCREENS).map(
      ([key, value]) => [`CASE_SCREENS.${key}`, value] as [string, Explainer],
    ),
  ];
}

describe('the plain-language dictionary', () => {
  it('never uses accusatory vocabulary', () => {
    for (const [name, explainer] of everyExplainer()) {
      const text = `${explainer.title} ${explainer.body} ${explainer.caution ?? ''}`.toLowerCase();
      for (const word of BANNED) {
        // Whole words only: "provenance" legitimately contains "proven", and
        // banning it as a substring would outlaw the provenance vocabulary the
        // honesty rules themselves depend on.
        const pattern = new RegExp(`\\b${word.replace(/ /g, '\\s+')}\\b`);
        expect(pattern.test(text), `${name} must not say "${word}"`).toBe(false);
      }
    }
  });

  it('only ever says "responsible" inside a negation', () => {
    for (const [name, explainer] of everyExplainer()) {
      const text = `${explainer.body} ${explainer.caution ?? ''}`.toLowerCase();
      if (!text.includes('responsible')) continue;
      expect(
        /(never|not|nothing|no)\b[^.]*\bresponsible/.test(text),
        `${name} mentions responsibility outside a negation`,
      ).toBe(true);
    }
  });

  it('gives every entry a title and a readable body', () => {
    for (const [name, explainer] of everyExplainer()) {
      expect(explainer.title.trim().length, `${name} has no title`).toBeGreaterThan(0);
      // Long enough to be a real explanation rather than a restated label.
      expect(explainer.body.trim().length, `${name} body is too short`).toBeGreaterThan(40);
    }
  });

  it('carries a stated limit on the claims that need one', () => {
    // These are the entries where an over-reading would be actively misleading.
    for (const key of ['investigative-score', 'band', 'origin-region', 'ais', 'candidate']) {
      expect(TERMS[key]?.caution, `TERMS.${key} must state its limit`).toBeTruthy();
    }
    expect(WHAT_IS_SPILLTRACE.caution).toBeTruthy();
  });
});

describe('pipeline stages', () => {
  it('covers every stage the pipeline can run', () => {
    const ids = STAGES.map((stage) => stage.id);
    for (const id of [
      'scene.search',
      'scene.download',
      'sar.preprocess',
      'ml.detect',
      'detect.verify',
      'env.fetch',
      'drift.hindcast',
      'ais.ingest',
      'ais.clean',
      'traj.build',
      'correlate',
      'score',
      'report.build',
    ]) {
      expect(ids, `${id} has no plain-English explanation`).toContain(id);
    }
  });

  it('gives each stage an everyday name that is not the machine name', () => {
    for (const stage of STAGES) {
      expect(stage.plain).not.toBe(stage.id);
      expect(stage.plain).not.toMatch(/\./);
    }
  });

  it('falls back to the machine name for an unknown stage', () => {
    expect(stagePlainName('ml.detect')).toBe('Look for oil');
    expect(stagePlainName('something.new')).toBe('something.new');
    expect(stageExplainer('something.new')).toBeUndefined();
  });
});

describe('screen lookup', () => {
  it('describes the top-level screens', () => {
    expect(screenExplainer('/dashboard')?.body).toContain('investigation');
    expect(screenExplainer('/map')).toBeDefined();
    expect(screenExplainer('/ml-ops')).toBeDefined();
  });

  it('describes each case-scoped screen from its last path segment', () => {
    const id = '7d45571d-ce8d-4e6f-8165-114385fcda5b';
    expect(screenExplainer(`/cases/${id}`)).toBe(CASE_SCREENS['']);
    expect(screenExplainer(`/cases/${id}/walkthrough`)).toBe(CASE_SCREENS['walkthrough']);
    expect(screenExplainer(`/cases/${id}/ranking`)).toBe(CASE_SCREENS['ranking']);
    expect(screenExplainer(`/cases/${id}/report`)).toBe(CASE_SCREENS['report']);
  });

  it('does not mistake the new-case form for a case', () => {
    expect(screenExplainer('/cases/new')).toBe(SCREENS['/cases/new']);
  });

  it('returns nothing for a screen it has no copy for', () => {
    expect(screenExplainer('/nowhere')).toBeUndefined();
  });
});
