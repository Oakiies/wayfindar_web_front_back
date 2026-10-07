/* eslint-disable @typescript-eslint/no-explicit-any */
import type { TrackingSeed } from '../services/navigationTestService';

type OpenCv = any;

export interface BrowserPoseEstimate {
  R: [[number, number, number], [number, number, number], [number, number, number]];
  t: [number, number, number];
  inliers: number;
  tracked: number;
  reprojectionErrorPx: number | null;
  mapPosition: { x: number; y: number } | null;
}

declare global {
  interface Window {
    cv?: OpenCv;
  }
}

let cvPromise: Promise<OpenCv | null> | null = null;

/** Load OpenCV.js once. Tracking remains disabled if a deployment blocks the CDN. */
function loadOpenCv(): Promise<OpenCv | null> {
  if (typeof window === 'undefined') {
    return Promise.resolve(null);
  }
  if (window.cv && typeof window.cv.Mat === 'function') {
    return Promise.resolve(window.cv);
  }
  if (cvPromise) {
    return cvPromise;
  }

  cvPromise = new Promise<OpenCv | null>((resolve) => {
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://docs.opencv.org/4.x/opencv.js';
    script.onload = () => {
      const cv = window.cv;
      if (!cv) {
        resolve(null);
        return;
      }
      if (cv.Mat) {
        resolve(cv);
        return;
      }
      cv.onRuntimeInitialized = () => resolve(window.cv ?? null);
      window.setTimeout(() => resolve(window.cv ?? null), 15_000);
    };
    script.onerror = () => resolve(null);
    document.head.appendChild(script);
  });
  return cvPromise;
}

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * Causal browser tracker: KLT follows the seeded 2D points in the current
 * camera frame, then PnP-RANSAC estimates the current pose from their fixed
 * 3D map points. It never reads a future frame and never sends these tracking
 * frames back to the server.
 */
export class BrowserKltPnPTracker {
  private cv: OpenCv | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private context: CanvasRenderingContext2D | null = null;
  private previousGray: any = null;
  private previousPoints: Array<[number, number]> = [];
  private points3d: Array<[number, number, number]> = [];
  private mapPointIds: number[] = [];
  private K: [number, number, number, number] | null = null;
  private imgWH: [number, number] | null = null;
  private floorProjection: TrackingSeed['floor_projection'] = null;
  private disposed = false;

  async warmup(): Promise<boolean> {
    this.cv = await loadOpenCv();
    return Boolean(this.cv);
  }

  reset(seed: TrackingSeed | null | undefined): void {
    this.releaseMat(this.previousGray);
    this.previousGray = null;
    this.previousPoints = [];
    this.points3d = [];
    this.mapPointIds = [];
    this.K = null;
    this.imgWH = null;
    this.floorProjection = null;

    if (!seed) {
      return;
    }
    const count = Math.min(seed.points_2d.length, seed.points_3d.length, seed.map_point_ids.length);
    for (let i = 0; i < count; i += 1) {
      const p2 = seed.points_2d[i];
      const p3 = seed.points_3d[i];
      const id = seed.map_point_ids[i];
      if (p2?.length === 2 && p3?.length === 3 && finite(p2[0]) && finite(p2[1]) &&
          finite(p3[0]) && finite(p3[1]) && finite(p3[2]) && Number.isFinite(id)) {
        this.previousPoints.push([p2[0], p2[1]]);
        this.points3d.push([p3[0], p3[1], p3[2]]);
        this.mapPointIds.push(id);
      }
    }
    this.K = seed.K;
    this.imgWH = seed.imgWH;
    this.floorProjection = seed.floor_projection ?? null;
  }

  get pointCount(): number {
    return this.previousPoints.length;
  }

  async process(video: HTMLVideoElement): Promise<BrowserPoseEstimate | null> {
    if (this.disposed || !this.cv || this.previousPoints.length < 6 ||
        !this.K || !this.imgWH || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
      return null;
    }
    const width = this.imgWH[0];
    const height = this.imgWH[1];
    if (!width || !height || !video.videoWidth || !video.videoHeight) {
      return null;
    }
    if (!this.canvas) {
      this.canvas = document.createElement('canvas');
      this.context = this.canvas.getContext('2d', { alpha: false, desynchronized: true });
    }
    if (!this.context) {
      return null;
    }
    this.canvas.width = width;
    this.canvas.height = height;
    this.context.drawImage(video, 0, 0, width, height);
    const image = this.context.getImageData(0, 0, width, height);
    const cv = this.cv;
    const gray = new cv.Mat(height, width, cv.CV_8UC4);
    gray.data.set(image.data);
    cv.cvtColor(gray, gray, cv.COLOR_RGBA2GRAY);

    if (!this.previousGray) {
      this.previousGray = gray;
      return null;
    }

    const previous = cv.matFromArray(this.previousPoints.length, 1, cv.CV_32FC2,
      this.previousPoints.flat());
    const next = new cv.Mat();
    const status = new cv.Mat();
    const error = new cv.Mat();
    const winSize = new cv.Size(21, 21);
    const criteria = new cv.TermCriteria(cv.TERM_CRITERIA_EPS | cv.TERM_CRITERIA_COUNT, 30, 0.01);
    cv.calcOpticalFlowPyrLK(this.previousGray, gray, previous, next, status, error, winSize, 3, criteria);

    const tracked2d: Array<[number, number]> = [];
    const tracked3d: Array<[number, number, number]> = [];
    const trackedIds: number[] = [];
    for (let i = 0; i < this.previousPoints.length; i += 1) {
      if (status.data[i] !== 1) continue;
      const x = next.data32F[i * 2];
      const y = next.data32F[i * 2 + 1];
      if (!finite(x) || !finite(y) || x < 0 || y < 0 || x >= width || y >= height) continue;
      tracked2d.push([x, y]);
      tracked3d.push(this.points3d[i]);
      trackedIds.push(this.mapPointIds[i]);
    }

    const pose = this.solvePnP(tracked2d, tracked3d);
    this.releaseMat(this.previousGray);
    this.previousGray = gray;
    this.releaseMat(previous);
    this.releaseMat(next);
    this.releaseMat(status);
    this.releaseMat(error);
    this.previousPoints = tracked2d;
    this.points3d = tracked3d;
    this.mapPointIds = trackedIds;
    return pose;
  }

  dispose(): void {
    this.disposed = true;
    this.releaseMat(this.previousGray);
    this.previousGray = null;
    this.previousPoints = [];
    this.points3d = [];
    this.mapPointIds = [];
  }

  private solvePnP(points2d: Array<[number, number]>, points3d: Array<[number, number, number]>): BrowserPoseEstimate | null {
    if (!this.cv || !this.K || points2d.length < 6) return null;
    const cv = this.cv;
    const objectPoints = cv.matFromArray(points3d.length, 1, cv.CV_32FC3, points3d.flat());
    const imagePoints = cv.matFromArray(points2d.length, 1, cv.CV_32FC2, points2d.flat());
    const cameraMatrix = cv.matFromArray(3, 3, cv.CV_64F, [
      this.K[0], 0, this.K[2], 0, this.K[1], this.K[3], 0, 0, 1,
    ]);
    const distortion = cv.Mat.zeros(4, 1, cv.CV_64F);
    const rvec = new cv.Mat();
    const tvec = new cv.Mat();
    const inlierMat = new cv.Mat();
    let ok = false;
    try {
      ok = cv.solvePnPRansac(objectPoints, imagePoints, cameraMatrix, distortion,
        rvec, tvec, false, 100, 8.0, 0.99, inlierMat,
        cv.SOLVEPNP_ITERATIVE ?? 0);
      if (!ok) return null;
      const rotation = new cv.Mat();
      cv.Rodrigues(rvec, rotation);
      const R = Array.from({ length: 3 }, (_, row) =>
        Array.from({ length: 3 }, (_, col) => Number(rotation.doubleAt(row, col)))) as BrowserPoseEstimate['R'];
      const t: [number, number, number] = [
        Number(tvec.doubleAt(0, 0)), Number(tvec.doubleAt(1, 0)), Number(tvec.doubleAt(2, 0)),
      ];
      const inliers = inlierMat.rows > 0 ? inlierMat.rows : 0;
      this.releaseMat(rotation);
      return {
        R,
        t,
        inliers,
        tracked: points2d.length,
        reprojectionErrorPx: null,
        mapPosition: this.projectCameraCenter(R, t),
      };
    } finally {
      this.releaseMat(objectPoints);
      this.releaseMat(imagePoints);
      this.releaseMat(cameraMatrix);
      this.releaseMat(distortion);
      this.releaseMat(rvec);
      this.releaseMat(tvec);
      this.releaseMat(inlierMat);
    }
  }

  private releaseMat(mat: any): void {
    if (mat && typeof mat.delete === 'function') mat.delete();
  }

  private projectCameraCenter(
    R: BrowserPoseEstimate['R'],
    t: [number, number, number],
  ): { x: number; y: number } | null {
    const projection = this.floorProjection;
    if (!projection) return null;
    // PnP returns world-to-camera Xc = R Xw + t. The camera centre is -Rᵀt.
    const center: [number, number, number] = [
      -(R[0][0] * t[0] + R[1][0] * t[1] + R[2][0] * t[2]),
      -(R[0][1] * t[0] + R[1][1] * t[1] + R[2][1] * t[2]),
      -(R[0][2] * t[0] + R[1][2] * t[1] + R[2][2] * t[2]),
    ];
    const vec: [number, number, number] = [
      center[0] - projection.traj_center[0],
      center[1] - projection.traj_center[1],
      center[2] - projection.traj_center[2],
    ];
    const x = vec[0] * projection.floor_v1[0] + vec[1] * projection.floor_v1[1] + vec[2] * projection.floor_v1[2];
    const y = vec[0] * projection.floor_v2[0] + vec[1] * projection.floor_v2[1] + vec[2] * projection.floor_v2[2];
    const h = projection.H;
    const w = h[2][0] * x + h[2][1] * y + h[2][2];
    if (!Number.isFinite(w) || Math.abs(w) < 1e-9) return null;
    const px = (h[0][0] * x + h[0][1] * y + h[0][2]) / w;
    const py = (h[1][0] * x + h[1][1] * y + h[1][2]) / w;
    return Number.isFinite(px) && Number.isFinite(py) ? { x: px, y: py } : null;
  }
}
