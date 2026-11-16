import { expect, test } from '@playwright/test';

// Catalogue furniture (#181): the headset chooses a piece and presses on the room map, and both
// pages draw it. Its own server, so the furniture never reaches other tests' rooms.
const ORIGIN = 'http://127.0.0.1:8776';

test('a piece chosen on the headset page and pressed onto the map is drawn on both pages', async ({ browser }) => {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const headset = await browser.newPage();
  await phone.goto(`${ORIGIN}/`);
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await headset.goto(`${ORIGIN}/quest/`);
  await headset.getByRole('button', { name: 'Connect headset', exact: true }).click();
  await expect(headset.getByTestId('connection')).toHaveText('Connected · VR headset');

  // Each piece shows its true size.
  const armchair = headset.getByRole('button', { name: 'Armchair · 0.85 × 0.85 × 0.9 m' });
  await armchair.click();
  await expect(armchair).toHaveAttribute('aria-pressed', 'true');
  await expect(headset.getByTestId('furniture-status')).toContainText('where the armchair goes');

  const plan = headset.getByTestId('quest-map-plan');
  const box = (await plan.boundingBox())!;
  await headset.mouse.click(box.x + 0.3 * box.width, box.y + 0.7 * box.height);

  await expect(headset.getByTestId('quest-scene')).toHaveAttribute('data-furniture', '1');
  await expect(phone.locator('#scene')).toHaveAttribute('data-furniture', '1');
  // Placed once: the next press on the map stands there again.
  await expect(armchair).toHaveAttribute('aria-pressed', 'false');

  // A phone that joins again draws the furniture with the room it loads.
  await phone.reload();
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  await expect(phone.locator('#scene')).toHaveAttribute('data-furniture', '1');
  await phone.close();
  await headset.close();
});

test('a described piece shows its picture while it is made, then is chosen to place at true size', async ({ page }) => {
  await page.goto(`${ORIGIN}/quest/`);
  await page.getByRole('button', { name: 'Connect headset', exact: true }).click();
  await expect(page.getByTestId('connection')).toHaveText('Connected · VR headset');
  const scene = page.getByTestId('quest-scene');
  const before = Number(await scene.getAttribute('data-furniture') ?? 0);

  await page.getByLabel('Make a new piece').fill('a green sofa, 2 m long');
  await page.getByRole('button', { name: 'Make it' }).click();

  // The fixture generator draws first, then models: the picture shows on the page and as the card.
  await expect(page.getByTestId('furniture-preview')).toBeVisible();
  await expect(scene).toHaveAttribute('data-card', 'shown');
  await expect(page.getByTestId('furniture-status')).toContainText('Here is the picture');

  // The fixture's 4 m box, 2 m long as asked.
  const made = page.getByRole('button', { name: 'A green sofa, 2 m long · 2 × 0.5 × 1 m' });
  await expect(made).toHaveAttribute('aria-pressed', 'true', { timeout: 10_000 });
  await expect(page.getByTestId('furniture-preview')).toBeHidden();
  await expect(scene).toHaveAttribute('data-card', '');

  const plan = page.getByTestId('quest-map-plan');
  const box = (await plan.boundingBox())!;
  await page.mouse.click(box.x + 0.6 * box.width, box.y + 0.6 * box.height);
  await expect(scene).toHaveAttribute('data-furniture', String(before + 1));
});
