/**
 * Plain-English explanations for everything on screen.
 *
 * One dictionary, used by `ScreenGuide` (the "What am I looking at?" strip at the
 * top of every screen), `ExplainTip` (the small "?" next to a jargon word) and
 * `CaseStory` (the narrated walkthrough). Keeping it in one file means a term is
 * explained the same way wherever it appears, and a reviewer can read the whole
 * vocabulary of the product in one sitting.
 *
 * Writing rules for everything in here:
 *
 * - **No jargon inside an explanation.** If a word needs its own entry, it gets one.
 * - **Say what it is NOT.** Half of this product's job is preventing an over-reading,
 *   so most entries carry a `caution` that states the limit out loud.
 * - **Never the banned vocabulary** (`docs/DESIGN_SYSTEM.md` §1): no guilty, culprit,
 *   responsible (except in a negation), proven, perpetrator, offender, polluter,
 *   suspect, or "legal probability".
 * - **No invented numbers.** Text here is fixed prose; every figure shown beside it
 *   comes from the API at render time.
 */

export interface Explainer {
  /** The everyday name for the thing. */
  title: string;
  /** One or two sentences a non-specialist can follow. */
  body: string;
  /** The limit of the thing — what it must not be read as. */
  caution?: string;
}

// --------------------------------------------------------------- the product

/** The 30-second version, used on the dashboard and in the tour. */
export const WHAT_IS_SPILLTRACE: Explainer = {
  title: 'What this system does',
  body:
    'Ships sometimes wash out their tanks at sea and leave a slick of oil behind. A radar satellite can see that slick from space, even at night and through cloud. SPILLTRACE finds the slick in the radar image, checks it is really oil, works out where in the sea it started by running wind and current backwards in time, and then lists the ships that were in that place at that time — each with a score you can open up and read factor by factor.',
  caution:
    'The result is a shortlist for an investigator to follow up. It is evidence to be checked by people, and it never establishes who is responsible.',
};

// ------------------------------------------------------- the pipeline stages

export interface StageExplainer extends Explainer {
  /** The machine name the API and logs use, e.g. `ml.detect`. */
  id: string;
  /** Everyday verb phrase for the step, used as the heading. */
  plain: string;
}

/**
 * The chain, in the order it runs. `plain` is what the screen shows; `id` is what
 * the logs and the API call it, kept visible so the two can be matched up.
 */
export const STAGES: readonly StageExplainer[] = [
  {
    id: 'scene.search',
    plain: 'Find a satellite pass',
    title: 'Find a satellite pass',
    body:
      'Asks the European Copernicus catalogue which Sentinel-1 radar images cover this patch of sea inside the chosen dates. Sentinel-1 is a free public radar satellite that images the same waters every few days.',
    caution:
      'A satellite only sees the sea when it passes over it. A spill between two passes may leave no image at all.',
  },
  {
    id: 'scene.download',
    plain: 'Fetch the image',
    title: 'Fetch the image',
    body:
      'Downloads the radar image that was chosen, and records its checksum so the exact file behind a result can always be identified later.',
  },
  {
    id: 'sar.preprocess',
    plain: 'Clean up the radar image',
    title: 'Clean up the radar image',
    body:
      'Raw radar is noisy and its brightness drifts across the image. This step converts it to decibels, trims the extreme 1% at each end, and rescales it so a dark patch on one side of the image means the same as a dark patch on the other.',
    caution:
      'The exact trim values used are written into the run record, because changing them would change what counts as "dark".',
  },
  {
    id: 'ml.detect',
    plain: 'Look for oil',
    title: 'Look for oil',
    body:
      'Oil flattens the small waves that radar bounces off, so an oil slick shows up as a dark patch on a bright sea. A trained neural network reads the cleaned image and gives every pixel a score from 0 to 1 for how oil-like it looks, and the dark shapes are traced into outlines.',
    caution:
      'A dark patch is only a dark patch. The next step exists precisely because several harmless things look identical here.',
  },
  {
    id: 'detect.verify',
    plain: 'Rule out the look-alikes',
    title: 'Rule out the look-alikes',
    body:
      'Low wind, algae blooms, rain cells and river plumes all flatten the sea and look just like oil on radar. Seven physical checks are run against the wind and the shape of the patch — how dark it is, how irregular its edge is, how sharp its boundary is — and each one reports what it found.',
    caution:
      'These checks reduce false alarms. They cannot prove oil, and a natural film can still pass them.',
  },
  {
    id: 'env.fetch',
    plain: 'Get the wind and current',
    title: 'Get the wind and current',
    body:
      'Pulls the measured wind and surface current for that exact patch of sea at that exact hour from Copernicus Marine, the European ocean service. Without this the drift step would be guesswork.',
  },
  {
    id: 'drift.hindcast',
    plain: 'Run the sea backwards',
    title: 'Run the sea backwards',
    body:
      'Oil does not stay where it was spilled — it drifts. Thousands of imaginary particles are placed in the slick and pushed backwards through the real wind and current, hour by hour, to see where they were before. Where they bunch together is where the oil plausibly started.',
    caution:
      'This produces a region, never a point. Small errors in wind grow the longer you run backwards, which is why the answer is a spread and not a coordinate.',
  },
  {
    id: 'ais.ingest',
    plain: 'Collect ship broadcasts',
    title: 'Collect ship broadcasts',
    body:
      'Most large ships continuously broadcast their identity, position, speed and heading over a public radio system called AIS. This step collects every such broadcast for that area and time window.',
    caution:
      'Public AIS coverage is incomplete. A ship missing from this list was not necessarily absent from the sea.',
  },
  {
    id: 'ais.clean',
    plain: 'Throw out bad ship data',
    title: 'Throw out bad ship data',
    body:
      'AIS is noisy: positions land on dry land, speeds come back impossible, two ships broadcast the same identity. Each bad message is flagged with the reason it was rejected rather than quietly deleted.',
  },
  {
    id: 'traj.build',
    plain: "Draw each ship's path",
    title: "Draw each ship's path",
    body:
      'Joins the scattered position reports of each ship into a track through the water, and marks any stretch where the ship stopped reporting so the gap is visible rather than smoothed over.',
    caution:
      'A gap in reporting has many innocent causes — receiver range, radio collisions, equipment faults. A gap is never treated as wrongdoing.',
  },
  {
    id: 'correlate',
    plain: 'Find who was there',
    title: 'Find who was there',
    body:
      'Takes the region the oil plausibly started in, and the window it plausibly started in, and finds which of the tracked ships were inside both. Ships that were far away, or there on the wrong day, drop out here.',
  },
  {
    id: 'score',
    plain: 'Weigh the evidence',
    title: 'Weigh the evidence',
    body:
      'Each remaining ship is scored on six separate things: how close it came to the origin region, how well its timing matches, how well its path matches, its heading, its speed, and how complete its AIS reporting was. Each factor is scored on its own and then combined with a fixed published weight.',
    caution:
      'The six factors stay visible and separately readable, so a rank can be argued with. The total is a sorting aid, not a measure of likelihood.',
  },
  {
    id: 'report.build',
    plain: 'Write the evidence report',
    title: 'Write the evidence report',
    body:
      'Assembles everything above into one document: which satellite image, which wind data, which model version, which checks passed, which ships were considered, and every caveat that applies.',
  },
  {
    id: 'demo.seed',
    plain: 'Create demonstration data',
    title: 'Create demonstration data',
    body:
      'Generates a complete, repeatable fake scenario — a fake slick, fake weather and fake ships — so the whole chain can be shown end to end without a satellite account.',
    caution:
      'Everything this produces is labelled SYNTHETIC everywhere it appears, and can never be mistaken for a real observation.',
  },
];

const STAGE_BY_ID = new Map(STAGES.map((stage) => [stage.id, stage]));

export function stageExplainer(id: string): StageExplainer | undefined {
  return STAGE_BY_ID.get(id);
}

/** Everyday name for a stage, falling back to the machine name. */
export function stagePlainName(id: string): string {
  return STAGE_BY_ID.get(id)?.plain ?? id;
}

// ---------------------------------------------------------------- the words

/** Jargon, decoded. Keys are lower-case and stable; `ExplainTip` looks them up. */
export const TERMS: Record<string, Explainer> = {
  sar: {
    title: 'Radar imaging (SAR)',
    body:
      'A satellite radar sends its own pulses down and listens for the echo, so it works at night and straight through cloud — unlike an ordinary camera. A rough, windy sea scatters the pulse and looks bright; a smooth sea reflects it away and looks dark.',
  },
  'sentinel-1': {
    title: 'Sentinel-1',
    body:
      'A pair of European radar satellites that image the world’s seas for free every few days. This is the source of every radar image here.',
  },
  slick: {
    title: 'Slick',
    body:
      'A thin film of oil spread out on the sea surface. It damps the small ripples underneath it, which is what makes it visible to radar as a dark patch.',
  },
  'look-alike': {
    title: 'Look-alike',
    body:
      'Something that is not oil but looks exactly like it on radar: a patch of very low wind, an algae bloom, a rain cell, fresh water from a river. Telling these apart from oil is the single hardest part of the job.',
  },
  ais: {
    title: 'AIS',
    body:
      'The Automatic Identification System — a public radio broadcast that most large ships transmit continuously, carrying their identity, position, speed and heading. It is how the sea is tracked.',
    caution:
      'Public AIS coverage is not complete anywhere, and is thinner far from shore.',
  },
  'ais-gap': {
    title: 'Reporting gap',
    body:
      'A stretch of time where a ship’s broadcasts were not received. Gaps are shown because they weaken what can be said about a ship, not because they say anything against it.',
    caution:
      'A gap has many ordinary causes: out of receiver range, radio collisions, an equipment fault. A gap can only lower confidence in a ship’s track; it can never raise a ship’s score.',
  },
  mmsi: {
    title: 'MMSI',
    body:
      'The nine-digit radio identity a ship broadcasts. It is the key everything here is grouped by, because it is present in every message.',
  },
  imo: {
    title: 'IMO number',
    body:
      'A permanent seven-digit number assigned to a hull for its whole life. Unlike the radio identity it does not change when a ship is renamed or re-flagged, but it is not always broadcast.',
  },
  'drift-hindcast': {
    title: 'Backwards drift',
    body:
      'Running the sea in reverse. Thousands of particles are placed in the slick and moved backwards through the measured wind and current to find where they plausibly came from.',
  },
  'origin-region': {
    title: 'Origin probability region',
    body:
      'The area of sea the oil plausibly came from, drawn as nested contours — the tight inner shape is where the backwards-drifted particles concentrated most.',
    caution:
      'This is a region, never an exact discharge point, and it is not a claim that a discharge happened.',
  },
  'detection-confidence': {
    title: 'Detection confidence',
    body:
      'How oil-like the pixels inside the outline looked to the model, averaged across the shape, on a 0 to 1 scale.',
    caution:
      'This measures appearance in a radar image only. It is not a probability that any ship discharged anything.',
  },
  'verification-confidence': {
    title: 'Verification confidence',
    body:
      'How well the patch survived the seven physical look-alike checks, on a 0 to 1 scale. It is deliberately kept separate from detection confidence and the two are never multiplied together.',
  },
  'origin-confidence': {
    title: 'Origin confidence',
    body:
      'How tightly the backwards-drifted particles bunched together. A high value means the drift run points at a compact area; a low value means the answer is spread out.',
    caution:
      'It describes the spread of a simulation. It is not a probability that a discharge occurred.',
  },
  'investigative-score': {
    title: 'Investigative score',
    body:
      'Six weighted factors added together into one number from 0 to 1, used to sort the candidate ships so an investigator knows where to look first. Every factor stays separately visible underneath.',
    caution:
      'It is a prototype engineering weighting, not a calibrated statistic. A 0.90 does not mean a 90% chance of anything.',
  },
  band: {
    title: 'Evidence-strength band',
    body:
      'The LOW, MODERATE or HIGH label beside a score. It is decided by the server, and it gets held down to MODERATE whenever the evidence cannot actually separate the top candidates from each other.',
    caution:
      'Because of that cap, a high number can still carry a MODERATE label — and when it does, the reason is printed next to it.',
  },
  provenance: {
    title: 'Data provenance',
    body:
      'Where a result’s inputs came from. REAL means live satellite, ocean and ship data. SYNTHETIC means generated for demonstration. MIXED means a combination of both — for example a real trained model run over a generated image.',
    caution:
      'This is always written as a word, never as a colour alone, so it cannot be missed or misread.',
  },
  aoi: {
    title: 'Area of interest',
    body:
      'The patch of sea an investigation covers, drawn on the map when the case is created. Everything in the case is limited to this box and its time window.',
  },
  'probability-raster': {
    title: 'Oil probability layer',
    body:
      'The model’s raw per-pixel output, painted over the map as a heat layer, before it was cut into a single outline. Turning it on shows you what the model actually saw, not just the conclusion it reached.',
  },
  pipeline: {
    title: 'Pipeline',
    body:
      'The chain of steps that turns a satellite image into a ranked list. Each step runs as its own job, so you can watch where a case is and see exactly which step failed if one does.',
  },
  candidate: {
    title: 'Candidate vessel',
    body:
      'A ship that was inside the origin region during the window the oil plausibly started in. Being on this list means "worth asking about", nothing more.',
    caution:
      'The nearest ship is not automatically the source, and the list is never padded to reach a target length.',
  },
};

export function termExplainer(key: string): Explainer | undefined {
  return TERMS[key];
}

// -------------------------------------------------------------- the screens

/** "What am I looking at?" for each route, keyed by pathname pattern. */
export const SCREENS: Record<string, Explainer> = {
  '/dashboard': {
    title: 'What am I looking at?',
    body:
      'The overview of every investigation you have running. The four tiles count what the system has produced so far; below them are your most recent cases and how strong the evidence in them is.',
    caution:
      'Counts are of things the system observed, not of confirmed spills or confirmed ships.',
  },
  '/map': {
    title: 'What am I looking at?',
    body:
      'Every investigation drawn on one chart of the sea. Each blue box is an area someone is investigating; each yellow dot is the centre of a slick that was detected there. Click any of them to open that case.',
    caution:
      'A dot marks where the oil was seen, which is not where it came from. Where it came from is on each case’s own map.',
  },
  '/analytics': {
    title: 'What am I looking at?',
    body:
      'Patterns across all your cases at once rather than inside one: how many slicks were detected week by week, how many survived the look-alike checks, and how the evidence strength is spread out.',
    caution:
      'Every figure is counted from your own cases. It is not a survey of Indian waters.',
  },
  '/cases': {
    title: 'What am I looking at?',
    body:
      'Every investigation you can open. A case is one patch of sea plus one stretch of time, and everything the chain found inside it.',
  },
  '/cases/new': {
    title: 'What am I looking at?',
    body:
      'Start an investigation. Draw a box on the sea, give it a start and end time, and the chain will look for satellite images covering it and work forwards from there.',
  },
  '/vessels': {
    title: 'What am I looking at?',
    body:
      'Every ship your cases have observed in AIS broadcasts, grouped by its radio identity, with how often it has appeared as a candidate.',
    caution:
      'Appearing here repeatedly usually means the ship uses a busy shipping lane. It is history, not evidence against it.',
  },
  '/activity': {
    title: 'What am I looking at?',
    body:
      'A running log of everything the system has done — every pipeline step that started, finished or failed, newest first.',
  },
  '/compare': {
    title: 'What am I looking at?',
    body:
      'Two investigations side by side, so the same measurement can be read across both without flipping between tabs.',
  },
  '/ml-ops': {
    title: 'What am I looking at?',
    body:
      'Which detection model is in use, what it scored when it was tested, and how the job queue is behaving right now.',
    caution:
      'A model with no recorded evaluation is shown as unmeasured — never as a score of zero.',
  },
  '/admin': {
    title: 'What am I looking at?',
    body:
      'System health: whether the database, queue and storage are up, which data source is wired to each part of the chain, and whether any of them is running on generated data.',
  },
};

/** The case-scoped screens, keyed by the last path segment. */
export const CASE_SCREENS: Record<string, Explainer> = {
  '': {
    title: 'What am I looking at?',
    body:
      'The investigation on one map. The blue box is the area being investigated, the yellow shape is the slick that was found, the purple region is where the oil plausibly started, and the lines are ships that were in the area. Use the layer switches on the right to turn each one on and off.',
    caution:
      'The purple region is a spread of possibilities from a simulation, not an exact spot where something happened.',
  },
  walkthrough: {
    title: 'What am I looking at?',
    body:
      'This investigation told as a story, step by step, in plain language — with the real number each step produced. Start here if anything else on the case is unclear.',
  },
  spill: {
    title: 'What am I looking at?',
    body:
      'The slick itself: how big it is, how oil-like it looked to the model, and what each of the seven physical checks concluded about whether it could be something harmless instead.',
    caution:
      'The two confidence numbers measure different things and are deliberately never combined into one.',
  },
  drift: {
    title: 'What am I looking at?',
    body:
      'Where the oil plausibly started. Thousands of particles were pushed backwards through the real wind and current; the contours show where they ended up bunching together.',
    caution:
      'This is a probability region, never an exact discharge coordinate.',
  },
  ranking: {
    title: 'What am I looking at?',
    body:
      'The ships that were inside the origin region during the window, sorted by a six-factor score. Open any row to see all six factors, their weights and the arithmetic behind the total.',
    caution:
      'This ranks who is worth asking about first. It never establishes responsibility, and the nearest ship is not automatically the source.',
  },
  report: {
    title: 'What am I looking at?',
    body:
      'The full record of this investigation as one document — every source, timestamp, model version and caveat — rendered by the server exactly as it would be handed over.',
  },
};

export function screenExplainer(pathname: string): Explainer | undefined {
  if (SCREENS[pathname]) return SCREENS[pathname];
  const caseMatch = /^\/cases\/[^/]+(?:\/([^/]+))?$/.exec(pathname);
  if (caseMatch) {
    if (pathname === '/cases/new') return SCREENS['/cases/new'];
    return CASE_SCREENS[caseMatch[1] ?? ''];
  }
  return undefined;
}
