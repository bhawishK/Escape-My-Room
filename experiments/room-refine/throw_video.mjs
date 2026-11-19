// Draws recorded throws (throw_trace.py) with Spark in a headless browser, as the headset would.
//
//   node experiments/room-refine/throw_video.mjs ROOM_DIR THROWS.json OUT_DIR
//
// For each throw it writes OUT_DIR/<n>-<frame>-seen.png and -xray.png; throw_gif.py joins them.
// Run from the repository root, so frontend/node_modules has three, Spark and Playwright.
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(resolve('frontend/package.json'));
const { chromium } = require('@playwright/test');

const [roomDir, throwsFile, outDir] = process.argv.slice(2).map(arg => resolve(arg));
const here = fileURLToPath(new URL('.', import.meta.url));
const modules = resolve('frontend/node_modules');
const ORIGIN = 'http://throw-video.invalid';
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json' };
const ROOTS = {
  '/three/': join(modules, 'three'),
  '/spark/': join(modules, '@sparkjsdev', 'spark'),
  '/room/': roomDir,
};

function inside(folder, relative) {
  const path = normalize(join(folder, decodeURIComponent(relative)));
  return path.startsWith(normalize(folder) + sep) ? path : null;
}

const recorded = JSON.parse(await readFile(throwsFile, 'utf8'));
await mkdir(outDir, { recursive: true });
const browser = await chromium.launch({
  channel: process.env.PW_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined),
  headless: true,
  args: ['--enable-unsafe-swiftshader'],
});
try {
  const page = await browser.newPage();
  const problems = [];
  page.on('pageerror', error => problems.push(String(error)));
  await page.route(`${ORIGIN}/**`, async route => {
    const path = new URL(route.request().url()).pathname;
    const prefix = Object.keys(ROOTS).find(start => path.startsWith(start));
    const file = path === '/' ? join(here, 'throw_video.html')
      : prefix ? inside(ROOTS[prefix], path.slice(prefix.length)) : null;
    try {
      if (!file) throw new Error('outside');
      await route.fulfill({ body: await readFile(file), contentType: TYPES[extname(file)] ?? 'application/octet-stream' });
    } catch {
      await route.fulfill({ status: 404, body: 'Not found' });
    }
  });
  for (const [index, flight] of recorded.flights.entries()) {
    await page.goto(`${ORIGIN}/`);
    await page.waitForFunction(() => window.ready === true, null, { timeout: 60_000 })
      .catch(() => { throw new Error(`The page did not start. ${problems.join(' ')}`); });
    // Look from the thrower's eyes toward where the throw goes, a metre and a half on, level.
    const [hx, , hz] = flight.hand;
    const [vx, , vz] = flight.velocity;
    const length = Math.hypot(vx, vz);
    const look_at = [hx + (vx / length) * 1.5, 0.6, hz + (vz / length) * 1.5];
    const started = performance.now();
    const frames = await page.evaluate(body => window.drawThrow(body), {
      eye: recorded.eye, look_at, box_size: recorded.box_size, frames: flight.frames, width: 480, height: 360,
    });
    for (const [n, frame] of frames.entries()) {
      for (const kind of ['seen', 'xray']) {
        const name = `${index + 1}-${String(n).padStart(3, '0')}-${kind}.png`;
        await writeFile(join(outDir, name), Buffer.from(frame[kind].split(',')[1], 'base64'));
      }
    }
    console.log(`${flight.name}: ${frames.length} frames in ${((performance.now() - started) / 1000).toFixed(0)} s`);
  }
  if (problems.length) console.log(`Page problems: ${problems.join(' ')}`);
} finally {
  await browser.close();
}
