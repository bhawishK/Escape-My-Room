/** Explains why the phone's camera could not start, for the person holding it. */
export function cameraError(error: unknown, which: 'front' | 'back'): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
      return 'Camera permission was denied. Allow camera access for this site in the browser settings, then try again.';
    }
    if (error.name === 'NotFoundError' || error.name === 'OverconstrainedError') return `No ${which} camera was found on this device.`;
    if (error.name === 'NotReadableError' || error.name === 'AbortError') {
      return 'The camera is in use by another app. Close it and try again.';
    }
  }
  return error instanceof Error ? error.message : 'The camera could not start.';
}
