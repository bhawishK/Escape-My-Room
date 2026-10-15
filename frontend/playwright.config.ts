import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';
import { join, resolve } from 'node:path';

const root = resolve(fileURLToPath(new URL('../', import.meta.url)));
const python = join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');

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
    env: { ESCAPE_ROOM_PREPARED_DIR: join(root, 'assets', room) },
    reuseExistingServer: false,
  })),
});
