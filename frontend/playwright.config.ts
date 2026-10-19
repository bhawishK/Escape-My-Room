import { defineConfig } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('../', import.meta.url)));
const python = join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
/** One Python server: the prepared room it serves and any extra settings. */
interface TestServer { port: number; room: string; settings: Record<string, string> }
const servers: TestServer[] = [
  { port: 8771, room: 'prepared-room', settings: {} },
  { port: 8772, room: 'multi-asset-room', settings: {} },
  // The development preparation worker, configured to fail its geometry stage.
  { port: 8773, room: 'prepared-room', settings: { ESCAPE_ROOM_FIXTURE_FAIL_STAGE: 'geometry' } },
];

// One fresh capture store per run. Workers inherit the variable, so they agree with the servers.
process.env.ESCAPE_ROOM_TEST_DATA ??= mkdtempSync(join(tmpdir(), 'escape-my-room-captures-'));
// Synthetic camera videos, written by the global setup before any browser starts.
process.env.ESCAPE_ROOM_FAKE_CAMERA ??= mkdtempSync(join(tmpdir(), 'escape-my-room-camera-'));
const fakeCamera = (video: string) => ({
  launchOptions: {
    args: [
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-video-capture=${join(process.env.ESCAPE_ROOM_FAKE_CAMERA!, video)}`,
    ],
  },
});

export default defineConfig({
  testDir: './tests',
  globalSetup: './tests/fake-camera.setup.ts',
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:8771',
    channel: process.env.PW_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined),
    headless: true,
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'default', testIgnore: /camera-.*\.spec\.ts/ },
    // The camera sees the stand-in room's desk tag from a known pose, then nothing, in a loop.
    { name: 'marker-camera', testMatch: /camera-tracking\.spec\.ts/, use: fakeCamera('desk-marker.y4m') },
    // The camera sees the calibration board in a series of tilts.
    { name: 'board-camera', testMatch: /camera-calibration\.spec\.ts/, use: fakeCamera('board.y4m') },
  ],
  webServer: servers.map(({ port, room, settings }) => ({
    command: `"${python}" -m uvicorn backend.app:app --app-dir "${root}" --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    env: {
      ESCAPE_ROOM_PREPARED_DIR: join(root, 'assets', room),
      ESCAPE_ROOM_DATA_DIR: join(process.env.ESCAPE_ROOM_TEST_DATA!, String(port)),
      // Small limits so the fixture photos can exceed them.
      ESCAPE_ROOM_CAPTURE_MAX_IMAGES: '4',
      ESCAPE_ROOM_CAPTURE_MAX_IMAGE_BYTES: String(64 * 1024),
      ESCAPE_ROOM_CAPTURE_MAX_IMAGE_PIXELS: '250000',
      // The deterministic development worker, slow enough for progress to be visible.
      ESCAPE_ROOM_PREPARATION_WORKER: 'fixture',
      ESCAPE_ROOM_FIXTURE_STAGE_SECONDS: '0.6',
      ...settings,
    },
    reuseExistingServer: false,
  })),
});
