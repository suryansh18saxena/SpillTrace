# SPILLTRACE design system — "Abyssal radar"

The frontend's visual language, motion rules and page conventions. Read this before
adding a screen; it is what keeps twenty-odd routes looking like one product.

## 1. Honesty comes before visuals

Every visual decision is subordinate to the constraints in `REQUIREMENTS.md` §7:

- **Vocabulary.** "Candidate", "investigative score", "investigative signal", "lead",
  "enquiry". Never: guilty, culprit, responsible (a negation such as "never establishes
  responsibility" is fine), proven, perpetrator, offender, polluter, suspect, "legal
  probability". `tests/candidate-ranking.test.tsx` enforces part of this list.
- **Scores** are 0–1 with two decimals (`formatScore`), never a percentage.
- **Bands are the server's.** LOW < 0.45 ≤ MODERATE < 0.80 ≤ HIGH are the edges, but the
  engine *caps* labels when the evidence cannot separate candidates, so a 0.95 can be
  MODERATE. Never recompute a band from a score; `ScoreMeter` takes the server's `band`
  and states the cap when there is one.
- **No invented numbers.** Every figure is computed from API data. Unknown is "—",
  "Unmeasured" or an explained empty state — never 0. A model with `metrics: {}` has no
  recorded evaluation.
- **Server notices render verbatim** via `<Notice>` / `<Disclaimer>`.
- **Red is system failure only** (a failed job). Never colour a rank #1 specially.
- **Provenance is text, not colour.** REAL-blue and SYNTHETIC-violet are indistinguishable
  under deuteranopia (validated), so provenance is always a labelled `<ProvenanceBadge>`.

## 2. Tokens (`frontend/src/styles/tokens.css`)

Dark-first; `[data-theme='light']` overrides the same names. Never hard-code a hex.

| Group | Tokens |
|---|---|
| Surfaces | `--color-bg`, `-bg-subtle`, `-surface`, `-surface-raised`, `-surface-overlay`, `-surface-hover` |
| Borders | `--color-border`, `-border-strong`, `-border-subtle`; glass: `--glass-bg(-strong)`, `--glass-border`, `--highlight-top` |
| Text | `--color-text`, `-text-secondary`, `-text-muted` |
| Accent | `--color-accent`, `--color-accent-2` (cyan — gradients/glows only), `--gradient-accent`, `--glow-accent` |
| Confidence | `--confidence-1/2/3` (+ `-subtle`, `-text`) — a validated one-hue ordinal ramp, warm grey → amber → gold |
| Status | `--color-success/warning/danger` — system state only |
| Map | `--map-aoi/spill/origin/vessel/track` |
| Charts | `--chart-series-1` (the single-series hue), `--chart-grid`, `--chart-axis`, `--chart-label` |
| Type | `--font-sans` (Geist), `--font-mono` (Geist Mono), `--font-serif` (Instrument Serif — editorial italics only, never a number) |
| Motion | `--ease-out` (expo), `--ease-spring`, `--duration-fast/normal/slow` |

Fonts are self-hosted (`geist`, `@fontsource/instrument-serif`) because the CSP allows
fonts from `'self'` only.

## 3. Motion (`frontend/src/lib/motion/`, `frontend/src/components/motion/`)

GSAP 3 (ScrollTrigger, SplitText, DrawSVG, MotionPath) registered once in
`lib/motion/gsap.ts`; Lenis inertial scroll on the public pages only.

- Primitives: `Reveal` (fade-up on scroll, optional stagger), `SplitReveal` (masked line
  reveal), `CountUp`, `Magnetic`, `Parallax`, `useSpotlight` (cursor light via CSS vars),
  `SmoothScroll`. Route transitions live in `app/(app)/template.tsx`.
- **Reduced motion is honoured everywhere**: each primitive checks
  `prefersReducedMotion()` and renders the final state.
- **No flash of hidden content**: `[data-reveal]` is pre-hidden only when the head script
  stamped `data-motion="ok"`, with a CSS failsafe that reveals it after 2.5 s.
- Transform and opacity only; no animated `filter: blur`; ambient loops pause off-screen.
  The reference machine is an i3 with integrated graphics.

## 4. Components

- **UI kit** `components/ui/*` — `Button`, `LinkButton`, `Card`, `Badge`, `Table` (built-in
  loading / error / empty), `Tabs`, `Input`, `Select`, `Dialog`, `Toast`, `Icons`.
- **Shell** `components/shell/*` — command palette (Ctrl/⌘ K), notification centre,
  user menu, onboarding tour, backdrop. Navigation is one registry:
  `components/layout/nav.tsx` feeds the sidebar, palette and breadcrumbs.
- **Charts** `components/charts/*` — `StatTile`, `ChartFrame` (Chart/Table toggle — always
  pass a `table`), `ColumnChart`, `BarList`, `SegmentBar`, `ScoreMeter`,
  `ContributionBars`, `Sparkline`.
- **Attribution** — `CandidateRanking`, `FactorTable`, `ConfidenceBadge`, `Disclaimer`,
  `PlainLanguageSummary` (rule-based, *not* a language model, and labelled as such).

## 5. Charts

One series = one hue; ordered classes use the confidence ramp; nominal categories use one
hue. Thin marks, 2 px gaps, hairline grid, text in text tokens. Every chart has a
hover/focus tooltip where values are not printed, and a table view. No dual axes; a single
number is a `StatTile`, not a one-bar chart.

## 6. Cross-case data

The API is case-scoped. Overview screens use `useCaseUniverse()` (`lib/api/aggregate.ts`),
which fans out to the 50 most recent cases using the same query keys as the case pages.
When it is truncated or a per-case request fails, the screen says so. Pure derivations live
in `lib/insights.ts` (weekly buckets, band counts, vessel appearances by MMSI, the
plain-language summary).

## 7. Page scaffold

```tsx
'use client';
import { PageHeader } from '@/components/layout/PageHeader';
import layout from '@/components/layout/layout.module.css';

export default function Page() {
  return (
    <main className={layout.content} id="main-content">
      <PageHeader eyebrow="Section" title="Title" subtitle="What this screen is for." />
      {/* … */}
    </main>
  );
}
```

Authenticated routes go in `app/(app)/<route>/`; public ones in `app/<route>/` and must not
call authenticated endpoints. A client page using `useSearchParams` must sit inside
`<Suspense>`. Add the route to `nav.tsx` so it appears in the sidebar and palette.

## 8. Maps

Every map is `<MapView>` over MapLibre GL, composed from ONE style: the self-hosted offline
graticule (`public/map-style.json`) plus the public imagery basemaps in `lib/map/basemaps.ts`
(Esri World Imagery — the default — Esri Ocean, CARTO Dark / Light, Offline). Switching a basemap
toggles layer visibility; it never calls `setStyle`, so evidence layers survive.

- **Basemap control** (`components/map/BasemapControl.tsx`) sits top-right under the navigation
  control; the analyst's choice and the labels toggle persist via `lib/preferences.ts`. Reference
  maps swap Dark/Light with the theme.
- **Globe**: pass `globeToggle` (and optionally `globe`/`autoRotate`) to `MapView`; used on the
  situational map. Auto-rotation stops on interaction and never runs under reduced motion.
- **Cinematic camera**: `fitTo` flies with a 32° pitch when motion is allowed (`cinematic` prop);
  instant under reduced motion.
- **Honesty**: imagery is context, not evidence. The attribution control names the imagery
  provider; the Offline basemap makes no external request and is the automatic fallback when tiles
  fail. Never draw an origin as a point, never colour a rank red — the map follows §1.
- **Tokens**: `--map-*` incl. `--map-sky` / `--map-horizon` for the globe atmosphere.

## 9. v3 — "Glass & instrument" (2026-09-12)

An additive layer over v2: every class API is unchanged, so pages inherit it for free.

**Tokens** (`tokens.css`, both themes): glass tiers `--glass-{1,2,3}-bg/-border`,
`--glass-blur-{sm,md,lg}`, `--glass-saturate`, `--glass-highlight`, `--glass-edge`,
`--glass-shadow`; neumorphic controls `--neo-bg`, `--neo-raised(-sm)`, `--neo-inset(-sm)`;
ambient light `--aurora-1..4`, `--aurora-opacity`, `--noise-opacity` (violet is also the
SYNTHETIC hue — aurora only, never on a control); elevation `--elev-0..4`; easings
`--ease-spring-soft`, `--ease-elastic`; `--duration-slower`; `--blur-{sm,md,lg}`.
Global utilities: `.glass`, `.glass-strong`, `.neo`, `.neo-inset`.

**Kit**: `Card` gains `variant="glass" | "solid" | "neo"` (glass default) and `interactive`
(hover lift + cursor spotlight). Primary buttons depress on press; secondary buttons are glass;
inputs are machined wells; tabs are a glass rail with a lit pill; table headers are sticky glass;
skeletons shimmer; dialogs/toasts/tooltips use the strongest glass tier and spring in.

**Shell**: glass sidebar and header (the header condenses after 24 px of scroll via
`data-condensed`); the backdrop is an aurora (three transform-only blobs, paused in hidden tabs,
static under reduced motion) plus a slow radar sweep and grain. Route transitions
(`app/(app)/template.tsx`) are a clip-path shutter + header stagger + a stagger of the first
screenful of `[data-enter]` / card panels, ≤ 700 ms.

**Motion primitives** (`components/motion/`): `TiltCard` (pointer tilt + glare, off on touch /
reduced motion), `BorderBeam` (conic light around a panel's edge), `ScrollProgress`,
`TextShimmer` (CSS-only sheen), `NumberTicker` (rolling digits that only ever display the string
they are given — unknown stays "—"). Existing: `Reveal`, `SplitReveal`, `CountUp`, `Magnetic`,
`Parallax`, `useSpotlight`, `SmoothScroll`.

**Theme**: dark is the default regardless of OS preference; light remains one click away and is
stored. **Budget**: no animated `filter`, transform/opacity only, backdrop-filter kept to
panels; the reference machine is an i3 with integrated graphics.

**Rules for page work**: mark the first-screen panels you want staggered with `data-enter`; use
`Card interactive` for link cards; never put the aurora hues on data; keep §1 intact.

