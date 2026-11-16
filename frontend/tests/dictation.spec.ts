import { expect, test, type Page } from '@playwright/test';

// Saying a furniture description on the headset page (#188). The browser's speech recognition is
// replaced by a fake that "hears" a fixed sentence, or refuses the microphone.
const ORIGIN = 'http://127.0.0.1:8776';

/** A fake SpeechRecognition: it hears `heard` in two parts once started, or fails with `error`. */
async function fakeRecognition(page: Page, options: { heard?: string; error?: string }): Promise<void> {
  await page.addInitScript(({ heard, error }) => {
    class FakeRecognition {
      lang = '';
      interimResults = false;
      continuous = false;
      onresult: ((event: unknown) => void) | null = null;
      onerror: ((event: { error: string }) => void) | null = null;
      onend: (() => void) | null = null;
      start(): void {
        setTimeout(() => {
          if (error) {
            this.onerror?.({ error });
            this.onend?.();
            return;
          }
          const words = (heard ?? '').split(' ');
          const half = words.slice(0, 2).join(' ');
          // First a guess while speaking, then the final words.
          this.onresult?.({ resultIndex: 0, results: [Object.assign([{ transcript: half }], { isFinal: false })] });
          this.onresult?.({ resultIndex: 0, results: [Object.assign([{ transcript: heard }], { isFinal: true })] });
        }, 50);
      }
      stop(): void {
        setTimeout(() => this.onend?.(), 20);
      }
    }
    // Both names: Chromium browsers have the unprefixed one too, which the page prefers.
    const speech = window as unknown as { SpeechRecognition: unknown; webkitSpeechRecognition: unknown };
    speech.SpeechRecognition = FakeRecognition;
    speech.webkitSpeechRecognition = FakeRecognition;
  }, options);
}

async function connect(page: Page): Promise<void> {
  await page.goto(`${ORIGIN}/quest/`);
  await page.getByRole('button', { name: 'Connect headset', exact: true }).click();
  await expect(page.getByTestId('connection')).toHaveText('Connected · VR headset');
}

test('holding to talk fills in the description, which can be edited and then made', async ({ page }) => {
  await fakeRecognition(page, { heard: 'a tall oak bookshelf' });
  await connect(page);
  const talk = page.getByRole('button', { name: 'Hold to say it' });
  await talk.dispatchEvent('pointerdown');
  await expect(page.getByLabel('Make a new piece')).toHaveValue('a tall oak bookshelf');
  await talk.dispatchEvent('pointerup');

  // Edited before it is made.
  await page.getByLabel('Make a new piece').fill('a tall oak bookshelf, 2 m tall');
  await page.getByRole('button', { name: 'Make it' }).click();
  await expect(page.getByTestId('furniture-status')).toContainText(/Making a picture|Here is the picture/);
});

test('a browser without speech recognition says so, and typing still works', async ({ page }) => {
  await page.addInitScript(() => {
    delete (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition;
    delete (window as unknown as { SpeechRecognition?: unknown }).SpeechRecognition;
  });
  await connect(page);
  await page.getByLabel('Make a new piece').fill('a small side table');
  await page.getByRole('button', { name: 'Hold to say it' }).dispatchEvent('pointerdown');

  await expect(page.getByTestId('furniture-status')).toContainText('type the description');
  // What was typed is kept.
  await expect(page.getByLabel('Make a new piece')).toHaveValue('a small side table');
});

test('a refused microphone says so plainly', async ({ page }) => {
  await fakeRecognition(page, { error: 'not-allowed' });
  await connect(page);
  await page.getByRole('button', { name: 'Hold to say it' }).dispatchEvent('pointerdown');

  await expect(page.getByTestId('furniture-status')).toContainText('microphone');
});
