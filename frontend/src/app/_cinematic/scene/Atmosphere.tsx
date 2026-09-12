'use client';

import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import * as THREE from 'three';
import { mulberry32, phase, scrollStore } from '../timeline';
import type { Palette } from './palette';

function glowTexture(): THREE.CanvasTexture {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d')!;
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(255,255,255,0.9)');
  g.addColorStop(0.25, 'rgba(255,255,255,0.35)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/** Sea spray and dust in the air, and the low light on the horizon. */
export function Atmosphere({ palette, dust }: { palette: Palette; dust: number }) {
  const points = useRef<THREE.Points>(null);
  const horizon = useRef<THREE.Sprite>(null);
  const texture = useMemo(() => glowTexture(), []);

  const geometry = useMemo(() => {
    const rand = mulberry32(11);
    const arr = new Float32Array(dust * 3);
    for (let i = 0; i < dust; i += 1) {
      arr[i * 3] = (rand() - 0.5) * 260;
      arr[i * 3 + 1] = rand() * 60 + 0.5;
      arr[i * 3 + 2] = (rand() - 0.5) * 260;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(arr, 3));
    return g;
  }, [dust]);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (points.current) {
      points.current.rotation.y = t * 0.008;
      points.current.position.y = Math.sin(t * 0.2) * 0.6;
    }
    if (horizon.current) {
      const mat = horizon.current.material;
      const fade = 1 - 0.7 * phase(scrollStore.progress, 'final');
      mat.opacity = 0.22 * fade;
    }
  });

  return (
    <group>
      <points ref={points} geometry={geometry} frustumCulled={false}>
        <pointsMaterial
          color={palette.horizon}
          size={0.35}
          sizeAttenuation
          transparent
          opacity={0.35}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </points>
      <sprite ref={horizon} position={[-60, 10, -200]} scale={[260, 120, 1]}>
        <spriteMaterial
          map={texture}
          color={palette.horizon}
          transparent
          opacity={0.22}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </sprite>
    </group>
  );
}
