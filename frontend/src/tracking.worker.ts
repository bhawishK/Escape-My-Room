import cvModule from '@techstark/opencv-js';
import type { CameraIntrinsics, TrackingMarker } from './protocol';
import { BoardCalibrator, MarkerLocator, openCV, type Frame, type Located } from './vision';

/* OpenCV runs here, off the page's thread, so the 3D view keeps its frame rate. */

export type WorkerRequest =
  | { kind: 'locate'; token: number; frame: Frame; intrinsics: CameraIntrinsics; markers: TrackingMarker[] }
  | { kind: 'board'; token: number; frame: Frame }
  | { kind: 'solve'; token: number }
  | { kind: 'reset-board' };

export type WorkerReply =
  | { kind: 'ready' }
  | { kind: 'load-failed'; message: string }
  | { kind: 'located'; token: number; result: Located; millis: number }
  | { kind: 'board'; token: number; corners: number; views: number }
  | { kind: 'solved'; token: number; intrinsics: CameraIntrinsics; rmsPx: number }
  | { kind: 'solve-failed'; token: number; message: string };

// The project compiles against the DOM library; these are the worker globals this file uses.
const scope = self as unknown as {
  postMessage(message: WorkerReply): void;
  onmessage: ((event: MessageEvent<WorkerRequest>) => void) | null;
};
const reply = (message: WorkerReply) => scope.postMessage(message);

openCV(cvModule).then(({ cv }) => {
  const locator = new MarkerLocator(cv);
  const calibrator = new BoardCalibrator(cv);
  scope.onmessage = (event: MessageEvent<WorkerRequest>) => {
    const request = event.data;
    if (request.kind === 'locate') {
      const started = performance.now();
      const result = locator.locate(request.frame, request.intrinsics, request.markers);
      reply({ kind: 'located', token: request.token, result, millis: performance.now() - started });
    } else if (request.kind === 'board') {
      const { corners } = calibrator.addView(request.frame);
      reply({ kind: 'board', token: request.token, corners, views: calibrator.views });
    } else if (request.kind === 'solve') {
      try {
        const { intrinsics, rmsPx } = calibrator.solve();
        reply({ kind: 'solved', token: request.token, intrinsics, rmsPx });
      } catch (error) {
        const message = error instanceof Error ? error.message : 'The calibration could not be solved.';
        reply({ kind: 'solve-failed', token: request.token, message });
      }
    } else {
      calibrator.reset();
    }
  };
  reply({ kind: 'ready' });
}).catch((error: unknown) => {
  reply({ kind: 'load-failed', message: error instanceof Error ? error.message : 'OpenCV could not load.' });
});
