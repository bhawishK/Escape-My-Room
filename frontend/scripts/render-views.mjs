// Render-and-ask (#98): render views of a splat room in a headless browser, for Python.
//
//   node frontend/scripts/render-views.mjs < request.json
//
// The request names the built frontend (`dist`), the room folder, its splat and placement, the
// views, and where to write them. Each view is written as `view-<n>.png` there; stdout is one JSON
// line: {"load_seconds": s, "views": [{"file": ..., "seconds": ...}]}. Nothing is served on a
// port: the browser's requests are answered from those two folders.
import { readFile, writeFile } from 'node:fs/promises';
import { extname, join, normalize, sep } from 'node:path';
import { chromium } from '@playwright/test';

const ORIGIN = 'http://room-views.invalid';
const TYPES = {
  '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css',
  '.wasm': 'application/wasm', '.json': 'application/json', '.ply': 'application/octet-stream',
  '.spz': 'application/octet-stream',
};

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

/** The file under `folder` that `relative` names, or null when it points outside. */
function inside(folder, relative) {
  const path = normalize(join(folder, decodeURIComponent(relative)));
  return path.startsWith(normalize(folder) + sep) ? path : null;
}

const request = await readStdin();
const browser = await chromium.launch({
  channel: process.env.PW_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined),
  headless: true,
  // Without a GPU, WebGL runs on the CPU (SwiftShader); Chromium now asks for it explicitly.
  args: ['--enable-unsafe-swiftshader'],
});
try {
  const page = await browser.newPage();
  const problems = [];
  page.on('pageerror', error => problems.push(String(error)));
  await page.route(`${ORIGIN}/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    const file = path.startsWith('/room/')
      ? inside(request.room_dir, path.slice('/room/'.length))
      : inside(request.dist, path === '/' ? 'render.html' : path.slice(1));
    try {
      if (!file) throw new Error('outside');
      await route.fulfill({
        body: await readFile(file),
        contentType: TYPES[extname(file)] ?? 'application/octet-stream',
      });
    } catch {
      await route.fulfill({ status: 404, body: 'Not found' });
    }
  });
  const started = performance.now();
  await page.goto(`${ORIGIN}/render.html`);
  await page.waitForFunction(() => typeof window.renderViews === 'function', null, { timeout: 30_000 })
    .catch(() => { throw new Error(`The render page did not start. ${problems.join(' ')}`.trim()); });
  const rendered = await page.evaluate(
    body => window.renderViews(body),
    { splat_url: `${ORIGIN}/room/${request.splat}`, placement: request.placement, views: request.views },
  );
  const views = [];
  for (const [index, view] of rendered.entries()) {
    const file = join(request.out_dir, `view-${index + 1}.png`);
    await writeFile(file, Buffer.from(view.png.split(',')[1], 'base64'));
    views.push({ file, seconds: view.seconds });
  }
  const load_seconds = (performance.now() - started) / 1000 - views.reduce((sum, v) => sum + v.seconds, 0);
  process.stdout.write(JSON.stringify({ load_seconds, views }) + '\n');
} catch (error) {
  process.stderr.write(`${error instanceof Error ? error.message : error}\n`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
