// Run from frontend/: `npm run markers`. Vite loads the TypeScript sources the tracker uses.
import { runnerImport } from 'vite';

const { module } = await runnerImport('./scripts/markers.ts');
const written = await module.writeSheets('../assets/prepared-room/manifest.json', '../docs/markers');
console.log(`wrote ${written.join(', ')} to docs/markers`);
process.exit(0);
