'use client';

import { Html, Line } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { useMemo, useRef, type ComponentRef } from 'react';
import * as THREE from 'three';
import { VESSELS, type VesselRecord } from '../content';
import { easeInOut, lerp, phase, ramp, scrollStore, smoothstep } from '../timeline';
import type { Palette } from './palette';
import {
  ambientTracks,
  DRIFT_HOURS,
  pathPositionAt,
  samplePath,
  VESSEL_PATHS,
  type VesselPath,
} from './world';
import styles from '../cinematic.module.css';

type LineRef = ComponentRef<typeof Line>;

interface VesselVisual {
  record: VesselRecord;
  path: VesselPath;
  segments: [number, number, number][][];
  length: number;
}

function bandColor(palette: Palette, record: VesselRecord): THREE.Color {
  if (record.band === 'HIGH') return record.rank === 1 ? palette.confidence3 : palette.confidence2;
  if (record.band === 'MODERATE') return palette.confidence1;
  return palette.track;
}

function trackLength(points: [number, number, number][]): number {
  let d = 0;
  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1]!;
    const b = points[i]!;
    d += Math.hypot(b[0] - a[0], b[2] - a[2]);
  }
  return d;
}

/** Splits a path into the drawn segments between its reporting gaps. */
function segmentsFor(path: VesselPath): [number, number, number][][] {
  const cuts: [number, number][] = [];
  let from = 0;
  for (const [a, b] of path.gaps ?? []) {
    cuts.push([from, a]);
    from = b;
  }
  cuts.push([from, 1]);
  return cuts.map(([a, b]) => samplePath(path, 40, a, b));
}

export interface VesselsProps {
  palette: Palette;
  ambientCount: number;
}

/**
 * Six seeded vessels and their AIS tracks, plus faint ambient traffic.
 *
 * MATCH draws the tracks in and sails the ships along them; BACKTRACK scrubs
 * every ship to where it was at T−h while the oil drifts back; ATTRIBUTION
 * holds each candidate at its closest approach, dims the two excluded
 * vessels, colours the rest by evidence band and rings the top candidate.
 */
export function Vessels({ palette, ambientCount }: VesselsProps) {
  const vessels = useMemo<VesselVisual[]>(
    () =>
      VESSEL_PATHS.map((path) => {
        const record = VESSELS.find((v) => v.key === path.key)!;
        const segments = segmentsFor(path);
        return { record, path, segments, length: trackLength(samplePath(path, 40)) };
      }),
    [],
  );
  const ambient = useMemo(() => ambientTracks(ambientCount), [ambientCount]);

  const trackRefs = useRef<(LineRef | null)[]>([]);
  const ambientRefs = useRef<(LineRef | null)[]>([]);
  const shipRefs = useRef<(THREE.Group | null)[]>([]);
  const haloRefs = useRef<(THREE.Mesh | null)[]>([]);
  const ringRef = useRef<LineRef>(null);
  const labelRefs = useRef<(HTMLDivElement | null)[]>([]);

  const ring = useMemo(() => {
    const pts: [number, number, number][] = [];
    for (let i = 0; i <= 64; i += 1) {
      const t = (i / 64) * Math.PI * 2;
      pts.push([Math.cos(t) * 4.2, 0.6, Math.sin(t) * 4.2]);
    }
    return pts;
  }, []);

  useFrame((state) => {
    const p = scrollStore.progress;
    const t = state.clock.elapsedTime;
    const match = phase(p, 'match');
    const back = easeInOut(phase(p, 'backtrack'));
    const attr = phase(p, 'attribution');
    const finalOut = 1 - ramp(p, 'final', 0.05, 0.45);
    const inMatch = p >= 0 && phase(p, 'match') > 0;

    const tracksIn = ramp(p, 'match', 0.04, 0.7);
    const ambientIn = ramp(p, 'match', 0.02, 0.5) * (1 - ramp(p, 'backtrack', 0.0, 0.35));

    for (let i = 0; i < ambient.length; i += 1) {
      const line = ambientRefs.current[i];
      if (!line) continue;
      line.material.opacity = 0.16 * ambientIn * finalOut;
    }

    let segIndex = 0;
    for (let i = 0; i < vessels.length; i += 1) {
      const v = vessels[i]!;
      const excluded = v.record.rank === null;
      const stagger = smoothstep(i * 0.08, 0.55 + i * 0.08, tracksIn);

      // Where along its track the ship is drawn.
      let u: number;
      if (attr > 0) {
        u = lerp(1 - back, v.path.holdAt, smoothstep(0, 0.3, attr));
      } else if (back > 0) {
        u = 1 - back;
      } else {
        u = lerp(0.1, 1, smoothstep(0, 1, match));
      }
      const [x, z] = pathPositionAt(v.path, u);

      // Track opacity: draw in, then dim the excluded and the also-rans.
      const excludedDim = excluded ? 1 - 0.85 * smoothstep(0.05, 0.35, attr) : 1;
      const rankDim =
        !excluded && v.record.rank !== 1 ? 1 - 0.45 * smoothstep(0.65, 0.95, attr) : 1;
      const trackAlpha = 0.85 * stagger * excludedDim * rankDim * finalOut;
      for (let s = 0; s < v.segments.length; s += 1) {
        const line = trackRefs.current[segIndex];
        segIndex += 1;
        if (!line) continue;
        line.material.opacity = trackAlpha;
        line.material.dashOffset = -stagger * v.length;
        // Colour shifts from vessel teal to its evidence band during attribution.
        const band = bandColor(palette, v.record);
        line.material.color.copy(palette.vessel).lerp(band, smoothstep(0.35, 0.7, attr));
      }

      const ship = shipRefs.current[i];
      if (ship) {
        ship.position.set(x, 0.45, z);
        const [nx, nz] = pathPositionAt(v.path, u + 0.01);
        ship.rotation.y = Math.atan2(-(nz - z), nx - x);
        const scale = stagger * (excluded ? 1 - 0.7 * smoothstep(0.05, 0.35, attr) : 1) * finalOut;
        ship.scale.setScalar(Math.max(0.0001, scale));
        ship.visible = scale > 0.001 && (inMatch || back > 0 || attr > 0);
      }
      const halo = haloRefs.current[i];
      if (halo) {
        const mat = halo.material as THREE.MeshBasicMaterial;
        const band = bandColor(palette, v.record);
        mat.color.copy(palette.vessel).lerp(band, smoothstep(0.35, 0.7, attr));
        mat.opacity = 0.55 * (0.8 + 0.2 * Math.sin(t * 2.2 + i));
      }

      const label = labelRefs.current[i];
      if (label) {
        // Labels step back while the drift plays (the particles are the subject),
        // return for attribution, and leave before the closing frame.
        const backDim = 1 - 0.5 * smoothstep(0, 0.2, back) * (1 - smoothstep(0, 0.2, attr));
        const labelOut = 1 - ramp(p, 'final', 0, 0.25);
        const show =
          smoothstep(0.55, 0.85, match) * (excluded ? excludedDim : 1) * backDim * labelOut;
        label.style.opacity = show.toFixed(3);
        label.dataset.state = excluded && attr > 0.35 ? 'excluded' : attr > 0.7 ? 'scored' : 'live';
        const timeEl = label.querySelector<HTMLElement>('[data-time]');
        if (timeEl) {
          const hours = back > 0 && attr === 0 ? back * DRIFT_HOURS : 0;
          timeEl.textContent = hours > 0 ? `T−${hours.toFixed(1)} h` : 'T−0 · acquisition';
        }
      }
    }

    const ringLine = ringRef.current;
    if (ringLine) {
      const winner = vessels[0]!;
      const [wx, wz] = pathPositionAt(winner.path, winner.path.holdAt);
      ringLine.position.set(wx, 0, wz);
      const s = 1 + 0.12 * Math.sin(t * 2.4);
      ringLine.scale.set(s, 1, s);
      ringLine.material.opacity = 0.9 * smoothstep(0.7, 0.95, attr) * finalOut;
    }
  });

  return (
    <group>
      {ambient.map((points, i) => (
        <Line
          key={`ambient-${i}`}
          ref={(el) => {
            ambientRefs.current[i] = el;
          }}
          points={points}
          color={palette.track.getStyle()}
          lineWidth={0.8}
          transparent
          opacity={0}
          depthWrite={false}
        />
      ))}

      {vessels.flatMap((v) =>
        v.segments.map((points, s) => (
          <Line
            key={`${v.record.key}-${s}`}
            ref={(el) => {
              trackRefs.current.push(el);
            }}
            points={points}
            color={palette.vessel.getStyle()}
            lineWidth={v.record.rank ? 1.6 : 1.1}
            transparent
            opacity={0}
            dashed
            dashSize={v.length}
            gapSize={v.length}
            dashScale={1}
            depthWrite={false}
          />
        )),
      )}

      {vessels.map((v, i) => {
        const size = 1.2 + (v.record.lengthM / 250) * 1.6;
        return (
          <group
            key={v.record.key}
            ref={(el) => {
              shipRefs.current[i] = el;
            }}
            visible={false}
          >
            <mesh position={[0, 0, 0]}>
              <boxGeometry args={[size, 0.28, size * 0.28]} />
              <meshStandardMaterial
                color={palette.vessel}
                emissive={palette.vessel}
                emissiveIntensity={1.6}
                roughness={0.4}
              />
            </mesh>
            <mesh
              ref={(el) => {
                haloRefs.current[i] = el;
              }}
              rotation-x={-Math.PI / 2}
              position={[0, -0.2, 0]}
            >
              <ringGeometry args={[size * 0.7, size * 1.25, 32]} />
              <meshBasicMaterial
                color={palette.vessel}
                transparent
                opacity={0.5}
                depthWrite={false}
                blending={THREE.AdditiveBlending}
              />
            </mesh>
            <Html
              position={[0, 1.6, 0]}
              center
              zIndexRange={[5, 0]}
              style={{ pointerEvents: 'none' }}
              wrapperClass={styles.htmlWrap}
            >
              <div
                ref={(el) => {
                  labelRefs.current[i] = el;
                }}
                className={styles.vesselLabel}
                data-state="live"
                style={{ opacity: 0 }}
              >
                <span className={styles.vesselName}>
                  {v.record.name.replace(' (SYNTHETIC)', '')}
                </span>
                <span className={styles.vesselMeta}>
                  MMSI {v.record.mmsi} · {v.record.type}
                </span>
                <span className={styles.vesselMeta} data-time>
                  T−0 · acquisition
                </span>
                {v.record.rank ? (
                  <span className={styles.vesselScore} data-band={v.record.band ?? ''}>
                    #{v.record.rank} · {v.record.score?.toFixed(3)} · {v.record.band}
                  </span>
                ) : (
                  <span className={styles.vesselScore} data-band="EXCLUDED">
                    EXCLUDED
                  </span>
                )}
              </div>
            </Html>
          </group>
        );
      })}

      <Line
        ref={ringRef}
        points={ring}
        color={palette.confidence3.getStyle()}
        lineWidth={1.6}
        transparent
        opacity={0}
        depthWrite={false}
      />
    </group>
  );
}
