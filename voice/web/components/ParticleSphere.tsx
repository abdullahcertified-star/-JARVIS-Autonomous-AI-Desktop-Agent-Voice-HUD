"use client";

import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { EffectComposer, Bloom } from "@react-three/postprocessing";
import * as THREE from "three";
import { useJarvisStore } from "@/lib/store";

const CORE_RADIUS = 0.9;
const SHELL_RADIUS = 2.1;
const PARTICLE_COUNT = 1400;
const SPIKE_COUNT = 22;

type Tuning = {
  color: THREE.Color;
  spinSpeed: number;
  pulse: number;
  brightness: number;
};

function tuningFor(state: string, level: number): Tuning {
  switch (state) {
    case "booting":
      return { color: new THREE.Color("#5fd6ff"), spinSpeed: 0.06, pulse: 0.4, brightness: 0.5 };
    case "listening":
      return {
        color: new THREE.Color("#ffb347"),
        spinSpeed: 0.25 + level * 0.6,
        pulse: 0.6 + level * 1.2,
        brightness: 1 + level * 0.8,
      };
    case "thinking":
      return { color: new THREE.Color("#ff8c1a"), spinSpeed: 1.1, pulse: 0.9, brightness: 1.1 };
    case "speaking":
      return { color: new THREE.Color("#ffc266"), spinSpeed: 0.35, pulse: 1.6, brightness: 1.3 };
    case "error":
      return { color: new THREE.Color("#ff3b3b"), spinSpeed: 0.15, pulse: 0.5, brightness: 0.9 };
    default:
      return { color: new THREE.Color("#ff9d2e"), spinSpeed: 0.12, pulse: 0.35, brightness: 0.75 };
  }
}

function Core() {
  const meshRef = useRef<THREE.Mesh>(null);
  const state = useJarvisStore((s) => s.state);
  const level = useJarvisStore((s) => s.level);
  const t = useRef(0);

  useFrame((_, delta) => {
    t.current += delta;
    const tuning = tuningFor(state, level);
    if (meshRef.current) {
      const scale = 1 + Math.sin(t.current * tuning.pulse * 3) * 0.06 * tuning.brightness;
      meshRef.current.scale.setScalar(scale);
      const mat = meshRef.current.material as THREE.MeshBasicMaterial;
      mat.color.lerp(tuning.color, 0.08);
    }
  });

  return (
    <mesh ref={meshRef}>
      <sphereGeometry args={[CORE_RADIUS, 48, 48]} />
      <meshBasicMaterial color="#ffb347" toneMapped={false} />
    </mesh>
  );
}

function ParticleShell() {
  const pointsRef = useRef<THREE.Points>(null);
  const state = useJarvisStore((s) => s.state);
  const level = useJarvisStore((s) => s.level);

  const positions = useMemo(() => {
    const arr = new Float32Array(PARTICLE_COUNT * 3);
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const r = SHELL_RADIUS * (0.75 + Math.random() * 0.5);
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      arr[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      arr[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      arr[i * 3 + 2] = r * Math.cos(phi);
    }
    return arr;
  }, []);

  useFrame((_, delta) => {
    const tuning = tuningFor(state, level);
    if (pointsRef.current) {
      pointsRef.current.rotation.y += delta * tuning.spinSpeed;
      pointsRef.current.rotation.x += delta * tuning.spinSpeed * 0.35;
      const mat = pointsRef.current.material as THREE.PointsMaterial;
      mat.color.lerp(tuning.color, 0.08);
      mat.size = 0.028 * tuning.brightness;
      mat.opacity = Math.min(0.55 + level * 0.4, 1);
    }
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial
        color="#ffb347"
        size={0.028}
        sizeAttenuation
        transparent
        opacity={0.6}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
      />
    </points>
  );
}

function Spikes() {
  const groupRef = useRef<THREE.Group>(null);
  const state = useJarvisStore((s) => s.state);
  const level = useJarvisStore((s) => s.level);

  const positions = useMemo(() => {
    const arr = new Float32Array(SPIKE_COUNT * 2 * 3);
    for (let i = 0; i < SPIKE_COUNT; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const dirX = Math.sin(phi) * Math.cos(theta);
      const dirY = Math.sin(phi) * Math.sin(theta);
      const dirZ = Math.cos(phi);
      const innerR = CORE_RADIUS * 0.9;
      const outerR = SHELL_RADIUS * (1.3 + Math.random() * 0.9);
      arr[i * 6] = dirX * innerR;
      arr[i * 6 + 1] = dirY * innerR;
      arr[i * 6 + 2] = dirZ * innerR;
      arr[i * 6 + 3] = dirX * outerR;
      arr[i * 6 + 4] = dirY * outerR;
      arr[i * 6 + 5] = dirZ * outerR;
    }
    return arr;
  }, []);

  useFrame((_, delta) => {
    const tuning = tuningFor(state, level);
    if (groupRef.current) {
      groupRef.current.rotation.y -= delta * tuning.spinSpeed * 0.5;
      groupRef.current.rotation.z += delta * tuning.spinSpeed * 0.2;
      const line = groupRef.current.children[0] as THREE.LineSegments;
      const mat = line.material as THREE.LineBasicMaterial;
      mat.color.lerp(tuning.color, 0.08);
      mat.opacity = 0.35 + level * 0.35;
    }
  });

  return (
    <group ref={groupRef}>
      <lineSegments>
        <bufferGeometry>
          <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        </bufferGeometry>
        <lineBasicMaterial color="#ffb347" transparent opacity={0.4} blending={THREE.AdditiveBlending} />
      </lineSegments>
    </group>
  );
}

function OrbitRings() {
  const ring1 = useRef<THREE.Mesh>(null);
  const ring2 = useRef<THREE.Mesh>(null);
  const state = useJarvisStore((s) => s.state);
  const level = useJarvisStore((s) => s.level);

  useFrame((_, delta) => {
    const tuning = tuningFor(state, level);
    if (ring1.current) ring1.current.rotation.z += delta * tuning.spinSpeed * 0.4;
    if (ring2.current) ring2.current.rotation.x += delta * tuning.spinSpeed * 0.3;
    for (const ref of [ring1, ring2]) {
      const mat = ref.current?.material as THREE.MeshBasicMaterial | undefined;
      mat?.color.lerp(tuning.color, 0.08);
    }
  });

  return (
    <>
      <mesh ref={ring1} rotation={[Math.PI / 2.4, 0.3, 0]}>
        <torusGeometry args={[SHELL_RADIUS * 1.15, 0.012, 8, 96]} />
        <meshBasicMaterial color="#ffb347" transparent opacity={0.5} toneMapped={false} />
      </mesh>
      <mesh ref={ring2} rotation={[0.6, Math.PI / 3, 0]}>
        <torusGeometry args={[SHELL_RADIUS * 1.35, 0.008, 8, 96]} />
        <meshBasicMaterial color="#ffb347" transparent opacity={0.3} toneMapped={false} />
      </mesh>
    </>
  );
}

export default function ParticleSphere() {
  return (
    <Canvas
      camera={{ position: [0, 0, 6.5], fov: 45 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: false, powerPreference: "high-performance" }}
      style={{ width: "100%", height: "100%", background: "#02060c" }}
      onCreated={({ gl }) => {
        gl.setClearColor(new THREE.Color("#02060c"), 1);
      }}
    >
      <color attach="background" args={["#02060c"]} />
      <Core />
      <ParticleShell />
      <Spikes />
      <OrbitRings />
      <EffectComposer multisampling={0}>
        <Bloom intensity={1.1} luminanceThreshold={0.2} luminanceSmoothing={0.3} radius={0.7} />
      </EffectComposer>
    </Canvas>
  );
}
