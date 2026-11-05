import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { defineConfig } from 'vite';

/**
 * The headset page (#156), built apart from the phone's page. Immersive Web SDK brings its own
 * three.js (super-three) while the phone's page uses the project's three.js; one copy must draw
 * everything here, or Spark's splat and IWSDK's scene would not mix. So every `three` import on
 * this page, Spark's and the shared modules' included, goes to IWSDK's copy.
 */
const iwsdk = dirname(createRequire(import.meta.url).resolve('@iwsdk/core/package.json'));
// `three` resolves to its `build/three.cjs`; the package is two folders up.
const three = dirname(dirname(createRequire(join(iwsdk, 'package.json')).resolve('three')));

export default defineConfig({
  resolve: {
    alias: [
      { find: /^three$/, replacement: join(three, 'build', 'three.module.js') },
      { find: /^three\/addons\/(.*)$/, replacement: join(three, 'examples', 'jsm', '$1') },
      { find: /^three\/examples\/(.*)$/, replacement: join(three, 'examples', '$1') },
    ],
  },
  server: {
    port: 5174,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', ws: true },
      '/assets': { target: 'http://127.0.0.1:8000' },
    },
  },
  build: {
    // Beside the phone's build, which empties `dist` first: this one must not.
    emptyOutDir: false,
    rolldownOptions: { input: { quest: 'quest/index.html' } },
  },
});
