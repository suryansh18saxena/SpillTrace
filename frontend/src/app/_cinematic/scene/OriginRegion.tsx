'use client';

import { Line } from '@react-three/drei';
import { useFrame } from '@react-three/fiber';
import { useMemo, useRef, type ComponentRef } from 'react';
import { ramp, scrollStore } from '../timeline';
import type { Palette } from './palette';
import { ORIGIN, ORIGIN_CENTER } from './world';

type LineRef = ComponentRef<typeof Line>;

function ellipse(scale: number, y: number): [number, number, number][] {
  const pts: [number, number, number][] = [];
  const c = Math.cos(ORIGIN.rot);
  const s = Math.sin(ORIGIN.rot);
  for (let i = 0; i <= 96; i += 1) {
    const t = (i / 96) * Math.PI * 2;
    const ex = ORIGIN.a * scale * Math.cos(t);
    const ez = ORIGIN.b * scale * Math.sin(t);
    pts.push([ORIGIN_CENTER.x + c * ex - s * ez, y, ORIGIN_CENTER.z + s * ex + c * ez]);
  }
  return pts;
}

/**
 * The origin probability region as three nested contours (90 / 75 / 50 %).
 * It is a region, never a point (CON-008): nothing in the scene marks a
 * coordinate, and the innermost ring is what remains when the case closes.
 */
export function OriginRegion({ palette }: { palette: Palette }) {
  const refs = useRef<(LineRef | null)[]>([]);
  const rings = useMemo(
    () => ORIGIN.levels.map((level, i) => ({ level, points: ellipse(level, 0.3 + i * 0.05) })),
    [],
  );
  const color = palette.origin.getStyle();

  useFrame((state) => {
    const p = scrollStore.progress;
    const t = state.clock.elapsedTime;
    const drawIn = ramp(p, 'backtrack', 0.72, 0.98);
    const outerOut = 1 - ramp(p, 'final', 0.1, 0.55);
    for (let i = 0; i < rings.length; i += 1) {
      const line = refs.current[i];
      if (!line) continue;
      const stagger = Math.max(0, Math.min(1, (drawIn - i * 0.12) / (1 - i * 0.24)));
      const pulse = 0.85 + 0.15 * Math.sin(t * 1.4 - i * 0.9);
      // The innermost ring is the signal that stays on screen at the end.
      const keep = i === rings.length - 1 ? 1 : outerOut;
      line.material.opacity = (0.85 - i * 0.18) * stagger * pulse * keep;
      line.material.dashOffset = -stagger * 400;
    }
  });

  return (
    <group>
      {rings.map((ring, i) => (
        <Line
          key={ring.level}
          ref={(el) => {
            refs.current[i] = el;
          }}
          points={ring.points}
          color={color}
          lineWidth={i === 2 ? 1.8 : 1.2}
          transparent
          opacity={0}
          dashed
          dashSize={400}
          gapSize={400}
          dashScale={1}
          depthWrite={false}
        />
      ))}
    </group>
  );
}
