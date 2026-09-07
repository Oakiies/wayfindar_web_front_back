import { useEffect, useRef, type RefObject } from 'react';
import * as THREE from 'three';

export interface ARWorldPayload {
  K: [number, number, number, number];
  imgWH: [number, number];
  R: number[][];
  t: [number, number, number];
  chevrons: number[][][];
  marker?: boolean;
  alphas?: number[];
  heldAge?: number;
}

interface ARWorldOverlayProps {
  payload: ARWorldPayload | null;
  videoRef: RefObject<HTMLVideoElement | null>;
  enabled?: boolean;
}

const NEAR = 0.02;
const FAR = 500;
const CHEVRON_COLOR = 0x28d2ff;
const MARKER_COLOR = 0xffc83c;
const DISTANCE_FADE = 0.35;

function disposeMeshes(scene: THREE.Scene | null, meshes: THREE.Mesh[]): void {
  for (const mesh of meshes) {
    scene?.remove(mesh);
    mesh.geometry.dispose();
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of materials) {
      material.dispose();
    }
  }
  meshes.length = 0;
}

function createPolygonMesh(points: number[][], opacity: number, color: number): THREE.Mesh | null {
  if (points.length < 3 || points.some((point) => point.length < 3 || point.some((value) => !Number.isFinite(value)))) {
    return null;
  }

  const origin = new THREE.Vector3(points[0][0], points[0][1], points[0][2]);
  const axisA = new THREE.Vector3(points[1][0], points[1][1], points[1][2]).sub(origin).normalize();
  const normal = new THREE.Vector3(points[2][0], points[2][1], points[2][2]).sub(origin).cross(axisA).normalize();
  if (axisA.lengthSq() < 1e-8 || normal.lengthSq() < 1e-8) {
    return null;
  }
  const axisB = new THREE.Vector3().crossVectors(normal, axisA).normalize();
  const shape = new THREE.Shape();

  points.forEach((point, index) => {
    const local = new THREE.Vector3(point[0], point[1], point[2]).sub(origin);
    const u = local.dot(axisA);
    const v = local.dot(axisB);
    if (index === 0) {
      shape.moveTo(u, v);
    } else {
      shape.lineTo(u, v);
    }
  });
  shape.closePath();

  const flatGeometry = new THREE.ShapeGeometry(shape);
  const flatPosition = flatGeometry.attributes.position;
  const vertices = new Float32Array(flatPosition.count * 3);
  for (let index = 0; index < flatPosition.count; index += 1) {
    const u = flatPosition.getX(index);
    const v = flatPosition.getY(index);
    vertices[index * 3] = origin.x + axisA.x * u + axisB.x * v;
    vertices[index * 3 + 1] = origin.y + axisA.y * u + axisB.y * v;
    vertices[index * 3 + 2] = origin.z + axisA.z * u + axisB.z * v;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(vertices, 3));
  if (flatGeometry.index) {
    geometry.setIndex(flatGeometry.index.clone());
  }
  flatGeometry.dispose();

  const material = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity,
    side: THREE.DoubleSide,
    depthWrite: false,
    depthTest: false,
  });
  return new THREE.Mesh(geometry, material);
}

const ARWorldOverlay = ({ payload, videoRef, enabled = true }: ARWorldOverlayProps) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const meshesRef = useRef<THREE.Mesh[]>([]);
  const imageSizeRef = useRef<[number, number]>([0, 0]);
  const layoutRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = canvas?.parentElement;
    const meshes = meshesRef.current;
    if (!canvas || !container) {
      return;
    }

    const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    rendererRef.current = renderer;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, 1, NEAR, FAR);
    sceneRef.current = scene;
    cameraRef.current = camera;

    const layout = () => {
      const box = container.getBoundingClientRect();
      if (!box.width || !box.height) {
        return;
      }
      const video = videoRef.current;
      const [payloadWidth, payloadHeight] = imageSizeRef.current;
      const sourceWidth = video?.videoWidth || payloadWidth;
      const sourceHeight = video?.videoHeight || payloadHeight;
      let width = box.width;
      let height = box.height;
      let left = 0;
      let top = 0;
      if (sourceWidth > 0 && sourceHeight > 0) {
        const scale = Math.min(box.width / sourceWidth, box.height / sourceHeight);
        width = sourceWidth * scale;
        height = sourceHeight * scale;
        left = (box.width - width) / 2;
        top = (box.height - height) / 2;
      }
      canvas.style.left = `${left}px`;
      canvas.style.top = `${top}px`;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      renderer.setSize(Math.max(1, width), Math.max(1, height), false);
    };
    layoutRef.current = layout;
    layout();

    const observer = new ResizeObserver(layout);
    observer.observe(container);
    const video = videoRef.current;
    video?.addEventListener('loadedmetadata', layout);
    window.addEventListener('resize', layout);

    return () => {
      observer.disconnect();
      video?.removeEventListener('loadedmetadata', layout);
      window.removeEventListener('resize', layout);
      disposeMeshes(sceneRef.current, meshes);
      renderer.dispose();
      rendererRef.current = null;
      sceneRef.current = null;
      cameraRef.current = null;
      layoutRef.current = () => undefined;
    };
  }, [videoRef]);

  useEffect(() => {
    const renderer = rendererRef.current;
    const scene = sceneRef.current;
    const camera = cameraRef.current;
    if (!renderer || !scene || !camera) {
      return;
    }

    disposeMeshes(scene, meshesRef.current);
    if (!enabled || !payload || !Array.isArray(payload.chevrons) || payload.chevrons.length === 0) {
      renderer.clear();
      return;
    }

    const [imageWidth, imageHeight] = payload.imgWH ?? [0, 0];
    if (!(imageWidth > 0 && imageHeight > 0) || payload.K?.length !== 4 || payload.R?.length !== 3 || payload.t?.length !== 3) {
      renderer.clear();
      return;
    }
    imageSizeRef.current = [imageWidth, imageHeight];
    layoutRef.current();

    const [fx, fy, cx, cy] = payload.K;
    camera.projectionMatrix.set(
      (2 * fx) / imageWidth, 0, 1 - (2 * cx) / imageWidth, 0,
      0, (2 * fy) / imageHeight, (2 * cy) / imageHeight - 1, 0,
      0, 0, -(FAR + NEAR) / (FAR - NEAR), (-2 * FAR * NEAR) / (FAR - NEAR),
      0, 0, -1, 0
    );
    camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();

    const rotation = payload.R;
    const translation = payload.t;
    const transpose = [
      [rotation[0][0], rotation[1][0], rotation[2][0]],
      [rotation[0][1], rotation[1][1], rotation[2][1]],
      [rotation[0][2], rotation[1][2], rotation[2][2]],
    ];
    const cameraX = -(transpose[0][0] * translation[0] + transpose[0][1] * translation[1] + transpose[0][2] * translation[2]);
    const cameraY = -(transpose[1][0] * translation[0] + transpose[1][1] * translation[1] + transpose[1][2] * translation[2]);
    const cameraZ = -(transpose[2][0] * translation[0] + transpose[2][1] * translation[1] + transpose[2][2] * translation[2]);
    const cameraMatrix = new THREE.Matrix4();
    cameraMatrix.set(
      transpose[0][0], -transpose[0][1], -transpose[0][2], cameraX,
      transpose[1][0], -transpose[1][1], -transpose[1][2], cameraY,
      transpose[2][0], -transpose[2][1], -transpose[2][2], cameraZ,
      0, 0, 0, 1
    );
    cameraMatrix.decompose(camera.position, camera.quaternion, camera.scale);
    camera.updateMatrixWorld(true);

    const stale = Math.max(0, Math.min(1, Number(payload.heldAge) || 0));
    const confidence = 1 - stale * 0.75;
    const count = payload.chevrons.length;
    payload.chevrons.forEach((polygon, index) => {
      const baseOpacity = payload.alphas && index < payload.alphas.length
        ? payload.alphas[index]
        : payload.marker
          ? 0.95
          : 1 - (index / Math.max(1, count - 1)) * DISTANCE_FADE;
      if (!(baseOpacity > 0.01)) {
        return;
      }
      const mesh = createPolygonMesh(
        polygon,
        baseOpacity * confidence,
        payload.marker ? MARKER_COLOR : CHEVRON_COLOR
      );
      if (mesh) {
        scene.add(mesh);
        meshesRef.current.push(mesh);
      }
    });
    renderer.render(scene, camera);
  }, [enabled, payload]);

  return (
    <canvas
      ref={canvasRef}
      className={`pointer-events-none absolute z-10 ${enabled ? 'block' : 'hidden'}`}
      aria-hidden="true"
    />
  );
};

export default ARWorldOverlay;
