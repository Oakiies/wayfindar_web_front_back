import React, { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { type MapPoint } from '../types/navigation';
import { type ArWorldPayload } from '../services/navigationTestService';
import {
  buildNavigationGuidance,
  buildRouteFrame,
  clamp,
  normalizeDegrees,
  normalizeSignedDegrees,
} from '../utils/navigationGuidance';

// ── Real camera-pose AR (world-registered chevrons) ──────────────────────────
//
// Ported from navigate_indoor/static/js/ar_world.js. That module rebuilds the
// three.js camera every frame from the localizer's actual pose (K, R, t) sent
// by the backend (app/services/ar_service.py), instead of viewing stylized
// geometry through a fixed virtual camera — that is what makes drawn floor
// chevrons land on the floor the user is really walking on, rather than
// reading as a HUD overlay. The delicate parts (H_matrix inverse, floor plane,
// metres-per-world-unit scale) already live server-side; this only does camera
// setup and drawing.
//
// Conventions:
//   OpenCV camera : x right, y down, z forward  (what the backend sends)
//   three.js/GL   : x right, y up,   z backward
// so the pose conversion flips y and z — see applyWorldPose. World-space
// chevron points are used AS-IS (no per-point axis flip needed): only the
// camera's basis is flipped, which is equivalent because the projection is
// relative to the camera.
const AR_WORLD_COLOR = 0x28d2ff; // floor chevrons
const AR_WORLD_MARKER_COLOR = 0xffc83c; // raised turn marker — distinct, means something else
const AR_POC_RIBBON_COLOR = 0x3cb4fa;
const AR_POC_CARET_COLOR = 0xb4ecff;
const AR_POC_EDGE_COLOR = 0x0a5a96;
const AR_POC_DESTINATION_COLOR = 0xe5484d;
const AR_POC_ARRIVED_COLOR = 0x22c55e;
const AR_WORLD_NEAR = 0.02;
const AR_WORLD_FAR = 500;

/**
 * Projection matrix straight from the pinhole intrinsics.
 *
 * Using fx/fy/cx/cy rather than a single fov keeps a non-centred principal
 * point honest; collapsing it to fov would silently assume cx,cy sit at the
 * exact image centre.
 */
interface ArCanvasLayout {
  width: number;
  height: number;
  left: number;
  top: number;
  fit: 'contain' | 'cover';
  imageScale: number;
  imageLeft: number;
  imageTop: number;
}

function applyWorldIntrinsics(
  camera: THREE.PerspectiveCamera,
  K: [number, number, number, number],
  imgW: number,
  imgH: number,
  layout?: ArCanvasLayout
): void {
  let [fx, fy, cx, cy] = K;
  let projectionW = imgW;
  let projectionH = imgH;
  if (layout?.fit === 'cover') {
    // The live camera uses object-cover. Convert image-pixel intrinsics into
    // viewport-pixel intrinsics after the image is scaled and cropped.
    fx *= layout.imageScale;
    fy *= layout.imageScale;
    cx = cx * layout.imageScale + layout.imageLeft;
    cy = cy * layout.imageScale + layout.imageTop;
    projectionW = layout.width;
    projectionH = layout.height;
  }
  const m = camera.projectionMatrix;
  m.set(
    (2 * fx) / projectionW, 0, 1 - (2 * cx) / projectionW, 0,
    0, (2 * fy) / projectionH, (2 * cy) / projectionH - 1, 0,
    0, 0, -(AR_WORLD_FAR + AR_WORLD_NEAR) / (AR_WORLD_FAR - AR_WORLD_NEAR), (-2 * AR_WORLD_FAR * AR_WORLD_NEAR) / (AR_WORLD_FAR - AR_WORLD_NEAR),
    0, 0, -1, 0
  );
  camera.projectionMatrixInverse.copy(m).invert();
}

/**
 * Camera pose from the OpenCV extrinsics (X_cam = R * X_world + t).
 *
 * Camera centre in world is -Rᵀt, and the camera-to-world basis is Rᵀ with its
 * y and z axes negated to go from OpenCV's (y down, z forward) to three.js's
 * (y up, z backward).
 */
function applyWorldPose(camera: THREE.PerspectiveCamera, R: number[][], t: number[]): void {
  const rt = [
    [R[0][0], R[1][0], R[2][0]],
    [R[0][1], R[1][1], R[2][1]],
    [R[0][2], R[1][2], R[2][2]],
  ];
  const cx = -(rt[0][0] * t[0] + rt[0][1] * t[1] + rt[0][2] * t[2]);
  const cy = -(rt[1][0] * t[0] + rt[1][1] * t[1] + rt[1][2] * t[2]);
  const cz = -(rt[2][0] * t[0] + rt[2][1] * t[1] + rt[2][2] * t[2]);

  const m = new THREE.Matrix4();
  m.set(
    rt[0][0], -rt[0][1], -rt[0][2], cx,
    rt[1][0], -rt[1][1], -rt[1][2], cy,
    rt[2][0], -rt[2][1], -rt[2][2], cz,
    0, 0, 0, 1
  );
  m.decompose(camera.position, camera.quaternion, camera.scale);
}

/**
 * Build a filled, CONCAVE polygon mesh from world-space points.
 *
 * The floor chevron is concave (notches beside the shaft), so a triangle fan
 * would fill those notches in — it needs real triangulation. Flatten onto the
 * polygon's own plane, triangulate there with THREE.Shape, then map the
 * result back into world space so the shape keeps its orientation.
 */
function buildWorldChevronGeometry(points: number[][]): THREE.BufferGeometry {
  const o = new THREE.Vector3(...(points[0] as [number, number, number]));
  const a = new THREE.Vector3(...(points[1] as [number, number, number])).sub(o).normalize();
  const nrm = new THREE.Vector3(...(points[2] as [number, number, number])).sub(o).cross(a).normalize();
  const b = new THREE.Vector3().crossVectors(nrm, a).normalize();
  const shape = new THREE.Shape();
  points.forEach((p, i) => {
    const v = new THREE.Vector3(...(p as [number, number, number])).sub(o);
    const u = v.dot(a);
    const w = v.dot(b);
    if (i === 0) {
      shape.moveTo(u, w);
    } else {
      shape.lineTo(u, w);
    }
  });
  shape.closePath();
  const flat = new THREE.ShapeGeometry(shape);
  const pos = flat.attributes.position;
  const verts = new Float32Array(pos.count * 3);
  for (let i = 0; i < pos.count; i += 1) {
    const u = pos.getX(i);
    const w = pos.getY(i);
    verts[i * 3] = o.x + a.x * u + b.x * w;
    verts[i * 3 + 1] = o.y + a.y * u + b.y * w;
    verts[i * 3 + 2] = o.z + a.z * u + b.z * w;
  }
  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.BufferAttribute(verts, 3));
  if (flat.index) {
    geom.setIndex(flat.index);
  }
  flat.dispose();
  return geom;
}

function buildWorldLine(
  points: number[][],
  loop = false,
  color = AR_POC_EDGE_COLOR,
  opacity = 0.22
): THREE.Line | THREE.LineLoop | null {
  if (points.length < 2 || points.some((point) => point.length < 3 || point.some((value) => !Number.isFinite(value)))) {
    return null;
  }
  const geometry = new THREE.BufferGeometry().setFromPoints(
    points.map((point) => new THREE.Vector3(point[0], point[1], point[2]))
  );
  const material = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity,
    depthWrite: false,
    depthTest: false,
  });
  return loop ? new THREE.LineLoop(geometry, material) : new THREE.Line(geometry, material);
}

function disposeWorldObject(object: THREE.Object3D): void {
  object.traverse((child) => {
    const drawable = child as THREE.Mesh | THREE.Line | THREE.LineLoop | THREE.Sprite;
    if ('geometry' in drawable && drawable.geometry) {
      drawable.geometry.dispose();
    }
    const material = drawable.material as THREE.Material | THREE.Material[] | undefined;
    if (material) {
      const materials = (Array.isArray(material) ? material : [material]) as THREE.Material[];
      materials.forEach((entry) => {
        const texture = (entry as THREE.Material & { map?: THREE.Texture | null }).map;
        if (texture) {
          texture.dispose();
        }
        entry.dispose();
      });
    }
  });
}

/**
 * Size + position the canvas so it maps 1:1 onto the video's ON-SCREEN pixels.
 *
 * Replay uses `object-contain`, while live camera pages use `object-cover`.
 * The canvas and projection matrix must use the same fit: contain letterboxes
 * the canvas over the displayed image, while cover keeps a full-viewport canvas
 * and moves the principal point to account for the cropped image.
 */
function layoutArCanvas(
  canvas: HTMLCanvasElement,
  renderer: THREE.WebGLRenderer,
  imgWH: [number, number] | null,
  fit: 'contain' | 'cover' = 'contain'
): ArCanvasLayout | null {
  const container = canvas.parentElement;
  if (!container) {
    return null;
  }
  const box = container.getBoundingClientRect();
  if (!box.width || !box.height) {
    return null;
  }

  let width = box.width;
  let height = box.height;
  let left = 0;
  let top = 0;

  const [imgW, imgH] = imgWH ?? [0, 0];
  let imageScale = 1;
  let imageLeft = 0;
  let imageTop = 0;
  if (imgW > 0 && imgH > 0) {
    imageScale = fit === 'cover'
      ? Math.max(box.width / imgW, box.height / imgH)
      : Math.min(box.width / imgW, box.height / imgH);
    const imageWidth = imgW * imageScale;
    const imageHeight = imgH * imageScale;
    imageLeft = (box.width - imageWidth) / 2;
    imageTop = (box.height - imageHeight) / 2;
    if (fit === 'contain') {
      width = imageWidth;
      height = imageHeight;
      left = imageLeft;
      top = imageTop;
    } else {
      // The canvas must cover the same viewport as object-cover. The crop is
      // represented in the projection's principal point above.
      width = box.width;
      height = box.height;
      left = 0;
      top = 0;
    }
  }

  canvas.style.left = `${left}px`;
  canvas.style.top = `${top}px`;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  renderer.setSize(width, height, false);
  return { width, height, left, top, fit, imageScale, imageLeft, imageTop };
}

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
  /** Real camera-pose payload from /api/live-localize. Present -> pixel-registered
   *  world chevrons (see ar_world helpers above); null/absent -> falls back to the
   *  stylized route-based ribbon below, which never depends on pose. */
  arWorld?: ArWorldPayload | null;
  /** Live PDR displacement in the same world units as the AR payload. */
  pdrPoseRef?: React.MutableRefObject<ArPdrPose>;
  /** The <video> this overlay sits over — read only for its native pixel size, to
   *  keep the pixel-registered camera's aspect in step with the live feed. */
  videoRef?: React.RefObject<HTMLVideoElement | null>;
  /** Must match the video element's object-fit when world AR is active. */
  videoFit?: 'contain' | 'cover';
  /** Replay PoC mode: a missing v2 payload means no AR geometry, not a stylized fallback. */
  strictWorldAr?: boolean;
}

export interface ArPdrPose {
  deltaWorld: [number, number, number];
  /** Camera yaw since the last accepted world pose, in the floor plane. */
  deltaYawRad: number;
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

function createDestinationLabelTexture(title: string, distanceM: number | null | undefined, arrived: boolean): THREE.CanvasTexture {
  const canvas = document.createElement('canvas');
  canvas.width = 640;
  canvas.height = 154;
  const context = canvas.getContext('2d');
  if (!context) {
    return new THREE.CanvasTexture(canvas);
  }

  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = 'rgba(253, 253, 253, 0.97)';
  context.strokeStyle = arrived ? '#22c55e' : '#e5484d';
  context.lineWidth = 6;
  const radius = 28;
  context.beginPath();
  context.roundRect(8, 8, canvas.width - 16, canvas.height - 16, radius);
  context.fill();
  context.stroke();
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillStyle = '#1c1c20';
  context.font = '700 42px Arial';
  context.fillText(title || 'Destination', canvas.width / 2, 57);
  context.fillStyle = '#787c84';
  context.font = '400 32px Arial';
  context.fillText(
    arrived ? 'Arrived' : Number.isFinite(distanceM) ? `${Math.round(Number(distanceM))} m away` : 'Destination',
    canvas.width / 2,
    110
  );
  return new THREE.CanvasTexture(canvas);
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
  arWorld = null,
  pdrPoseRef,
  videoRef,
  videoFit = 'contain',
  strictWorldAr = false,
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const routeGroupRef = useRef<THREE.Group | null>(null);
  const markerGroupRef = useRef<THREE.Group | null>(null);
  const worldGroupRef = useRef<THREE.Group | null>(null);
  const worldModeRef = useRef(false);
  const worldBasePoseRef = useRef<{ R: number[][]; t: number[] } | null>(null);
  const worldTargetPoseRef = useRef<{ position: THREE.Vector3; quaternion: THREE.Quaternion } | null>(null);
  const worldSmoothPoseRef = useRef<{ position: THREE.Vector3; quaternion: THREE.Quaternion } | null>(null);
  const worldPoseLastUpdateAtRef = useRef(0);
  const worldYawAxisRef = useRef<THREE.Vector3 | null>(null);
  const worldIntrinsicsRef = useRef<{ K: [number, number, number, number]; imgWH: [number, number] } | null>(null);
  // The image size to lay the canvas out against. This must be the payload's
  // calibration image size because K is expressed in that same coordinate
  // system; using the browser's possibly downscaled video dimensions would
  // silently apply the projection scale twice.
  const imgWHRef = useRef<[number, number] | null>(null);
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
    worldGroupRef.current = new THREE.Group();
    scene.add(routeGroupRef.current);
    scene.add(markerGroupRef.current);
    scene.add(worldGroupRef.current);

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
      if (!rendererRef.current || !cameraRef.current) {
        return;
      }
      // Match the canvas to the live video's fit mode and native image size.
      // Stylized fallback has no image projection, so it lays out full-bleed.
      const imgWH: [number, number] | null = worldModeRef.current
        ? imgWHRef.current
        : null;
      const layout = layoutArCanvas(canvas, rendererRef.current, imgWH, videoFit);
      // The pixel-registered camera's projection matrix comes from K/imgWH
      if (worldModeRef.current && worldIntrinsicsRef.current && layout) {
        applyWorldIntrinsics(
          cameraRef.current,
          worldIntrinsicsRef.current.K,
          worldIntrinsicsRef.current.imgWH[0],
          worldIntrinsicsRef.current.imgWH[1],
          layout,
        );
      } else if (!worldModeRef.current) {
        const rect = canvas.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          cameraRef.current.aspect = rect.width / rect.height;
          cameraRef.current.updateProjectionMatrix();
        }
      }
    };

    updateSize();
    const observer = new ResizeObserver(updateSize);
    const resizeTarget = canvas.parentElement ?? canvas;
    observer.observe(resizeTarget);
    window.addEventListener('resize', updateSize);

    const renderLoop = () => {
      if (rendererRef.current && sceneRef.current && cameraRef.current) {
        // Keep the POC's world geometry, but move the virtual camera with the
        // high-rate PDR delta between VaL corrections. The next VaL payload
        // replaces this base pose and resets the accumulated delta.
        if (worldModeRef.current && worldTargetPoseRef.current) {
          const targetPose = worldTargetPoseRef.current;
          if (!worldSmoothPoseRef.current) {
            worldSmoothPoseRef.current = {
              position: targetPose.position.clone(),
              quaternion: targetPose.quaternion.clone(),
            };
          }
          const now = performance.now();
          const dt = worldPoseLastUpdateAtRef.current > 0
            ? Math.min(0.1, Math.max(0, (now - worldPoseLastUpdateAtRef.current) / 1000))
            : 1 / 60;
          worldPoseLastUpdateAtRef.current = now;
          // VaL fixes arrive at a much lower rate than the render loop. Smooth
          // the visual-pose correction so a new fix does not teleport the AR
          // camera and make the floor lane appear to jump sideways.
          const positionFollow = 1 - Math.exp(-dt / 0.18);
          const rotationFollow = 1 - Math.exp(-dt / 0.22);
          worldSmoothPoseRef.current.position.lerp(targetPose.position, positionFollow);
          worldSmoothPoseRef.current.quaternion.slerp(targetPose.quaternion, rotationFollow).normalize();
          cameraRef.current.position.copy(worldSmoothPoseRef.current.position);
          cameraRef.current.quaternion.copy(worldSmoothPoseRef.current.quaternion);
          const poseDelta = pdrPoseRef?.current;
          const [dx, dy, dz] = poseDelta?.deltaWorld ?? [0, 0, 0];
          cameraRef.current.position.x += Number.isFinite(dx) ? dx : 0;
          cameraRef.current.position.y += Number.isFinite(dy) ? dy : 0;
          cameraRef.current.position.z += Number.isFinite(dz) ? dz : 0;
          const deltaYaw = Number(poseDelta?.deltaYawRad ?? 0);
          const yawAxis = worldYawAxisRef.current;
          if (yawAxis && Number.isFinite(deltaYaw) && Math.abs(deltaYaw) > 1e-6) {
            const yaw = new THREE.Quaternion().setFromAxisAngle(yawAxis, deltaYaw);
            // Rotate around the world floor normal, not the screen/camera
            // axis, so the route stays registered while the phone turns.
            cameraRef.current.quaternion.premultiply(yaw);
          }
          cameraRef.current.updateMatrixWorld(true);
        }
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

      worldGroupRef.current?.clear();
      worldBasePoseRef.current = null;
      worldTargetPoseRef.current = null;
      worldSmoothPoseRef.current = null;
      worldPoseLastUpdateAtRef.current = 0;
      worldYawAxisRef.current = null;

      renderer.dispose();
      rendererRef.current = null;
      sceneRef.current = null;
      cameraRef.current = null;
      routeGroupRef.current = null;
      markerGroupRef.current = null;
      worldGroupRef.current = null;
    };
  }, [videoRef, pdrPoseRef, videoFit]);

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
    routeGroup.visible = false;
    markerGroup.visible = false;

    // A live ar_world payload takes over rendering (see the effect below) —
    // leave the stylized fallback empty rather than drawing both at once.
    // The AR Fusion PoC enables strictWorldAr so it never shows a screen-space
    // arrow that could be mistaken for a floor-registered cue.
    if (!enabled || arWorld || strictWorldAr) {
      return;
    }

    routeGroup.visible = true;
    markerGroup.visible = true;

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
  }, [enabled, arWorld, routeRenderData, strictWorldAr]);

  // ── World-registered AR (real camera pose) ──────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    const renderer = rendererRef.current;
    const camera = cameraRef.current;
    const worldGroup = worldGroupRef.current;
    if (!canvas || !renderer || !camera || !worldGroup) {
      return;
    }

    // Rebuild once per localization update. Dispose every drawable, including
    // the v2 ribbon lines and destination marker sprites, so replaying a long
    // video does not leak GPU resources.
    [...worldGroup.children].forEach(disposeWorldObject);
    worldGroup.clear();

    const worldCarets = arWorld?.carets?.length ? arWorld.carets : arWorld?.chevrons ?? [];
    const hasRibbon = (arWorld?.ribbon_quads?.length ?? 0) > 0;
    const hasWorld = enabled && !!arWorld && (worldCarets.length > 0 || hasRibbon) && arWorld.imgWH[0] > 0 && arWorld.imgWH[1] > 0;
    worldModeRef.current = hasWorld;
    worldGroup.visible = hasWorld;

    if (!hasWorld || !arWorld) {
      // Leaving world mode: go back to full-bleed layout and restore the
      // stylized camera's normal fov/aspect projection (the last frame in
      // world mode left projectionMatrix set directly from K/imgWH, and
      // updateSize() leaves that alone while worldModeRef is true, so both
      // have to be restored explicitly here on the transition out).
      imgWHRef.current = null;
      worldBasePoseRef.current = null;
      worldTargetPoseRef.current = null;
      worldSmoothPoseRef.current = null;
      worldPoseLastUpdateAtRef.current = 0;
      worldYawAxisRef.current = null;
      layoutArCanvas(canvas, renderer, null, videoFit);
      worldIntrinsicsRef.current = null;
      const rect = canvas.getBoundingClientRect();
      if (rect.width > 0 && rect.height > 0) {
        camera.aspect = rect.width / rect.height;
      }
      camera.updateProjectionMatrix();
      return;
    }

    const [imgW, imgH] = arWorld.imgWH;
    imgWHRef.current = [imgW, imgH];
    const layout = layoutArCanvas(
      canvas,
      renderer,
      // K/imgWH describe the actual image coordinate system used by PnP.
      // The live video may be a downscaled 1280x720 stream while calibration
      // remains 1920x1080; using video dimensions here would scale K twice.
      [imgW, imgH],
      videoFit,
    );

    worldIntrinsicsRef.current = { K: [...arWorld.K] as [number, number, number, number], imgWH: [imgW, imgH] };
    applyWorldIntrinsics(camera, arWorld.K, imgW, imgH, layout ?? undefined);
    worldBasePoseRef.current = {
      R: arWorld.R.map((row) => [...row]),
      t: [...arWorld.t],
    };
    const mapXAxis = arWorld.pdr_map_x_axis_world;
    const mapYAxis = arWorld.pdr_map_y_axis_world;
    if (Array.isArray(mapXAxis) && mapXAxis.length >= 3 && Array.isArray(mapYAxis) && mapYAxis.length >= 3) {
      worldYawAxisRef.current = new THREE.Vector3(...mapXAxis)
        .cross(new THREE.Vector3(...mapYAxis))
        .normalize();
    } else {
      worldYawAxisRef.current = null;
    }
    applyWorldPose(camera, arWorld.R, arWorld.t);
    worldTargetPoseRef.current = {
      position: camera.position.clone(),
      quaternion: camera.quaternion.clone(),
    };
    if (!worldSmoothPoseRef.current) {
      worldSmoothPoseRef.current = {
        position: camera.position.clone(),
        quaternion: camera.quaternion.clone(),
      };
    }
    worldPoseLastUpdateAtRef.current = performance.now();
    // The pose is assigned by decomposing a matrix outside Three.js's usual
    // lookAt/update path. Force the same camera-world update used by the
    // original ar_world.js before the render loop can draw this payload.
    camera.updateMatrixWorld(true);

    const isMarker = !!arWorld.marker;
    const color = arWorld.arVersion === 'poc_ar_arrow_v2'
      ? AR_POC_CARET_COLOR
      : isMarker ? AR_WORLD_MARKER_COLOR : AR_WORLD_COLOR;

    // v2: continuous floor ribbon first, then the readable carets painted on
    // it. Each ribbon quad has its own camera-depth fade from the PoC.
    const metresPerUnit = Number(arWorld.metres_per_unit) || 1;
    const heldConfidence = 1 - Math.max(0, Math.min(1, Number(arWorld.heldAge) || 0)) * 0.75;
    arWorld.ribbon_quads?.forEach(([quad, depth]) => {
      if (!Array.isArray(quad) || quad.length < 3) {
        return;
      }
      const geometry = buildWorldChevronGeometry(quad);
      const depthMetres = Number(depth) * metresPerUnit;
      const alpha = Number.isFinite(depthMetres)
          ? Math.max(0, Math.min(1, depthMetres <= 0.9 ? 0 : depthMetres > 30 ? 1 - (depthMetres - 30) / 12 : 1)) * 0.20 * heldConfidence
        : 0.08;
      if (alpha > 0.01) {
        worldGroup.add(new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
          color: AR_POC_RIBBON_COLOR,
          transparent: true,
          opacity: alpha,
          side: THREE.DoubleSide,
          depthWrite: false,
          depthTest: false,
        })));
      } else {
        geometry.dispose();
      }
    });
    arWorld.ribbon_edges?.forEach((edge) => {
      const line = buildWorldLine(edge, false, AR_POC_EDGE_COLOR, 0.22 * heldConfidence);
      if (line) {
        worldGroup.add(line);
      }
    });

    const n = worldCarets.length;
    worldCarets.forEach((poly, i) => {
      if (poly.length < 3) {
        return;
      }
      // The service fades each arrow by its distance, so one dims as it is
      // walked over while the next brightens in behind it.
      const alpha = arWorld.alphas && i < arWorld.alphas.length
        ? arWorld.alphas[i]
        : isMarker
          ? 0.95
          : 1 - (i / Math.max(1, n - 1)) * 0.35;
      if (alpha <= 0.01) {
        return;
      }
      const compositeAlpha = Math.min(1, alpha * 0.92 * heldConfidence);
      const geometry = buildWorldChevronGeometry(poly);
      const material = new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: compositeAlpha,
        side: THREE.DoubleSide,
        depthWrite: false,
        depthTest: false,
      });
      worldGroup.add(new THREE.Mesh(geometry, material));
      // render_v2.py composites the same dark edge over every caret.  Keep it
      // as a separate line so the concave shape remains readable in Three.js.
      const outline = buildWorldLine(
        [...poly, poly[0]],
        false,
        AR_POC_EDGE_COLOR,
        compositeAlpha,
      );
      if (outline) {
        worldGroup.add(outline);
      }
    });

    // v2 destination landmark: perspective floor bullseye, tapered stem,
    // teardrop head, and the same compact destination label used by the PoC.
    const destinationMarker = arWorld.destination_marker;
    if (destinationMarker) {
      const markerColour = destinationMarker.arrived ? AR_POC_ARRIVED_COLOR : AR_POC_DESTINATION_COLOR;
      const floor = new THREE.Group();
      const floorInner = buildWorldChevronGeometry(destinationMarker.floor_inner);
      floor.add(new THREE.Mesh(floorInner, new THREE.MeshBasicMaterial({
        color: markerColour,
        transparent: true,
        opacity: 0.18 * heldConfidence,
        side: THREE.DoubleSide,
        depthWrite: false,
        depthTest: false,
      })));
      const outer = buildWorldLine(destinationMarker.floor_outer, true, markerColour, 0.95 * heldConfidence);
      if (outer) {
        floor.add(outer);
      }
      const inner = buildWorldLine(destinationMarker.floor_inner, true, 0xffffff, 0.82 * heldConfidence);
      if (inner) {
        floor.add(inner);
      }
      const stemGeometry = buildWorldChevronGeometry(destinationMarker.stem);
      floor.add(new THREE.Mesh(stemGeometry, new THREE.MeshBasicMaterial({
        color: markerColour,
        transparent: true,
        opacity: 0.95 * heldConfidence,
        side: THREE.DoubleSide,
        depthWrite: false,
        depthTest: false,
      })));
      const headGeometry = buildWorldChevronGeometry(destinationMarker.head);
      floor.add(new THREE.Mesh(headGeometry, new THREE.MeshBasicMaterial({
        color: markerColour,
        transparent: true,
        opacity: 0.98 * heldConfidence,
        side: THREE.DoubleSide,
        depthWrite: false,
        depthTest: false,
      })));

      const labelTexture = createDestinationLabelTexture(
        destinationMarker.title,
        destinationMarker.distance_m,
        !!destinationMarker.arrived
      );
      const labelMaterial = new THREE.SpriteMaterial({
        map: labelTexture,
        transparent: true,
        opacity: heldConfidence,
        depthWrite: false,
        depthTest: false,
      });
      const label = new THREE.Sprite(labelMaterial);
      label.position.set(...(destinationMarker.top as [number, number, number]));
      label.position.y += 0.55;
      label.scale.set(1.65, 0.40, 1);
      floor.add(label);
      worldGroup.add(floor);
    }
  }, [enabled, arWorld, videoRef, videoFit]);

  return (
    // Sized here as a full-bleed default only — layoutArCanvas (called from the
    // init effect and the world-registered-AR effect above) sets left/top/
    // width/height inline once mounted, matching the selected video fit in
    // world mode. These classes are visible for the first frame and for the
    // stylized (non-world) mode.
    <canvas
      ref={canvasRef}
      className={`pointer-events-none absolute inset-0 z-10 h-full w-full transition-opacity duration-200 ${
        enabled ? 'opacity-100' : 'opacity-0'
      }`}
    />
  );
};

export default ARFloorThreeOverlay;
