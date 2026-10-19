import { alignmentFromPose, type CalibrationInput } from './alignment';
import type { DiagnosticScene } from './scene';

export interface XRReport {
  secure_context: boolean;
  api_available: boolean;
  immersive_vr: boolean;
  mode: XRSessionMode | null;
  reference_space: 'local' | null;
  dom_overlay: string | null;
  positional_tracking: 'not-tested' | 'tracked' | 'lost' | 'emulated';
  input_sources: string[];
  user_agent: string;
}

/** The headset's immersive VR session. The phone does not use WebXR; it tracks with its camera. */
export class XRDiagnostic {
  private session: XRSession | null = null;
  private reference: XRReferenceSpace | null = null;
  private latest: CalibrationInput | null = null;
  private confirmHeld = false;
  private readonly report: XRReport = {
    secure_context: isSecureContext, api_available: Boolean(navigator.xr),
    immersive_vr: false, mode: null, reference_space: null,
    dom_overlay: null, positional_tracking: 'not-tested', input_sources: [],
    user_agent: navigator.userAgent,
  };

  constructor(
    private readonly view: DiagnosticScene,
    private readonly overlay: HTMLElement,
    private readonly changed: (report: XRReport, active: boolean) => void,
    private readonly confirm: () => void,
  ) {}

  async inspect(): Promise<XRReport> {
    if (navigator.xr && isSecureContext) {
      this.report.immersive_vr = await navigator.xr.isSessionSupported('immersive-vr').catch(() => false);
    }
    this.changed({ ...this.report }, this.session !== null);
    return { ...this.report };
  }

  async start(): Promise<void> {
    const mode: XRSessionMode = 'immersive-vr';
    if (!isSecureContext) throw new Error('Open the trusted HTTPS URL to start XR. LAN HTTP cannot enable tracking.');
    if (!navigator.xr) throw new Error('WebXR is unavailable here. Use the Quest browser for VR.');
    // Quest composites this panel from its state at session start, so it must already be visible.
    this.overlay.hidden = false;
    // Called immediately from the user's button gesture; don't await capability probing first.
    let session: XRSession;
    try {
      session = await navigator.xr.requestSession(mode, {
        requiredFeatures: ['local'],
        optionalFeatures: ['local-floor', 'dom-overlay'],
        domOverlay: { root: this.overlay },
      });
    } catch (error) {
      this.overlay.hidden = true;
      throw error;
    }
    this.session = session;
    const ended = () => {
      this.session = null;
      this.reference = null;
      this.latest = null;
      this.confirmHeld = false;
      this.view.setPresenting(false);
      this.report.mode = null;
      this.changed({ ...this.report }, false);
    };
    session.addEventListener('end', ended, { once: true });
    try {
      // A stable local reference exposes translation; viewer space does not.
      this.reference = await session.requestReferenceSpace('local');
      this.report.mode = mode;
      this.report.reference_space = 'local';
      this.report.dom_overlay = session.domOverlayState?.type ?? 'unavailable';
      // Grip and the A or X button confirm while the headset pose is live.
      session.addEventListener('squeezestart', () => this.confirm());
      if (this.report.dom_overlay === 'unavailable') {
        session.addEventListener('select', () => { void this.end(); });
      }
      this.report.positional_tracking = 'not-tested';
      const updateInputs = () => {
        this.report.input_sources = Array.from(session.inputSources).map(
          input => `${input.targetRayMode}:${input.handedness}`,
        );
        this.changed({ ...this.report }, true);
      };
      session.addEventListener('inputsourceschange', updateInputs);
      this.view.renderer.xr.setReferenceSpaceType('local');
      await this.view.renderer.xr.setSession(session);
      this.view.setPresenting(true);
      updateInputs();
    } catch (error) {
      await session.end();
      throw error;
    }
  }

  frame(frame?: XRFrame): void {
    if (!frame || !this.reference || !this.session) return;
    const pose = frame.getViewerPose(this.reference);
    if (pose && !pose.emulatedPosition) {
      const p = pose.transform.position;
      const q = pose.transform.orientation;
      this.latest = alignmentFromPose(
        { x: p.x, y: p.y, z: p.z },
        { x: q.x, y: q.y, z: q.z, w: q.w },
      );
    }
    const status = !pose ? 'lost' : pose.emulatedPosition ? 'emulated' : 'tracked';
    if (status !== this.report.positional_tracking) {
      this.report.positional_tracking = status;
      this.changed({ ...this.report }, true);
    }
    this.readConfirmButtons();
  }

  async end(): Promise<void> {
    await this.session?.end();
  }

  getReport(): XRReport { return { ...this.report }; }

  private readConfirmButtons(): void {
    let pressed = false;
    for (const source of this.session?.inputSources ?? []) {
      const buttons = source.gamepad?.buttons;
      // Quest grip is button 1. A on the right controller and X on the left are button 4.
      if (buttons?.[1]?.pressed || buttons?.[4]?.pressed) pressed = true;
    }
    if (pressed && !this.confirmHeld) this.confirm();
    this.confirmHeld = pressed;
  }

  /** Headset pose mapped to the floor center, or null before a tracked frame. */
  confirmedAlignment(): CalibrationInput | null {
    return this.latest;
  }
}

export function xrError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
      return 'XR permission was denied. Allow XR/camera access in browser settings, use trusted HTTPS, and try again.';
    }
    if (error.name === 'NotSupportedError') {
      return 'This device cannot start immersive VR with a local reference space. Use the Quest browser.';
    }
  }
  return error instanceof Error ? error.message : 'XR could not start. Check device support and browser permissions.';
}
