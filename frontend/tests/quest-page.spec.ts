import { type Page, expect, test } from '@playwright/test';

// The headset's page in Immersive Web SDK (#156), at /quest/. Desktop browsers have no VR, so
// these cover what happens before VR: joining, the room and its splat, and standing on the map.

async function connectHeadset(page: Page, origin = ''): Promise<void> {
  await page.goto(`${origin}/quest/`);
  await page.getByRole('button', { name: 'Connect headset', exact: true }).click();
  await expect(page.getByTestId('connection')).toHaveText('Connected · VR headset');
}

test('the headset page joins as the headset, and the phone sees it come and go', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const headset = await browser.newPage();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(phone.getByTestId('vr-status')).toHaveText('Waiting for VR device');

  await connectHeadset(headset);
  await expect(phone.getByTestId('vr-status')).toHaveText('VR device connected');
  await expect(headset.getByTestId('phone-status')).toHaveText('Phone connected');
  await headset.getByRole('button', { name: 'Disconnect', exact: true }).click();
  await expect(phone.getByTestId('vr-status')).toHaveText('Waiting for VR device');
  await phone.close();
  await headset.close();
});

test('the headset page loads the live room into its scene', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await connectHeadset(page);
  await expect(page.getByTestId('room-status')).toHaveText(/^Room ready · version \d+$/);
  await expect(page.getByTestId('quest-scene')).toHaveAttribute('data-room-version', /\d+/);
  // A desktop browser has no VR: the page says so and does not offer it.
  await expect(page.getByRole('button', { name: 'Enter VR', exact: true })).toBeDisabled();
  await expect(page.getByTestId('report')).toContainText('"iwsdk_version": "1.0.1"');
  expect(errors.filter(text => text.includes('THREE'))).toEqual([]);
});

test('a splat room is drawn by Spark inside the IWSDK scene, on one three.js', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await connectHeadset(page, 'http://127.0.0.1:8774');
  await expect(page.getByTestId('room-status')).toHaveText(/^Room ready/, { timeout: 30_000 });
  // Only set once the splat is a child of the room in IWSDK's scene.
  await expect(page.getByTestId('quest-scene')).toHaveAttribute('data-splat', 'shown');
  // A second three.js copy would refuse Spark's objects with "not an instance of THREE.Object3D".
  expect(errors.filter(text => text.includes('THREE'))).toEqual([]);
});

test('the headset stands where it presses on the map', async ({ page }) => {
  await connectHeadset(page);
  const plan = page.getByTestId('quest-map-plan');
  await expect(plan).toBeVisible();
  const box = (await plan.boundingBox())!;
  await page.mouse.move(box.x + 0.75 * box.width, box.y + 0.25 * box.height);
  await page.mouse.down();
  await page.mouse.move(box.x + 0.75 * box.width, box.y + 0.25 * box.height - 50, { steps: 5 });
  await page.mouse.up();
  await expect(page.getByTestId('alignment-status')).toHaveText('Aligned');
});
