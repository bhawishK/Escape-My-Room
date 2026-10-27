import { type Browser, type Page, expect, test } from '@playwright/test';
import { engineFrame, useFakeEngine } from './fixtures/fake-engine';

/**
 * The room's 2D map (#124). The stand-in room (port 8771) has no map image, so its floor (4 m round
 * the origin, x and z from -2 to 2) and furniture are drawn as outlines; its landmark map names a
 * desk, a cabinet and a door. The splat test room (port 8774) has a map image.
 */
const FLOOR = { min: -2, max: 2 };
/** How far across (or down) the map a place is, in percent, to a tenth. */
const across = (metres: number) => Number((((metres - FLOOR.min) / (FLOOR.max - FLOOR.min)) * 100).toFixed(1));

async function phoneAndHeadset(browser: Browser): Promise<{ phone: Page; vr: Page }> {
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const vr = await browser.newPage();
  await useFakeEngine(phone);
  await vr.goto('/');
  await vr.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await phone.goto('/');
  await phone.getByRole('button', { name: 'Connect phone', exact: true }).click();
  return { phone, vr };
}

/** Where a map element sits, as the percentages it is placed at. */
const placedAt = (page: Page, testId: string) =>
  page.getByTestId(testId).first().evaluate(element =>
    [parseFloat((element as HTMLElement).style.left), parseFloat((element as HTMLElement).style.top)]);

test('both devices always show the map, the objects as icons and the players as dots', async ({ browser }) => {
  const { phone, vr } = await phoneAndHeadset(browser);
  await engineFrame(phone, { x: 0.5, y: 1.5, z: -1 });

  for (const [page, map] of [[phone, 'phone-map'], [vr, 'page-map']] as const) {
    const shown = page.getByTestId(map);
    await expect(shown).toBeVisible();
    // The desk at (0, -1.2) and the box at (-0.5, -0.4), as icons where they stand.
    expect(await placedAt(page, `${map}-icon-desk`)).toEqual([across(0), across(-1.2)]);
    expect(await placedAt(page, `${map}-icon-box`)).toEqual([across(-0.5), across(-0.4)]);
    await expect(page.getByTestId(`${map}-icon-desk`).first()).toHaveAttribute('title', 'Desk');
    // The phone as a dot where it is, its arrow the way it faces.
    await expect.poll(() => placedAt(page, `${map}-dot-mobile_master`)).toEqual([across(0.5), across(-1)]);
  }
  await expect(phone.getByTestId('phone-map-dot-mobile_master')).toHaveAttribute('data-you', 'true');
  await expect(vr.getByTestId('page-map-dot-mobile_master')).toHaveAttribute('data-you', 'false');
  await phone.close();
  await vr.close();
});

test('a splat room draws its map image', async ({ page }) => {
  await page.goto('http://127.0.0.1:8774');
  await page.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  await expect(page.getByTestId('page-map-plan')).toHaveCSS('background-image', /map\.png/);
});

/** Presses on the open map at fractions of its width and height, and drags `drag` pixels. */
async function pressOnMap(page: Page, x: number, y: number, drag = { x: 0, y: 0 }): Promise<void> {
  const plan = page.getByTestId('phone-map-plan');
  const box = (await plan.boundingBox())!;
  const at = { x: box.x + x * box.width, y: box.y + y * box.height };
  await page.mouse.move(at.x, at.y);
  await page.mouse.down();
  await page.mouse.move(at.x + drag.x, at.y + drag.y, { steps: 5 });
  await page.mouse.up();
}

test('tapping where you stand and dragging the way you face places the phone there', async ({ browser }) => {
  const { phone, vr } = await phoneAndHeadset(browser);
  await engineFrame(phone, { x: 0, y: 1.5, z: 1.6 });
  await phone.getByTestId('phone-map').click();
  await expect(phone.getByTestId('phone-map-prompt')).toHaveText('Tap where you stand, and drag the way you face');

  // A quarter of the way across and three quarters down is (-1, 1); dragging right faces +x.
  await pressOnMap(phone, 0.25, 0.75, { x: 60, y: 0 });

  await expect(vr.getByTestId('marker-position')).toHaveText('-1.00, 1.50, 1.00 m');
  await expect(vr.getByTestId('presence-phone')).toContainText('heading -1.57 rad');
  await expect(phone.getByTestId('phone-map-prompt')).toHaveText('Placed · walk 2 m or more and tap where you are, to set the scale');
  await phone.close();
  await vr.close();
});

test('a second tap after walking sets the scale', async ({ browser }) => {
  const { phone, vr } = await phoneAndHeadset(browser);
  await engineFrame(phone, { x: 0, y: 1.5, z: 1.6 });
  await phone.getByTestId('phone-map').click();
  await pressOnMap(phone, 0.25, 0.75, { x: 60, y: 0 });
  // 8th Wall sees a 1 m walk; the person taps 2.5 m further along on the map, at (1.5, 1).
  await engineFrame(phone, { x: 1, y: 1.5, z: 1.6 });
  await pressOnMap(phone, 0.875, 0.75);

  // 8th Wall walked along its +x, and the two taps lie along the room's +x: no turn.
  await expect(phone.getByTestId('view-status')).toHaveText('Calibrated · ×2.50 · turned 0°');
  await expect(vr.getByTestId('marker-position')).toHaveText('1.50, 1.50, 1.00 m');
  await phone.close();
  await vr.close();
});

test('the headset chooses where it stands by tapping the map', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect VR headset', exact: true }).click();
  const plan = page.getByTestId('page-map-plan');
  await expect(plan).toBeVisible();
  const box = (await plan.boundingBox())!;
  // Three quarters across and a quarter down is (1, -1); dragging up faces -z.
  await page.mouse.move(box.x + 0.75 * box.width, box.y + 0.25 * box.height);
  await page.mouse.down();
  await page.mouse.move(box.x + 0.75 * box.width, box.y + 0.25 * box.height - 50, { steps: 5 });
  await page.mouse.up();

  await expect(page.getByTestId('alignment-status')).toHaveText('Aligned · yaw 0.00 rad · origin 1.00, 0.00, -1.00');
});

test('a player off the map is kept at its edge, so they never disappear', async ({ browser }) => {
  const { phone, vr } = await phoneAndHeadset(browser);
  // Three metres right of the floor's edge.
  await engineFrame(phone, { x: 5, y: 1.5, z: 0 });

  await expect.poll(() => placedAt(vr, 'page-map-dot-mobile_master')).toEqual([100, across(0)]);
  await expect(vr.getByTestId('page-map-dot-mobile_master')).toHaveAttribute('data-off-map', 'true');
  await phone.close();
  await vr.close();
});
