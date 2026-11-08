// A physics worker that starts, then dies when the room loads, so tests see physics stop mid-session.
import { createInterface } from 'node:readline';

process.stdout.write(`${JSON.stringify({ type: 'ready', engine: 'havok', version: 'fake' })}\n`);
createInterface({ input: process.stdin }).on('line', () => {
  process.stderr.write('The fake worker crashed on purpose.\n');
  process.exit(3);
});
