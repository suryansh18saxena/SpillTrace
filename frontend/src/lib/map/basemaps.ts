/**
 * Basemap catalogue for every SPILLTRACE map (AD-5, amended 2026-09-12).
 *
 * Until this change the map drew a self-hosted graticule on a flat ocean and made
 * no external request. Investigation screens need geographic context, so the
 * default basemap is now Esri World Imagery, with an ocean chart, a dark
 * reference map and the original offline graticule as alternatives.
 *
 * What this does and does not disclose:
 *   - Tile services below are public and unauthenticated. No key, token or
 *     credential is ever attached (CON-004) — `useMap` only adds the bearer token
 *     to requests aimed at our own API origin.
 *   - A tile request reveals the viewport (tile x/y/z) to the tile provider. An
 *     analyst who must not disclose an area of interest switches to "Offline",
 *     which restores the zero-external-request behaviour. Imagery is context;
 *     every evidence layer still comes from the SPILLTRACE API.
 *
 * All basemaps live in ONE MapLibre style so switching toggles layer visibility
 * and never calls `setStyle`, which would destroy the data layers `MapView`
 * manages on top.
 */

import type {
  LayerSpecification,
  RasterSourceSpecification,
  StyleSpecification,
} from 'maplibre-gl';

export type BasemapId = 'satellite' | 'ocean' | 'dark' | 'light' | 'offline';

export interface BasemapDefinition {
  id: BasemapId;
  label: string;
  /** One line for the switcher's tooltip. */
  description: string;
  attribution: string;
  /** External hosts the basemap fetches from; empty for offline. */
  external: boolean;
  /** Which theme this basemap is designed for; `null` means both. */
  theme: 'dark' | 'light' | null;
}

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';

export const ESRI_IMAGERY_ATTRIBUTION =
  'Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community';
export const ESRI_OCEAN_ATTRIBUTION =
  'Ocean basemap © Esri, Garmin, GEBCO, NOAA NGDC, and other contributors';
export const CARTO_ATTRIBUTION = '© OpenStreetMap contributors © CARTO';
export const OFFLINE_ATTRIBUTION = 'SPILLTRACE offline graticule · no third-party tiles';

export const BASEMAPS: readonly BasemapDefinition[] = [
  {
    id: 'satellite',
    label: 'Satellite',
    description: 'Esri World Imagery with place names and boundaries.',
    attribution: ESRI_IMAGERY_ATTRIBUTION,
    external: true,
    theme: null,
  },
  {
    id: 'ocean',
    label: 'Ocean',
    description: 'Esri ocean chart with bathymetry and maritime reference.',
    attribution: ESRI_OCEAN_ATTRIBUTION,
    external: true,
    theme: null,
  },
  {
    id: 'dark',
    label: 'Dark',
    description: 'CARTO Dark Matter reference map.',
    attribution: CARTO_ATTRIBUTION,
    external: true,
    theme: 'dark',
  },
  {
    id: 'light',
    label: 'Light',
    description: 'CARTO Positron reference map.',
    attribution: CARTO_ATTRIBUTION,
    external: true,
    theme: 'light',
  },
  {
    id: 'offline',
    label: 'Offline',
    description: 'Self-hosted graticule only — no request leaves this origin.',
    attribution: OFFLINE_ATTRIBUTION,
    external: false,
    theme: null,
  },
];

export const DEFAULT_BASEMAP: BasemapId = 'satellite';

export function isBasemapId(value: unknown): value is BasemapId {
  return BASEMAPS.some((basemap) => basemap.id === value);
}

/** Hosts the CSP must allow for `img-src` and `connect-src`. Kept next to the URLs. */
export const BASEMAP_HOSTS = [
  'https://server.arcgisonline.com',
  'https://services.arcgisonline.com',
  'https://*.basemaps.cartocdn.com',
] as const;

/** Source ids owned by the basemap layer set. */
const SOURCE = {
  imagery: 'bm-esri-imagery',
  imageryLabels: 'bm-esri-reference',
  oceanBase: 'bm-esri-ocean',
  oceanRef: 'bm-esri-ocean-ref',
  dark: 'bm-carto-dark',
  light: 'bm-carto-light',
} as const;

/** Style-layer ids per basemap, in draw order. */
const LAYERS: Record<BasemapId, readonly string[]> = {
  satellite: ['bm-esri-imagery'],
  ocean: ['bm-esri-ocean', 'bm-esri-ocean-ref'],
  dark: ['bm-carto-dark'],
  light: ['bm-carto-light'],
  // The offline layers come from public/map-style.json (`ocean`, graticule-*).
  offline: ['ocean', 'graticule-minor', 'graticule-major'],
};

/** The labels overlay belongs to the satellite basemap only. */
export const LABELS_LAYER_ID = 'bm-esri-reference';

/** Every layer id that belongs to a basemap (used to find the insertion point). */
export const ALL_BASEMAP_LAYER_IDS: readonly string[] = [
  ...new Set([...Object.values(LAYERS).flat(), LABELS_LAYER_ID]),
];

/** Source ids whose tile failures mean "imagery is unreachable". */
export const EXTERNAL_SOURCE_IDS: readonly string[] = Object.values(SOURCE);

function raster(
  tiles: string[],
  attribution: string,
  options: { tileSize?: number; maxzoom?: number } = {},
): RasterSourceSpecification {
  return {
    type: 'raster',
    tiles,
    tileSize: options.tileSize ?? 256,
    maxzoom: options.maxzoom ?? 19,
    attribution,
  };
}

const CARTO_SUBDOMAINS = ['a', 'b', 'c', 'd'];
const carto = (style: 'dark_all' | 'light_all') =>
  CARTO_SUBDOMAINS.map((sub) => `https://${sub}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}@2x.png`);

const BASEMAP_SOURCES: Record<string, RasterSourceSpecification> = {
  [SOURCE.imagery]: raster(
    [`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`],
    ESRI_IMAGERY_ATTRIBUTION,
    { maxzoom: 19 },
  ),
  [SOURCE.imageryLabels]: raster(
    [`${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`],
    '',
    { maxzoom: 19 },
  ),
  [SOURCE.oceanBase]: raster(
    [`${ESRI}/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}`],
    ESRI_OCEAN_ATTRIBUTION,
    { maxzoom: 13 },
  ),
  [SOURCE.oceanRef]: raster(
    [`${ESRI}/Ocean/World_Ocean_Reference/MapServer/tile/{z}/{y}/{x}`],
    '',
    { maxzoom: 13 },
  ),
  [SOURCE.dark]: raster(carto('dark_all'), CARTO_ATTRIBUTION, { tileSize: 512, maxzoom: 20 }),
  [SOURCE.light]: raster(carto('light_all'), CARTO_ATTRIBUTION, { tileSize: 512, maxzoom: 20 }),
};

function rasterLayer(id: string, source: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: 'raster',
    source,
    layout: { visibility: 'none' },
    paint: { 'raster-fade-duration': 160, 'raster-resampling': 'linear', ...extra },
  } as LayerSpecification;
}

/**
 * Merge every basemap into the self-hosted offline style. The offline style's
 * own layers (`ocean` background + graticule) stay in place and are simply
 * hidden when an imagery basemap is active.
 */
export function buildCompositeStyle(offline: StyleSpecification): StyleSpecification {
  const sources = { ...offline.sources, ...BASEMAP_SOURCES };
  const offlineLayers = offline.layers ?? [];
  const background = offlineLayers.filter((layer) => layer.type === 'background');
  const rest = offlineLayers.filter((layer) => layer.type !== 'background');
  const basemapLayers: LayerSpecification[] = [
    rasterLayer('bm-esri-imagery', SOURCE.imagery),
    rasterLayer('bm-esri-ocean', SOURCE.oceanBase),
    rasterLayer('bm-esri-ocean-ref', SOURCE.oceanRef),
    rasterLayer('bm-carto-dark', SOURCE.dark),
    rasterLayer('bm-carto-light', SOURCE.light),
    // Labels sit above imagery but below every SPILLTRACE data layer.
    rasterLayer(LABELS_LAYER_ID, SOURCE.imageryLabels, { 'raster-opacity': 0.9 }),
  ];
  return {
    ...offline,
    sources,
    layers: [...background, ...basemapLayers, ...rest],
  };
}

export interface BasemapState {
  basemap: BasemapId;
  labels: boolean;
}

/** Minimal surface of the MapLibre map this module touches (keeps it testable). */
export interface BasemapMap {
  getLayer(id: string): unknown;
  setLayoutProperty(id: string, name: string, value: unknown): unknown;
}

/** Apply a basemap choice by toggling visibility — never by swapping styles. */
export function applyBasemap(map: BasemapMap, state: BasemapState): void {
  const active = new Set<string>(LAYERS[state.basemap]);
  if (state.basemap === 'satellite' && state.labels) active.add(LABELS_LAYER_ID);
  for (const id of ALL_BASEMAP_LAYER_IDS) {
    if (!map.getLayer(id)) continue;
    map.setLayoutProperty(id, 'visibility', active.has(id) ? 'visible' : 'none');
  }
}

export function basemapDefinition(id: BasemapId): BasemapDefinition {
  return BASEMAPS.find((basemap) => basemap.id === id) ?? BASEMAPS[0]!;
}

/** The reference-map flavour that suits the current theme. */
export function referenceBasemapFor(theme: 'dark' | 'light'): BasemapId {
  return theme === 'light' ? 'light' : 'dark';
}
