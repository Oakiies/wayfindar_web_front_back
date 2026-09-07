import React, { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { type MapPoint } from '../types/navigation';
import {
  buildNavigationGuidance,
  buildRouteFrame,
  clamp,
  normalizeDegrees,
  normalizeSignedDegrees,
} from '../utils/navigationGuidance';

export interface TransitionTargetMarker {
  node_id?: string;
  x: number;
  y: number;
  type?: string;
  name?: string;
  to_floor?: string;
}

interface ARFloorThreeOverlayProps {
  routePath: MapPoint[];
  livePosition?: MapPoint | null;
  liveHeadingDeg?: number | null;
  transitionTarget?: TransitionTargetMarker | null;
  enabled?: boolean;
}

interface ChevronPose {
  x: number;
  z: number;
  yaw: number;
  scale: number;
}

interface TransitionPose {
  x: number;
  z: number;
  label: string;
  toFloor?: string;
}

interface RouteRenderData {
  chevrons: ChevronPose[];
  transition: TransitionPose | null;
}

interface SampledPathPoint {
  point: MapPoint;
  headingDeg: number;
  distanceAlongPath: number;
}

function pointDistance(a: MapPoint, b: MapPoint): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function sampleForwardPath(
  points: MapPoint[],
  startDistance: number,
  spacing: number,
  maxSamples: number,
  endPadding: number
): SampledPathPoint[] {
  if (points.length < 2 || maxSamples <= 0) {
    return [];
  }

  const segmentLengths: number[] = [];
  let totalLength = 0;
  for (let index = 1; index < points.length; index += 1) {
    const length = pointDistance(points[index - 1], points[index]);
    segmentLengths.push(length);
    totalLength += length;
  }

  if (!Number.isFinite(totalLength) || totalLength <= 1) {
    return [];
  }

  const maxDistance = Math.max(0, totalLength - endPadding);
  if (startDistance >= maxDistance) {
    return [];
  }

  const samples: SampledPathPoint[] = [];
  let targetDistance = startDistance;
  let segmentStartDistance = 0;
  let segmentIndex = 0;

  while (targetDistance <= maxDistance && samples.length < maxSamples && segmentIndex < segmentLengths.length) {
    const segmentLength = segmentLengths[segmentIndex];
    const nextBoundary = segmentStartDistance + segmentLength;

    if (segmentLength <= 1e-6) {
      segmentStartDistance = nextBoundary;
      segmentIndex += 1;
      continue;
    }

    if (targetDistance > nextBoundary) {
      segmentStartDistance = nextBoundary;
      segmentIndex += 1;
      continue;
    }

    const start = points[segmentIndex];
    const end = points[segmentIndex + 1];
    const t = clamp((targetDistance - segmentStartDistance) / segmentLength, 0, 1);
    samples.push({
      point: {
        x: start.x + (end.x - start.x) * t,
        y: start.y + (end.y - start.y) * t,
      },
      headingDeg: normalizeDegrees((Math.atan2(end.y - start.y, end.x - start.x) * 180) / Math.PI),
      distanceAlongPath: targetDistance,
    });

    targetDistance += spacing;
  }

  return samples;
}

function createChevronGeometry(): THREE.ExtrudeGeometry {
  const shape = new THREE.Shape();
  shape.moveTo(0.0, 0.54);
  shape.lineTo(0.56, -0.30);
  shape.lineTo(0.22, -0.10);
  shape.lineTo(0.0, -0.22);
  shape.lineTo(-0.22, -0.10);
  shape.lineTo(-0.56, -0.30);
  shape.closePath();

  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: 0.18,
    bevelEnabled: true,
    bevelThickness: 0.04,
    bevelSize: 0.03,
    bevelSegments: 3,
  });
  geometry.rotateX(-Math.PI / 2);
  // Keep arrow almost touching the floor plane.
  geometry.translate(0, 0.004, 0);
  return geometry;
}

function createLabelTexture(text: string): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 384;
  canvas.height = 128;
  const context = canvas.getContext('2d');
  if (!context) {
    return new THREE.CanvasTexture(canvas);
  }

  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = 'rgba(6, 78, 59, 0.88)';
  context.strokeStyle = 'rgba(167, 243, 208, 0.95)';
  context.lineWidth = 6;

  const radius = 28;
  const x = 8;
  const y = 8;
  const width = canvas.width - 16;
  const height = canvas.height - 16;
  context.beginPath();
  context.moveTo(x + radius, y);
  context.lineTo(x + width - radius, y);
  context.quadraticCurveTo(x + width, y, x + width, y + radius);
  context.lineTo(x + width, y + height - radius);
  context.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  context.lineTo(x + radius, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - radius);
  context.lineTo(x, y + radius);
  context.quadraticCurveTo(x, y, x + radius, y);
  context.closePath();
  context.fill();
  context.stroke();

  context.fillStyle = '#ecfdf5';
  context.font = '700 44px Arial';
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillText(text, canvas.width / 2, canvas.height / 2);

  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return texture;
}

function buildRouteRenderData(
  routePath: MapPoint[],
  livePosition: MapPoint | null,
  liveHeadingDeg: number | null,
  transitionTarget: TransitionTargetMarker | null
): RouteRenderData {
  const routeFrame = buildRouteFrame(routePath, livePosition, liveHeadingDeg);
  const guidance = buildNavigationGuidance(routePath, livePosition, liveHeadingDeg);
  if (!routeFrame) {
    return { chevrons: [], transition: null };
  }

  const anchor = routeFrame.anchor;
  const forwardRoute = routeFrame.forwardPoints;
  const baseHeading = routeFrame.headingReferenceDeg ?? routeFrame.routeHeadingDeg ?? 0;

  const chevrons: ChevronPose[] = [];
  const allowChevrons = guidance?.kind !== 'uturn' && guidance?.kind !== 'arrive';
  const spacing = guidance?.isUpcomingTurn ? 18 : 24;
  const startDistance = guidance?.isUpcomingTurn ? 10 : 16;
  const transitionPoint =
    transitionTarget && Number.isFinite(transitionTarget.x) && Number.isFinite(transitionTarget.y)
      ? { x: Number(transitionTarget.x), y: Number(transitionTarget.y) }
      : null;
  const endPadding = transitionPoint ? 36 : 22;
  const sampledPoints = sampleForwardPath(forwardRoute, startDistance, spacing, guidance?.isUpcomingTurn ? 6 : 5, endPadding);

  for (const sample of sampledPoints) {
    if (!allowChevrons) {
      break;
    }

    if (transitionPoint && pointDistance(sample.point, transitionPoint) < 28) {
      continue;
    }

    const dx = sample.point.x - anchor.x;
    const dy = sample.point.y - anchor.y;
    const distance = Math.hypot(dx, dy);
    if (!Number.isFinite(distance) || distance < 0.5) {
      continue;
    }

    const worldHeading = normalizeDegrees((Math.atan2(dy, dx) * 180) / Math.PI);
    const relative = normalizeSignedDegrees(worldHeading - baseHeading);
    const tangentRelative = normalizeSignedDegrees(sample.headingDeg - baseHeading);
    if (distance > 8 && Math.abs(relative) > 165) {
      continue;
    }

    const relRad = (relative * Math.PI) / 180;
    const tangentRad = (tangentRelative * Math.PI) / 180;
    const worldDistance = clamp(distance * 0.11, 1.5, 14.0);
    const z = -Math.cos(relRad) * worldDistance;
    if (z > -0.6) {
      continue;
    }

    chevrons.push({
      x: Math.sin(relRad) * worldDistance * 0.95,
      z,
      yaw: -tangentRad,
      scale: clamp(1.85 - worldDistance * 0.07, 0.92, 1.75),
    });
  }

  let transition: TransitionPose | null = null;
  if (
    transitionTarget &&
    Number.isFinite(transitionTarget.x) &&
    Number.isFinite(transitionTarget.y)
  ) {
    const tx = Number(transitionTarget.x) - anchor.x;
    const ty = Number(transitionTarget.y) - anchor.y;
    const dist = Math.hypot(tx, ty);
    if (Number.isFinite(dist) && dist > 0.5) {
      const worldHeading = normalizeDegrees((Math.atan2(ty, tx) * 180) / Math.PI);
      const relative = normalizeSignedDegrees(worldHeading - baseHeading);
      const relRad = (relative * Math.PI) / 180;
      const worldDistance = clamp(dist * 0.11, 2.2, 17.0);
      transition = {
        x: Math.sin(relRad) * worldDistance * 0.95,
        z: -Math.cos(relRad) * worldDistance,
        label:
          typeof transitionTarget.type === 'string' && transitionTarget.type.toLowerCase().includes('stair')
            ? 'STAIRS'
            : 'LIFT',
        toFloor: transitionTarget.to_floor,
      };
    }
  }

  return { chevrons, transition };
}

const ARFloorThreeOverlay: React.FC<ARFloorThreeOverlayProps> = ({
  routePath,
  livePosition = null,
  liveHeadingDeg = null,
  transitionTarget = null,
  enabled = true,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const routeGroupRef = useRef<THREE.Group | null>(null);
  const markerGroupRef = useRef<THREE.Group | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const chevronGeometryRef = useRef<THREE.ExtrudeGeometry | null>(null);
  const chevronTopMaterialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  const chevronSideMaterialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  const markerGroundMaterialRef = useRef<THREE.MeshBasicMaterial | null>(null);
  const markerRingMaterialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  const markerPoleMaterialRef = useRef<THREE.MeshStandardMaterial | null>(null);
  const markerLabelTextureRef = useRef<THREE.Texture | null>(null);
  const markerLabelMaterialRef = useRef<THREE.SpriteMaterial | null>(null);

  const routeRenderData = useMemo(
    () => buildRouteRenderData(routePath, livePosition, liveHeadingDeg, transitionTarget),
    [routePath, livePosition, liveHeadingDeg, transitionTarget]
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }

    const renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true,
      powerPreference: 'high-performance',
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x000000, 0);
    rendererRef.current = renderer;

    const scene = new THREE.Scene();
    sceneRef.current = scene;

    const camera = new THREE.PerspectiveCamera(60, 1, 0.1, 90);
    camera.position.set(0, 1.55, 0.35);
    camera.lookAt(0, 0, -8);
    cameraRef.current = camera;

    const hemi = new THREE.HemisphereLight(0xffffff, 0x1f2937, 0.9);
    scene.add(hemi);
    const directional = new THREE.DirectionalLight(0xffffff, 1.0);
    directional.position.set(2.5, 4.5, 1.5);
    scene.add(directional);

    routeGroupRef.current = new THREE.Group();
    markerGroupRef.current = new THREE.Group();
    scene.add(routeGroupRef.current);
    scene.add(markerGroupRef.current);

    chevronGeometryRef.current = createChevronGeometry();
    chevronTopMaterialRef.current = new THREE.MeshStandardMaterial({
      color: 0x2cb9ee,
      emissive: 0x0a4d72,
      emissiveIntensity: 0.4,
      roughness: 0.22,
      metalness: 0.35,
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
      toneMapped: false,
    });
    chevronSideMaterialRef.current = new THREE.MeshStandardMaterial({
      color: 0x0c6691,
      roughness: 0.45,
      metalness: 0.2,
      transparent: true,
      opacity: 0.9,
      depthWrite: false,
      toneMapped: false,
    });
    markerGroundMaterialRef.current = new THREE.MeshBasicMaterial({
      color: 0x22c55e,
      transparent: true,
      opacity: 0.26,
      depthWrite: false,
    });
    markerRingMaterialRef.current = new THREE.MeshStandardMaterial({
      color: 0x4ade80,
      emissive: 0x16a34a,
      emissiveIntensity: 0.7,
      roughness: 0.4,
      metalness: 0.15,
      transparent: true,
      opacity: 0.95,
      depthWrite: false,
    });
    markerPoleMaterialRef.current = new THREE.MeshStandardMaterial({
      color: 0x86efac,
      emissive: 0x166534,
      emissiveIntensity: 0.2,
      roughness: 0.45,
      metalness: 0.05,
      depthWrite: false,
    });

    const updateSize = () => {
      const parent = canvas.parentElement;
      if (!parent || !rendererRef.current || !cameraRef.current) {
        return;
      }
      const rect = parent.getBoundingClientRect();
      const width = Math.max(1, Math.round(rect.width));
      const height = Math.max(1, Math.round(rect.height));
      rendererRef.current.setSize(width, height, false);
      cameraRef.current.aspect = width / height;
      cameraRef.current.updateProjectionMatrix();
    };

    updateSize();
    const observer = new ResizeObserver(updateSize);
    const resizeTarget = canvas.parentElement ?? canvas;
    observer.observe(resizeTarget);
    window.addEventListener('resize', updateSize);

    const renderLoop = () => {
      if (rendererRef.current && sceneRef.current && cameraRef.current) {
        rendererRef.current.render(sceneRef.current, cameraRef.current);
      }
      animationFrameRef.current = window.requestAnimationFrame(renderLoop);
    };
    animationFrameRef.current = window.requestAnimationFrame(renderLoop);

    return () => {
      if (animationFrameRef.current !== null) {
        window.cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
      window.removeEventListener('resize', updateSize);
      observer.disconnect();

      markerLabelTextureRef.current?.dispose();
      markerLabelTextureRef.current = null;
      markerLabelMaterialRef.current?.dispose();
      markerLabelMaterialRef.current = null;

      chevronGeometryRef.current?.dispose();
      chevronGeometryRef.current = null;
      chevronTopMaterialRef.current?.dispose();
      chevronTopMaterialRef.current = null;
      chevronSideMaterialRef.current?.dispose();
      chevronSideMaterialRef.current = null;
      markerGroundMaterialRef.current?.dispose();
      markerGroundMaterialRef.current = null;
      markerRingMaterialRef.current?.dispose();
      markerRingMaterialRef.current = null;
      markerPoleMaterialRef.current?.dispose();
      markerPoleMaterialRef.current = null;

      renderer.dispose();
      rendererRef.current = null;
      sceneRef.current = null;
      cameraRef.current = null;
      routeGroupRef.current = null;
      markerGroupRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!canvasRef.current) {
      return;
    }
    canvasRef.current.style.opacity = enabled ? '1' : '0';
  }, [enabled]);

  useEffect(() => {
    const routeGroup = routeGroupRef.current;
    const markerGroup = markerGroupRef.current;
    if (!routeGroup || !markerGroup) {
      return;
    }

    routeGroup.clear();
    markerGroup.clear();

    if (!enabled) {
      return;
    }

    const chevronGeometry = chevronGeometryRef.current;
    const chevronTopMaterial = chevronTopMaterialRef.current;
    const chevronSideMaterial = chevronSideMaterialRef.current;
    if (chevronGeometry && chevronTopMaterial && chevronSideMaterial) {
      for (const chevron of routeRenderData.chevrons) {
        const mesh = new THREE.Mesh(chevronGeometry, [chevronTopMaterial, chevronSideMaterial]);
        // Push arrow down and flatten thickness so it looks floor-attached.
        mesh.position.set(chevron.x, 0.0005, chevron.z);
        mesh.rotation.y = chevron.yaw;
        mesh.scale.set(chevron.scale, 0.24, chevron.scale);
        routeGroup.add(mesh);
      }
    }

    const transition = routeRenderData.transition;
    if (
      transition &&
      markerGroundMaterialRef.current &&
      markerRingMaterialRef.current &&
      markerPoleMaterialRef.current
    ) {
      const marker = new THREE.Group();
      marker.position.set(transition.x, 0.01, transition.z);

      const glowDisk = new THREE.Mesh(new THREE.CircleGeometry(0.52, 40), markerGroundMaterialRef.current);
      glowDisk.rotation.x = -Math.PI / 2;
      marker.add(glowDisk);

      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.5, 0.06, 14, 44), markerRingMaterialRef.current);
      ring.rotation.x = -Math.PI / 2;
      marker.add(ring);

      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.04, 1.05, 14), markerPoleMaterialRef.current);
      pole.position.y = 0.52;
      marker.add(pole);

      const labelText = transition.toFloor ? `${transition.label} -> ${transition.toFloor.toUpperCase()}` : transition.label;
      markerLabelTextureRef.current?.dispose();
      markerLabelTextureRef.current = createLabelTexture(labelText);
      markerLabelMaterialRef.current?.dispose();
      markerLabelMaterialRef.current = new THREE.SpriteMaterial({
        map: markerLabelTextureRef.current,
        transparent: true,
        depthWrite: false,
      });

      const sprite = new THREE.Sprite(markerLabelMaterialRef.current);
      sprite.position.y = 1.45;
      sprite.scale.set(2.5, 0.82, 1);
      marker.add(sprite);

      markerGroup.add(marker);
    }
  }, [enabled, routeRenderData]);

  return (
    <canvas
      ref={canvasRef}
      className={`pointer-events-none absolute inset-0 z-10 h-full w-full transition-opacity duration-200 ${
        enabled ? 'opacity-100' : 'opacity-0'
      }`}
    />
  );
};

export default ARFloorThreeOverlay;
