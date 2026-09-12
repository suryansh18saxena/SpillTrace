'use client';

import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import * as THREE from 'three';
import { ramp, scrollStore, smoothstep } from '../timeline';
import type { Palette } from './palette';
import { AOI } from './world';

const CURTAIN_VERT = /* glsl */ `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`;
const CURTAIN_FRAG = /* glsl */ `
  uniform vec3 uColor; uniform float uOpacity;
  varying vec2 vUv;
  void main() {
    float band = 1.0 - smoothstep(0.0, 0.5, abs(vUv.x - 0.5));
    float fall = pow(1.0 - vUv.y, 1.6);
    gl_FragColor = vec4(uColor, band * fall * uOpacity);
  }
`;

const ALTITUDE = 74;

/**
 * The satellite pass: a small bright body crossing the AOI with a scan
 * curtain falling to the surface, in step with the sweep the ocean draws.
 */
export function Satellite({ palette }: { palette: Palette }) {
  const group = useRef<THREE.Group>(null);
  const body = useRef<THREE.Mesh>(null);
  const curtain = useRef<THREE.ShaderMaterial>(null);

  const uniforms = useMemo(
    () => ({ uColor: { value: palette.accent2.clone() }, uOpacity: { value: 0 } }),
    [palette],
  );

  useFrame((state) => {
    const g = group.current;
    if (!g) return;
    const p = scrollStore.progress;
    const scanT = ramp(p, 'detect', 0.04, 0.62);
    const alive = smoothstep(0, 0.06, scanT) * (1 - smoothstep(0.94, 1, scanT));
    const x = AOI.minX - 10 + (AOI.maxX - AOI.minX + 20) * scanT;
    g.position.set(x, ALTITUDE, -8);
    g.visible = alive > 0.001;
    if (curtain.current) curtain.current.uniforms.uOpacity!.value = 0.28 * alive;
    if (body.current) {
      const s = 1 + 0.25 * Math.sin(state.clock.elapsedTime * 6);
      body.current.scale.setScalar(s * alive);
    }
  });

  return (
    <group ref={group} visible={false}>
      <mesh ref={body}>
        <sphereGeometry args={[0.9, 12, 12]} />
        <meshBasicMaterial color={palette.text} />
      </mesh>
      <mesh position={[0, -ALTITUDE / 2, 0]}>
        <planeGeometry args={[2.2, ALTITUDE, 1, 1]} />
        <shaderMaterial
          ref={curtain}
          vertexShader={CURTAIN_VERT}
          fragmentShader={CURTAIN_FRAG}
          uniforms={uniforms}
          transparent
          depthWrite={false}
          side={THREE.DoubleSide}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
      <mesh position={[0, -ALTITUDE / 2, 0]} rotation-y={Math.PI / 2}>
        <planeGeometry args={[2.2, ALTITUDE, 1, 1]} />
        <shaderMaterial
          vertexShader={CURTAIN_VERT}
          fragmentShader={CURTAIN_FRAG}
          uniforms={uniforms}
          transparent
          depthWrite={false}
          side={THREE.DoubleSide}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
    </group>
  );
}
