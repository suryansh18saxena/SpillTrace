'use client';

import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import * as THREE from 'three';
import { easeInOut, gaussian, mulberry32, phase, ramp, scrollStore } from '../timeline';
import type { Palette } from './palette';
import { CURRENT, DIFFUSIVITY, SLICK, WIND, WIND_DRIFT_FACTOR, WIND_DRIFT_SIGMA } from './world';

const VERT = /* glsl */ `
  attribute vec3 aStart; attribute float aAlpha; attribute vec3 aSeed; attribute float aMember;
  uniform float uT; uniform float uTime; uniform float uSize; uniform float uPixelRatio; uniform float uK;
  uniform vec2 uWind; uniform vec2 uCurrent;
  varying float vT; varying float vM;
  void main() {
    float h = uT * 18.0;
    vec2 vel = uCurrent + aAlpha * uWind;
    vec2 disp = -vel * 3.6 * h;
    float sig = sqrt(2.0 * uK * h * 3600.0) / 1000.0;
    vec2 diff = aSeed.xy * sig * aSeed.z;
    vec3 p = aStart + vec3(disp.x, 0.0, disp.y) + vec3(diff.x, 0.0, diff.y);
    p.y = 0.35 + 0.15 * sin(uTime * 1.3 + aSeed.x * 20.0);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uSize * uPixelRatio * (0.8 + 1.6 * uT) * (60.0 / max(-mv.z, 1.0));
    vT = uT; vM = aMember;
  }
`;

const FRAG = /* glsl */ `
  uniform vec3 uColorA; uniform vec3 uColorB; uniform float uOpacity;
  varying float vT; varying float vM;
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    float r = length(c);
    float a = 1.0 - smoothstep(0.15, 0.5, r);
    vec3 col = mix(uColorA, uColorB, smoothstep(0.1, 0.9, vT));
    col *= 0.85 + 0.15 * fract(vM * 0.618);
    gl_FragColor = vec4(col, a * uOpacity);
  }
`;

export interface DriftFieldProps {
  palette: Palette;
  count: number;
  members?: number;
}

/**
 * The reverse-drift ensemble, integrated on the GPU with the run's own model:
 * each particle carries its own wind-drift factor drawn from N(0.03, 0.01),
 * moves against current + α·wind, and spreads by √(2·K·t). Scrolling the
 * BACKTRACK section is scrubbing t from the acquisition back to T−18 h.
 */
export function DriftField({ palette, count, members = 6 }: DriftFieldProps) {
  const material = useRef<THREE.ShaderMaterial>(null);

  const geometry = useMemo(() => {
    const rand = mulberry32(42);
    const start = new Float32Array(count * 3);
    const alpha = new Float32Array(count);
    const seed = new Float32Array(count * 3);
    const member = new Float32Array(count);
    const c = Math.cos(SLICK.rot);
    const s = Math.sin(SLICK.rot);
    for (let i = 0; i < count; i += 1) {
      const r = Math.sqrt(rand());
      const th = rand() * Math.PI * 2;
      const ex = SLICK.a * r * Math.cos(th);
      const ez = SLICK.b * r * Math.sin(th);
      start[i * 3] = SLICK.center[0] + c * ex + s * ez;
      start[i * 3 + 1] = 0;
      start[i * 3 + 2] = SLICK.center[1] - s * ex + c * ez;
      const a = WIND_DRIFT_FACTOR + WIND_DRIFT_SIGMA * gaussian(rand);
      alpha[i] = Math.min(0.08, Math.max(0, a));
      const dir = rand() * Math.PI * 2;
      seed[i * 3] = Math.cos(dir);
      seed[i * 3 + 1] = Math.sin(dir);
      seed[i * 3 + 2] = Math.abs(gaussian(rand));
      member[i] = i % members;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(start.slice(), 3));
    g.setAttribute('aStart', new THREE.BufferAttribute(start, 3));
    g.setAttribute('aAlpha', new THREE.BufferAttribute(alpha, 1));
    g.setAttribute('aSeed', new THREE.BufferAttribute(seed, 3));
    g.setAttribute('aMember', new THREE.BufferAttribute(member, 1));
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(-14, 0, 0), 120);
    return g;
  }, [count, members]);

  const uniforms = useMemo(
    () => ({
      uT: { value: 0 },
      uTime: { value: 0 },
      uSize: { value: 2.6 },
      uPixelRatio: { value: 1 },
      uK: { value: DIFFUSIVITY },
      uWind: { value: new THREE.Vector2(WIND.x, WIND.z) },
      uCurrent: { value: new THREE.Vector2(CURRENT.x, CURRENT.z) },
      uColorA: { value: palette.spill.clone() },
      uColorB: { value: palette.origin.clone() },
      uOpacity: { value: 0 },
    }),
    [palette],
  );

  useFrame((state) => {
    const m = material.current;
    if (!m) return;
    const p = scrollStore.progress;
    const u = m.uniforms;
    u.uTime!.value = state.clock.elapsedTime;
    u.uPixelRatio!.value = state.gl.getPixelRatio();

    const back = phase(p, 'backtrack');
    u.uT!.value = easeInOut(back);
    const fadeIn = ramp(p, 'backtrack', 0.0, 0.12);
    const fadeOut = 1 - ramp(p, 'final', 0.05, 0.5);
    // Particles thin out once the region is drawn, so the contours read clearly.
    const settle = 1 - 0.55 * ramp(p, 'attribution', 0, 0.4);
    u.uOpacity!.value = 0.85 * fadeIn * fadeOut * settle;
  });

  return (
    <points geometry={geometry} frustumCulled={false}>
      <shaderMaterial
        ref={material}
        vertexShader={VERT}
        fragmentShader={FRAG}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}
