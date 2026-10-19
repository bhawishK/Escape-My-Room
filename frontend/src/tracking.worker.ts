/** OpenCV runs here, off the page's thread, so the 3D view keeps its frame rate. */
import cvModule from '@techstark/opencv-js';
import type { CameraIntrinsics, TrackingMarker } from './protocol';
import { MarkerLocator, openCV, type Frame, type Located } from './vision';

export interface WorkerRequest {
  kind: 'locate';
  token: number;
  frame: Frame;
  intrinsics: CameraIntrinsics;
  markers: TrackingMarker[];
}

export type WorkerReply =
  | { kind: 'ready' }
  | { kind: 'load-failed'; message: string }
  | { kind: 'located'; token: number; result: Located; millis: number };

// The project compiles against the DOM library; these are the worker globals this file uses.
const scope = self as unknown as {
  postMessage(message: WorkerReply): void;
  onmessage: ((event: MessageEvent<WorkerRequest>) => void) | null;
};
const reply = (message: WorkerReply) => scope.postMessage(message);

openCV(cvModule).then(({ cv }) => {
  const locator = new MarkerLocator(cv);
  scope.onmessage = (event: MessageEvent<WorkerRequest>) => {
    const request = event.data;
    const started = performance.now();
    const result = locator.locate(request.frame, request.intrinsics, request.markers);
    reply({ kind: 'located', token: request.token, result, millis: performance.now() - started });
  };
  reply({ kind: 'ready' });
}).catch((error: unknown) => {
  reply({ kind: 'load-failed', message: error instanceof Error ? error.message : 'OpenCV could not load.' });
});
