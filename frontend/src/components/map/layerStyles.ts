import type { LayerDescriptor } from '@/lib/api/types';
import type { MapLayerKind } from './MapView';

export interface LayerStyle {
  kind: MapLayerKind;
  colorVar: string;
  fallback: string;
  /** Feature property in `[0,1]` that graduates the fill. */
  graduatedBy?: string;
  graduatedInverse?: boolean;
  circleRadius?: number;
  lineWidth?: number;
  /** Default opacity when the analyst has not moved the slider. */
  opacity?: number;
  /** What the legend says this layer means. */
  legend?: string;
}

/**
 * Presentation for the layer ids the API's manifest emits.
 *
 * The map is built from the manifest, not from this table: a layer the backend
 * adds tomorrow still renders, in neutral grey, with its server-provided title.
 * This only decides how the ids we *do* know about should look.
 */
export const LAYER_STYLES: Record<string, LayerStyle> = {
  aoi: {
    kind: 'polygon',
    colorVar: '--map-aoi',
    fallback: '#4f8ff7',
    opacity: 0.9,
    legend: 'The searched area and time window.',
  },
  scene_footprint: {
    kind: 'polygon',
    colorVar: '--map-track',
    fallback: '#7a8798',
    opacity: 0.8,
    legend: 'Ground coverage of the SAR scene the detection came from.',
  },
  oil_probability: {
    kind: 'raster',
    colorVar: '--map-spill',
    fallback: '#f0c04a',
    opacity: 0.7,
    legend: 'Per-pixel oil-likelihood raster, before thresholding.',
  },
  spill: {
    kind: 'polygon',
    colorVar: '--map-spill',
    fallback: '#f0c04a',
    opacity: 1,
    lineWidth: 2,
    legend: 'Oil-like surface feature detected in the SAR scene.',
  },
  origin_region: {
    kind: 'polygon',
    colorVar: '--map-origin',
    fallback: '#a371f7',
    // CON-008: the origin is a probability region, so it is drawn graduated by
    // probability mass and never as one confident outline around a "discharge
    // point". Inverse, so the tight 50 % contour reads stronger than the loose
    // 90 % one and the nesting is legible at a glance.
    graduatedBy: 'probability_mass',
    graduatedInverse: true,
    opacity: 1,
    legend: 'Nested 90 / 75 / 50 % reverse-drift probability contours.',
  },
  drift_particles: {
    kind: 'point',
    colorVar: '--map-origin',
    fallback: '#a371f7',
    circleRadius: 2.5,
    opacity: 0.75,
    legend: 'Back-tracked particles at the selected simulation step.',
  },
  trajectories: {
    kind: 'line',
    colorVar: '--map-track',
    fallback: '#7a8798',
    lineWidth: 1.6,
    opacity: 0.9,
    legend: 'AIS trajectory segments. A break is a reporting gap, not a course change.',
  },
  vessels: {
    kind: 'point',
    colorVar: '--map-vessel',
    fallback: '#5fd3c4',
    circleRadius: 5,
    opacity: 1,
    legend: 'Last known AIS position of each vessel in the window.',
  },
};

const FALLBACK: LayerStyle = {
  kind: 'polygon',
  colorVar: '--color-neutral',
  fallback: '#74849a',
  opacity: 0.9,
};

export function styleForLayer(
  layer: Pick<LayerDescriptor, 'id' | 'type' | 'geometry'>,
): LayerStyle {
  const known = LAYER_STYLES[layer.id];
  if (known) return known;
  const kind: MapLayerKind =
    layer.type === 'raster'
      ? 'raster'
      : layer.geometry === 'line'
        ? 'line'
        : layer.geometry === 'point'
          ? 'point'
          : 'polygon';
  return { ...FALLBACK, kind };
}

/** Layers that carry hover tooltips and click-to-select. */
export const SELECTABLE_LAYERS = new Set([
  'spill',
  'origin_region',
  'vessels',
  'trajectories',
  'scene_footprint',
  'aoi',
]);
