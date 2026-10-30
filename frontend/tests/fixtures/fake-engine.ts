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
  /** Camera frames drawn for positioning, and read back (#133). */
  framesDrawn: number;
  framesRead: number;
}

/**
 * Stands in for the 8th Wall engine binary, following its camera pipeline module contract: modules
 * are added, `run` starts them, and `frame` delivers one tracking result to every module. With
 * `camera`, each frame also brings a camera image on the "GPU", which positioning (#133) can copy.
 */
function installFakeEngine(options: { camera: boolean }): void {
  type Module = {
    name: string;
    onCameraStatusChange?: (args: { status: string }) => void;
    onStart?: (args: { canvas: unknown }) => void;
    onProcessGpu?: (args: unknown) => void;
    onUpdate?: (args: unknown) => void;
  };
  let modules: Module[] = [];
  const calls = {
    configure: [] as unknown[], origins: [] as unknown[], modules: [] as string[], runs: 0, stops: 0, recenters: 0, cameraFeed: false,
    framesDrawn: 0, framesRead: 0,
  };
  // A grey 480 x 640 camera image, read back through a stand-in for the GPU context.
  const gl = {
    FRAMEBUFFER: 1, FRAMEBUFFER_BINDING: 2, RGBA: 3, UNSIGNED_BYTE: 4,
    getParameter: () => null,
    bindFramebuffer: () => undefined,
    readPixels: (_x: number, _y: number, _w: number, _h: number, _f: number, _t: number, pixels: Uint8Array) => {
      calls.framesRead++;
      pixels.fill(128);
    },
  };
  const camera = { computeTexture: {}, computeCtx: gl, textureWidth: 480, textureHeight: 640 };
  // The projection 8th Wall gives for a canvas this frame covers: a 480-pixel focal length.
  const intrinsics = [2, 0, 0, 0, 0, 1.5, 0, 0, 0, 0, -1, -1, 0, 0, -0.02, 0];
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
    GlTextureRenderer: {
      pipelineModule: () => { calls.cameraFeed = true; return { name: 'gltexturerenderer' }; },
      ...options.camera ? {
        create: () => ({ render: () => { calls.framesDrawn++; }, framebuffer: () => ({}), destroy: () => undefined }),
      } : {},
    },
  };
  const target = window as unknown as Record<string, unknown>;
  target.XR8 = engine;
  target.fakeEngine = {
    calls,
    frame(reality: Record<string, unknown>) {
      const result = { trackingStatus: 'NORMAL', trackingReason: 'UNSPECIFIED', intrinsics, ...reality };
      if (options.camera) modules.forEach(module => module.onProcessGpu?.({ frameStartResult: camera }));
      modules.forEach(module => module.onUpdate?.({ processCpuResult: { reality: result } }));
    },
  };
}

/**
 * Replaces the real engine with the fake, and grants motion permission when asked. With `camera`,
 * frames come with a camera image that positioning can send to Python.
 */
export async function useFakeEngine(page: Page, options = { camera: false }): Promise<void> {
  // The page loads the real engine from the CDN; keep it from replacing the fake.
  await page.route('**/@8thwall/**', route => route.abort());
  await page.addInitScript(installFakeEngine, options);
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
