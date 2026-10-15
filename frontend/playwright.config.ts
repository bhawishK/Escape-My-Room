import { defineConfig } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('../', import.meta.url)));
const python = join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
// One fresh capture store per run. Workers inherit the variable, so they agree with the servers.
process.env.ESCAPE_ROOM_TEST_DATA ??= mkdtempSync(join(tmpdir(), 'escape-my-room-captures-'));

export default defineConfig({
  testDir: './tests',
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:8771',
    channel: process.env.PW_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined),
    headless: true,
    screenshot: 'only-on-failure',
  },
  webServer: [
    { port: 8771, room: 'prepared-room' },
    { port: 8772, room: 'multi-asset-room' },
  ].map(({ port, room }) => ({
    command: `"${python}" -m uvicorn backend.app:app --app-dir "${root}" --host 127.0.0.1 --port ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    env: {
      ESCAPE_ROOM_PREPARED_DIR: join(root, 'assets', room),
      ESCAPE_ROOM_DATA_DIR: join(process.env.ESCAPE_ROOM_TEST_DATA!, String(port)),
      // Small limits so the fixture photos can exceed them.
      ESCAPE_ROOM_CAPTURE_MAX_IMAGES: '4',
      ESCAPE_ROOM_CAPTURE_MAX_IMAGE_BYTES: String(64 * 1024),
      ESCAPE_ROOM_CAPTURE_MAX_IMAGE_PIXELS: '250000',
    },
    reuseExistingServer: false,
  })),
});
