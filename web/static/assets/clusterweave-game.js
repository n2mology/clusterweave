(function initializeClusterWeaveGame(global) {
  'use strict';

  const Content = global.ClusterWeaveGameContent;
  const Core = global.ClusterWeaveGameCore;
  const document = global.document;
  if (!document) return;

  const byId = (id) => document.getElementById(id);
  if (!Content || !Core) {
    const fallback = byId('clusterweave-game-launcher');
    if (fallback) {
      fallback.removeAttribute('hidden');
      fallback.removeAttribute('inert');
      fallback.setAttribute('aria-hidden', 'false');
      fallback.querySelector('strong').textContent = 'Game unavailable';
      fallback.querySelector('p').textContent = 'The workflow is unaffected. Reload after the optional game assets are available.';
      fallback.querySelector('.clusterweave-game-launcher-actions')?.setAttribute('hidden', '');
    }
    return;
  }

  const dom = {
    shell: byId('clusterweave-game'),
    launcher: byId('clusterweave-game-launcher'),
    bootstrap: byId('clusterweave-game-bootstrap'),
    bootstrapOpen: byId('clusterweave-game-bootstrap-open'),
    start: byId('clusterweave-game-start'),
    best: byId('clusterweave-game-best'),
    close: byId('clusterweave-game-close'),
    hostState: byId('clusterweave-game-host-state'),
    canvas: byId('clusterweave-game-canvas'),
    viewport: byId('clusterweave-game-viewport'),
    overlay: byId('clusterweave-game-overlay'),
    overlayTitle: byId('clusterweave-game-overlay-title'),
    overlayCopy: byId('clusterweave-game-overlay-copy'),
    overlayActions: byId('clusterweave-game-overlay-actions'),
    depth: byId('clusterweave-game-depth'),
    score: byId('clusterweave-game-score'),
    bestRun: byId('clusterweave-game-best-run'),
    kit: byId('clusterweave-game-kit'),
    health: byId('clusterweave-game-health'),
    architecture: byId('clusterweave-game-architecture'),
    architectureSlots: byId('clusterweave-game-architecture-slots'),
    architectureStatus: byId('clusterweave-game-architecture-status'),
    toast: byId('clusterweave-game-toast'),
    guide: byId('clusterweave-game-guide'),
    jump: byId('clusterweave-game-jump'),
    pause: byId('clusterweave-game-pause'),
    end: byId('clusterweave-game-end'),
    screenReaderCard: byId('clusterweave-game-screen-reader-card'),
    status: byId('clusterweave-game-status'),
  };

  if (!dom.shell || !dom.launcher || !dom.canvas || !dom.viewport) return;
  const context = dom.canvas.getContext('2d', { alpha: false });
  if (!context) {
    dom.launcher.removeAttribute('hidden');
    dom.launcher.classList.remove('hidden');
    dom.launcher.removeAttribute('inert');
    dom.launcher.setAttribute('aria-hidden', 'false');
    dom.launcher.querySelector('strong').textContent = 'Game unavailable';
    return;
  }

  const TICKS_PER_SECOND = Content.constants.ticksPerSecond;
  const FIXED_STEP = 1 / TICKS_PER_SECOND;
  const WORLD_TO_CSS = 2;
  const MAX_CANVAS_DPR = 2;
  const PHYSICS = Object.freeze({
    baseSpeed: Number(Content.constants.baseSpeed || Content.constants.baseSpeedUnitsPerSecond) || 84,
    jumpVelocity: Number(Content.constants.jumpVelocity) || -195,
    gravity: Number(Content.constants.gravity) || 400,
    terminalVelocity: Number(Content.constants.terminalVelocity) || 320,
    coyoteTicks: Number(Content.constants.coyoteTicks) || 7,
    jumpBufferTicks: Number(Content.constants.jumpBufferTicks) || 9,
  });


  function scaledMotionPhysics(scaleValue = 1) {
    const motionScale = Math.max(1, Number(scaleValue) || 1);
    const jumpVelocity = PHYSICS.jumpVelocity * motionScale;
    const gravity = PHYSICS.gravity * motionScale * motionScale;
    const terminalVelocity = PHYSICS.terminalVelocity * motionScale;
    const airtimeSeconds = Math.abs(jumpVelocity) * 2 / gravity;
    return {
      motionScale,
      jumpVelocity,
      gravity,
      terminalVelocity,
      jumpRise: (jumpVelocity * jumpVelocity) / (2 * gravity),
      airtimeSeconds,
      jumpDistance: (PHYSICS.baseSpeed * motionScale) * airtimeSeconds,
    };
  }

  function motionScaleForPace(paceValue) {
    const constants = Content.constants || {};
    const basePace = Number(constants.basePacePermille) || 1000;
    const finalScale = Math.max(
      1,
      (Number(constants.finalStageMotionScalePermille) || 3000) / 1000,
    );
    const pace = Math.max(basePace, Number(paceValue) || basePace);
    return Math.max(1, Math.min(finalScale, pace / basePace));
  }

  function setRuntimePace(paceValue) {
    const pace = Math.max(1, Number(paceValue) || Content.constants.basePacePermille || 1000);
    runtime.currentPacePermille = pace;
    runtime.currentSpeed = PHYSICS.baseSpeed * pace / 1000;
    if (runtime.player?.onGround) runtime.player.motionScale = motionScaleForPace(pace);
  }

  function activeMotionPhysics() {
    const playerScale = runtime.player?.onGround ? 0 : runtime.player?.motionScale;
    const motion = scaledMotionPhysics(playerScale || motionScaleForPace(runtime.currentPacePermille));
    motion.jumpDistance = runtime.currentSpeed * motion.airtimeSeconds;
    return motion;
  }
  const COMPACT_QUERY = global.matchMedia('(max-width: 820px), (pointer: coarse) and (max-width: 1180px)');
  const REDUCED_MOTION_QUERY = global.matchMedia('(prefers-reduced-motion: reduce)');
  const FORCED_COLORS_QUERY = global.matchMedia('(forced-colors: active)');
  const KEY_ACTIONS = new Map([
    [' ', 'jump'],
    ['ArrowUp', 'jump'],
    ['w', 'jump'],
    ['W', 'jump'],
  ]);

  const session = Core.createSessionState({ seed: 'clusterweave-resident-tab' });
  const host = {
    epoch: 0,
    lifecycle: 'idle',
    phase: 'excavate',
    connection: global.navigator.onLine === false ? 'browser-offline' : 'connected',
  };
  const presentation = {
    open: false,
    view: 'wide',
    fromBootstrap: false,
    originalParent: dom.shell.parentNode,
    originalNext: dom.shell.nextSibling,
    returnFocus: null,
    inertRecords: [],
    overlayInertRecords: [],
  };
  const runtime = {
    run: null,
    pauseReasons: new Set(),
    frame: 0,
    inFrame: false,
    failed: false,
    lastFrameTime: 0,
    accumulator: 0,
    animationOwned: false,
    resizeObserver: null,
    resizeTimer: 0,
    toastTimer: 0,
    viewWidth: dom.canvas.width,
    viewHeight: dom.canvas.height,
    cssWidth: 0,
    cssHeight: 0,
    canvasDpr: 1,
    currentPacePermille: Content.constants.basePacePermille || 1000,
    currentSpeed: PHYSICS.baseSpeed,
    eventSerial: 0,
    eventLog: [],
    player: {
      x: 72,
      y: 100,
      width: Math.max(23, Number(Content.geometry.playerWidth) || 0),
      height: Math.max(36, Number(Content.geometry.playerHeight) || 0),
      motionScale: 1,
      velocityY: 0,
      onGround: true,
      supportId: 'ground',
      coyoteTicks: 0,
      jumpBufferTicks: 0,
      squashTicks: 0,
    },
    entities: [],
    particles: [],
    visualRng: Core.createSeededRng('clusterweave-visuals'),
    spawnTicks: Content.constants.safeRunwayTicks,
    entitySerial: 0,
    safeVisualTicks: Content.constants.safeRunwayTicks,
    cameraTicks: 0,
    palettePulseTicks: 0,
    architectureHoldTicks: 0,
    celebrationGenes: [],
    celebrationNumber: 0,
    beaconCue: '',
    beaconCueTicks: 0,
    announcedRoles: new Set(),
    bootstrapReady: false,
    heldActions: new Set(),
    hudSignature: '',
    launcherSignature: '',
    orientation: global.innerWidth >= global.innerHeight ? 'landscape' : 'portrait',
    motionReduced: REDUCED_MOTION_QUERY.matches || FORCED_COLORS_QUERY.matches,
    qaManualClock: false,
  };

  function setElementVisible(element, visible) {
    if (!element) return;
    element.classList.toggle('hidden', !visible);
    element.toggleAttribute('hidden', !visible);
    element.toggleAttribute('inert', !visible);
    element.setAttribute('aria-hidden', visible ? 'false' : 'true');
  }

  function recordEvent(type, detail = {}) {
    runtime.eventSerial += 1;
    const event = {
      id: runtime.eventSerial,
      tick: runtime.run?.ticks || 0,
      type: String(type || 'event'),
      ...detail,
    };
    runtime.eventLog.push(event);
    if (runtime.eventLog.length > 256) runtime.eventLog.splice(0, runtime.eventLog.length - 256);
    return event;
  }

  function announce(message) {
    const text = String(message || '').trim();
    if (!text || !dom.status) return;
    dom.status.textContent = '';
    global.requestAnimationFrame(() => { dom.status.textContent = text; });
  }

  function showToast(message, options = {}) {
    if (!dom.toast) return;
    global.clearTimeout(runtime.toastTimer);
    dom.toast.textContent = String(message || '');
    dom.toast.dataset.kind = options.kind || 'pickup';
    dom.toast.dataset.visible = 'true';
    dom.toast.removeAttribute('hidden');
    dom.toast.setAttribute('aria-hidden', 'false');
    runtime.toastTimer = global.setTimeout(() => {
      dom.toast.dataset.visible = 'false';
      dom.toast.setAttribute('hidden', '');
      dom.toast.setAttribute('aria-hidden', 'true');
    }, runtime.motionReduced ? 700 : (options.long ? 1500 : 950));
  }

  function hostIsTerminal() {
    return host.lifecycle === 'success' || host.lifecycle === 'failed';
  }

  function gameIsAvailable() {
    return host.lifecycle === 'pending'
      || host.lifecycle === 'running'
      || host.connection === 'reconnecting'
      || host.connection === 'browser-offline'
      || runtime.bootstrapReady
      || presentation.open;
  }

  function updateLauncher() {
    const visible = gameIsAvailable() && !hostIsTerminal();
    const signature = [
      visible,
      session.bestScore,
      session.bestArchitectures,
      runtime.run?.state || '',
      runtime.pauseReasons.has('closed'),
    ].join(':');
    if (signature === runtime.launcherSignature) return;
    runtime.launcherSignature = signature;
    setElementVisible(dom.launcher, visible);
    if (dom.best) {
      dom.best.textContent = session.bestScore
        ? `Session best · ${session.bestScore} · ${session.bestArchitectures} weave${session.bestArchitectures === 1 ? '' : 's'}`
        : 'Session best · 0';
    }
    if (dom.start) {
      dom.start.textContent = '';
      dom.start.setAttribute('aria-label', 'Play');
    }
  }

  function hostStatusText() {
    if (host.lifecycle === 'success') return 'Results ready';
    if (host.lifecycle === 'failed') return 'Workflow needs attention';
    if (host.connection === 'browser-offline') return 'Browser offline · game stays local';
    if (host.connection === 'reconnecting') return 'Reconnecting · game stays local';
    if (host.lifecycle === 'loading') return 'Switching workflow';
    if (host.lifecycle === 'pending') return 'Workflow queued';
    if (host.lifecycle === 'running') return 'Workflow running';
    return 'Local arcade ready';
  }

  function renderHostState() {
    dom.shell.dataset.hostLifecycle = host.lifecycle;
    dom.shell.dataset.hostConnection = host.connection;
    if (dom.hostState) dom.hostState.textContent = hostStatusText();
  }

  /*
   * DNA animation ownership is intentionally compact/mobile-only. A desktop
   * bootstrap overlay may be fullscreen but must not suspend the DNA station.
   */
  function dispatchAnimationOwnership() {
    const active = presentation.open && COMPACT_QUERY.matches;
    if (runtime.animationOwned === active) return;
    runtime.animationOwned = active;
    global.dispatchEvent(new CustomEvent('clusterweave:game-animation', { detail: { active } }));
  }

  function animationShouldRun() {
    return presentation.open
      && !runtime.failed
      && !runtime.qaManualClock
      && !document.hidden
      && runtime.run?.state === 'playing';
  }

  function startFrameLoop() {
    if (runtime.frame || runtime.inFrame || !animationShouldRun()) return;
    runtime.lastFrameTime = global.performance.now();
    runtime.accumulator = 0;
    runtime.frame = global.requestAnimationFrame(frameLoop);
  }

  function stopFrameLoop() {
    if (runtime.frame) global.cancelAnimationFrame(runtime.frame);
    runtime.frame = 0;
    runtime.lastFrameTime = 0;
    runtime.accumulator = 0;
  }

  function syncFrameLoop() {
    if (animationShouldRun()) startFrameLoop();
    else {
      stopFrameLoop();
      if (presentation.open) renderCanvas();
    }
  }

  function frameLoop(now) {
    runtime.frame = 0;
    if (!animationShouldRun()) return;
    runtime.inFrame = true;
    try {
      const delta = Math.min(0.1, Math.max(0, (now - runtime.lastFrameTime) / 1000));
      runtime.lastFrameTime = now;
      runtime.accumulator += delta;
      let steps = 0;
      while (runtime.accumulator >= FIXED_STEP && steps < 8) {
        updateSimulation();
        runtime.accumulator -= FIXED_STEP;
        steps += 1;
      }
      renderCanvas();
    } catch (error) {
      runtime.inFrame = false;
      handleRuntimeFailure(error);
      return;
    }
    runtime.inFrame = false;
    if (animationShouldRun()) runtime.frame = global.requestAnimationFrame(frameLoop);
  }

  function restoreBackgroundInert() {
    presentation.inertRecords.forEach(({ element, inert }) => { element.inert = inert; });
    presentation.inertRecords = [];
  }

  function applyBackgroundInert() {
    restoreBackgroundInert();
    presentation.inertRecords = Array.from(document.body.children)
      .filter((element) => element !== dom.shell)
      .map((element) => ({ element, inert: element.inert }));
    presentation.inertRecords.forEach(({ element }) => { element.inert = true; });
  }

  function restoreShellPlacement() {
    restoreBackgroundInert();
    const parent = presentation.originalParent;
    if (!parent || dom.shell.parentNode === parent) return;
    const reference = presentation.originalNext?.parentNode === parent
      ? presentation.originalNext
      : byId('workflow-progress-panel');
    parent.insertBefore(dom.shell, reference || null);
  }

  function desiredView() {
    return presentation.fromBootstrap || COMPACT_QUERY.matches ? 'fullscreen' : 'wide';
  }

  function applyPresentation(view = desiredView()) {
    const nextView = view === 'fullscreen' ? 'fullscreen' : 'wide';
    presentation.view = nextView;
    if (nextView === 'fullscreen') {
      if (dom.shell.parentNode !== document.body) document.body.appendChild(dom.shell);
      applyBackgroundInert();
      dom.shell.setAttribute('role', 'dialog');
      dom.shell.setAttribute('aria-modal', 'true');
    } else {
      restoreShellPlacement();
      dom.shell.setAttribute('role', 'region');
      dom.shell.removeAttribute('aria-modal');
    }
    document.body.dataset.clusterweaveGame = 'open';
    document.body.dataset.clusterweaveGameView = nextView;
    document.body.dataset.clusterweaveGameBootstrap = presentation.fromBootstrap ? 'true' : 'false';
    resizeCanvas(true);
    dispatchAnimationOwnership();
  }

  function closePresentation(options = {}) {
    if (!presentation.open) return;
    pauseGame('closed', { overlay: false });
    presentation.open = false;
    stopFrameLoop();
    dispatchAnimationOwnership();
    restoreShellPlacement();
    setElementVisible(dom.shell, false);
    delete document.body.dataset.clusterweaveGame;
    delete document.body.dataset.clusterweaveGameView;
    delete document.body.dataset.clusterweaveGameBootstrap;
    runtime.heldActions.clear();
    restoreOverlayBackground();
    updateLauncher();
    const shouldReturnFocus = options.returnFocus !== false;
    if (shouldReturnFocus) {
      global.requestAnimationFrame(() => {
        const preferred = elementIsVisibleAndFocusable(presentation.returnFocus)
          ? presentation.returnFocus
          : elementIsVisibleAndFocusable(dom.start)
            ? dom.start
            : byId('workflow-progress-panel');
        preferred?.focus?.({ preventScroll: true });
      });
    }
    if (options.reason === 'success' || options.reason === 'failed') {
      global.dispatchEvent(new CustomEvent('clusterweave:game-workflow-focus', {
        detail: { lifecycle: options.reason },
      }));
    }
  }

  function setHostState(next = {}) {
    const hasEpoch = Object.prototype.hasOwnProperty.call(next, 'epoch');
    const rawEpoch = hasEpoch ? Number(next.epoch) : host.epoch;
    if (!Number.isSafeInteger(rawEpoch) || rawEpoch < 0) return false;
    const epoch = rawEpoch;
    if (epoch < host.epoch) return false;
    const phase = String(next.phase || '').toLowerCase();
    if (next.phase != null && !['excavate', 'classify', 'compare', 'contextualize'].includes(phase)) return false;
    let lifecycle = String(next.lifecycle || '').toLowerCase();
    if (lifecycle === 'complete') lifecycle = 'success';
    if (next.lifecycle != null && !['idle', 'loading', 'pending', 'running', 'success', 'failed'].includes(lifecycle)) {
      return false;
    }
    const epochChanged = epoch !== host.epoch;
    host.epoch = epoch;
    if (['excavate', 'classify', 'compare', 'contextualize'].includes(phase)) host.phase = phase;
    if (['idle', 'loading', 'pending', 'running', 'success', 'failed'].includes(lifecycle)) {
      host.lifecycle = lifecycle;
    }
    renderHostState();
    if (epochChanged && lifecycle === 'loading' && presentation.open) pauseGame('lifecycle');
    if ((host.lifecycle === 'pending' || host.lifecycle === 'running') && runtime.pauseReasons.has('lifecycle')) {
      runtime.pauseReasons.delete('lifecycle');
      showPauseOverlay('Workflow switched', 'Your local run was preserved. Resume when ready.');
    }
    if (hostIsTerminal()) {
      const message = host.lifecycle === 'success'
        ? 'Results ready. Returning to the workflow.'
        : 'Workflow needs attention. Returning to the workflow.';
      announce(message);
      closePresentation({ reason: host.lifecycle, returnFocus: false });
    }
    updateLauncher();
    return true;
  }

  function setConnectionState(connection) {
    if (!['connected', 'reconnecting', 'browser-offline'].includes(connection)) return false;
    host.connection = connection;
    renderHostState();
    updateLauncher();
    return true;
  }

  function groundY() {
    return Math.max(72, runtime.viewHeight - 24);
  }

  function resizeCanvas(initial = false) {
    if (!presentation.open) return;
    const box = dom.canvas.getBoundingClientRect();
    if (box.width < 1 || box.height < 1) return;
    const previousWidth = runtime.viewWidth;
    const previousHeight = runtime.viewHeight;
    const cssWidth = Math.max(1, Math.round(box.width));
    const cssHeight = Math.max(1, Math.round(box.height));
    const dpr = Math.max(1, Math.min(MAX_CANVAS_DPR, Number(global.devicePixelRatio) || 1));
    const width = cssWidth / WORLD_TO_CSS;
    const height = cssHeight / WORLD_TO_CSS;
    const backingWidth = Math.max(1, Math.round(cssWidth * dpr));
    const backingHeight = Math.max(1, Math.round(cssHeight * dpr));
    if (
      runtime.cssWidth === cssWidth
      && runtime.cssHeight === cssHeight
      && runtime.canvasDpr === dpr
      && dom.canvas.width === backingWidth
      && dom.canvas.height === backingHeight
    ) return;
    dom.canvas.width = backingWidth;
    dom.canvas.height = backingHeight;
    context.setTransform(dpr * WORLD_TO_CSS, 0, 0, dpr * WORLD_TO_CSS, 0, 0);
    context.imageSmoothingEnabled = true;
    runtime.cssWidth = cssWidth;
    runtime.cssHeight = cssHeight;
    runtime.canvasDpr = dpr;
    runtime.viewWidth = width;
    runtime.viewHeight = height;
    if (!initial && previousWidth > 0) {
      const rightEdgeShift = width - previousWidth;
      runtime.entities.forEach((entity) => {
        if (entity.x > runtime.player.x) entity.x += rightEdgeShift;
      });
      if (runtime.run) runtime.run.safeRunwayTicks = Math.max(
        runtime.run.safeRunwayTicks,
        Content.constants.safeRunwayTicks,
      );
      runtime.safeVisualTicks = Content.constants.safeRunwayTicks;
    }
    runtime.player.x = Math.max(30, Math.min(84, Math.floor(width * 0.16)));
    if (runtime.player.onGround || previousHeight !== height) {
      runtime.player.y = groundY() - runtime.player.height;
      runtime.player.velocityY = 0;
      runtime.player.onGround = true;
      runtime.player.supportId = 'ground';
    }
    renderCanvas();
  }

  function scheduleResizePause() {
    global.clearTimeout(runtime.resizeTimer);
    runtime.resizeTimer = global.setTimeout(() => {
      resizeCanvas(false);
      if (presentation.open && runtime.run) {
        runtime.run.safeRunwayTicks = Math.max(runtime.run.safeRunwayTicks, Content.constants.safeRunwayTicks);
        runtime.safeVisualTicks = Content.constants.safeRunwayTicks;
      }
    }, 80);
  }

  function resetScene() {
    runtime.entities = [];
    runtime.particles = [];
    runtime.visualRng = Core.createSeededRng((runtime.run?.seed || 0) ^ 0xa5a5a5a5);
    setRuntimePace(Core.difficultyForTier(runtime.run?.tier || 1).pacePermille);
    runtime.eventSerial = 0;
    runtime.eventLog = [];
    runtime.spawnTicks = Content.constants.safeRunwayTicks;
    runtime.entitySerial = 0;
    runtime.safeVisualTicks = Content.constants.safeRunwayTicks;
    runtime.cameraTicks = 0;
    runtime.palettePulseTicks = 0;
    runtime.architectureHoldTicks = 0;
    runtime.celebrationGenes = [];
    runtime.celebrationNumber = 0;
    runtime.beaconCue = '';
    runtime.beaconCueTicks = 0;
    runtime.announcedRoles.clear();
    runtime.player.x = Math.max(30, Math.min(84, Math.floor(runtime.viewWidth * 0.16)));
    runtime.player.y = groundY() - runtime.player.height;
    runtime.player.velocityY = 0;
    runtime.player.onGround = true;
    runtime.player.supportId = 'ground';
    runtime.player.coyoteTicks = 0;
    runtime.player.jumpBufferTicks = 0;
    runtime.player.squashTicks = 0;
    recordEvent('runway-reset');
  }

  function overlayButton(label, action, kind = '') {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    if (kind) button.dataset.action = kind;
    button.addEventListener('click', action, { once: true });
    return button;
  }

  function elementIsVisibleAndFocusable(element) {
    return !!(
      element
      && element.isConnected
      && !element.disabled
      && !element.closest?.('[hidden], [inert]')
      && element.getClientRects?.().length
    );
  }

  function restoreOverlayBackground() {
    presentation.overlayInertRecords.forEach(({ element, inert }) => { element.inert = inert; });
    presentation.overlayInertRecords = [];
  }

  function makeOverlayBackgroundInert() {
    restoreOverlayBackground();
    const elements = [
      dom.canvas,
      dom.close,
      dom.jump,
      dom.pause,
      dom.end,
      dom.guide,
      dom.architecture,
      dom.health,
    ].filter(Boolean);
    presentation.overlayInertRecords = elements.map((element) => ({ element, inert: element.inert }));
    presentation.overlayInertRecords.forEach(({ element }) => { element.inert = true; });
  }

  function showOverlay(title, copy, actions = []) {
    if (!dom.overlay) return;
    makeOverlayBackgroundInert();
    dom.overlayTitle.textContent = title;
    dom.overlayCopy.textContent = copy;
    dom.overlayActions.replaceChildren(...actions.map((item) => overlayButton(item.label, item.action, item.kind)));
    dom.overlay.removeAttribute('hidden');
    dom.overlay.setAttribute('aria-hidden', 'false');
    dom.shell.dataset.gameOverlay = 'open';
    announce(`${title}. ${copy}`);
    global.requestAnimationFrame(() => dom.overlayActions.querySelector('button')?.focus({ preventScroll: true }));
  }

  function hideOverlay() {
    if (!dom.overlay) return;
    restoreOverlayBackground();
    dom.overlay.setAttribute('hidden', '');
    dom.overlay.setAttribute('aria-hidden', 'true');
    dom.overlayActions.replaceChildren();
    delete dom.shell.dataset.gameOverlay;
  }

  function showPauseOverlay(title = 'Run paused', copy = 'ClusterWeave keeps working while the run waits.') {
    showOverlay(title, copy, [
      { label: 'Resume run', action: () => resumeGame('user') },
      { label: 'New run', action: () => startNewRun() },
      { label: 'Exit', kind: 'close', action: () => closePresentation({ reason: 'close' }) },
    ]);
  }

  function pauseGame(reason = 'user', options = {}) {
    if (!runtime.run || runtime.failed || runtime.run.state === 'game_over') return false;
    runtime.pauseReasons.add(String(reason || 'user'));
    Core.pauseRun(runtime.run);
    runtime.heldActions.clear();
    if (options.overlay !== false && presentation.open) showPauseOverlay();
    updateHud();
    dispatchAnimationOwnership();
    syncFrameLoop();
    return true;
  }

  function resumeGame(reason = 'user') {
    if (!runtime.run || runtime.run.state === 'game_over' || runtime.failed) return false;
    const key = String(reason || 'user');
    runtime.pauseReasons.delete(key);
    if (key === 'user') {
      ['closed', 'viewport', 'visibility', 'focus', 'lifecycle'].forEach((item) => runtime.pauseReasons.delete(item));
    }
    if (runtime.pauseReasons.size > 0) return false;
    if (!Core.resumeRun(runtime.run)) return false;
    runtime.safeVisualTicks = Content.constants.safeRunwayTicks;
    runtime.entities = runtime.entities.filter((entity) => (
      !['obstacle', 'pit'].includes(entity.type)
      || entity.x > runtime.player.x + 140
    ));
    hideOverlay();
    dom.canvas.focus({ preventScroll: true });
    updateHud();
    dispatchAnimationOwnership();
    syncFrameLoop();
    return true;
  }

  function initializeRun(seed) {
    runtime.run = Core.createRun({ session, seed });
    Core.startRun(runtime.run);
    runtime.pauseReasons.clear();
    runtime.failed = false;
    runtime.hudSignature = '';
    dom.shell.dataset.gameState = runtime.run.state;
    resetScene();
  }

  function normalizeOpenOptions(first, second) {
    if (first && typeof first === 'object') return first;
    return second && typeof second === 'object' ? second : {};
  }

  function openGame(first = {}, second = {}) {
    if (hostIsTerminal()) return false;
    const options = normalizeOpenOptions(first, second);
    presentation.returnFocus = options.returnFocus || document.activeElement;
    presentation.fromBootstrap = !!options.fromBootstrap;
    const canResume = !options.forceNew
      && !runtime.failed
      && runtime.run?.state === 'paused'
      && runtime.pauseReasons.has('closed');
    presentation.open = true;
    setElementVisible(dom.shell, true);
    applyPresentation();
    if (!canResume) initializeRun(options.seed);
    renderHostState();
    updateHud();
    renderCanvas();
    if (canResume) {
      showPauseOverlay('Run held', 'Your candidate architecture is still here in this tab.');
    } else {
      hideOverlay();
      global.requestAnimationFrame(() => dom.canvas.focus({ preventScroll: true }));
      showToast('SPACE / TAP TO JUMP', { kind: 'start', long: true });
      syncFrameLoop();
    }
    return true;
  }

  function startNewRun(options = {}) {
    const seed = typeof options === 'object' ? options.seed : options;
    if (runtime.run) Core.restartRun(runtime.run, { seed });
    else initializeRun(seed);
    runtime.pauseReasons.clear();
    runtime.failed = false;
    runtime.hudSignature = '';
    resetScene();
    hideOverlay();
    updateHud();
    renderCanvas();
    dom.canvas.focus({ preventScroll: true });
    showToast('NEW RUN // CLEAR RUNWAY', { kind: 'start' });
    syncFrameLoop();
  }

  function healthPhrase(currentValue, maximumValue) {
    const names = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five'];
    const maximum = Math.max(1, Math.floor(Number(maximumValue) || Content.constants.maxHealth || 5));
    const current = Math.max(0, Math.min(maximum, Math.floor(Number(currentValue) || 0)));
    const maximumLabel = names[maximum]?.toLowerCase() || maximum;
    return `${names[current] || current} of ${maximumLabel} hearts`;
  }

  function renderHealth(snapshot) {
    if (!dom.health || !snapshot) return;
    const maximum = Math.max(1, Number(snapshot.maxHealth) || Content.constants.maxHealth || 5);
    const current = Math.max(0, Math.min(maximum, Number(snapshot.health) || 0));
    const hearts = Array.from(dom.health.querySelectorAll('[data-health-heart]'));
    hearts.forEach((heart, index) => {
      const active = index < current;
      heart.classList.toggle('is-active', active);
      heart.dataset.active = active ? 'true' : 'false';
    });
    dom.health.setAttribute('aria-valuemax', String(maximum));
    dom.health.setAttribute('aria-valuenow', String(current));
    dom.health.setAttribute('aria-valuetext', healthPhrase(current, maximum));
    dom.health.dataset.health = String(current);
  }

  function renderArchitecture() {
    if (!runtime.run || !dom.architectureSlots) return;
    const celebrating = runtime.architectureHoldTicks > 0 && runtime.celebrationGenes.length > 0;
    const genes = celebrating ? runtime.celebrationGenes : runtime.run.architecture.genes;
    const fragment = document.createDocumentFragment();
    for (let index = 0; index < Content.constants.genesPerArchitecture; index += 1) {
      const slot = document.createElement('span');
      slot.className = 'clusterweave-game-gene-slot';
      slot.setAttribute('role', 'listitem');
      slot.setAttribute('aria-hidden', 'true');
      const gene = genes[index];
      if (gene) {
        slot.classList.add('is-filled');
        slot.dataset.role = gene.roleId;
        slot.dataset.strand = gene.strand < 0 ? 'left' : 'right';
      } else {
        slot.dataset.strand = index % 2 ? 'left' : 'right';
      }
      fragment.appendChild(slot);
    }
    dom.architectureSlots.replaceChildren(fragment);
    if (dom.architecture) dom.architecture.dataset.celebrating = celebrating ? 'true' : 'false';
    dom.architectureSlots.setAttribute(
      'aria-label',
      celebrating
        ? `Collected gene sequence ${runtime.celebrationNumber} complete with ${genes.length} regions`
        : `Collected gene regions, ${genes.length} of ${Content.constants.genesPerArchitecture}`,
    );
    if (dom.architectureStatus) {
      dom.architectureStatus.textContent = celebrating
        ? `Architecture ${runtime.celebrationNumber} complete`
        : `${genes.length} / ${Content.constants.genesPerArchitecture} regions`;
    }
    const spokenGenes = genes.map((gene) => {
      const role = Content.roles[gene.roleId];
      return `${role.shortLabel.toLowerCase()} ${gene.strand < 0 ? 'left' : 'right'}-facing`;
    });
    if (dom.screenReaderCard) {
      dom.screenReaderCard.textContent = `${healthPhrase(runtime.run.health, Content.constants.maxHealth)}. Depth ${runtime.run.tier}. ${genes.length} of ${Content.constants.genesPerArchitecture} regions collected. ${spokenGenes.join(', ') || 'Sequence empty'}.`;
    }
  }

  function updateHud() {
    if (!runtime.run) return;
    const snapshot = Core.snapshot(runtime.run);
    const kitLabel = snapshot.upgrade.label;
    const signature = [
      snapshot.state,
      snapshot.score,
      snapshot.tier,
      snapshot.best.score,
      snapshot.completedArchitectures,
      snapshot.architecture.completed,
      snapshot.health,
      snapshot.maxHealth,
      kitLabel,
      snapshot.paletteId,
      runtime.architectureHoldTicks > 0,
    ].join('|');
    if (signature !== runtime.hudSignature) {
      runtime.hudSignature = signature;
      if (dom.depth) dom.depth.textContent = String(snapshot.tier).padStart(2, '0');
      if (dom.score) dom.score.textContent = String(snapshot.score).padStart(5, '0');
      if (dom.bestRun) dom.bestRun.textContent = String(snapshot.best.score).padStart(5, '0');
      if (dom.kit) dom.kit.textContent = kitLabel;
      dom.shell.dataset.gameState = snapshot.state;
      dom.shell.dataset.gameDepth = String(snapshot.tier);
      dom.shell.dataset.gamePalette = snapshot.paletteId;
      if (dom.pause) dom.pause.textContent = snapshot.state === 'paused' ? 'Resume' : 'Pause';
      renderHealth(snapshot);
      renderArchitecture();
      updateLauncher();
    }
    dispatchAnimationOwnership();
    syncFrameLoop();
  }

  function entityId(prefix) {
    runtime.entitySerial += 1;
    return `${runtime.run.seed}:${prefix}:${runtime.entitySerial}`;
  }

  function laneY(lane, width = 24, height = 12) {
    const ground = groundY();
    const offsets = Content.geometry.laneOffsets || {};
    const offset = offsets[lane] ?? offsets.low ?? 10;
    return ground - height - offset;
  }

  function obstacleDimensions(shape) {
    return Content.geometry.obstacles?.[shape] || Content.geometry.obstacles?.pylon || { width: 13, height: 24 };
  }

  function spawnPlacement(placement, baseX, metadata = {}) {
    const kind = ['gene', 'obstacle', 'warning', 'pit', 'platform'].includes(placement.kind)
      ? placement.kind
      : 'warning';
    const entity = {
      id: placement.id || entityId(kind),
      type: kind,
      x: baseX + Math.max(0, Number(placement.at) || 0),
      y: groundY() - 10,
      width: 8,
      height: 8,
      removed: false,
      shape: placement.shape || '',
      phraseId: metadata.phraseId || '',
      templateId: metadata.templateId || '',
    };
    if (entity.type === 'gene') {
      entity.width = Math.max(22, Number(Content.geometry.geneWidth) || 24);
      entity.height = Math.max(11, Number(Content.geometry.geneHeight) || 12);
      entity.y = laneY(placement.lane, entity.width, entity.height);
      entity.roleId = placement.roleId || 'unassigned';
      entity.strand = placement.strand === -1 ? -1 : 1;
      entity.predicted = true;
    } else if (entity.type === 'obstacle') {
      const size = obstacleDimensions(entity.shape);
      entity.width = size.width;
      entity.height = size.height;
      entity.y = groundY() - entity.height;
    } else if (entity.type === 'pit') {
      const pitShape = Content.geometry.pits?.[entity.shape] || Content.geometry.pits?.medium || {};
      entity.shape = entity.shape || 'dnase';
      entity.width = Math.max(18, Number(placement.width) || Number(pitShape.width) || 34);
      entity.height = Math.max(24, runtime.viewHeight - groundY());
      entity.y = groundY();
    } else if (entity.type === 'platform') {
      const platformShape = Content.geometry.platforms?.[entity.shape] || Content.geometry.platforms?.field || {};
      entity.width = Math.max(26, Number(placement.width) || Number(platformShape.width) || 48);
      entity.elevation = Math.max(8, Number(placement.elevation ?? placement.height) || Number(platformShape.elevation ?? platformShape.height) || 16);
      entity.height = Math.max(5, Number(placement.thickness) || Number(platformShape.thickness) || 7);
      entity.y = groundY() - entity.elevation;
    } else {
      entity.width = entity.shape === 'beacon' ? 10 : Math.max(13, Number(placement.width) || 13);
      entity.height = entity.shape === 'beacon' ? 27 : 9;
      entity.y = groundY() - entity.height;
    }
    runtime.entities.push(entity);
    return entity;
  }

  function spawnPhrase(options = {}) {
    const settings = options && typeof options === 'object' ? options : { templateId: options };
    const phrase = Core.generatePhrase(runtime.run, {
      templateId: settings.templateId,
      boundary: settings.boundary,
    });
    if (!phrase) return null;
    const difficulty = Core.difficultyForTier(runtime.run.tier);
    const numericOffset = Number(settings.offset);
    const baseX = Number.isFinite(numericOffset)
      ? runtime.player.x + Math.max(8, numericOffset)
      : runtime.viewWidth + 20;
    const spawned = [];
    phrase.placements.forEach((placement) => {
      const hazard = placement.kind === 'obstacle' || placement.kind === 'pit';
      if (!settings.forceHazards && runtime.safeVisualTicks > 0 && hazard) return;
      spawned.push(spawnPlacement(placement, baseX, {
        phraseId: phrase.id,
        templateId: phrase.templateId,
      }));
    });
    const placementEnd = phrase.placements.reduce((end, placement) => (
      Math.max(end, (Number(placement.at) || 0) + (Number(placement.width) || 28))
    ), 0);
    const span = Math.max(placementEnd, Number(phrase.span) || 120);
    const recoveryDistance = Math.max(36, Number(phrase.recoveryDistance) || 80);
    const travelSpeed = Math.max(1, runtime.currentSpeed || PHYSICS.baseSpeed);
    runtime.spawnTicks = Math.max(1, Math.ceil((span + recoveryDistance) / travelSpeed * TICKS_PER_SECOND));
    if (runtime.run.completedArchitectures >= 5 || phrase.boundary) {
      runtime.beaconCue = phrase.boundary ? 'BOUNDARY' : String(phrase.safeRoute || 'RUN').toUpperCase();
      runtime.beaconCueTicks = difficulty.reactionTicks;
    }
    recordEvent('phrase-spawned', {
      phraseId: phrase.id,
      templateId: phrase.templateId,
      boundary: !!phrase.boundary,
      respite: !!phrase.respite,
      entityIds: spawned.map((entity) => entity.id),
    });
    return { ...phrase, entityIds: spawned.map((entity) => entity.id) };
  }

  function rectanglesOverlap(a, b) {
    return a.x < b.x + b.width
      && a.x + a.width > b.x
      && a.y < b.y + b.height
      && a.y + a.height > b.y;
  }

  function playerBox() {
    return {
      x: runtime.player.x + 4,
      y: runtime.player.y + 3,
      width: runtime.player.width - 8,
      height: runtime.player.height - 6,
    };
  }

  function addParticles(x, y, color, count = 8) {
    if (runtime.motionReduced) return;
    const bounded = Math.min(20 - runtime.particles.length, Math.max(0, count));
    for (let index = 0; index < bounded; index += 1) {
      runtime.particles.push({
        x,
        y,
        vx: (Core.randomInt(runtime.visualRng, 25) - 12) / 5,
        vy: -(2 + Core.randomInt(runtime.visualRng, 18) / 6),
        life: 18 + Core.randomInt(runtime.visualRng, 16),
        color,
      });
    }
  }

  function handleCollectionResult(result, entity) {
    if (!result?.collected) return;
    const role = Content.roles[result.gene.roleId];
    const x = entity?.x ?? runtime.player.x + runtime.player.width;
    const y = entity?.y ?? runtime.player.y;
    addParticles(x, y, role.color, 9);
    if (!runtime.announcedRoles.has(result.gene.roleId)) {
      runtime.announcedRoles.add(result.gene.roleId);
      showToast(`${role.label} REGION +${result.basePoints}`, { kind: 'pickup' });
    }
    if (!result.architectureComplete) {
      announce(`${role.shortLabel} predicted region collected. ${runtime.run.architecture.genes.length} of ${Content.constants.genesPerArchitecture}.`);
    }
    if (result.architectureComplete) {
      runtime.palettePulseTicks = runtime.motionReduced ? 1 : 48;
      runtime.cameraTicks = runtime.motionReduced ? 0 : 12;
      runtime.celebrationGenes = runtime.run.lastArchitecture?.genes.map((gene) => ({ ...gene })) || [];
      runtime.celebrationNumber = result.completedArchitectures;
      runtime.architectureHoldTicks = runtime.motionReduced ? 45 : 90;
      const upgrade = result.upgradeUnlocked ? Content.upgrades.find((item) => item.id === result.upgradeUnlocked) : null;
      const upgradeText = upgrade ? ` · ${upgrade.label} EQUIPPED` : '';
      showToast(
        `ARCHITECTURE ${result.completedArchitectures} COMPLETE · DEPTH ${result.tier}${upgradeText}`,
        { kind: 'complete', long: true },
      );
      announce(`Gene sequence ${result.completedArchitectures} complete. Depth ${result.tier}.${upgrade ? ` ${upgrade.label} equipped.` : ''}`);
    }
    updateHud();
  }

  function collectEntity(entity) {
    if (!entity || entity.removed || entity.type !== 'gene') return { collected: false };
    const result = Core.collectGene(runtime.run, {
      id: entity.id,
      roleId: entity.roleId,
      strand: entity.strand,
    });
    if (result.collected) {
      entity.removed = true;
      handleCollectionResult(result, entity);
    }
    return result;
  }

  function hazardIsActive() {
    return runtime.safeVisualTicks <= 0 && (runtime.run?.safeRunwayTicks || 0) <= 0;
  }

  function pitUnderPlayer() {
    if (!hazardIsActive()) return null;
    const footX = runtime.player.x + runtime.player.width * 0.5;
    return runtime.entities.find((entity) => (
      !entity.removed
      && entity.type === 'pit'
      && footX > entity.x + 3
      && footX < entity.x + entity.width - 3
    )) || null;
  }

  function platformUnderPlayer() {
    const box = playerBox();
    return runtime.entities
      .filter((entity) => (
        !entity.removed
        && entity.type === 'platform'
        && box.x + box.width > entity.x + 2
        && box.x < entity.x + entity.width - 2
      ))
      .sort((left, right) => left.y - right.y)[0] || null;
  }

  function triggerObstacleDamage(entity = null, reason = 'orange-obstacle') {
    if (entity?.damageApplied) return { damaged: false, reason: 'already-damaged' };
    if (entity) {
      entity.damageApplied = true;
      entity.removed = true;
    }
    const result = Core.damage(runtime.run, reason);
    if (!result.damaged) return result;
    const x = entity?.x ?? runtime.player.x + runtime.player.width / 2;
    const y = entity?.y ?? runtime.player.y + runtime.player.height / 2;
    addParticles(x, y, '#ff9a36', 14);
    runtime.cameraTicks = runtime.motionReduced ? 0 : 10;
    recordEvent('damage', {
      reason,
      health: result.health,
      healthLost: result.healthLost,
      entityId: entity?.id || '',
    });
    if (result.gameOver) {
      showGameOver();
    } else {
      showToast(`HEART LOST // ${result.health} LEFT`, { kind: 'damage' });
      announce(`Obstacle hit. ${result.health} heart${result.health === 1 ? '' : 's'} remaining.`);
    }
    updateHud();
    return result;
  }

  function triggerCrash(reason = 'fatal-terrain-collision', entity = null) {
    const result = Core.crash(runtime.run, reason);
    if (!result.crashed) return result;
    const x = entity?.x ?? runtime.player.x + runtime.player.width / 2;
    const y = entity?.y ?? runtime.player.y + runtime.player.height / 2;
    addParticles(x, y, '#ff9a36', 18);
    runtime.cameraTicks = runtime.motionReduced ? 0 : 18;
    recordEvent('crash', { reason, fatal: true, entityId: entity?.id || '' });
    if (result.gameOver) showGameOver();
    updateHud();
    return result;
  }

  function collectEntities() {
    const player = playerBox();
    for (const entity of runtime.entities) {
      if (entity.removed) continue;
      if (entity.type === 'gene' && rectanglesOverlap(player, entity)) {
        collectEntity(entity);
      } else if (
        entity.type === 'obstacle'
        && hazardIsActive()
        && rectanglesOverlap(player, entity)
      ) {
        triggerObstacleDamage(entity);
        break;
      }
    }
  }

  function requestJump() {
    if (!runtime.run || !presentation.open) return;
    if (runtime.run.state === 'game_over') {
      startNewRun();
      return;
    }
    if (runtime.run.state === 'paused') {
      resumeGame('user');
      return;
    }
    if (runtime.run.state !== 'playing') return;
    runtime.player.jumpBufferTicks = PHYSICS.jumpBufferTicks;
    attemptBufferedJump();
  }

  function attemptBufferedJump() {
    const player = runtime.player;
    if (player.jumpBufferTicks <= 0 || (!player.onGround && player.coyoteTicks <= 0)) return false;
    const motion = activeMotionPhysics();
    player.motionScale = motion.motionScale;
    player.velocityY = motion.jumpVelocity;
    player.onGround = false;
    player.supportId = null;
    player.coyoteTicks = 0;
    player.jumpBufferTicks = 0;
    player.squashTicks = 0;
    addParticles(player.x + 7, player.y + player.height, '#fff8e7', 4);
    recordEvent('jump', { y: player.y, speed: runtime.currentSpeed });
    return true;
  }

  function releaseJump() {
    // One dependable arc keeps keyboard, pointer, and touch timing equivalent.
    recordEvent('jump-release');
  }

  function updateParticles() {
    runtime.particles.forEach((particle) => {
      particle.x += particle.vx;
      particle.y += particle.vy;
      particle.vy += 0.18;
      particle.life -= 1;
    });
    runtime.particles = runtime.particles.filter((particle) => particle.life > 0).slice(-20);
  }

  function landPlayer(top, supportId) {
    const player = runtime.player;
    player.y = top - player.height;
    player.velocityY = 0;
    player.onGround = true;
    player.supportId = supportId;
    player.motionScale = motionScaleForPace(runtime.currentPacePermille);
    player.squashTicks = 6;
    player.coyoteTicks = PHYSICS.coyoteTicks;
    addParticles(player.x + player.width / 2, top - 1, '#b8a5ff', 3);
    recordEvent('land', { supportId, y: player.y });
    // A buffered input on the landing tick must launch before collision checks.
    attemptBufferedJump();
  }

  function updateSimulation() {
    if (!runtime.run || runtime.run.state !== 'playing') return;
    Core.advanceTicks(runtime.run, 1);
    runtime.safeVisualTicks = Math.max(0, runtime.safeVisualTicks - 1);
    runtime.cameraTicks = Math.max(0, runtime.cameraTicks - 1);
    runtime.palettePulseTicks = Math.max(0, runtime.palettePulseTicks - 1);
    runtime.architectureHoldTicks = Math.max(0, runtime.architectureHoldTicks - 1);
    runtime.beaconCueTicks = Math.max(0, runtime.beaconCueTicks - 1);

    const player = runtime.player;
    const difficulty = Core.difficultyForTier(runtime.run.tier);
    if (player.onGround) {
      const paceDifference = difficulty.pacePermille - runtime.currentPacePermille;
      const rampTicks = Math.max(1, Number(Content.constants.paceRampTicks) || 90);
      const paceStep = Math.max(1, Math.ceil(Math.abs(paceDifference) / rampTicks));
      setRuntimePace(
        runtime.currentPacePermille
          + Math.sign(paceDifference) * Math.min(Math.abs(paceDifference), paceStep),
      );
    }
    runtime.entities.forEach((entity) => { entity.x -= runtime.currentSpeed / TICKS_PER_SECOND; });
    runtime.entities = runtime.entities
      .filter((entity) => !entity.removed && entity.x + entity.width > -36)
      .slice(-Content.constants.maxEntities);
    player.jumpBufferTicks = Math.max(0, player.jumpBufferTicks - 1);
    player.squashTicks = Math.max(0, player.squashTicks - 1);
    if (player.onGround) player.coyoteTicks = PHYSICS.coyoteTicks;
    else player.coyoteTicks = Math.max(0, player.coyoteTicks - 1);

    if (player.onGround && player.supportId && player.supportId !== 'ground') {
      const support = runtime.entities.find((entity) => entity.id === player.supportId && !entity.removed);
      const stillSupported = support
        && player.x + player.width - 4 > support.x
        && player.x + 4 < support.x + support.width;
      if (stillSupported) player.y = support.y - player.height;
      else {
        player.onGround = false;
        player.supportId = null;
      }
    } else if (player.onGround && pitUnderPlayer()) {
      player.onGround = false;
      player.supportId = null;
      recordEvent('pit-edge');
    } else if (player.onGround) {
      player.y = groundY() - player.height;
      player.supportId = 'ground';
    }

    attemptBufferedJump();
    const ground = groundY();
    if (!player.onGround) {
      const previousBottom = player.y + player.height;
      const motion = activeMotionPhysics();
      const previousVelocity = player.velocityY;
      const nextVelocity = Math.min(
        motion.terminalVelocity,
        previousVelocity + motion.gravity / TICKS_PER_SECOND,
      );
      player.y += (previousVelocity + nextVelocity) / (2 * TICKS_PER_SECOND);
      player.velocityY = nextVelocity;
      const nextBottom = player.y + player.height;
      let landed = false;
      if (player.velocityY >= 0) {
        const platform = platformUnderPlayer();
        if (platform && previousBottom <= platform.y + 2 && nextBottom >= platform.y) {
          landPlayer(platform.y, platform.id);
          landed = true;
        }
      }
      const pit = pitUnderPlayer();
      if (!landed && !pit && nextBottom >= ground) {
        landPlayer(ground, 'ground');
        landed = true;
      }
      if (!landed && pit && nextBottom > ground + 8) {
        triggerCrash('dnase-pit', pit);
        return;
      }
    }

    runtime.spawnTicks -= 1;
    if (runtime.spawnTicks <= 0) {
      if (runtime.safeVisualTicks > 0 || (runtime.run.safeRunwayTicks || 0) > 0) {
        runtime.spawnTicks = 1;
      } else {
        spawnPhrase();
      }
    }
    collectEntities();
    updateParticles();
    updateHud();
  }

  function showGameOver() {
    const snapshot = Core.snapshot(runtime.run);
    showOverlay(
      'SHIFT OVER',
      `${snapshot.score} points · ${snapshot.completedArchitectures} architecture${snapshot.completedArchitectures === 1 ? '' : 's'} · depth ${snapshot.tier}.`,
      [
        { label: 'Run again', action: () => startNewRun() },
        { label: 'Exit', kind: 'close', action: () => closePresentation({ reason: 'close' }) },
      ],
    );
    announce(`Run over. Score ${snapshot.score}. Choose Run again to start over.`);
    syncFrameLoop();
  }

  function endRun() {
    if (!runtime.run || runtime.run.state === 'game_over') return;
    if (runtime.run.state === 'paused') {
      runtime.pauseReasons.clear();
      Core.resumeRun(runtime.run);
    }
    triggerCrash('run-ended');
  }

  function pixelRect(x, y, width, height, color) {
    context.fillStyle = color;
    context.fillRect(Math.round(x), Math.round(y), Math.max(1, Math.round(width)), Math.max(1, Math.round(height)));
  }

  function outlineRect(x, y, width, height, color = '#05070d', thickness = 1) {
    const px = Math.round(x);
    const py = Math.round(y);
    const pw = Math.max(1, Math.round(width));
    const ph = Math.max(1, Math.round(height));
    pixelRect(px, py, pw, thickness, color);
    pixelRect(px, py + ph - thickness, pw, thickness, color);
    pixelRect(px, py, thickness, ph, color);
    pixelRect(px + pw - thickness, py, thickness, ph, color);
  }

  function polygon(points, fill, stroke = '#05070d', lineWidth = 1.5) {
    if (!points.length) return;
    context.beginPath();
    context.moveTo(points[0][0], points[0][1]);
    points.slice(1).forEach(([x, y]) => context.lineTo(x, y));
    context.closePath();
    context.fillStyle = fill;
    context.fill();
    if (stroke && lineWidth > 0) {
      context.strokeStyle = stroke;
      context.lineWidth = lineWidth;
      context.lineJoin = 'miter';
      context.stroke();
    }
  }


  function jointedLimb(points, color, outerWidth = 5, innerWidth = 2.4) {
    context.save();
    context.lineCap = 'square';
    context.lineJoin = 'miter';
    context.beginPath();
    context.moveTo(points[0][0], points[0][1]);
    points.slice(1).forEach(([x, y]) => context.lineTo(x, y));
    context.strokeStyle = '#05070d';
    context.lineWidth = outerWidth;
    context.stroke();
    context.strokeStyle = color;
    context.lineWidth = innerWidth;
    context.stroke();
    context.restore();
  }
  function currentPalette() {
    return Core.paletteForTier(runtime.run?.tier || 1);
  }

  function drawHyphae(palette, ground, drift) {
    context.save();
    context.globalAlpha = 0.42;
    context.strokeStyle = palette.mist;
    context.lineWidth = 2;
    for (let root = -40; root < runtime.viewWidth + 70; root += 92) {
      const x = root - (drift % 92);
      context.beginPath();
      context.moveTo(x, ground - 8);
      context.lineTo(x + 16, ground - 32);
      context.lineTo(x + 31, ground - 39);
      context.moveTo(x + 16, ground - 32);
      context.lineTo(x + 9, ground - 53);
      context.moveTo(x + 31, ground - 39);
      context.lineTo(x + 45, ground - 61);
      context.stroke();
      const biology = palette.biology || '#65e8ff';
      pixelRect(x + 7, ground - 56, 3, 3, biology);
      pixelRect(x + 3, ground - 60, 2, 2, biology);
      pixelRect(x + 13, ground - 61, 2, 2, biology);
      pixelRect(x + 43, ground - 65, 3, 3, biology);
      pixelRect(x + 49, ground - 68, 2, 2, biology);
      pixelRect(x + 39, ground - 70, 1, 1, biology);
    }
    context.restore();
  }

  function backdropSceneryLayout(widthValue, groundValue, motionValue) {
    const width = Math.max(1, Number(widthValue) || 1);
    const ground = Math.max(0, Number(groundValue) || 0);
    const motion = Math.max(0, Math.floor(Number(motionValue) || 0));
    const compact = width < 260 || ground < 100;
    const period = compact ? 152 : 128;
    const drift = Math.floor(motion / 14);
    const lanes = ground < 100
      ? [Math.max(26, ground - 38)]
      : [Math.max(26, ground - 66), Math.max(26, ground - 48)];
    const bacteria = [];
    const origin = 16;
    const firstTile = Math.floor((drift - origin - 20) / period);
    for (let tile = firstTile; ; tile += 1) {
      const anchorX = origin + tile * period - drift;
      const left = anchorX - 13;
      const right = anchorX + 20;
      if (left >= width) break;
      if (right <= 0) continue;
      const centerY = lanes[Math.abs(tile) % lanes.length];
      bacteria.push({
        tile,
        x: Math.round(left),
        y: Math.round(centerY - 6),
        width: 33,
        height: 12,
        anchorX: Math.round(anchorX),
        centerY: Math.round(centerY),
      });
    }
    return { period, drift, bacteria };
  }

  function drawSpiralFlagellate(instance, palette) {
    const biology = palette.biology || '#65e8ff';
    context.save();
    context.translate(instance.anchorX, instance.centerY);
    context.globalAlpha = 0.52;
    context.lineCap = 'square';
    context.lineJoin = 'miter';

    context.beginPath();
    context.moveTo(0, 0);
    context.lineTo(-4, -3);
    context.lineTo(-8, 2);
    context.lineTo(-13, -1);
    context.strokeStyle = biology;
    context.lineWidth = 1;
    context.stroke();

    context.beginPath();
    context.moveTo(0, 0);
    context.lineTo(4, -3);
    context.lineTo(8, 3);
    context.lineTo(12, -3);
    context.lineTo(16, 3);
    context.lineTo(20, 0);
    context.strokeStyle = palette.mist;
    context.lineWidth = 4;
    context.stroke();
    context.strokeStyle = biology;
    context.lineWidth = 2;
    context.stroke();
    context.restore();
  }

  function drawSpiralFlagellates(instances, palette) {
    instances.forEach((instance) => drawSpiralFlagellate(instance, palette));
  }

  function drawBackdrop() {
    const width = runtime.viewWidth;
    const height = runtime.viewHeight;
    const ground = groundY();
    const palette = currentPalette();
    const ticks = runtime.run?.ticks || 0;
    const motion = runtime.motionReduced ? 0 : ticks;
    pixelRect(0, 0, width, height, palette.sky);

    const gridShift = Math.floor(motion / 7) % 16;
    context.strokeStyle = palette.grid;
    context.lineWidth = 1;
    for (let x = -gridShift; x < width; x += 16) {
      context.beginPath();
      context.moveTo(x + 0.5, 0);
      context.lineTo(x + 0.5, ground);
      context.stroke();
    }
    for (let y = 8; y < ground; y += 16) {
      context.beginPath();
      context.moveTo(0, y + 0.5);
      context.lineTo(width, y + 0.5);
      context.stroke();
    }

    context.save();
    context.globalAlpha = 0.24;
    context.strokeStyle = palette.accent;
    context.lineWidth = 2;
    context.beginPath();
    for (let x = -12; x <= width + 12; x += 8) {
      const y = 34 + Math.round(Math.sin((x + motion / 5) / 19) * 7);
      if (x === -12) context.moveTo(x, y);
      else context.lineTo(x, y);
    }
    context.stroke();
    context.restore();
    const scenery = backdropSceneryLayout(width, ground, motion);
    drawSpiralFlagellates(scenery.bacteria, palette);
    drawHyphae(palette, ground, Math.floor(motion / 10));

    for (let x = -((Math.floor(motion / 5)) % 70); x < width + 70; x += 70) {
      const base = ground - 11;
      pixelRect(x + 8, base - 13, 3, 13, palette.mist);
      pixelRect(x + 2, base - 16, 15, 4, palette.mist);
      pixelRect(x + 5, base - 19, 9, 3, palette.mist);
    }

    pixelRect(0, ground, width, height - ground, palette.ground);
    pixelRect(0, ground, width, 2, '#05070d');
    pixelRect(0, ground + 8, width, height - ground - 8, palette.under);
    for (let x = -((Math.floor(motion / 2)) % 18); x < width; x += 18) {
      pixelRect(x, ground + 5, 10, 2, palette.grid);
      pixelRect(x + 5, ground + 13, 13, 2, palette.sky);
    }

    context.fillStyle = '#fff8e7';
    context.font = '800 6px ui-monospace, monospace';
    context.fillStyle = palette.accent;
    const label = runtime.beaconCueTicks > 0
      ? `BEACON ${runtime.beaconCue}`
      : runtime.run?.boundaryPending
        ? 'BOUNDARY WEAVE'
        : `DEPTH ${runtime.run?.tier || 1}`;
    context.fillText(label, Math.max(6, width - context.measureText(label).width - 6), 9);
    if (runtime.palettePulseTicks > 0) {
      context.globalAlpha = Math.min(0.62, runtime.palettePulseTicks / 60);
      outlineRect(2, 2, width - 4, ground - 4, palette.accent, 2);
      context.globalAlpha = 1;
    }
  }

  function drawGene(entity) {
    const x = Math.round(entity.x);
    const y = Math.round(entity.y);
    const width = Math.round(entity.width);
    const height = Math.round(entity.height);
    const role = Content.roles[entity.roleId] || Content.roles.unassigned;
    const shoulder = 7;
    const blunt = 2;
    let points;
    if (entity.strand > 0) {
      points = [
        [x, y],
        [x + width - shoulder, y],
        [x + width - 1, y + height / 2 - blunt],
        [x + width - 1, y + height / 2 + blunt],
        [x + width - shoulder, y + height],
        [x, y + height],
      ];
    } else {
      points = [
        [x + width, y],
        [x + shoulder, y],
        [x + 1, y + height / 2 - blunt],
        [x + 1, y + height / 2 + blunt],
        [x + shoulder, y + height],
        [x + width, y + height],
      ];
    }
    polygon(points, role.color, '#05070d', 2);
  }

  function drawObstacle(entity) {
    const x = Math.round(entity.x);
    const y = Math.round(entity.y);
    polygon([
      [x, y + entity.height],
      [x + 2, y + 3],
      [x + entity.width * 0.42, y],
      [x + entity.width - 2, y + 2],
      [x + entity.width, y + entity.height],
    ], '#ff9a36', '#05070d', 2);
    for (let stripe = 5; stripe < entity.height - 2; stripe += 7) {
      polygon([
        [x + 3, y + stripe],
        [x + Math.max(6, entity.width - 4), y + stripe - 3],
        [x + Math.max(6, entity.width - 4), y + stripe],
        [x + 3, y + stripe + 3],
      ], '#05070d', null, 0);
    }
    pixelRect(x + Math.floor(entity.width / 2) - 1, y - 5, 3, 5, '#fff8e7');
    outlineRect(x + Math.floor(entity.width / 2) - 1, y - 5, 3, 5, '#05070d');
  }

  function drawPit(entity) {
    const x = Math.round(entity.x);
    const y = Math.round(entity.y);
    const bottom = runtime.viewHeight + 2;
    pixelRect(x - 2, y - 1, entity.width + 4, bottom - y + 1, '#020407');
    polygon([[x - 4, y - 1], [x + 5, y - 1], [x + 1, y + 5]], '#ff9a36', '#05070d', 1.5);
    polygon([
      [x + entity.width - 5, y - 1],
      [x + entity.width + 4, y - 1],
      [x + entity.width - 1, y + 5],
    ], '#ff9a36', '#05070d', 1.5);
    for (let chevron = 7; chevron < entity.width - 7; chevron += 11) {
      polygon([
        [x + chevron - 3, y + 3],
        [x + chevron, y + 7],
        [x + chevron + 3, y + 3],
        [x + chevron + 1, y + 3],
        [x + chevron, y + 5],
        [x + chevron - 1, y + 3],
      ], '#ff9a36', null, 0);
    }
    context.save();
    context.fillStyle = '#fff8e7';
    context.font = '900 5px ui-monospace, monospace';
    if (entity.width >= 30) context.fillText('DNASE', x + 5, y + 15);
    context.strokeStyle = '#37f3ff';
    context.lineWidth = 1.5;
    context.beginPath();
    context.moveTo(x + 5, y + 20);
    context.lineTo(x + entity.width * 0.44, y + 16);
    context.moveTo(x + entity.width * 0.56, y + 20);
    context.lineTo(x + entity.width - 5, y + 16);
    context.stroke();
    context.restore();
  }

  function drawPlatform(entity) {
    const x = Math.round(entity.x);
    const y = Math.round(entity.y);
    pixelRect(x, y, entity.width, entity.height, '#05070d');
    pixelRect(x + 2, y + 2, entity.width - 4, Math.max(2, entity.height - 3), '#d7ff1f');
    pixelRect(x + 4, y - 3, entity.width - 8, 3, '#fff8e7');
    for (let brace = 8; brace < entity.width - 4; brace += 16) {
      polygon([
        [x + brace - 3, y + entity.height],
        [x + brace + 2, y + entity.height],
        [x + brace + 7, groundY()],
        [x + brace + 3, groundY()],
      ], '#7b6dff', '#05070d', 1);
    }
  }

  function drawWarning(entity) {
    const x = Math.round(entity.x);
    const y = Math.round(entity.y);
    const palette = currentPalette();
    if (entity.shape === 'beacon') {
      pixelRect(x + 3, y, 4, entity.height, '#fff8e7');
      polygon([[x - 2, y + 1], [x + 11, y + 1], [x + 8, y + 8], [x, y + 8]], palette.accent, '#05070d', 1.5);
      pixelRect(x + 3, y + 3, 3, 3, '#05070d');
    } else {
      polygon([
        [x, y + entity.height],
        [x + 4, y + 1],
        [x + entity.width - 4, y + 1],
        [x + entity.width, y + entity.height],
      ], '#ff9a36', '#05070d', 1.5);
      pixelRect(x + 4, y + 5, Math.max(3, entity.width - 8), 2, '#05070d');
    }
  }

  function scoutFootPose(player, paceRatio) {
    if (runtime.motionReduced) {
      return {
        phase: 0,
        left: { stride: 0, lift: 0 },
        right: { stride: 0, lift: 0 },
      };
    }
    if (!player.onGround) {
      return {
        phase: -1,
        left: { stride: 1, lift: 2 },
        right: { stride: -1, lift: 2 },
      };
    }
    const cycle = [
      { left: [2, 0], right: [-2, 0] },
      { left: [1, 0], right: [0, 3] },
      { left: [-1, 0], right: [2, 2] },
      { left: [-2, 0], right: [3, 0] },
      { left: [-2, 0], right: [2, 0] },
      { left: [0, 3], right: [1, 0] },
      { left: [2, 2], right: [-1, 0] },
      { left: [3, 0], right: [-2, 0] },
    ];
    const phase = Math.floor((runtime.run?.ticks || 0) * Math.max(1, paceRatio) / 2) % cycle.length;
    const pose = cycle[phase];
    return {
      phase,
      left: { stride: pose.left[0], lift: pose.left[1] },
      right: { stride: pose.right[0], lift: pose.right[1] },
    };
  }

  function drawScout() {
    const player = runtime.player;
    const visualWidth = Math.max(34, Number(Content.geometry.playerVisualWidth) || 34);
    const visualHeight = Math.max(44, Number(Content.geometry.playerVisualHeight) || 44);
    const x = Math.round(player.x - (visualWidth - player.width) / 2);
    const y = Math.round(player.y - (visualHeight - player.height));
    const paceRatio = runtime.currentPacePermille / Math.max(1, Content.constants.basePacePermille || 1000);
    const gait = scoutFootPose(player, paceRatio);
    const completed = runtime.run?.completedArchitectures || 0;

    context.save();
    context.lineJoin = 'round';
    context.lineCap = 'round';

    // A compact upgrade cell remains fixed behind the coat.
    if (completed >= 3) {
      context.beginPath();
      context.roundRect(x + 4, y + 24, 7, 10, 2);
      context.fillStyle = '#d7ff1f';
      context.fill();
      context.strokeStyle = '#05070d';
      context.lineWidth = 1.4;
      context.stroke();
    }

    // Static trouser cuffs. Only the boots below them use gait coordinates.
    context.beginPath();
    context.roundRect(x + 10, y + 33, 6, 8, 2);
    context.roundRect(x + 19, y + 33, 6, 8, 2);
    context.fillStyle = '#151c29';
    context.fill();
    context.strokeStyle = '#05070d';
    context.lineWidth = 1.5;
    context.stroke();

    const drawBoot = (centerX, centerY) => {
      context.beginPath();
      context.ellipse(centerX, centerY, 5, 2.6, 0, 0, Math.PI * 2);
      context.fillStyle = '#10141d';
      context.fill();
      context.strokeStyle = '#05070d';
      context.lineWidth = 1.6;
      context.stroke();
      context.beginPath();
      context.moveTo(centerX + 0.5, centerY - 1);
      context.quadraticCurveTo(centerX + 2.5, centerY - 1.8, centerX + 3.4, centerY - 0.2);
      context.strokeStyle = '#778193';
      context.lineWidth = 1;
      context.stroke();
    };
    drawBoot(x + 12 + gait.left.stride, y + 41 - gait.left.lift);
    drawBoot(x + 22 + gait.right.stride, y + 41 - gait.right.lift);

    // Rounded white coat and black lapels create the reference's compact profile.
    context.beginPath();
    context.moveTo(x + 13, y + 18);
    context.quadraticCurveTo(x + 9, y + 20, x + 9, y + 26);
    context.lineTo(x + 9, y + 35);
    context.quadraticCurveTo(x + 18, y + 39, x + 28, y + 36);
    context.lineTo(x + 27, y + 24);
    context.quadraticCurveTo(x + 26, y + 19, x + 22, y + 18);
    context.closePath();
    context.fillStyle = '#fff8e7';
    context.fill();
    context.strokeStyle = '#05070d';
    context.lineWidth = 2;
    context.stroke();

    context.beginPath();
    context.moveTo(x + 17, y + 19);
    context.lineTo(x + 14, y + 25);
    context.lineTo(x + 18, y + 23);
    context.lineTo(x + 22, y + 26);
    context.lineTo(x + 21, y + 19);
    context.strokeStyle = '#202733';
    context.lineWidth = 1.4;
    context.stroke();

    // Fixed sleeve and black safety glove.
    context.beginPath();
    context.moveTo(x + 12, y + 21);
    context.quadraticCurveTo(x + 7, y + 22, x + 6, y + 29);
    context.lineTo(x + 10, y + 30);
    context.quadraticCurveTo(x + 11, y + 25, x + 15, y + 24);
    context.closePath();
    context.fillStyle = '#fff8e7';
    context.fill();
    context.strokeStyle = '#05070d';
    context.lineWidth = 1.6;
    context.stroke();
    context.beginPath();
    context.ellipse(x + 8, y + 31, 3, 3.2, -0.25, 0, Math.PI * 2);
    context.fillStyle = '#111722';
    context.fill();
    context.strokeStyle = '#05070d';
    context.lineWidth = 1.4;
    context.stroke();

    // Dark belt with three bright, readable sample vials.
    context.beginPath();
    context.roundRect(x + 13, y + 28, 17, 5, 1.5);
    context.fillStyle = '#1a202b';
    context.fill();
    context.strokeStyle = '#05070d';
    context.lineWidth = 1.4;
    context.stroke();
    ['#37f3ff', '#d7ff1f', '#ff9a36'].forEach((color, index) => {
      const vialX = x + 16 + index * 4;
      context.beginPath();
      context.roundRect(vialX, y + 26, 3.5, 7, 1);
      context.fillStyle = '#e9fbff';
      context.fill();
      context.strokeStyle = '#05070d';
      context.lineWidth = 1;
      context.stroke();
      pixelRect(vialX + 1, y + 29, 2, 3, color);
    });

    // Warm side-facing head beneath the oversized orange safety helmet.
    context.beginPath();
    context.ellipse(x + 19, y + 12, 11, 9.5, -0.02, 0, Math.PI * 2);
    context.fillStyle = '#ff9a62';
    context.fill();
    context.strokeStyle = '#05070d';
    context.lineWidth = 2;
    context.stroke();
    context.beginPath();
    context.ellipse(x + 9, y + 13, 3, 3.5, 0, 0, Math.PI * 2);
    context.fillStyle = '#f58248';
    context.fill();
    context.strokeStyle = '#05070d';
    context.lineWidth = 1.4;
    context.stroke();

    context.beginPath();
    context.moveTo(x + 7, y + 9);
    context.bezierCurveTo(x + 8, y + 2, x + 13, y, x + 20, y);
    context.bezierCurveTo(x + 27, y, x + 31, y + 4, x + 31, y + 10);
    context.lineTo(x + 29, y + 11);
    context.lineTo(x + 8, y + 11);
    context.closePath();
    context.fillStyle = '#ff7d35';
    context.fill();
    context.strokeStyle = '#05070d';
    context.lineWidth = 2;
    context.stroke();
    context.beginPath();
    context.ellipse(x + 19, y + 4, 4, 1.8, -0.12, 0, Math.PI * 2);
    context.fillStyle = '#ffd08d';
    context.globalAlpha = 0.72;
    context.fill();
    context.globalAlpha = 1;

    // Black wraparound frame and vivid blue visor define the face at game scale.
    context.beginPath();
    context.moveTo(x + 6, y + 8);
    context.lineTo(x + 29, y + 8);
    context.quadraticCurveTo(x + 33, y + 9, x + 31, y + 12);
    context.lineTo(x + 29, y + 16);
    context.quadraticCurveTo(x + 27, y + 19, x + 23, y + 18);
    context.lineTo(x + 14, y + 15);
    context.lineTo(x + 7, y + 14);
    context.closePath();
    context.fillStyle = '#05070d';
    context.fill();
    context.beginPath();
    context.moveTo(x + 14, y + 9.5);
    context.lineTo(x + 29, y + 9.5);
    context.quadraticCurveTo(x + 31, y + 10, x + 29.5, y + 13);
    context.lineTo(x + 27, y + 16);
    context.quadraticCurveTo(x + 25, y + 17.5, x + 22, y + 16.5);
    context.lineTo(x + 15, y + 14);
    context.closePath();
    context.fillStyle = '#0a9ed6';
    context.fill();
    context.beginPath();
    context.moveTo(x + 17, y + 10.5);
    context.lineTo(x + 27, y + 10.5);
    context.strokeStyle = '#65e8ff';
    context.lineWidth = 1.2;
    context.stroke();
    pixelRect(x + 7, y + 10, 7, 3, '#151c29');

    if (completed >= 5) {
      context.beginPath();
      context.arc(x + 11, y + 24, 2.2, 0, Math.PI * 2);
      context.fillStyle = '#ff63bd';
      context.fill();
      context.strokeStyle = '#05070d';
      context.lineWidth = 1;
      context.stroke();
    }

    context.restore();
  }

  function drawParticles() {
    runtime.particles.forEach((particle) => {
      pixelRect(particle.x, particle.y, particle.life > 12 ? 2 : 1, particle.life > 12 ? 2 : 1, particle.color);
    });
  }

  function renderCanvas() {
    if (!presentation.open || !runtime.run || runtime.failed) return;
    context.save();
    if (runtime.cameraTicks > 0 && !runtime.motionReduced) {
      const shift = runtime.cameraTicks % 2 ? 1 : -1;
      context.translate(shift, runtime.cameraTicks % 3 ? 0 : 1);
    }
    drawBackdrop();
    runtime.entities.forEach((entity) => {
      if (entity.type === 'pit') drawPit(entity);
    });
    runtime.entities.forEach((entity) => {
      if (entity.type === 'platform') drawPlatform(entity);
      else if (entity.type === 'gene') drawGene(entity);
      else if (entity.type === 'obstacle') drawObstacle(entity);
      else if (entity.type === 'warning') drawWarning(entity);
    });
    drawParticles();
    drawScout();
    context.restore();
  }

  function handleRuntimeFailure(error) {
    runtime.failed = true;
    stopFrameLoop();
    dispatchAnimationOwnership();
    global.console?.error?.('Candidate Weave stopped safely:', error);
    if (runtime.run) Core.pauseRun(runtime.run);
    showOverlay(
      'GAME PAUSED SAFELY',
      'The game stopped. The ClusterWeave workflow is unaffected.',
      [
        { label: 'New run', action: () => startNewRun() },
        { label: 'Exit', kind: 'close', action: () => closePresentation({ reason: 'close' }) },
      ],
    );
  }

  function inputOwnedByGame(event) {
    return presentation.open && (dom.shell.contains(event.target) || dom.shell.contains(document.activeElement));
  }

  function interactiveInputTarget(target) {
    return target instanceof Element && !!target.closest('button, a, input, textarea, select, summary, [contenteditable="true"]');
  }

  function typingInputTarget(target) {
    return target instanceof Element && !!target.closest('input, textarea, select, [contenteditable="true"]');
  }

  function handleKeyDown(event) {
    if (!inputOwnedByGame(event)) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopImmediatePropagation();
      closePresentation({ reason: 'close' });
      return;
    }
    if (event.key === 'Tab' && presentation.view === 'fullscreen') {
      trapFullscreenTab(event);
      return;
    }
    if ((event.key === 'p' || event.key === 'P') && !typingInputTarget(event.target)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (runtime.run?.state === 'paused') resumeGame('user');
      else pauseGame('user');
      return;
    }
    const action = KEY_ACTIONS.get(event.key);
    if (!action || interactiveInputTarget(event.target) || runtime.heldActions.has(action)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    runtime.heldActions.add(action);
    requestJump();
  }

  function handleKeyUp(event) {
    const action = KEY_ACTIONS.get(event.key);
    if (!action || !presentation.open) return;
    runtime.heldActions.delete(action);
    releaseJump();
    if (inputOwnedByGame(event)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }

  function focusableGameElements() {
    return Array.from(dom.shell.querySelectorAll('button:not([disabled]):not([hidden]), a[href], canvas[tabindex], summary'))
      .filter((element) => !element.inert && !element.closest('[hidden], [inert]') && element.getClientRects().length > 0);
  }

  function trapFullscreenTab(event) {
    const focusable = focusableGameElements();
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function handleVisibilityChange() {
    if (!presentation.open || !runtime.run || runtime.failed) return;
    if (document.hidden) pauseGame('visibility', { overlay: false });
    else if (runtime.pauseReasons.has('visibility')) {
      showPauseOverlay('Run paused', 'The tab was hidden. Resume into a clear runway.');
    }
  }

  function handleViewportChange() {
    if (!presentation.open || !runtime.run) {
      dispatchAnimationOwnership();
      return;
    }
    const paused = pauseGame('viewport', { overlay: false });
    applyPresentation();
    if (paused) showPauseOverlay('View changed', 'Your run was preserved and the track has a clear runway.');
    else if (runtime.run.state === 'game_over') showGameOver();
  }

  function handleOrientationChange() {
    const nextOrientation = global.innerWidth >= global.innerHeight ? 'landscape' : 'portrait';
    if (nextOrientation === runtime.orientation) return;
    runtime.orientation = nextOrientation;
    if (!presentation.open || !runtime.run) return;
    const paused = pauseGame('viewport', { overlay: false });
    scheduleResizePause();
    if (paused) showPauseOverlay('View rotated', 'Your run was preserved. Resume when ready.');
    else if (runtime.run.state === 'game_over') showGameOver();
  }

  function handleMotionPreferenceChange() {
    runtime.motionReduced = REDUCED_MOTION_QUERY.matches || FORCED_COLORS_QUERY.matches;
    dom.shell.dataset.motion = runtime.motionReduced ? 'reduced' : 'full';
    renderCanvas();
  }

  function bindEvents() {
    dom.start?.addEventListener('click', (event) => openGame({ returnFocus: event.currentTarget }));
    dom.bootstrapOpen?.addEventListener('click', (event) => openGame({
      returnFocus: event.currentTarget,
      fromBootstrap: true,
    }));
    dom.close?.addEventListener('click', () => closePresentation({ reason: 'close' }));
    dom.jump?.addEventListener('click', (event) => {
      event.preventDefault();
      requestJump();
    });
    dom.pause?.addEventListener('click', () => {
      if (runtime.run?.state === 'paused') resumeGame('user');
      else pauseGame('user');
    });
    dom.end?.addEventListener('click', endRun);
    dom.canvas.addEventListener('pointerdown', (event) => {
      event.preventDefault();
      dom.canvas.focus({ preventScroll: true });
      requestJump();
    });
    document.addEventListener('keydown', handleKeyDown, true);
    document.addEventListener('keyup', handleKeyUp, true);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    global.addEventListener('pagehide', () => pauseGame('visibility', { overlay: false }));
    global.addEventListener('pageshow', () => {
      if (presentation.open && !runtime.failed && runtime.pauseReasons.has('visibility')) {
        showPauseOverlay('Run paused', 'Resume after returning to the page.');
      }
    });
    global.addEventListener('blur', () => {
      if (presentation.open) pauseGame('visibility', { overlay: false });
    });
    global.addEventListener('resize', handleOrientationChange);
    global.addEventListener('orientationchange', handleOrientationChange);
    global.addEventListener('offline', () => setConnectionState('browser-offline'));
    global.addEventListener('online', () => setConnectionState('reconnecting'));
    COMPACT_QUERY.addEventListener?.('change', handleViewportChange);
    REDUCED_MOTION_QUERY.addEventListener?.('change', handleMotionPreferenceChange);
    FORCED_COLORS_QUERY.addEventListener?.('change', handleMotionPreferenceChange);
    dom.canvas.addEventListener('contextlost', (event) => {
      event.preventDefault();
      handleRuntimeFailure(new Error('Canvas context lost'));
    });
    dom.shell.addEventListener('focusout', () => {
      global.setTimeout(() => {
        if (presentation.open && presentation.view === 'wide' && !dom.shell.contains(document.activeElement)) {
          pauseGame('focus', { overlay: false });
        }
      }, 0);
    });
    if ('ResizeObserver' in global) {
      runtime.resizeObserver = new ResizeObserver(scheduleResizePause);
      runtime.resizeObserver.observe(dom.viewport);
    } else global.addEventListener('resize', scheduleResizePause);
  }

  function watchBootstrapFallback() {
    const splash = byId('bootstrap-splash');
    if (!splash || !dom.bootstrap) return;
    const synchronize = () => {
      if (splash.classList.contains('hidden')) {
        runtime.bootstrapReady = false;
        setElementVisible(dom.bootstrap, false);
        updateLauncher();
      }
    };
    new MutationObserver(synchronize).observe(splash, { attributes: true, attributeFilter: ['class'] });
    global.setTimeout(() => {
      if (!splash.classList.contains('hidden') && document.body.dataset.clusterweaveGameBootstrapEligible !== 'false') {
        runtime.bootstrapReady = true;
        setElementVisible(dom.bootstrap, true);
        updateLauncher();
      }
    }, 5000);
  }

  function debugSnapshot() {
    return Object.freeze({
      host: { ...host },
      presentation: {
        open: presentation.open,
        view: presentation.view,
        fromBootstrap: presentation.fromBootstrap,
        mobileAnimationOwned: runtime.animationOwned,
      },
      run: runtime.run ? Core.snapshot(runtime.run) : null,
      runtime: {
        entityCount: runtime.entities.length,
        entityTypes: runtime.entities.map((entity) => entity.type),
        player: {
          x: runtime.player.x,
          y: runtime.player.y,
          onGround: runtime.player.onGround,
          velocityY: runtime.player.velocityY,
        },
        animationRunning: !!runtime.frame,
        pauseReasons: Array.from(runtime.pauseReasons),
        safeRunwayTicks: runtime.run?.safeRunwayTicks || 0,
        motion: runtime.motionReduced ? 'reduced' : 'full',
        manualClock: runtime.qaManualClock,
        imageSmoothingEnabled: context.imageSmoothingEnabled,
        paletteId: runtime.run ? Core.paletteForTier(runtime.run.tier).id : Content.palettes[0].id,
      },
      content: Core.validationReport,
    });
  }

  function qaScene() {
    const visualWidth = Math.max(34, Number(Content.geometry.playerVisualWidth) || 34);
    const visualHeight = Math.max(44, Number(Content.geometry.playerVisualHeight) || 44);
    const visual = {
      x: runtime.player.x - (visualWidth - runtime.player.width) / 2,
      y: runtime.player.y - (visualHeight - runtime.player.height),
      width: visualWidth,
      height: visualHeight,
    };
    const motion = activeMotionPhysics();
    const difficulty = Core.difficultyForTier(runtime.run?.tier || 1);
    const paceRatio = runtime.currentPacePermille / Math.max(1, Content.constants.basePacePermille || 1000);
    const gait = scoutFootPose(runtime.player, paceRatio);
    const backdropMotion = runtime.motionReduced ? 0 : (runtime.run?.ticks || 0);
    const backdropScenery = backdropSceneryLayout(runtime.viewWidth, groundY(), backdropMotion);
    const avatar = {
      profile: 'sideways',
      silhouette: 'rounded',
      labCoat: true,
      facing: 'right',
      motion: 'feet-only',
      gait: 'alternating-lift-forward',
      paceSynchronizedGait: true,
      animatedParts: ['leftFoot', 'rightFoot'],
      staticParts: ['head', 'torso', 'arms', 'labCoat', 'helmet', 'visor', 'glove', 'glassware', 'vialBelt'],
      design: {
        helmet: 'orange',
        visor: 'blue-wraparound',
        coat: 'white',
        glove: 'black',
        boots: 'black',
        vialBelt: true,
      },
      pose: {
        phase: gait.phase,
        cycleLength: 8,
        parts: {
          head: { x: visual.x + 6, y: visual.y, width: 27, height: 21 },
          torso: { x: visual.x + 6, y: visual.y + 18, width: 24, height: 21 },
          leftFoot: {
            x: visual.x + 7 + gait.left.stride,
            y: visual.y + 38.4 - gait.left.lift,
            width: 10,
            height: 5.2,
            stride: gait.left.stride,
            lift: gait.left.lift,
            planted: gait.left.lift === 0,
          },
          rightFoot: {
            x: visual.x + 17 + gait.right.stride,
            y: visual.y + 38.4 - gait.right.lift,
            width: 10,
            height: 5.2,
            stride: gait.right.stride,
            lift: gait.right.lift,
            planted: gait.right.lift === 0,
          },
        },
      },
    };
    return {
      groundY: groundY(),
      canvas: {
        cssWidth: runtime.cssWidth,
        cssHeight: runtime.cssHeight,
        backingWidth: dom.canvas.width,
        backingHeight: dom.canvas.height,
        dpr: runtime.canvasDpr,
        worldScale: WORLD_TO_CSS,
      },
      world: {
        width: runtime.viewWidth,
        height: runtime.viewHeight,
        groundY: groundY(),
      },
      health: {
        current: runtime.run?.health ?? 0,
        max: Content.constants.maxHealth,
        hearts: Array.from({ length: Content.constants.maxHealth }, (_, index) => index < (runtime.run?.health ?? 0)),
      },
      backdrop: {
        layer: 'behind-terrain',
        decorativeOnly: true,
        collisionEnabled: false,
        forms: [
          'mushroom',
          'filamentous-fungus',
          'block-spores',
          'spiral-flagellated-bacterium',
        ],
        bacteria: {
          silhouette: 'angular-spiral',
          flagella: 'polar',
          colorRole: 'biology',
          period: backdropScenery.period,
          visibleCount: backdropScenery.bacteria.length,
          instances: backdropScenery.bacteria.map((instance) => ({ ...instance })),
        },
        motion: {
          mode: runtime.motionReduced ? 'static' : 'slow-parallax',
          driftDivisor: 14,
          drift: backdropScenery.drift,
        },
      },
      physics: {
        baseSpeed: PHYSICS.baseSpeed,
        speed: runtime.currentSpeed,
        currentSpeed: runtime.currentSpeed,
        pacePermille: runtime.currentPacePermille,
        targetPacePermille: difficulty.pacePermille,
        paceRampTicks: Math.max(1, Number(Content.constants.paceRampTicks) || 90),
        isFinalStage: difficulty.isFinalStage === true,
        motionScale: motion.motionScale,
        jumpVelocity: motion.jumpVelocity,
        gravity: motion.gravity,
        terminalVelocity: motion.terminalVelocity,
        coyoteTicks: PHYSICS.coyoteTicks,
        jumpBufferTicks: PHYSICS.jumpBufferTicks,
        jumpRise: motion.jumpRise,
        airtimeSeconds: motion.airtimeSeconds,
        jumpDistance: motion.jumpDistance,
        maxJumpDistance: Number(Content.constants.maxJumpDistance) || 112,
        minimumLandingRun: Number(Content.constants.minimumLandingRun) || 18,
      },
      player: {
        x: runtime.player.x,
        y: runtime.player.y,
        width: runtime.player.width,
        height: runtime.player.height,
        onGround: runtime.player.onGround,
        supportId: runtime.player.supportId,
        velocityY: runtime.player.velocityY,
        coyoteTicks: runtime.player.coyoteTicks,
        jumpBufferTicks: runtime.player.jumpBufferTicks,
        visual,
        avatar,
        hit: playerBox(),
      },
      collectibles: {
        gene: {
          silhouette: 'blocky-blunted-arrow',
          labels: false,
        },
      },
      entities: runtime.entities.map((entity) => ({ ...entity })),
      events: runtime.eventLog.map((event) => ({ ...event })),
    };
  }

  function qaStart(options = {}) {
    const normalized = typeof options === 'object' ? options : { seed: options };
    runtime.qaManualClock = normalized.manual === true;
    setHostState({ epoch: host.epoch + 1, lifecycle: 'running', phase: host.phase });
    openGame({ returnFocus: dom.start, forceNew: true, seed: normalized.seed });
    return debugSnapshot();
  }

  function qaSpawnGene(roleId = 'core', strand = 1, options = {}) {
    if (!runtime.run) return null;
    const settings = options && typeof options === 'object' ? options : { lane: options };
    const offset = Math.max(8, Number(settings.offset) || 24);
    const entity = spawnPlacement({
      kind: 'gene',
      id: entityId('qa-gene'),
      roleId: Content.roles[roleId] ? roleId : 'unassigned',
      strand: strand === -1 || strand === 'left' ? -1 : 1,
      lane: Content.geometry.laneOffsets[settings.lane] != null ? settings.lane : 'low',
      at: 0,
    }, runtime.player.x + offset);
    renderCanvas();
    return entity.id;
  }

  function qaCollectNearest() {
    const entity = runtime.entities.find((item) => item.type === 'gene' && !item.removed);
    if (!entity) return debugSnapshot();
    entity.x = runtime.player.x + 3;
    entity.y = runtime.player.y + 5;
    collectEntities();
    renderCanvas();
    return debugSnapshot();
  }

  function qaCompleteArchitecture() {
    if (!runtime.run) return debugSnapshot();
    const architectureId = runtime.run.architecture.id;
    const remaining = Content.constants.genesPerArchitecture - runtime.run.architecture.genes.length;
    let ordinal = 0;
    while (ordinal < remaining && runtime.run.architecture.id === architectureId) {
      const roleId = Content.roleOrder[ordinal % Content.roleOrder.length];
      const result = Core.collectGene(runtime.run, {
        id: `${runtime.run.seed}:qa-complete:${architectureId}:${ordinal}`,
        roleId,
        strand: ordinal % 2 ? -1 : 1,
      });
      handleCollectionResult(result);
      ordinal += 1;
    }
    renderCanvas();
    return debugSnapshot();
  }

  function qaReachTier(tier) {
    const numericTier = Number(tier);
    const target = Number.isFinite(numericTier)
      ? Math.min(64, Math.max(1, Math.floor(numericTier)))
      : 1;
    let attempts = 0;
    while (runtime.run?.state === 'playing' && runtime.run.tier < target && attempts < target + 2) {
      const before = runtime.run.tier;
      qaCompleteArchitecture();
      attempts += 1;
      if (runtime.run.tier <= before) break;
    }
    return debugSnapshot();
  }

  function qaSpawnPhrase(templateId, options = {}) {
    if (!runtime.run) return null;
    const settings = templateId && typeof templateId === 'object'
      ? templateId
      : { ...(options || {}), templateId };
    if (settings.forceHazards !== false) {
      runtime.safeVisualTicks = 0;
      runtime.run.safeRunwayTicks = 0;
    }
    const phrase = spawnPhrase({ ...settings, forceHazards: settings.forceHazards !== false });
    renderCanvas();
    return phrase;
  }

  function qaSpawnPit(options = {}) {
    if (!runtime.run) return null;
    const settings = options && typeof options === 'object' ? options : { offset: options };
    const offset = Math.max(8, Number(settings.offset) || 80);
    if (settings.forceHazards !== false) {
      runtime.safeVisualTicks = 0;
      runtime.run.safeRunwayTicks = 0;
    }
    const entity = spawnPlacement({
      kind: 'pit',
      at: 0,
      shape: settings.shape || 'hop',
      width: Number(settings.width) || undefined,
    }, runtime.player.x + offset, { templateId: 'qa-pit' });
    recordEvent('qa-pit-spawned', { entityId: entity.id, width: entity.width });
    renderCanvas();
    return entity.id;
  }

  function qaSetTier(tier, options = {}) {
    if (!runtime.run) return debugSnapshot();
    const numeric = Number(tier);
    const target = Number.isFinite(numeric) ? Math.min(64, Math.max(1, Math.floor(numeric))) : 1;
    runtime.run.tier = target;
    runtime.run.completedArchitectures = target - 1;
    if ('boundary' in options) runtime.run.boundaryPending = options.boundary === true;
    if (options.boundary === false) runtime.run.respitePhrasesRemaining = 0;
    const difficulty = Core.difficultyForTier(target);
    const instant = options.instant !== false;
    if (instant) setRuntimePace(difficulty.pacePermille);
    runtime.player.motionScale = motionScaleForPace(runtime.currentPacePermille);
    recordEvent('qa-tier-set', {
      tier: target,
      targetPacePermille: difficulty.pacePermille,
      instant,
      boundaryPending: !!runtime.run.boundaryPending,
    });
    updateHud();
    renderCanvas();
    return debugSnapshot();
  }

  function qaEvents(options = {}) {
    const since = Math.max(0, Number(options?.since) || 0);
    return runtime.eventLog.filter((event) => event.id > since).map((event) => ({ ...event }));
  }

  const publicApi = {
    setHostState,
    setConnectionState,
    open: openGame,
    close: closePresentation,
    pause: pauseGame,
    resume: resumeGame,
    snapshot: debugSnapshot,
    validationReport: Core.validationReport,
  };

  if (new URLSearchParams(global.location.search).has('gameQa')) {
    publicApi.qa = Object.freeze({
      start: qaStart,
      scene: qaScene,
      events: qaEvents,
      spawnPhrase: qaSpawnPhrase,
      spawnPit: qaSpawnPit,
      setTier: qaSetTier,
      action(action) {
        if (action === 'jump' || action === 'jump-down') requestJump();
        if (action === 'jump-up') releaseJump();
        return debugSnapshot();
      },
      tick(count = 1) {
        const numericCount = Number(count);
        const ticks = Number.isFinite(numericCount)
          ? Math.min(10000, Math.max(0, Math.floor(numericCount)))
          : 0;
        for (let index = 0; index < ticks; index += 1) updateSimulation();
        renderCanvas();
        return debugSnapshot();
      },
      spawnGene: qaSpawnGene,
      collectNearest: qaCollectNearest,
      completeArchitecture: qaCompleteArchitecture,
      reachTier: qaReachTier,
      setProgress(completedArchitectures = 0) {
        return qaReachTier(Math.max(0, Math.floor(Number(completedArchitectures) || 0)) + 1);
      },
      collide() {
        triggerObstacleDamage(null, 'qa-orange-obstacle');
        renderCanvas();
        return debugSnapshot();
      },
      restart() {
        startNewRun();
        return debugSnapshot();
      },
      clearRunway() {
        runtime.entities = [];
        runtime.safeVisualTicks = 0;
        runtime.spawnTicks = Content.constants.safeRunwayTicks * 2;
        if (runtime.run) runtime.run.safeRunwayTicks = 0;
        runtime.player.y = groundY() - runtime.player.height;
        runtime.player.velocityY = 0;
        runtime.player.onGround = true;
        runtime.player.supportId = 'ground';
        recordEvent('qa-runway-cleared');
        renderCanvas();
        return debugSnapshot();
      },
      spawn(type, options = {}) {
        if (type === 'gene') return qaSpawnGene(options.roleId, options.strand, options);
        if (type === 'pit') return qaSpawnPit(options);
        const kind = type === 'warning' || type === 'platform' ? type : 'obstacle';
        const offset = Math.max(8, Number(options.offset) || 22);
        const entity = spawnPlacement({
          kind,
          at: 0,
          shape: options.shape || (kind === 'platform' ? 'step' : kind === 'warning' ? 'chevron' : 'pylon'),
          width: options.width,
          height: options.height,
          elevation: options.elevation,
        }, runtime.player.x + offset, { templateId: 'qa-spawn' });
        renderCanvas();
        return entity.id;
      },
    });
  }

  global.ClusterWeaveGame = Object.freeze(publicApi);
  bindEvents();
  watchBootstrapFallback();
  handleMotionPreferenceChange();
  renderHostState();
  updateLauncher();
})(window);
