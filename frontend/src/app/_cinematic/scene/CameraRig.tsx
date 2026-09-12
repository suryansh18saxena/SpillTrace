'use client';

import { useFrame, useThree } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import * as THREE from 'three';
import { lerp, scrollStore, sectionRange, smoothstep, type SectionId } from '../timeline';
import { ORIGIN_CENTER } from './world';

interface Key {
  at: number;
  pos: [number, number, number];
  look: [number, number, number];
  fov: number;
}

const O = ORIGIN_CENTER;

/** A moment within a section, as absolute progress. */
function at(id: SectionId, local: number): number {
  const [a, b] = sectionRange(id);
  return a + (b - a) * local;
}

/**
 * One continuous camera move for the whole page. The rig starts a metre and a
 * half above the waves, rises to see the slick, looks straight down for the
 * radar frame, pulls up for the traffic, follows the oil back to its origin,
 * settles on the candidates and finally draws away until only the signal is
 * left.
 */
function buildKeys(): Key[] {
  return [
    { at: at('hero', 0), pos: [-6, 1.6, 16], look: [8, 1.2, -34], fov: 40 },
    { at: at('hero', 0.5), pos: [-10, 9, 24], look: [0, 0.4, -6], fov: 40 },
    { at: at('hero', 1), pos: [-14, 20, 30], look: [0, 0, 0], fov: 41 },
    { at: at('detect', 0.5), pos: [2, 52, 26], look: [0, 0, -2], fov: 42 },
    { at: at('detect', 1), pos: [6, 44, 20], look: [0, 0, 0], fov: 42 },
    { at: at('segment', 0.5), pos: [10, 30, 14], look: [0, 0, 0], fov: 42 },
    { at: at('segment', 1), pos: [12, 34, 18], look: [0, 0, 0], fov: 43 },
    { at: at('match', 0.5), pos: [0, 125, 70], look: [0, 0, -12], fov: 48 },
    { at: at('match', 1), pos: [-10, 108, 58], look: [-8, 0, -6], fov: 48 },
    { at: at('backtrack', 0.05), pos: [6, 40, 30], look: [0, 0, 0], fov: 44 },
    { at: at('backtrack', 0.5), pos: [-12, 30, 22], look: [-14, 0, 0], fov: 44 },
    { at: at('backtrack', 1), pos: [O.x - 6, 34, O.z + 28], look: [O.x, 0, O.z], fov: 44 },
    { at: at('attribution', 0.5), pos: [O.x - 4, 62, O.z + 44], look: [O.x + 4, 0, O.z], fov: 46 },
    { at: at('attribution', 1), pos: [O.x - 10, 50, O.z + 34], look: [O.x, 0, O.z], fov: 46 },
    { at: at('explain', 0.5), pos: [O.x - 20, 42, O.z + 26], look: [O.x, 0, O.z], fov: 45 },
    { at: at('explain', 1), pos: [O.x - 26, 48, O.z + 34], look: [O.x, 0, O.z], fov: 45 },
    { at: at('final', 0.5), pos: [-60, 150, 120], look: [-10, 0, 0], fov: 44 },
    { at: at('final', 1), pos: [-80, 230, 190], look: [-10, 0, 0], fov: 44 },
  ];
}

export function CameraRig() {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const keys = useMemo(buildKeys, []);
  const pos = useRef(new THREE.Vector3(...keys[0]!.pos));
  const look = useRef(new THREE.Vector3(...keys[0]!.look));
  const target = useRef(new THREE.Vector3());
  const eye = useRef(new THREE.Vector3());

  useFrame((state, delta) => {
    const p = scrollStore.progress;
    const t = state.clock.elapsedTime;

    let i = 0;
    while (i < keys.length - 2 && p > keys[i + 1]!.at) i += 1;
    const a = keys[i]!;
    const b = keys[i + 1]!;
    const s = smoothstep(a.at, b.at, p);

    eye.current.set(
      lerp(a.pos[0], b.pos[0], s),
      lerp(a.pos[1], b.pos[1], s),
      lerp(a.pos[2], b.pos[2], s),
    );
    target.current.set(
      lerp(a.look[0], b.look[0], s),
      lerp(a.look[1], b.look[1], s),
      lerp(a.look[2], b.look[2], s),
    );

    // A little sway close to the water, and the pointer nudging the gaze.
    const low = 1 - smoothstep(4, 30, eye.current.y);
    eye.current.x += Math.sin(t * 0.35) * 0.6 * low;
    eye.current.y += Math.sin(t * 0.27) * 0.25 * low;
    target.current.x += scrollStore.pointerX * (2 + 6 * (1 - low));
    target.current.y += scrollStore.pointerY * 1.5;

    const k = 1 - Math.exp(-delta * 6);
    pos.current.lerp(eye.current, k);
    look.current.lerp(target.current, k);
    camera.position.copy(pos.current);
    camera.lookAt(look.current);
    const fov = lerp(a.fov, b.fov, s);
    if (Math.abs(camera.fov - fov) > 0.01) {
      camera.fov = fov;
      camera.updateProjectionMatrix();
    }
  });

  return null;
}
