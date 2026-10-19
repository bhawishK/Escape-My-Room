import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { DESK_MARKER, MARKER_CAMERA, STANDING_AT } from './fake-camera';
import { loadOpenCV, lookAt, renderMarkers, y4m } from './synthetic';

/** Writes the fake camera's video. Chromium loops it for as long as a page uses it. */
export default async function setup(): Promise<void> {
  const { cv } = await loadOpenCV();
  const directory = process.env.ESCAPE_ROOM_FAKE_CAMERA!;
  const seen = renderMarkers(cv, MARKER_CAMERA, lookAt(STANDING_AT, DESK_MARKER.position), [DESK_MARKER]);
  const empty = renderMarkers(cv, MARKER_CAMERA, lookAt(STANDING_AT, DESK_MARKER.position), []);
  // At 10 frames per second: 1.5 s with the tag in view, then 1 s without it.
  writeFileSync(join(directory, 'desk-marker.y4m'), y4m([...Array(15).fill(seen), ...Array(10).fill(empty)], 10));
}
