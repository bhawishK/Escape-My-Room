import type { DiagnosticScene } from './scene';
import type { PoseInput, ReferenceSpace, Role } from './protocol';

export interface XRReport {
  secure_context: boolean;
  api_available: boolean;
  immersive_ar: boolean;
  immersive_vr: boolean;
  mode: XRSessionMode | null;
  reference_space: ReferenceSpace | null;
  dom_overlay: string | null;
  positional_tracking: 'not-tested' | 'tracked' | 'lost' | 'emulated';
  input_sources: string[];
  user_agent: string;
}

export class XRDiagnostic {
  private session: XRSession | null = null;
  private reference: XRReferenceSpace | null = null;
  private referenceType: ReferenceSpace | null = null;
  private role: Role = 'mobile_master';
  private lastPoseAt = -Infinity;
  private readonly report: XRReport = {
    secure_context: isSecureContext, api_available: Boolean(navigator.xr),
    immersive_ar: false, immersive_vr: false, mode: null, reference_space: null,
    dom_overlay: null, positional_tracking: 'not-tested', input_sources: [],
    user_agent: navigator.userAgent,
  };

  constructor(
    private readonly view: DiagnosticScene,
    private readonly overlay: HTMLElement,
    private readonly publish: (pose: PoseInput) => void,
    private readonly changed: (report: XRReport, active: boolean) => void,
  ) {}

  async inspect(): Promise<XRReport> {
    if (navigator.xr && isSecureContext) {
      const [ar, vr] = await Promise.all([
        navigator.xr.isSessionSupported('immersive-ar').catch(() => false),
        navigator.xr.isSessionSupported('immersive-vr').catch(() => false),
      ]);
      this.report.immersive_ar = ar;
      this.report.immersive_vr = vr;
    }
    this.changed({ ...this.report }, this.session !== null);
    return { ...this.report };
  }

  async start(role: Role): Promise<void> {
    const mode: XRSessionMode = role === 'mobile_master' ? 'immersive-ar' : 'immersive-vr';
    if (!isSecureContext) throw new Error('Open the trusted HTTPS URL to start XR. LAN HTTP cannot enable tracking.');
    if (!navigator.xr) throw new Error('WebXR is unavailable here. The iPhone mobile view works; physical phone tracking is pending.');
    this.role = role;
    // Called immediately from the user's button gesture; don't await capability probing first.
    const session = await navigator.xr.requestSession(mode, {
      requiredFeatures: ['local'],
      optionalFeatures: ['local-floor', 'dom-overlay'],
      domOverlay: { root: this.overlay },
    });
    this.session = session;
    const ended = () => {
      this.session = null;
      this.reference = null;
      this.referenceType = null;
      this.view.setAR(false);
      this.report.mode = null;
      if (this.role === 'mobile_master') this.publishUnavailable('inactive');
      this.changed({ ...this.report }, false);
    };
    session.addEventListener('end', ended, { once: true });
    try {
      // A stable local reference exposes translation; viewer space does not.
      this.reference = await session.requestReferenceSpace('local');
      this.referenceType = 'local';
      this.reference.addEventListener('reset', () => this.publishUnavailable('lost'));
      this.report.mode = mode;
      this.report.reference_space = this.referenceType;
      this.report.dom_overlay = session.domOverlayState?.type ?? 'unavailable';
      this.report.positional_tracking = 'not-tested';
      this.lastPoseAt = -Infinity;
      const updateInputs = () => {
        this.report.input_sources = Array.from(session.inputSources).map(
          input => `${input.targetRayMode}:${input.handedness}`,
        );
        this.changed({ ...this.report }, true);
      };
      session.addEventListener('inputsourceschange', updateInputs);
      session.addEventListener('visibilitychange', () => {
        if (session.visibilityState !== 'visible') this.publishUnavailable('lost');
      });
      // Select is a usable headset exit fallback when there is no DOM overlay.
      session.addEventListener('select', () => { void this.end(); });
      this.view.renderer.xr.setReferenceSpaceType(this.referenceType);
      this.view.setAR(mode === 'immersive-ar');
      await this.view.renderer.xr.setSession(session);
      updateInputs();
    } catch (error) {
      await session.end();
      throw error;
    }
  }

  frame(time: number, frame?: XRFrame): void {
    if (!frame || !this.reference || !this.session) return;
    const pose = frame.getViewerPose(this.reference);
    const status = !pose ? 'lost' : pose.emulatedPosition ? 'emulated' : 'tracked';
    if (status !== this.report.positional_tracking) {
      this.report.positional_tracking = status;
      this.changed({ ...this.report }, true);
    }
    if (this.role !== 'mobile_master' || time - this.lastPoseAt < 50) return;
    this.lastPoseAt = time;
    if (!pose || pose.emulatedPosition || this.session.visibilityState !== 'visible') {
      this.publishUnavailable(status === 'emulated' ? 'emulated' : 'lost');
      return;
    }
    const p = pose.transform.position;
    this.publish({ tracking_status: 'tracked', reference_space: this.referenceType,
      position: { x: p.x, y: p.y, z: p.z } });
  }

  private publishUnavailable(status: 'lost' | 'emulated' | 'inactive'): void {
    if (this.role === 'mobile_master') {
      this.publish({ tracking_status: status, reference_space: this.referenceType, position: null });
    }
  }

  async end(): Promise<void> {
    await this.session?.end();
  }

  getReport(): XRReport { return { ...this.report }; }
}

export function xrError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError' || error.name === 'SecurityError') {
      return 'XR permission was denied. Allow XR/camera access in browser settings, use trusted HTTPS, and try again.';
    }
    if (error.name === 'NotSupportedError') {
      return 'This device cannot start the requested XR mode/local reference space. Use the mobile view or a supported XR device.';
    }
  }
  return error instanceof Error ? error.message : 'XR could not start. Check device support and browser permissions.';
}
