/** Live-camera capture constants + error mapping (extracted from App.tsx). */

export const LOCALHOST_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);
export const LIVE_CAMERA_CAPTURE_INTERVAL_MS = 1000;
export const LIVE_CAMERA_MAX_WIDTH = 960;
export const LIVE_CAMERA_JPEG_QUALITY = 0.7;

export function resolveCameraErrorMessage(error: unknown): string {
  if (!error || typeof error !== 'object') {
    return 'Unable to access camera';
  }

  const errorName = 'name' in error && typeof error.name === 'string' ? error.name : '';

  switch (errorName) {
    case 'NotAllowedError':
      return 'Camera permission denied. Allow camera access in browser settings.';
    case 'NotFoundError':
      return 'No camera device found on this phone.';
    case 'NotReadableError':
      return 'Camera is being used by another app.';
    case 'OverconstrainedError':
      return 'Requested camera mode is not supported on this device.';
    case 'SecurityError':
      return 'Camera requires HTTPS when opening from mobile network.';
    default:
      return 'Unable to start camera. Check camera permission and HTTPS URL.';
  }
}
