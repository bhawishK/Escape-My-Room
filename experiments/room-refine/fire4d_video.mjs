// Renders a generated 4D fire (L4GM splat frames, #220) inside a room with Spark, headless.
//
//   node experiments/room-refine/fire4d_video.mjs ROOM_DIR FRAMES_DIR OUT_DIR
//
// Writes OUT_DIR/<view>-<frame>.png. Run from the repository root (frontend/node_modules).
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(resolve('frontend/package.json'));
const { chromium } = require('@playwright/test');

const [roomDir, framesDir, outDir] = process.argv.slice(2).map(arg => resolve(arg));
const here = fileURLToPath(new URL('.', import.meta.url));
const modules = resolve('frontend/node_modules');
const ORIGIN = 'http://fire-4d.invalid';
const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.json': 'application/json' };
const ROOTS = { '/three/': join(modules, 'three'), '/spark/': join(modules, '@sparkjsdev', 'spark'), '/room/': roomDir, '/fire/': framesDir };

// The bedside power strip in room 10 (the concept's ignition point), and L4GM's object: its base
// at y = -0.43 and 0.72 units long, scaled to a 30 cm power strip.
const FIRE = process.env.FIRE ? JSON.parse(process.env.FIRE)
  : { at: [0.95, 0.74, -1.02], base: -0.43, scale: Number(process.env.FIRE_SCALE || 1) * 0.30 / 0.72, turn: 0.4 };
// Where to look from: FIRE_VIEWS as JSON, else the power strip's two views.
const VIEWS = process.env.FIRE_VIEWS ? JSON.parse(process.env.FIRE_VIEWS) : [
  { name: 'room', eye: [-0.7, 1.6, 0.55], at: [0.75, 0.8, -1.0], fov: 70 },
  { name: 'close', eye: [0.25, 1.15, -0.25], at: [0.95, 0.85, -1.02], fov: 55 },
];

function inside(folder, relative) {
  const path = normalize(join(folder, decodeURIComponent(relative)));
  return path.startsWith(normalize(folder) + sep) ? path : null;
}

await mkdir(outDir, { recursive: true });
const frames = (await readdir(framesDir)).filter(name => name.endsWith('.ply')).sort();
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
    const file = path === '/' ? join(here, 'fire4d_video.html') : prefix ? inside(ROOTS[prefix], path.slice(prefix.length)) : null;
    try {
      if (!file) throw new Error('outside');
      await route.fulfill({ body: await readFile(file), contentType: TYPES[extname(file)] ?? 'application/octet-stream' });
    } catch {
      await route.fulfill({ status: 404, body: 'Not found' });
    }
  });
  await page.goto(`${ORIGIN}/`);
  await page.waitForFunction(() => window.ready === true, null, { timeout: 60_000 })
    .catch(() => { throw new Error(`The page did not start. ${problems.join(' ')}`); });
  const started = performance.now();
  const shots = await page.evaluate(body => window.drawFire(body), {
    frames: frames.map(name => `${ORIGIN}/fire/${name}`), fire: FIRE, views: VIEWS, width: 960, height: 600,
  });
  for (const [view, images] of Object.entries(shots)) {
    for (const [n, png] of images.entries()) {
      await writeFile(join(outDir, `${view}-${String(n).padStart(3, '0')}.png`), Buffer.from(png.split(',')[1], 'base64'));
    }
  }
  console.log(`${frames.length} frames x ${VIEWS.length} views in ${((performance.now() - started) / 1000).toFixed(0)} s`);
  if (problems.length) console.log(`Page problems: ${problems.join(' ')}`);
} finally {
  await browser.close();
}
