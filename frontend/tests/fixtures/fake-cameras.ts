import type { Page } from '@playwright/test';

/**
 * Cameras that play a blank picture, remembering which way each was asked to face. Opening one
 * while another is still live is recorded too: a phone browser runs one camera at a time.
 */
export function fakeCameras(): void {
  // The canvas is kept, so its track only ends when the page stops it.
  const opened: { facing: string; stream: MediaStream; canvas: HTMLCanvasElement }[] = [];
  const overlaps: string[] = [];
  Object.assign(window, { openedCameras: opened, cameraOverlaps: overlaps });
  Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { value: async (constraints: MediaStreamConstraints) => {
    const facing = JSON.stringify((constraints.video as MediaTrackConstraints).facingMode);
    const live = opened.filter(camera => camera.stream.getTracks().some(track => track.readyState === 'live'));
    if (live.length > 0) overlaps.push(`${facing} opened while ${live.map(camera => camera.facing).join(', ')} live`);
    const canvas = document.createElement('canvas');
    canvas.width = 640;
    canvas.height = 480;
    canvas.getContext('2d')!.fillRect(0, 0, 640, 480);
    const stream = canvas.captureStream(10);
    opened.push({ facing, stream, canvas });
    return stream;
  } });
}

/** Which cameras are still running: "front", "back", or both. */
export const liveCameras = (page: Page) => page.evaluate(() =>
  (window as unknown as { openedCameras: { facing: string; stream: MediaStream }[] }).openedCameras
    .filter(camera => camera.stream.getTracks().some(track => track.readyState === 'live'))
    .map(camera => (camera.facing.includes('environment') ? 'back' : 'front')));

/** Every time a camera opened while another was still live. */
export const cameraOverlaps = (page: Page) => page.evaluate(() =>
  (window as unknown as { cameraOverlaps: string[] }).cameraOverlaps);
