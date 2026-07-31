export function createMotionBoundary({
  document,
  window,
  state,
  gsapMotion,
  retiredMotionStorageKeys: RETIRED_MOTION_STORAGE_KEYS,
  gsapBrowserPath: GSAP_BROWSER_PATH,
  renderWeaveHelix,
}) {
  let motionLifecycleWired = false;

function reducedMotionPreferred() {
  return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

function clearRetiredMotionSettings() {
  try {
    RETIRED_MOTION_STORAGE_KEYS.forEach(key => window.localStorage?.removeItem(key));
  } catch (error) {}
}

function richMotionDisabled() {
  return false;
}

function initializeRetiredMotionControls() {
  clearRetiredMotionSettings();
  document.body.dataset.richMotion = 'enabled';
  document.body.dataset.threeWeavemap = 'disabled';
  document.body.dataset.threeWeavemapOptIn = 'disabled';
}

function wireMotionLifecycleGuards() {
  if (motionLifecycleWired) return;
  motionLifecycleWired = true;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      teardownGsapMotion('page-hidden');
      return;
    }
    const helix = document.getElementById('weavemap-helix');
    if (helix) delete helix.dataset.rendered;
    if (richDomMotionEnabled()) warmGsapMotion();
    renderWeaveHelix(state.activeJobMeta);
  });
  window.addEventListener('pagehide', () => {
    teardownGsapMotion('pagehide');
  });
}

function richDomMotionEnabled() {
  return !reducedMotionPreferred() && !richMotionDisabled();
}

function markGsapMotionFallback(reason) {
  gsapMotion.fallbackReason = reason || 'unavailable';
  document.body.dataset.gsapMotion = 'fallback';
}

function gsapMotionReady() {
  if (!richDomMotionEnabled()) return null;
  if (gsapMotion.gsap) return gsapMotion.gsap;
  if (window.gsap) {
    gsapMotion.gsap = window.gsap;
    gsapMotion.fallbackReason = '';
    document.body.dataset.gsapMotion = 'ready';
    return gsapMotion.gsap;
  }
  return null;
}

function loadGsapMotion() {
  if (!richDomMotionEnabled()) {
    document.body.dataset.gsapMotion = 'disabled';
    return Promise.resolve(null);
  }
  const ready = gsapMotionReady();
  if (ready) return Promise.resolve(ready);
  if (gsapMotion.promise) return gsapMotion.promise;
  document.body.dataset.gsapMotion = 'loading';
  gsapMotion.promise = new Promise(resolve => {
    const finish = () => {
      const lib = window.gsap || null;
      if (!lib) {
        markGsapMotionFallback('vendor-load-failed');
        resolve(null);
        return;
      }
      gsapMotion.gsap = lib;
      gsapMotion.fallbackReason = '';
      document.body.dataset.gsapMotion = richDomMotionEnabled() ? 'ready' : 'disabled';
      resolve(lib);
    };
    const fail = () => {
      markGsapMotionFallback('vendor-load-failed');
      resolve(null);
    };
    const existing = document.querySelector(`script[src="${GSAP_BROWSER_PATH}"]`);
    if (existing) {
      existing.addEventListener('load', finish, { once: true });
      existing.addEventListener('error', fail, { once: true });
      window.setTimeout(() => { if (window.gsap) finish(); }, 0);
      return;
    }
    const script = document.createElement('script');
    script.src = GSAP_BROWSER_PATH;
    script.async = true;
    script.onload = finish;
    script.onerror = fail;
    document.head.appendChild(script);
  });
  return gsapMotion.promise;
}

function warmGsapMotion() {
  if (!richDomMotionEnabled()) {
    document.body.dataset.gsapMotion = 'disabled';
    return;
  }
  loadGsapMotion().catch(() => markGsapMotionFallback('vendor-load-failed'));
}

function killGsapTimeline(key) {
  const timeline = gsapMotion.timelines.get(key);
  if (timeline && typeof timeline.kill === 'function') timeline.kill();
  gsapMotion.timelines.delete(key);
}

function clearDocsMotionVars(docs = document.getElementById('docs')) {
  if (!docs) return;
  [
    '--docs-motion-overlay-opacity',
    '--docs-motion-panel-opacity',
    '--docs-motion-panel-y',
    '--docs-motion-panel-scale',
  ].forEach(name => docs.style.removeProperty(name));
  document.body?.style?.removeProperty('--docs-motion-overlay-opacity');
}

function teardownGsapMotion(reason = '') {
  gsapMotion.timelines.forEach(timeline => {
    if (timeline && typeof timeline.kill === 'function') timeline.kill();
  });
  gsapMotion.timelines.clear();
  clearDocsMotionVars();
  document.body.dataset.gsapMotion = richDomMotionEnabled() ? (gsapMotion.gsap ? 'ready' : 'idle') : 'disabled';
  if (reason) gsapMotion.fallbackReason = reason;
}

function motionTargets(targets, root = document) {
  const input = Array.isArray(targets) ? targets : [targets];
  const nodes = [];
  input.forEach(target => {
    if (!target) return;
    if (typeof target === 'string') nodes.push(...Array.from(root.querySelectorAll(target)));
    else nodes.push(target);
  });
  return Array.from(new Set(nodes)).filter(el => {
    if (!el || !el.isConnected || el.hidden || el.classList?.contains('hidden')) return false;
    return !!(el.getClientRects && el.getClientRects().length);
  });
}

function runGsapMotion(key, build) {
  const gsap = gsapMotionReady();
  if (!gsap) {
    warmGsapMotion();
    return false;
  }
  killGsapTimeline(key);
  try {
    const timeline = gsap.timeline({
      defaults: { overwrite: 'auto' },
      onComplete: () => {
        if (gsapMotion.timelines.get(key) === timeline) gsapMotion.timelines.delete(key);
      },
      onInterrupt: () => {
        if (gsapMotion.timelines.get(key) === timeline) gsapMotion.timelines.delete(key);
      },
    });
    gsapMotion.timelines.set(key, timeline);
    build(timeline, gsap);
    return true;
  } catch (error) {
    killGsapTimeline(key);
    markGsapMotionFallback('animation-error');
    return false;
  }
}

function animateEntryTabTransition(selectedName) {
  const panel = document.getElementById(`entry-panel-${selectedName}`);
  if (!panel) return;
  const selectors = selectedName === 'existing'
    ? ['.access-copy', '.reviewer-access > summary']
    : ['.input-node-head', '.intake-grid', '.settings-section', '.workflow-controls', '.data-use-ack', '.run-row'];
  const targets = motionTargets(selectors, panel);
  const activeTab = document.querySelector('.entry-tab.active');
  runGsapMotion(`entry-${selectedName}`, timeline => {
    if (targets.length) {
      timeline.fromTo(targets,
        { opacity: 0.72, y: 8 },
        { opacity: 1, y: 0, duration: 0.18, ease: 'power2.out', stagger: 0.022, clearProps: 'opacity,transform' },
        0);
    }
    if (activeTab) {
      timeline.fromTo(activeTab,
        { scale: 0.985 },
        { scale: 1, duration: 0.16, ease: 'power2.out', clearProps: 'transform' },
        0);
    }
  });
}

function animateLaunchTransition() {
  const targets = motionTargets(['#workflow-progress-panel', '#weavemap .weavemap-stage-wrap', '#results-card .card-header']);
  const uploadCard = document.getElementById('upload-card');
  runGsapMotion('launch-transition', timeline => {
    if (uploadCard) {
      timeline.fromTo(uploadCard,
        { filter: 'brightness(1.08)' },
        { filter: 'brightness(1)', duration: 0.2, ease: 'power2.out', clearProps: 'filter' },
        0);
    }
    if (targets.length) {
      timeline.fromTo(targets,
        { opacity: 0.74, y: 12 },
        { opacity: 1, y: 0, duration: 0.24, ease: 'power2.out', stagger: 0.035, clearProps: 'opacity,transform' },
        0.02);
    }
  });
}

function animateExistingResultUnlock() {
  const targets = motionTargets([document.getElementById('result-link-status') || document.getElementById('existing-run-status'), document.getElementById('entry-tab-existing')]);
  if (!targets.length) return;
  runGsapMotion('existing-unlock', timeline => {
    timeline.fromTo(targets,
      { opacity: 0.7, y: 5 },
      { opacity: 1, y: 0, duration: 0.16, ease: 'power2.out', stagger: 0.025, clearProps: 'opacity,transform' });
  });
}

function animateResultDashboardOpen(source = '') {
  const targets = motionTargets([
    '#result-dashboard-section .result-dashboard-head',
    '#result-bubble-panel',
    '#weavemap .weavemap-stage-wrap',
  ]);
  if (!targets.length) return;
  runGsapMotion(`result-dashboard-${source || 'open'}`, timeline => {
    timeline.fromTo(targets,
      { opacity: 0.76, y: 14 },
      { opacity: 1, y: 0, duration: 0.22, ease: 'power2.out', stagger: 0.028, clearProps: 'opacity,transform' });
  });
}

function animateResultFocusChange(category = '') {
  const selected = document.querySelector('.dna-result-output.is-selected .dna-result-output-trigger');
  const targets = motionTargets([
    selected,
    '#result-reader-surface',
  ]);
  if (!targets.length) return;
  runGsapMotion(`result-focus-${category || state.resultFocusMode}`, timeline => {
    timeline.fromTo(targets,
      { opacity: 0.78, y: 7, scale: 0.992 },
      { opacity: 1, y: 0, scale: 1, duration: 0.18, ease: 'power2.out', stagger: 0.022, clearProps: 'opacity,transform' });
  });
}

function animateResultReaderOpen() {
  const container = document.getElementById('files-container');
  if (!container) return;
  const targets = motionTargets(['.artifact-reader-head', '.summary-condensed-head', '.summary-markdown-body'], container);
  if (!targets.length) return;
  runGsapMotion('result-reader-open', timeline => {
    timeline.fromTo(targets,
      { opacity: 0.72, y: 8 },
      { opacity: 1, y: 0, duration: 0.18, ease: 'power2.out', stagger: 0.02, clearProps: 'opacity,transform' });
  });
}

function animateSummaryReaderDocument() {
  const targets = motionTargets('#summary-reader-doc > *');
  if (!targets.length) return;
  runGsapMotion('summary-reader-doc', timeline => {
    timeline.fromTo(targets,
      { opacity: 0.72, y: 6 },
      { opacity: 1, y: 0, duration: 0.16, ease: 'power2.out', clearProps: 'opacity,transform' });
  });
}

function animateRerunPanelReady() {
  const targets = motionTargets('#rerun-panel .rerun-summary > .summary-head');
  if (!targets.length) return;
  runGsapMotion('rerun-panel-ready', timeline => {
    timeline.fromTo(targets,
      { opacity: 0.72, y: 7 },
      { opacity: 1, y: 0, duration: 0.16, ease: 'power2.out', clearProps: 'opacity,transform' });
  });
}

function animateRerunPanelOpen(details) {
  const targets = motionTargets('.rerun-panel-body', details || document);
  if (!targets.length) return;
  runGsapMotion('rerun-panel-open', timeline => {
    timeline.fromTo(targets,
      { opacity: 0.72, y: -6 },
      { opacity: 1, y: 0, duration: 0.18, ease: 'power2.out', clearProps: 'opacity,transform' });
  });
}

function wireRerunPanelMotion(details) {
  if (!details || details.dataset.motionWired === '1') return;
  details.dataset.motionWired = '1';
  details.addEventListener('toggle', () => {
    if (details.open) animateRerunPanelOpen(details);
  });
}

function animateRerunQueued() {
  const status = document.getElementById('rerun-status');
  if (!status) return;
  runGsapMotion('rerun-queued', timeline => {
    timeline.fromTo(status,
      { opacity: 0.68, y: 4 },
      { opacity: 1, y: 0, duration: 0.16, ease: 'power2.out', clearProps: 'opacity,transform' });
  });
}

function animateOpsPanelToggle(expanded) {
  const panel = document.getElementById('ops-side-panel');
  const toggle = document.getElementById('ops-panel-toggle');
  runGsapMotion(`ops-panel-${expanded ? 'open' : 'closed'}`, timeline => {
    if (expanded && panel && motionTargets(panel).length) {
      timeline.fromTo(panel,
        { opacity: 0.78, x: -18 },
        { opacity: 1, x: 0, duration: 0.2, ease: 'power2.out', clearProps: 'opacity,transform' },
        0);
    }
    if (toggle && motionTargets(toggle).length) {
      timeline.fromTo(toggle,
        { scale: 0.96 },
        { scale: 1, duration: 0.16, ease: 'power2.out', clearProps: 'transform' },
        0);
    }
  });
}

function animateDiagnosticsReveal() {
  const targets = motionTargets(['#ops-side-panel', '#ops-panel-toggle', '.runtime-diagnostics-only']);
  if (!targets.length) return;
  runGsapMotion('diagnostics-reveal', timeline => {
    timeline.fromTo(targets,
      { opacity: 0.72, y: 8 },
      { opacity: 1, y: 0, duration: 0.2, ease: 'power2.out', stagger: 0.025, clearProps: 'opacity,transform' });
  });
}

function setDocsMotionVars(docs, values) {
  if (!docs) return;
  Object.entries(values).forEach(([name, value]) => {
    docs.style.setProperty(name, String(value));
    if (name === '--docs-motion-overlay-opacity') document.body?.style?.setProperty(name, String(value));
  });
}

function animateDocsDisclosureOpen() {
  const docs = document.getElementById('docs');
  killGsapTimeline('docs-disclosure-open');
  killGsapTimeline('docs-disclosure-close');
  clearDocsMotionVars(docs);
}

function animateDocsDisclosureClose(docs, done) {
  killGsapTimeline('docs-disclosure-open');
  killGsapTimeline('docs-disclosure-close');
  clearDocsMotionVars(docs);
  return false;
}

function animateDnaOverlayPolish(stageWrap, renderKey) {
  if (!stageWrap || gsapMotion.lastWeaveMotionKey === renderKey) return;
  gsapMotion.lastWeaveMotionKey = renderKey;
  const targets = motionTargets([
    '.dna-base-popover.active .dna-popover-panel',
    '.dna-base-popover.failed .dna-popover-panel',
    '.dna-result-output:not(.is-dimmed) .dna-result-output-trigger',
  ], stageWrap);
  if (!targets.length) return;
  runGsapMotion('dna-overlay-polish', timeline => {
    timeline.fromTo(targets,
      { opacity: 0.76, x: 8 },
      { opacity: 1, x: 0, duration: 0.18, ease: 'power2.out', stagger: 0.018, clearProps: 'opacity,transform' });
  });
}

  return {
    reducedMotionPreferred,
    clearRetiredMotionSettings,
    richMotionDisabled,
    initializeRetiredMotionControls,
    wireMotionLifecycleGuards,
    richDomMotionEnabled,
    markGsapMotionFallback,
    gsapMotionReady,
    loadGsapMotion,
    warmGsapMotion,
    killGsapTimeline,
    clearDocsMotionVars,
    teardownGsapMotion,
    motionTargets,
    runGsapMotion,
    animateEntryTabTransition,
    animateLaunchTransition,
    animateExistingResultUnlock,
    animateResultDashboardOpen,
    animateResultFocusChange,
    animateResultReaderOpen,
    animateSummaryReaderDocument,
    animateRerunPanelReady,
    animateRerunPanelOpen,
    wireRerunPanelMotion,
    animateRerunQueued,
    animateOpsPanelToggle,
    animateDiagnosticsReveal,
    setDocsMotionVars,
    animateDocsDisclosureOpen,
    animateDocsDisclosureClose,
    animateDnaOverlayPolish,
  };
}

globalThis.__clusterweaveInstallMotionBoundary?.(createMotionBoundary);
