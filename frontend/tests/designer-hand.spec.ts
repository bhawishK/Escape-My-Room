import { expect, test } from '@playwright/test';

// The designer's giant hand on the phone (#185). The test is the headset, over its own socket.
const ORIGIN = 'http://127.0.0.1:8771';

/** A headset socket that has been welcomed, and a sender for its hand. */
async function headset(): Promise<{ hand: (position: object | null) => void; close: () => void }> {
  const socket = new WebSocket(`${ORIGIN.replace('http', 'ws')}/api/ws?role=vr_solver`);
  await new Promise<void>((resolve, reject) => {
    socket.addEventListener('message', () => resolve(), { once: true });
    socket.addEventListener('error', () => reject(new Error('The headset socket failed.')), { once: true });
  });
  let sequence = 0;
  return {
    hand: position => socket.send(JSON.stringify({ type: 'designer_hand', sequence: ++sequence, position })),
    close: () => socket.close(),
  };
}

test('the phone shows the designer\'s hand while it reaches in, and hides it when it goes or stops coming', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${ORIGIN}/`);
  await page.getByRole('button', { name: 'Connect phone', exact: true }).click();
  const scene = page.locator('#scene');
  const designer = await headset();
  try {
    designer.hand({ x: 0.5, y: 1.0, z: -0.4 });
    await expect(scene).toHaveAttribute('data-designer-hand', 'shown');
    designer.hand(null);
    await expect(scene).toHaveAttribute('data-designer-hand', '');

    // A hand that stops coming lapses, as a stale presence does, after 1.5 s.
    designer.hand({ x: 0.2, y: 1.0, z: -0.4 });
    await expect(scene).toHaveAttribute('data-designer-hand', 'shown');
    await expect(scene).toHaveAttribute('data-designer-hand', '', { timeout: 3000 });
  } finally {
    designer.close();
  }
});
