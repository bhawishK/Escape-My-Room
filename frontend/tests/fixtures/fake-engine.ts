import type { Page } from '@playwright/test';

/** What the fake 8th Wall engine was asked to do, for a test to check. */
export interface EngineCalls {
  configure: Record<string, unknown>[];
  origins: { origin?: unknown; facing?: unknown }[];
  modules: string[];
  runs: number;
  stops: number;
  pauses: number;
  resumes: number;
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
  const calls = {
    configure: [] as unknown[], origins: [] as unknown[], modules: [] as string[],
    runs: 0, stops: 0, pauses: 0, resumes: 0, recenters: 0, cameraFeed: false,
  };
  // With fake cameras installed, the engine holds the back camera while it runs, as the real one does.
  let backCamera: MediaStream | null = null;
  const openBack = async () => {
    if ((window as unknown as { openedCameras?: unknown }).openedCameras === undefined) return;
    backCamera = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } });
  };
  const closeBack = () => {
    backCamera?.getTracks().forEach(track => track.stop());
    backCamera = null;
  };
  const cameraOpens = () => {
    for (const status of ['requesting', 'hasStream', 'hasVideo']) modules.forEach(module => module.onCameraStatusChange?.({ status }));
  };
  const engine = {
    addCameraPipelineModule(module: Module) { modules.push(module); calls.modules.push(module.name); },
    addCameraPipelineModules(added: Module[]) { added.forEach(module => engine.addCameraPipelineModule(module)); },
    clearCameraPipelineModules() { modules = []; },
    run({ canvas }: { canvas: unknown }) {
      calls.runs++;
      void openBack();
      // The camera opens, as a person allowing camera access sees it.
      cameraOpens();
      modules.forEach(module => module.onStart?.({ canvas }));
    },
    stop() { calls.stops++; closeBack(); },
    // Pausing releases the back camera and resuming opens it again, as in the engine's open camera code.
    pause() { calls.pauses++; closeBack(); },
    resume() {
      calls.resumes++;
      return openBack().then(() => { cameraOpens(); return false; });
    },
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
 * Aims the phone at the box: 1.2 m back and 1.2 m up, tilted 45° down, so the screen's centre meets
 * the floor exactly at the box. The box fills the middle of the screen, and holding it aims at its
 * own place, so a test that carries and drops it leaves it where it was. Its place comes from Python:
 * tests share one room.
 */
export async function aimAtBox(page: Page): Promise<void> {
  const room = await (await page.request.get('/api/room')).json() as { entities: { id: string; position: { x: number; z: number } }[] };
  const box = room.entities.find(entity => entity.id === 'box')!.position;
  const tilted = { x: Math.sin(-Math.PI / 8), y: 0, z: 0, w: Math.cos(-Math.PI / 8) };
  await engineFrame(page, { x: box.x, y: 1.2, z: box.z + 1.2 }, tilted);
  // The view moves to the new pose on its next drawn frame.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}
