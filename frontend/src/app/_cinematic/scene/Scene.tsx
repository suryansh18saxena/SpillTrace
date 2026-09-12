'use client';

import { AdaptiveDpr, PerformanceMonitor } from '@react-three/drei';
import { Canvas } from '@react-three/fiber';
import { useEffect, useMemo, useState } from 'react';
import * as THREE from 'three';
import { scrollStore } from '../timeline';
import { Atmosphere } from './Atmosphere';
import { CameraRig } from './CameraRig';
import { DriftField } from './DriftField';
import { Ocean } from './Ocean';
import { OriginRegion } from './OriginRegion';
import { readPalette } from './palette';
import { detectTier, QUALITY, type Tier } from './quality';
import { Satellite } from './Satellite';
import { Vessels } from './Vessels';

/**
 * The WebGL layer behind the story. Loaded only on the client, after the
 * server-rendered copy is already on screen; steps its own quality down if the
 * frame rate says so; and never blocks the page from being readable without it.
 */
export default function Scene() {
  const [tier, setTier] = useState<Tier>('low');
  const palette = useMemo(readPalette, []);

  useEffect(() => {
    setTier(detectTier());
    const onMove = (e: PointerEvent) => {
      scrollStore.pointerX = (e.clientX / window.innerWidth - 0.5) * 2;
      scrollStore.pointerY = -(e.clientY / window.innerHeight - 0.5) * 2;
    };
    window.addEventListener('pointermove', onMove, { passive: true });
    return () => window.removeEventListener('pointermove', onMove);
  }, []);

  const q = QUALITY[tier];

  return (
    <Canvas
      dpr={[1, q.maxDpr]}
      camera={{ fov: 40, near: 0.3, far: 900, position: [-6, 1.6, 16] }}
      gl={{ antialias: false, powerPreference: 'high-performance', alpha: false, stencil: false }}
      onCreated={({ gl, scene }) => {
        gl.setClearColor(palette.bg);
        gl.toneMapping = THREE.ACESFilmicToneMapping;
        gl.toneMappingExposure = 1.05;
        scene.fog = new THREE.FogExp2(palette.bg.getHex(), 0.0028);
      }}
    >
      <PerformanceMonitor onDecline={() => setTier('low')} flipflops={2} />
      <AdaptiveDpr pixelated />
      <ambientLight intensity={0.35} />
      <directionalLight position={[-40, 60, -80]} intensity={0.9} color={palette.horizon} />
      <CameraRig />
      <Ocean palette={palette} segments={q.oceanSegments} />
      <Satellite palette={palette} />
      <DriftField palette={palette} count={q.particles} />
      <OriginRegion palette={palette} />
      <Vessels palette={palette} ambientCount={q.ambientTracks} />
      <Atmosphere palette={palette} dust={q.dust} />
    </Canvas>
  );
}
