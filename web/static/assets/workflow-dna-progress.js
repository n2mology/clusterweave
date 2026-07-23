import * as THREE from '../vendor/three-0.184.0/three.module.min.js';

const AXIS_MIN = -5.6;
const AXIS_MAX = 5.6;
const TURNS = 4;
const SEGMENTS = 192;
const RUNG_STEP = 8;
const BACKBONE_OVERLAP = 1.08;
const TWO_PI = Math.PI * 2;
const UP = new THREE.Vector3(0, 1, 0);
const FRAME_INTERVAL_MS = 1000 / 30;

const DEFAULT_PROFILE = Object.freeze({
  radius: 0.72,
  depthScale: 0.56,
  cameraWide: 17,
  cameraNarrow: 19,
  backboneScale: 1,
  rungScale: 1,
  ballScale: 1,
  railScale: 1,
});

const LARGE_PROFILE = Object.freeze({
  radius: 1.04,
  depthScale: 0.78,
  cameraWide: 12.4,
  cameraNarrow: 14.6,
  backboneScale: 2.15,
  rungScale: 2.35,
  ballScale: 1.55,
  railScale: 1.55,
});

const COMPACT_PROFILE = Object.freeze({
  radius: 0.66,
  depthScale: 0.5,
  cameraWide: 17.5,
  cameraNarrow: 19,
  backboneScale: 1.12,
  rungScale: 1.18,
  ballScale: 1.08,
  railScale: 1.05,
});

const COLORS = Object.freeze({
  idleBackbone: new THREE.Color(0x6a7175),
  idleRung: new THREE.Color(0x8d969a),
  top: new THREE.Color(0xff3ba7),
  bottom: new THREE.Color(0x00d9ff),
  head: new THREE.Color(0xd7ff1f),
  headEnd: new THREE.Color(0x00d9ff),
  rung: [0xd7ff1f, 0xff7a18, 0x00d9ff, 0xff3ba7, 0xc9b8ff].map((color) => new THREE.Color(color)),
});

function clampProgress(value) {
  return Math.max(0, Math.min(1, Number(value) || 0));
}

function profileForState(state) {
  if (state === 'running' || state === 'failed') return LARGE_PROFILE;
  if (state === 'complete') return COMPACT_PROFILE;
  return DEFAULT_PROFILE;
}

export function createWorkflowDnaProgress(options) {
  return new WorkflowDnaProgress(options);
}

export class WorkflowDnaProgress {
  constructor(options = {}) {
    const { canvas, region = canvas?.parentElement, autoSpiral = true } = options;
    if (!(canvas instanceof HTMLCanvasElement)) throw new TypeError('workflow DNA progress requires a canvas');
    if (!(region instanceof Element)) throw new TypeError('workflow DNA progress requires a region element');

    this.canvas = canvas;
    this.region = region;
    this.progress = 0;
    this.hasProgressState = false;
    this.geometryDirty = true;
    this.baseAutoSpiral = Boolean(autoSpiral);
    this.motionPaused = false;
    this.profile = DEFAULT_PROFILE;
    this.phase = 0;
    this.lastFrameTime = performance.now();
    this.lastRenderTime = 0;
    this.frame = 0;
    this.suspended = false;
    this.manualSuspended = false;
    this.pageHidden = document.hidden;
    this.offscreen = false;
    this.disposed = false;
    this.backboneSegments = [];
    this.rungs = [];
    this.materials = [];
    this.geometries = [];
    this.resizeObserver = null;
    this.intersectionObserver = null;
    this.topA = new THREE.Vector3();
    this.topB = new THREE.Vector3();
    this.bottomA = new THREE.Vector3();
    this.bottomB = new THREE.Vector3();
    this.direction = new THREE.Vector3();
    this.colorScratch = new THREE.Color();
    this.reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    this.reducedMotionListener = () => {
      this.geometryDirty = true;
      this.renderFrame(performance.now(), true);
      this.syncAnimationLoop();
    };
    this.visibilityListener = () => {
      this.pageHidden = document.hidden;
      this.syncSuspension();
    };
    this.beforeUnloadListener = () => this.dispose();

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(26, 1, 0.1, 100);
    this.camera.position.set(0, 0.1, 17);
    this.camera.lookAt(0, 0, 0);

    this.root = new THREE.Group();
    this.root.rotation.x = -0.08;
    this.scene.add(this.root);

    this.addLights();
    this.createGeometries();
    this.buildMeshes();
    this.resize();
    this.bindLifecycle();
    this.syncSuspension();
    this.animate();
  }

  addLights() {
    this.scene.add(new THREE.AmbientLight(0xffffff, 1.55));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(-4, 5, 9);
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x9fdfff, 1.2);
    rim.position.set(5, -3, 8);
    this.scene.add(rim);
  }

  createGeometries() {
    this.backboneGeometry = new THREE.CylinderGeometry(0.055, 0.055, 1, 18, 1, true);
    this.rungGeometry = new THREE.CylinderGeometry(0.03, 0.03, 1, 12, 1, false);
    this.ballGeometry = new THREE.SphereGeometry(0.28, 40, 24);
    this.geometries.push(this.backboneGeometry, this.rungGeometry, this.ballGeometry);
  }

  bindLifecycle() {
    if (typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(this.region);
    } else {
      window.addEventListener('resize', this.reducedMotionListener);
    }
    if (typeof IntersectionObserver !== 'undefined') {
      this.intersectionObserver = new IntersectionObserver((entries) => {
        this.offscreen = !entries.some((entry) => entry.isIntersecting);
        this.syncSuspension();
      }, { rootMargin: '96px' });
      this.intersectionObserver.observe(this.region);
    }
    this.reducedMotion.addEventListener?.('change', this.reducedMotionListener);
    document.addEventListener('visibilitychange', this.visibilityListener);
    window.addEventListener('beforeunload', this.beforeUnloadListener, { once: true });
  }

  material(color, roughness = 0.54, metalness = 0.02) {
    const material = new THREE.MeshStandardMaterial({
      color,
      roughness,
      metalness,
      transparent: true,
      opacity: 1,
    });
    this.materials.push(material);
    return material;
  }

  buildMeshes() {
    for (let index = 0; index < SEGMENTS - 1; index += 1) {
      const top = new THREE.Mesh(this.backboneGeometry, this.material(COLORS.idleBackbone));
      const bottom = new THREE.Mesh(this.backboneGeometry, this.material(COLORS.idleBackbone));
      top.userData = { t: (index + 0.5) / (SEGMENTS - 1), rail: 'top' };
      bottom.userData = { t: (index + 0.5) / (SEGMENTS - 1), rail: 'bottom' };
      this.backboneSegments.push(top, bottom);
      this.root.add(top, bottom);
    }

    for (let index = 0; index < SEGMENTS; index += RUNG_STEP) {
      const rung = new THREE.Mesh(this.rungGeometry, this.material(COLORS.idleRung, 0.62, 0.01));
      rung.userData = { t: index / (SEGMENTS - 1) };
      this.rungs.push(rung);
      this.root.add(rung);
    }

    this.ballMaterial = this.material(COLORS.head, 0.38, 0.08);
    this.ball = new THREE.Mesh(this.ballGeometry, this.ballMaterial);
    this.ball.userData = { control: 'workflow-progress-ball', appliedAs: 'color-fade-only' };
    this.root.add(this.ball);

    const railMaterial = this.material(0x050505, 0.7, 0);
    railMaterial.opacity = 0.12;
    const railGeometry = new THREE.CylinderGeometry(0.018, 0.018, AXIS_MAX - AXIS_MIN, 14, 1, false);
    this.geometries.push(railGeometry);
    this.centerRail = new THREE.Mesh(railGeometry, railMaterial);
    this.centerRail.rotation.z = Math.PI / 2;
    this.centerRail.position.set((AXIS_MIN + AXIS_MAX) / 2, 0, 0);
    this.root.add(this.centerRail);
  }

  helixPoint(index, offset, target) {
    const t = index / (SEGMENTS - 1);
    const x = AXIS_MIN + (AXIS_MAX - AXIS_MIN) * t;
    const angle = t * TURNS * TWO_PI + offset + this.phase;
    return target.set(
      x,
      Math.cos(angle) * this.profile.radius,
      Math.sin(angle) * this.profile.radius * this.profile.depthScale,
    );
  }

  placeCylinder(mesh, start, end, radialScale = 1, axialScale = 1) {
    const direction = this.direction.subVectors(end, start);
    const length = Math.max(direction.length(), 0.0001);
    mesh.position.copy(start).add(end).multiplyScalar(0.5);
    mesh.quaternion.setFromUnitVectors(UP, direction.normalize());
    mesh.scale.set(radialScale, length * axialScale, radialScale);
  }

  colorForSegment(t, rail) {
    if (this.progress <= 0.001 || t > this.progress) {
      return rail === 'rung' ? COLORS.idleRung : COLORS.idleBackbone;
    }
    const headWeight = Math.max(0, 1 - Math.min(1, (this.progress - t) / 0.46));
    const base = rail === 'top'
      ? COLORS.top
      : rail === 'bottom'
        ? COLORS.bottom
        : COLORS.rung[Math.floor(t * 100) % COLORS.rung.length];
    return this.colorScratch.copy(base).lerp(COLORS.head, headWeight * 0.72);
  }

  applyColors() {
    this.backboneSegments.forEach((mesh) => {
      const t = mesh.userData.t;
      const complete = this.progress > 0.001 && t <= this.progress;
      mesh.material.color.copy(this.colorForSegment(t, mesh.userData.rail));
      mesh.material.opacity = complete ? 1 : 0.42;
    });
    this.rungs.forEach((mesh) => {
      const t = mesh.userData.t;
      const complete = this.progress > 0.001 && t <= this.progress;
      mesh.material.color.copy(this.colorForSegment(t, 'rung'));
      mesh.material.opacity = complete ? 0.96 : 0.34;
    });
    this.ballMaterial.color.copy(this.colorScratch.copy(COLORS.head).lerp(COLORS.headEnd, this.progress * 0.35));
  }

  updateGeometry() {
    for (let index = 0; index < SEGMENTS - 1; index += 1) {
      this.helixPoint(index, 0, this.topA);
      this.helixPoint(index + 1, 0, this.topB);
      this.helixPoint(index, Math.PI, this.bottomA);
      this.helixPoint(index + 1, Math.PI, this.bottomB);
      this.placeCylinder(this.backboneSegments[index * 2], this.topA, this.topB, this.profile.backboneScale, BACKBONE_OVERLAP);
      this.placeCylinder(this.backboneSegments[index * 2 + 1], this.bottomA, this.bottomB, this.profile.backboneScale, BACKBONE_OVERLAP);
    }
    this.rungs.forEach((rung) => {
      const index = Math.round(rung.userData.t * (SEGMENTS - 1));
      this.helixPoint(index, 0, this.topA);
      this.helixPoint(index, Math.PI, this.bottomA);
      this.placeCylinder(rung, this.topA, this.bottomA, this.profile.rungScale);
    });
    this.ball.position.set(AXIS_MIN + (AXIS_MAX - AXIS_MIN) * this.progress, 0, 0.05);
    this.ball.scale.setScalar(this.profile.ballScale);
    this.centerRail.scale.set(this.profile.railScale, 1, this.profile.railScale);
  }

  setProgress(progress, payload = {}) {
    const nextProgress = clampProgress(progress);
    const nextProfile = profileForState(payload.state);
    const nextMotionPaused = Boolean(payload.motionPaused);
    const changed = !this.hasProgressState
      || nextProgress !== this.progress
      || nextProfile !== this.profile
      || nextMotionPaused !== this.motionPaused;
    this.progress = nextProgress;
    this.profile = nextProfile;
    this.motionPaused = nextMotionPaused;
    this.hasProgressState = true;
    if (!changed) return;
    this.applyCameraProfile();
    this.applyColors();
    this.geometryDirty = true;
    this.renderFrame(performance.now(), true);
    this.syncAnimationLoop();
  }

  setAutoSpiral(enabled) {
    this.baseAutoSpiral = Boolean(enabled);
    this.syncAnimationLoop();
  }

  applyCameraProfile() {
    const box = this.region.getBoundingClientRect();
    const width = Math.max(1, Math.floor(box.width));
    this.camera.position.z = width < 560 ? this.profile.cameraNarrow : this.profile.cameraWide;
    this.camera.updateProjectionMatrix();
  }

  resize() {
    const box = this.region.getBoundingClientRect();
    const width = Math.max(1, Math.floor(box.width));
    const height = Math.max(1, Math.floor(box.height));
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.applyCameraProfile();
    this.renderFrame(performance.now(), true);
  }

  renderFrame(now, force = false) {
    if (this.disposed || this.suspended) return;
    if (!force && now - this.lastRenderTime < FRAME_INTERVAL_MS) return;
    const delta = Math.min(0.05, Math.max(0, (now - this.lastFrameTime) / 1000));
    this.lastFrameTime = now;
    this.lastRenderTime = now;
    if (this.shouldAnimate()) {
      this.phase += delta * 1.15;
      this.updateGeometry();
      this.geometryDirty = false;
    } else if (force || this.geometryDirty) {
      this.updateGeometry();
      this.geometryDirty = false;
    }
    this.renderer.render(this.scene, this.camera);
  }

  shouldAnimate() {
    return this.baseAutoSpiral
      && !this.motionPaused
      && !this.reducedMotion.matches;
  }

  syncAnimationLoop() {
    if (this.disposed) return;
    if (this.suspended || !this.shouldAnimate()) {
      if (this.frame) {
        window.cancelAnimationFrame(this.frame);
        this.frame = 0;
      }
      return;
    }
    this.animate();
  }

  animate() {
    if (this.disposed || this.suspended || !this.shouldAnimate() || this.frame) return;
    this.frame = window.requestAnimationFrame((now) => {
      this.frame = 0;
      if (this.disposed || this.suspended) return;
      this.renderFrame(now);
      this.animate();
    });
  }

  suspend() {
    if (this.disposed || this.manualSuspended) return;
    this.manualSuspended = true;
    this.syncSuspension();
  }

  syncSuspension() {
    if (this.disposed) return;
    const shouldSuspend = this.manualSuspended || this.pageHidden || this.offscreen;
    if (shouldSuspend === this.suspended) return;
    this.suspended = shouldSuspend;
    if (this.frame) {
      window.cancelAnimationFrame(this.frame);
      this.frame = 0;
    }
    if (!shouldSuspend) {
      this.lastFrameTime = performance.now();
      this.renderFrame(this.lastFrameTime, true);
      this.syncAnimationLoop();
    }
  }

  resume() {
    if (this.disposed || !this.manualSuspended) return;
    this.manualSuspended = false;
    this.syncSuspension();
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.suspended = true;
    if (this.frame) {
      window.cancelAnimationFrame(this.frame);
      this.frame = 0;
    }
    this.resizeObserver?.disconnect();
    this.intersectionObserver?.disconnect();
    window.removeEventListener('resize', this.reducedMotionListener);
    window.removeEventListener('beforeunload', this.beforeUnloadListener);
    document.removeEventListener('visibilitychange', this.visibilityListener);
    this.reducedMotion.removeEventListener?.('change', this.reducedMotionListener);
    this.materials.forEach((material) => material.dispose());
    this.geometries.forEach((geometry) => geometry.dispose());
    this.renderer.dispose();
  }
}
