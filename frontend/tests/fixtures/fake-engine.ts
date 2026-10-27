import type { Page } from '@playwright/test';

/** What the fake 8th Wall engine was asked to do, for a test to check. */
export interface EngineCalls {
  configure: Record<string, unknown>[];
  origins: { origin?: unknown; facing?: unknown }[];
  modules: string[];
  runs: number;
  stops: number;
  recenters: number;
  cameraFeed: boolean;
}

/**
 * Stands in for the 8th Wall engine binary, following its camera pipeline module contract: modules
 * are added, `run` starts them, and `frame` delivers one tracking result to every module.
 */
function installFakeEngine(): void {
  type Module = {
    name: string;
    onCameraStatusChange?: (args: { status: string }) => void;
    onStart?: (args: { canvas: unknown }) => void;
    onUpdate?: (args: unknown) => void;
  };
  let modules: Module[] = [];
  const calls = { configure: [] as unknown[], origins: [] as unknown[], modules: [] as string[], runs: 0, stops: 0, recenters: 0, cameraFeed: false };
  const engine = {
    addCameraPipelineModule(module: Module) { modules.push(module); calls.modules.push(module.name); },
    addCameraPipelineModules(added: Module[]) { added.forEach(module => engine.addCameraPipelineModule(module)); },
    clearCameraPipelineModules() { modules = []; },
    run({ canvas }: { canvas: unknown }) {
      calls.runs++;
      // The camera opens, as a person allowing camera access sees it.
      for (const status of ['requesting', 'hasStream', 'hasVideo']) modules.forEach(module => module.onCameraStatusChange?.({ status }));
      modules.forEach(module => module.onStart?.({ canvas }));
    },
    stop() { calls.stops++; },
    XrController: {
      configure(options: unknown) { calls.configure.push(options); },
      updateCameraProjectionMatrix(options: unknown) { calls.origins.push(options); },
      recenter() { calls.recenters++; },
      pipelineModule: () => ({ name: 'reality' }),
    },
    XrDevice: { isDeviceBrowserCompatible: () => true, incompatibleReasons: () => [] },
    XrConfig: {
      device: () => ({ MOBILE: 'mobile', MOBILE_AND_HEADSETS: 'mobile-and-headsets', ANY: 'any' }),
      camera: () => ({ BACK: 'back', FRONT: 'front' }),
    },
    GlTextureRenderer: { pipelineModule: () => { calls.cameraFeed = true; return { name: 'gltexturerenderer' }; } },
  };
  const target = window as unknown as Record<string, unknown>;
  target.XR8 = engine;
  target.fakeEngine = {
    calls,
    frame(reality: Record<string, unknown>) {
      const result = { trackingStatus: 'NORMAL', trackingReason: 'UNSPECIFIED', ...reality };
      modules.forEach(module => module.onUpdate?.({ processCpuResult: { reality: result } }));
    },
  };
}

/** Replaces the real engine with the fake, and grants motion permission when asked. */
export async function useFakeEngine(page: Page): Promise<void> {
  // The page loads the real engine from the CDN; keep it from replacing the fake.
  await page.route('**/@8thwall/**', route => route.abort());
  await page.addInitScript(installFakeEngine);
  await grantMotionPermission(page);
}

/** Grants motion and orientation permission when the page asks, as iPhone does after a tap. */
export async function grantMotionPermission(page: Page): Promise<void> {
  await page.addInitScript(() => {
    for (const event of [DeviceOrientationEvent, DeviceMotionEvent]) Object.assign(event, { requestPermission: async () => 'granted' });
  });
}

/** Delivers one engine frame: a camera position in metres and a rotation as a quaternion. */
export async function engineFrame(
  page: Page, position: { x: number; y: number; z: number }, rotation = { x: 0, y: 0, z: 0, w: 1 },
  tracking: { trackingStatus: 'NORMAL' | 'LIMITED'; trackingReason: string } = { trackingStatus: 'NORMAL', trackingReason: 'UNSPECIFIED' },
): Promise<void> {
  await page.evaluate(([position, rotation, tracking]) => {
    (window as unknown as { fakeEngine: { frame: (reality: unknown) => void } }).fakeEngine.frame({ position, rotation, ...tracking });
  }, [position, rotation, tracking] as const);
}

/** A frame while the engine is still working out where it is, as at start-up and after a loss. */
export const INITIALIZING = { trackingStatus: 'LIMITED', trackingReason: 'INITIALIZING' } as const;

export async function engineCalls(page: Page): Promise<EngineCalls> {
  return page.evaluate(() => (window as unknown as { fakeEngine: { calls: EngineCalls } }).fakeEngine.calls);
}

/**
 * Closes the room's map, which opens with the room view until the person has placed themselves
 * on it (#127), so a test can reach the buttons beneath it.
 */
export async function closeMap(page: Page): Promise<void> {
  await page.locator('#room-view-hud').waitFor();
  const close = page.getByRole('button', { name: 'Close map', exact: true });
  if (await close.isVisible()) await close.click();
}
