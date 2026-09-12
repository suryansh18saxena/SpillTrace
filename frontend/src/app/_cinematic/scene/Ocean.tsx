'use client';

import { useFrame } from '@react-three/fiber';
import { useMemo, useRef } from 'react';
import * as THREE from 'three';
import { phase, ramp, scrollStore, smoothstep } from '../timeline';
import type { Palette } from './palette';
import { AOI, SLICK } from './world';

const NOISE = /* glsl */ `
  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float vnoise(vec2 p) {
    vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
    float a = hash(i); float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0)); float d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
  }
`;

/** Signed "distance" to the slick: < 1 inside, with a slowly wandering, organic edge. */
const SLICK_FN = /* glsl */ `
  uniform vec2 uSlickCenter; uniform vec2 uSlickAxes; uniform float uSlickRot;
  float slickD(vec2 p) {
    vec2 q = p - uSlickCenter;
    float c = cos(uSlickRot); float s = sin(uSlickRot);
    q = vec2(c * q.x - s * q.y, s * q.x + c * q.y);
    vec2 e = q / uSlickAxes;
    float d = dot(e, e);
    d += 0.38 * (vnoise(p * 0.09 + uTime * 0.012) - 0.5);
    d += 0.14 * (vnoise(p * 0.36 - uTime * 0.02) - 0.5);
    return d;
  }
`;

const VERT = /* glsl */ `
  uniform float uTime; uniform float uSlick; uniform float uWaveScale;
  varying vec3 vWorld; varying vec3 vNormal;
  ${NOISE}
  ${SLICK_FN}
  float waveH(vec2 p, float damp) {
    float h = 0.0;
    h += 0.42 * sin(dot(p, vec2(0.70, 0.30)) * 0.55 + uTime * 1.10);
    h += 0.26 * sin(dot(p, vec2(-0.35, 0.80)) * 0.95 + uTime * 1.55);
    h += 0.14 * sin(dot(p, vec2(0.90, -0.60)) * 1.70 + uTime * 2.10);
    h += 0.08 * sin(dot(p, vec2(-0.75, -0.45)) * 3.10 + uTime * 2.70);
    h += 0.06 * (vnoise(p * 0.6 + uTime * 0.3) - 0.5);
    return h * uWaveScale * damp;
  }
  void main() {
    vec3 wp = (modelMatrix * vec4(position, 1.0)).xyz;
    vec2 p = wp.xz;
    float d = slickD(p);
    float mask = 1.0 - smoothstep(0.80, 1.10, d);
    float damp = 1.0 - 0.88 * mask * uSlick;
    float h = waveH(p, damp);
    float e = 0.35;
    float hx = waveH(p + vec2(e, 0.0), damp);
    float hz = waveH(p + vec2(0.0, e), damp);
    vec3 n = normalize(vec3(-(hx - h) / e, 1.0, -(hz - h) / e));
    wp.y += h;
    vWorld = wp; vNormal = n;
    gl_Position = projectionMatrix * viewMatrix * vec4(wp, 1.0);
  }
`;

const FRAG = /* glsl */ `
  uniform vec3 uDeep; uniform vec3 uShallow; uniform vec3 uHorizon; uniform vec3 uSpill;
  uniform vec3 uAccent; uniform vec3 uFog; uniform vec3 uSunDir; uniform vec3 uCamPos;
  uniform float uTime; uniform float uSlick; uniform float uSar; uniform float uProb;
  uniform float uSeg; uniform float uBoundary; uniform float uScanX; uniform float uScan;
  uniform float uFogDensity; uniform vec4 uAoi; uniform float uSpecScale;
  varying vec3 vWorld; varying vec3 vNormal;
  ${NOISE}
  ${SLICK_FN}
  void main() {
    // The slick mask is evaluated per pixel here, not per vertex: the mesh is
    // coarser than the slick's minor axis, so a vertex mask reads as a staircase.
    float d = slickD(vWorld.xz);
    float mask = 1.0 - smoothstep(0.80, 1.10, d);

    vec3 V = normalize(uCamPos - vWorld);
    vec3 N = normalize(vNormal);
    float fres = pow(1.0 - max(dot(N, V), 0.0), 3.0);
    vec3 base = mix(uDeep, uShallow, 0.35 + 0.4 * N.y * N.y);
    base = mix(base, uHorizon, fres * 0.55);

    vec3 H = normalize(normalize(uSunDir) + V);
    float ndh = max(dot(N, H), 0.0);
    float spec = (pow(ndh, 160.0) * 1.4 + pow(ndh, 24.0) * 0.12) * uSpecScale;
    float sparkle = step(0.985, vnoise(vWorld.xz * 9.0 + uTime * 2.0)) * 0.35 * uSpecScale;
    float damp = 1.0 - 0.9 * mask * uSlick;
    vec3 col = base + (spec + sparkle) * damp * vec3(0.85, 0.93, 1.0);
    col = mix(col, col * 0.55, mask * uSlick * 0.9);

    // Radar look: speckle, oil is the dark damped region, faint graticule.
    float spk = vnoise(vWorld.xz * 14.0) * 0.55 + vnoise(vWorld.xz * 41.0) * 0.45;
    spk = pow(spk, 1.4);
    float sarV = mix(0.55, 0.10, mask) * spk * 1.6 + 0.04;
    vec3 sar = vec3(sarV) * vec3(0.92, 0.96, 1.0);
    vec2 g = abs(fract(vWorld.xz / 10.0) - 0.5);
    float grid = 1.0 - smoothstep(0.0, 0.03, min(g.x, g.y));
    sar += grid * 0.06;
    col = mix(col, sar, uSar);

    // Per-pixel oil probability, as the model would draw it.
    float prob = clamp(mask * 1.15 - 0.05 * vnoise(vWorld.xz * 3.0), 0.0, 1.0);
    vec3 heat = mix(vec3(0.06, 0.10, 0.24), uSpill, prob);
    heat = mix(heat, vec3(1.0, 0.96, 0.80), pow(prob, 6.0));
    col = mix(col, mix(col, heat, 0.85), uProb * step(0.02, prob));

    // Segmentation outline.
    float edge = 1.0 - smoothstep(0.0, 0.14, abs(d - 0.95));
    float glow = 1.0 - smoothstep(0.0, 0.45, abs(d - 0.95));
    col += uSeg * (edge * uSpill * 1.6 + glow * uSpill * 0.25) + uSeg * mask * uSpill * 0.10;

    // Scan sweep across the surface.
    float sd = vWorld.x - uScanX;
    float line = 1.0 - smoothstep(0.0, 0.9, abs(sd));
    float trail = (1.0 - smoothstep(0.0, 18.0, -sd)) * step(sd, 0.0);
    col += uScan * (line * uAccent * 2.2 + trail * uAccent * 0.10);

    // Area-of-interest boundary.
    float bx = min(abs(vWorld.x - uAoi.x), abs(vWorld.x - uAoi.z));
    float bz = min(abs(vWorld.z - uAoi.y), abs(vWorld.z - uAoi.w));
    float inside = step(uAoi.x, vWorld.x) * step(vWorld.x, uAoi.z) * step(uAoi.y, vWorld.z) * step(vWorld.z, uAoi.w);
    float bl = (1.0 - smoothstep(0.0, 0.5, min(bx, bz))) * inside;
    col += uBoundary * bl * uAccent * 1.8;

    float dist = length(uCamPos - vWorld);
    float f = 1.0 - exp(-uFogDensity * uFogDensity * dist * dist);
    col = mix(col, uFog, clamp(f, 0.0, 1.0));
    gl_FragColor = vec4(col, 1.0);
  }
`;

export interface OceanProps {
  palette: Palette;
  segments: number;
}

/**
 * The ocean surface and, on it, everything the pipeline sees: the damped slick,
 * the radar rendering, the probability field, the segmentation outline, the
 * scan sweep and the AOI boundary — all blended by scroll progress.
 */
export function Ocean({ palette, segments }: OceanProps) {
  const material = useRef<THREE.ShaderMaterial>(null);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uSlick: { value: 0 },
      uWaveScale: { value: 1 },
      uSlickCenter: { value: new THREE.Vector2(SLICK.center[0], SLICK.center[1]) },
      uSlickAxes: { value: new THREE.Vector2(SLICK.a, SLICK.b) },
      uSlickRot: { value: SLICK.rot },
      uDeep: { value: palette.oceanDeep.clone() },
      uShallow: { value: palette.ocean.clone().lerp(palette.horizon, 0.18) },
      uHorizon: { value: palette.horizon.clone() },
      uSpill: { value: palette.spill.clone() },
      uAccent: { value: palette.accent.clone() },
      uFog: { value: palette.bg.clone() },
      uSunDir: { value: new THREE.Vector3(-0.35, 0.22, -1).normalize() },
      uCamPos: { value: new THREE.Vector3() },
      uSar: { value: 0 },
      uProb: { value: 0 },
      uSeg: { value: 0 },
      uBoundary: { value: 0 },
      uScanX: { value: AOI.minX - 20 },
      uScan: { value: 0 },
      uFogDensity: { value: 0.0045 },
      uSpecScale: { value: 1 },
      uAoi: { value: new THREE.Vector4(AOI.minX, AOI.minZ, AOI.maxX, AOI.maxZ) },
    }),
    [palette],
  );

  useFrame((state) => {
    const m = material.current;
    if (!m) return;
    const p = scrollStore.progress;
    const u = m.uniforms;
    u.uTime!.value = state.clock.elapsedTime;
    u.uCamPos!.value.copy(state.camera.position);
    // Glints read as texture up close and as glare from altitude; fade them with height.
    u.uSpecScale!.value = 1 - 0.72 * smoothstep(45, 130, state.camera.position.y);

    // The slick surfaces as the camera rises, and sinks back into the dark at the end.
    const slickIn = ramp(p, 'hero', 0.3, 0.72);
    const slickOut = 1 - ramp(p, 'final', 0.25, 0.8);
    u.uSlick!.value = slickIn * slickOut;

    // Satellite pass: one sweep across the AOI, then the radar rendering holds.
    const scanT = ramp(p, 'detect', 0.04, 0.62);
    u.uScanX!.value = AOI.minX - 10 + (AOI.maxX - AOI.minX + 20) * scanT;
    u.uScan!.value = smoothstep(0, 0.08, scanT) * (1 - smoothstep(0.92, 1, scanT));
    const sarIn = ramp(p, 'detect', 0.5, 0.92);
    const sarOut = 1 - ramp(p, 'segment', 0.55, 0.9);
    u.uSar!.value = sarIn * sarOut;

    // Probability field, then the outline that survives the rest of the story.
    const probIn = ramp(p, 'segment', 0.12, 0.42);
    const probOut = 1 - ramp(p, 'segment', 0.62, 0.9);
    u.uProb!.value = probIn * probOut;
    const segIn = ramp(p, 'segment', 0.55, 0.9);
    u.uSeg!.value = segIn * slickOut;

    const boundaryIn = ramp(p, 'hero', 0.78, 0.98);
    const boundaryOut = 1 - ramp(p, 'final', 0.1, 0.5);
    u.uBoundary!.value = boundaryIn * boundaryOut * (1 - 0.5 * u.uSar!.value);

    // Calmer water while the radar frame holds, thicker air as the case closes.
    u.uWaveScale!.value = 1 - 0.55 * u.uSar!.value;
    u.uFogDensity!.value = 0.0045 + 0.009 * phase(p, 'final');
  });

  return (
    <mesh rotation-x={-Math.PI / 2} position={[0, 0, 0]} frustumCulled={false}>
      <planeGeometry args={[620, 620, segments, segments]} />
      <shaderMaterial
        ref={material}
        vertexShader={VERT}
        fragmentShader={FRAG}
        uniforms={uniforms}
      />
    </mesh>
  );
}
