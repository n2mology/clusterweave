// ── State ──────────────────────────────────────────────────────────────────
let selectedFiles = [];
let acceptedManualAccessions = [];
let accessionFileSources = [];
let accessionFileSourceSerial = 0;
let genomeCheckCache = new Map();
let activeJobId   = null;
let pendingReadTokens = new Map();
let jobLoadSeq = 0;
let pollTimerId = null;
let logCursor     = 0;
let systemLogCursor = 0;
let workerStatus = 'unknown'; // unknown, starting, ready, processing
let systemPollTimer = null;
let runtimeCapabilities = null;
let runtimeStatusSnapshot = {
  server: 'Checking',
  submissions: 'Checking',
  runningJobs: null,
  queuedJobs: null,
  jobsProcessed: 'Not available',
  scope: 'public',
};
let activeJobMeta = null;
let activeStageState = null;
let weaveActivity = { jobId: null, lastLogCount: null, lastStatus: null, events: [] };
let dnaPopoverDragOffsets = new Map();
let dnaPopoverDragTargets = new Map();
let activeFileTree = null;
let activeFileTreeIndex = new Map();
let activeFileTreeJobId = null;
let figureZoomState = new Map();
let activeFigurePan = null;
let jobHistoryInFlight = false;
let lastJobHistoryRenderKey = '';
let jobHistoryById = new Map();
let currentUIMode = 'guided';
let accessMode = 'public'; // public, admin, local
let authChecked = false;
let resultObjectUrls = [];
let smtpEnabled = false;
let lastSubmittedRun = null;
let stageTickerId = null;
let resultDashboardOpen = false;
let resultFocusMode = 'overview';
let activeResultCategory = 'figures';
let activeResultFiles = [];
let activeResultArtifacts = null;
let resultArchiveObjectUrl = '';
let resultArchiveRequestSeq = 0;
let activeArchiveDownload = null;
let resultHelperObjectUrls = [];
let summaryReaderSeq = 0;
let publicQuota = {
  max_accessions: 25,
  max_genome_files: 25,
  max_upload_file_mb: 250,
  max_upload_total_mb: 1024,
};

const PUBLIC_CANONICAL_CPUS = 8;
const PUBLIC_CANONICAL_STAGE_DEFAULTS = {
  'run-genome-prep': true,
  'run-annotation': true,
  'run-bigscape': true,
  'run-summary': true,
  'run-clinker': true,
  'run-figures': true,
  'run-nplinker': false,
};

const PUBLIC_LOCKED_CHECKBOX_DEFAULTS = {
  'run-genome-prep': true,
  'run-annotation': true,
  'run-ncbi-install': false,
  'run-nplinker': false,
  'force-rerun': false,
  'figures-required': false,
};

const STORAGE_KEYS = {
  submitToken: 'clusterweave.submitToken',
  adminToken: 'clusterweave.adminToken',
  openedRuns: 'clusterweave.openedRuns',
  opsPanelWidth: 'clusterweave.opsPanelWidth',
  resultFocusWidth: 'clusterweave.resultFocusWidth',
};

// Pipeline stages for the progress bar
const STAGES = [
  { key: 'prep',       label: 'Prep' },
  { key: 'annotation', label: 'Annotation' },
  { key: 'bigscape',   label: 'BiG-SCAPE' },
  { key: 'summary',    label: 'Summary' },
  { key: 'clinker',    label: 'clinker' },
  { key: 'figures',    label: 'Figures' },
  { key: 'nplinker',   label: 'NPLinker' },
];

const STAGE_RUNTIME_HINTS = {
  prep: '1-10 min',
  annotation: '30-180 min',
  bigscape: '10-60 min',
  summary: '2-15 min',
  clinker: '5-45 min',
  figures: '2-10 min',
  nplinker: 'Optional; varies by omics input',
};

const STAGE_DETAILS = {
  prep: {
    name: 'Prep',
    hint: 'Inputs, layout, and accession preparation',
    queued: 'Waiting for submitted sources.',
    active: 'Preparing sources and project workspace.',
    done: 'Inputs are staged for analysis.',
  },
  annotation: {
    name: 'Annotation / BGC detection',
    hint: 'Genome annotation and biosynthetic cluster detection',
    queued: 'Waiting for prepared genomes.',
    active: 'Detecting biosynthetic gene cluster candidates.',
    done: 'BGC detection has advanced.',
  },
  bigscape: {
    name: 'BiG-SCAPE',
    hint: 'Gene cluster family graph construction',
    queued: 'Waiting for detected clusters.',
    active: 'Building family context.',
    done: 'Family context has advanced.',
  },
  summary: {
    name: 'Summary',
    hint: 'Crosswalk tables and shortlist context',
    queued: 'Waiting for family outputs.',
    active: 'Building tables and ranking context.',
    done: 'Summary tables have advanced.',
  },
  clinker: {
    name: 'clinker',
    hint: 'Synteny panel staging',
    queued: 'Waiting for prioritized regions.',
    active: 'Staging synteny comparisons.',
    done: 'Synteny panel staging has advanced.',
  },
  figures: {
    name: 'Figures',
    hint: 'Rendered figures and visual summaries',
    queued: 'Waiting for summary outputs.',
    active: 'Rendering visual summaries.',
    done: 'Figure rendering has advanced.',
  },
  nplinker: {
    name: 'NPLinker',
    hint: 'Optional paired omics follow-up',
    queued: 'Waiting for enabled omics inputs.',
    active: 'Running optional omics follow-up.',
    done: 'Optional omics follow-up has advanced.',
  },
};

const NAV_TARGETS = {
  overview: { anchor: 'overview', focus: 'overview' },
  intake: { anchor: 'intake', focus: 'manual-accessions' },
  weavemap: { anchor: 'weavemap', focus: 'weavemap' },
  runs: { anchor: 'jobs-card', focus: 'jobs-card' },
  outputs: { anchor: 'results-card', focus: 'results-card', fallback: 'jobs-card' },
  qa: { anchor: 'console-card', focus: 'console-card' },
  docs: { anchor: 'docs', focus: 'docs' },
};

// ── Helpers ────────────────────────────────────────────────────────────────
function setCardCollapsed(id, collapsed) {
  const body = document.getElementById(id + '-body');
  const hdr = document.querySelector('#' + id + ' .card-header');
  if (body) body.classList.toggle('hidden', collapsed);
  if (hdr) hdr.classList.toggle('collapsed', collapsed);
}

function setOpsPanelCollapsed(collapsed) {
  const isCollapsed = !!collapsed;
  document.body.dataset.opsPanel = isCollapsed ? 'collapsed' : 'open';
  const toggle = document.getElementById('ops-panel-toggle');
  if (!toggle) return;
  const label = isCollapsed ? 'Show diagnostics panel' : 'Collapse diagnostics panel';
  toggle.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
  toggle.setAttribute('title', label);
  const icon = toggle.querySelector('[data-ops-toggle-icon]');
  if (icon) icon.textContent = isCollapsed ? '›' : '‹';
  const srLabel = toggle.querySelector('[data-ops-toggle-label]');
  if (srLabel) srLabel.textContent = label;
}

function toggleOpsPanel() {
  if (!canUseAdminSurfaces()) return;
  setOpsPanelCollapsed(document.body.dataset.opsPanel !== 'collapsed');
}

function panelResizeConfig(kind) {
  if (kind === 'result') {
    return {
      cssVar: '--result-drawer-width',
      storageKey: STORAGE_KEYS.resultFocusWidth,
      elementId: 'result-dashboard-section',
      reverse: true,
    };
  }
  return {
    cssVar: '--ops-panel-width',
    storageKey: STORAGE_KEYS.opsPanelWidth,
    elementId: 'ops-side-panel',
    reverse: false,
  };
}

function panelResizeBounds(kind) {
  const width = Math.max(320, window.innerWidth || document.documentElement.clientWidth || 0);
  if (kind === 'result') {
    return { min: Math.min(360, width - 48), max: Math.min(760, Math.max(360, width - 460)) };
  }
  return { min: Math.min(288, width - 48), max: Math.min(520, Math.max(320, width - 220)) };
}

function normalizedPanelWidth(kind, value) {
  const bounds = panelResizeBounds(kind);
  const fallback = kind === 'result' ? bounds.min : Math.min(Math.max(336, bounds.min), bounds.max);
  const numeric = Number.parseFloat(value);
  return clampNumber(Number.isFinite(numeric) ? numeric : fallback, bounds.min, bounds.max);
}

function setPanelWidth(kind, value, options = {}) {
  const config = panelResizeConfig(kind);
  if (window.innerWidth <= 980) {
    document.documentElement.style.removeProperty(config.cssVar);
    return null;
  }
  const width = normalizedPanelWidth(kind, value);
  document.documentElement.style.setProperty(config.cssVar, `${Math.round(width)}px`);
  if (options.persist !== false) sessionSet(config.storageKey, String(Math.round(width)));
  return width;
}

function applyStoredPanelWidths() {
  ['ops', 'result'].forEach(kind => {
    const config = panelResizeConfig(kind);
    if (window.innerWidth <= 980) {
      document.documentElement.style.removeProperty(config.cssVar);
      return;
    }
    const stored = sessionGet(config.storageKey);
    if (stored) setPanelWidth(kind, stored, { persist: false });
  });
}

function currentPanelWidth(kind) {
  const config = panelResizeConfig(kind);
  const el = document.getElementById(config.elementId);
  const rectWidth = el ? el.getBoundingClientRect().width : 0;
  return rectWidth || normalizedPanelWidth(kind, sessionGet(config.storageKey));
}

function handlePanelResizeKeydown(kind, event) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  if (kind === 'ops' && !canUseAdminSurfaces()) return;
  if (window.innerWidth <= 980) return;
  event.preventDefault();
  const bounds = panelResizeBounds(kind);
  const step = event.shiftKey ? 48 : 18;
  let next = currentPanelWidth(kind);
  if (event.key === 'Home') next = bounds.min;
  else if (event.key === 'End') next = bounds.max;
  else if (kind === 'result') next += event.key === 'ArrowLeft' ? step : -step;
  else next += event.key === 'ArrowRight' ? step : -step;
  setPanelWidth(kind, next);
}

function startPanelResize(kind, event) {
  if (kind === 'ops' && !canUseAdminSurfaces()) return;
  if (window.innerWidth <= 980) return;
  event.preventDefault();
  event.stopPropagation();
  const config = panelResizeConfig(kind);
  const startX = event.clientX;
  const startWidth = currentPanelWidth(kind);
  const handle = event.currentTarget;
  if (handle && event.pointerId !== undefined && handle.setPointerCapture) {
    try { handle.setPointerCapture(event.pointerId); } catch (err) {}
  }
  document.body.classList.add('is-panel-resizing');
  let pendingWidth = startWidth;
  let lastWidth = startWidth;
  let resizeFrame = 0;
  const applyPendingWidth = () => {
    resizeFrame = 0;
    lastWidth = setPanelWidth(kind, pendingWidth, { persist: false }) || lastWidth;
    if (kind === 'result') scheduleDnaOverlaySync();
  };
  const queueWidth = width => {
    pendingWidth = width;
    if (!resizeFrame) resizeFrame = window.requestAnimationFrame(applyPendingWidth);
  };
  const move = moveEvent => {
    moveEvent.preventDefault();
    moveEvent.stopPropagation();
    const delta = config.reverse ? startX - moveEvent.clientX : moveEvent.clientX - startX;
    queueWidth(startWidth + delta);
  };
  const stop = stopEvent => {
    if (stopEvent) stopEvent.stopPropagation();
    if (resizeFrame) {
      window.cancelAnimationFrame(resizeFrame);
      applyPendingWidth();
    }
    setPanelWidth(kind, lastWidth);
    if (handle && event.pointerId !== undefined && handle.releasePointerCapture) {
      try { handle.releasePointerCapture(event.pointerId); } catch (err) {}
    }
    document.body.classList.remove('is-panel-resizing');
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', stop);
    window.removeEventListener('pointercancel', stop);
  };
  window.addEventListener('pointermove', move, { passive: false });
  window.addEventListener('pointerup', stop, { once: true });
  window.addEventListener('pointercancel', stop, { once: true });
}

function wirePanelResizers() {
  [
    ['ops-panel-resizer', 'ops'],
    ['result-focus-resizer', 'result'],
  ].forEach(([id, kind]) => {
    const handle = document.getElementById(id);
    if (!handle || handle.dataset.resizeWired === '1') return;
    handle.dataset.resizeWired = '1';
    handle.addEventListener('pointerdown', event => startPanelResize(kind, event));
    handle.addEventListener('keydown', event => handlePanelResizeKeydown(kind, event));
  });
}

function scheduleDnaOverlaySync() {
  const helix = document.getElementById('weavemap-helix');
  const stageWrap = helix?.closest?.('.weavemap-stage-wrap') || helix?.parentElement || null;
  if (!helix || !stageWrap) return;
  window.requestAnimationFrame(() => syncAndPositionDnaPopovers(stageWrap, helix));
}

function setUIMode(mode, options = {}) {
  if (accessMode === 'public' && mode !== 'guided') mode = 'guided';
  const normalized = ['guided', 'lab', 'advanced'].includes(mode) ? mode : 'guided';
  currentUIMode = normalized;
  document.body.dataset.uiMode = normalized;
  document.querySelectorAll('[data-mode-option]').forEach(btn => {
    const active = btn.dataset.modeOption === normalized;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  });

  const workflowControls = document.getElementById('workflow-controls');
  const advancedPanel = document.getElementById('advanced-panel');
  if (normalized === 'advanced') {
    if (workflowControls) workflowControls.open = true;
    if (advancedPanel) advancedPanel.open = true;
  } else if (normalized === 'lab') {
    if (workflowControls) workflowControls.open = true;
    if (advancedPanel && !options.keepAdvancedOpen) advancedPanel.open = false;
    setCardCollapsed('console-card', false);
  } else if (!options.preserveDisclosure) {
    if (workflowControls) workflowControls.open = false;
    if (advancedPanel) advancedPanel.open = false;
  }
}

function setAccessMode(mode) {
  accessMode = ['public', 'admin', 'local'].includes(mode) ? mode : 'public';
  document.body.dataset.access = accessMode;
  setOpsPanelCollapsed(accessMode !== 'public' && document.body.dataset.opsPanel === 'collapsed');
  if (accessMode === 'public') {
    document.body.dataset.managementView = 'closed';
    setUIMode('guided', { preserveDisclosure: true });
    document.getElementById('rerun-panel').innerHTML = '';
    if (!activeJobId && !document.getElementById('upload-card')?.classList.contains('upload-card-locked')) {
      setCardCollapsed('upload-card', false);
    }
  }
  document.getElementById('progress-card')?.classList.toggle('hidden', !canUseAdminSurfaces() || !activeJobId);
  updateAccessTokenStatus();
  renderOpenedRuns();
  if (document.getElementById('run-btn')) {
    syncControlState();
    renderFileList();
  }
}

function canUseAdminSurfaces() {
  return accessMode === 'admin' || accessMode === 'local';
}

function publicWorkflowLocked() {
  return !canUseAdminSurfaces();
}

function publicStageDefault(id, fallback = true) {
  return Object.prototype.hasOwnProperty.call(PUBLIC_CANONICAL_STAGE_DEFAULTS, id)
    ? PUBLIC_CANONICAL_STAGE_DEFAULTS[id]
    : fallback;
}

function publicLockedCheckboxDefault(id) {
  return Object.prototype.hasOwnProperty.call(PUBLIC_LOCKED_CHECKBOX_DEFAULTS, id)
    ? PUBLIC_LOCKED_CHECKBOX_DEFAULTS[id]
    : null;
}

function effectiveCheckboxValue(id, publicFallback = true) {
  if (publicWorkflowLocked()) {
    if (id === 'execute-clinker') return effectiveCheckboxValue('run-clinker', true);
    const lockedDefault = publicLockedCheckboxDefault(id);
    if (lockedDefault !== null) return lockedDefault;
  }
  const el = document.getElementById(id);
  return el ? !!el.checked : publicStageDefault(id, publicFallback);
}

function effectiveCpuCount() {
  if (publicWorkflowLocked()) return PUBLIC_CANONICAL_CPUS;
  return parseInt(document.getElementById('cpus')?.value || '4', 10) || 4;
}

function effectiveAnnotationStrategy() {
  if (publicWorkflowLocked()) return 'auto';
  return document.getElementById('genefinding-mode')?.value || 'auto';
}

function applyPublicCanonicalDefaults() {
  Object.keys(PUBLIC_LOCKED_CHECKBOX_DEFAULTS).forEach(id => {
    const el = document.getElementById(id);
    if (!el || el.type !== 'checkbox') return;
    if (!publicWorkflowLocked()) {
      if (el.dataset.publicLocked === 'true') {
        el.disabled = false;
        el.title = '';
        delete el.dataset.publicLocked;
      }
      return;
    }
    const value = PUBLIC_LOCKED_CHECKBOX_DEFAULTS[id];
    el.checked = !!value;
    el.disabled = true;
    el.dataset.publicLocked = 'true';
    if (id === 'run-genome-prep' || id === 'run-annotation') {
      el.title = 'Required for hosted public submissions.';
    }
  });
  if (!publicWorkflowLocked()) return;
  const cpus = document.getElementById('cpus');
  if (cpus) cpus.value = String(PUBLIC_CANONICAL_CPUS);
  const annoCpus = document.getElementById('anno-cpus');
  if (annoCpus) annoCpus.value = String(PUBLIC_CANONICAL_CPUS);
  const genefinding = document.getElementById('genefinding-mode');
  if (genefinding) genefinding.value = 'auto';
  const fallbackOrder = document.getElementById('annotation-fallback-order');
  if (fallbackOrder) fallbackOrder.value = 'funannotate';
}

function setActiveNav(target) {
  document.querySelectorAll('[data-nav-target]').forEach(el => {
    const active = el.dataset.navTarget === target;
    el.classList.toggle('active', active);
    if (el.classList.contains('nav-link')) {
      if (active) el.setAttribute('aria-current', 'page');
      else el.removeAttribute('aria-current');
    }
    if (el.classList.contains('ops-nav-button')) {
      el.setAttribute('aria-pressed', active ? 'true' : 'false');
    }
  });
}

function currentNavTarget() {
  return document.querySelector('.nav-link.active[data-nav-target]')?.dataset.navTarget || 'overview';
}

function runHasKnownResultFiles(job) {
  return Array.isArray(job?.result_files) && job.result_files.map(normalizedResultPath).filter(Boolean).length > 0;
}

function shouldPreserveResultsDashboardForJobLoad(jobId, options = {}) {
  if (options.deferResultsShell || options.resultsDashboard === false) return false;
  if (options.resultsDashboard === true || options.keepResultsDashboard === true) return true;
  const historyJob = jobHistoryById.get(String(jobId || ''));
  const historyStatus = String(historyJob?.status || '').toLowerCase();
  return resultDashboardOpen
    || document.body.dataset.resultsDashboard === 'open'
    || currentNavTarget() === 'outputs'
    || runHasKnownResultFiles(historyJob)
    || ['success', 'failed'].includes(historyStatus);
}

function shouldOpenResultDashboardDuringRefresh(files = activeResultFiles, job = activeJobMeta) {
  const hasOutputs = (files || []).map(normalizedResultPath).filter(Boolean).length > 0 || runHasKnownResultFiles(job);
  const wantsResults = resultDashboardOpen
    || document.body.dataset.resultsDashboard === 'open'
    || currentNavTarget() === 'outputs'
    || !canUseAdminSurfaces();
  if (canUseAdminSurfaces() && document.body.dataset.managementView === 'open' && !wantsResults && !hasOutputs) return false;
  return wantsResults || hasOutputs;
}

function closePrimaryNav() {
  const nav = document.getElementById('primary-nav');
  const toggle = document.getElementById('nav-toggle');
  if (nav) nav.classList.remove('open');
  if (toggle) toggle.setAttribute('aria-expanded', 'false');
}

function togglePrimaryNav() {
  const nav = document.getElementById('primary-nav');
  const toggle = document.getElementById('nav-toggle');
  if (!nav || !toggle) return;
  const open = !nav.classList.contains('open');
  nav.classList.toggle('open', open);
  toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function syncDocsDisclosureState() {
  const docs = document.getElementById('docs');
  const isOpen = !!(docs && docs.open);
  document.body.dataset.docsDisclosure = isOpen ? 'open' : 'closed';
  const summary = docs?.querySelector('.docs-summary');
  if (summary) summary.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  if (isOpen) {
    const runtimeStatus = document.getElementById('runtime-status-menu');
    if (runtimeStatus) runtimeStatus.open = false;
  }
}

function closeDocsDisclosure(options = {}) {
  const docs = document.getElementById('docs');
  if (!docs || !docs.open) return;
  docs.open = false;
  syncDocsDisclosureState();
  if (options.returnFocus) docs.querySelector('.docs-summary')?.focus();
}

function wireDocsDisclosure() {
  const docs = document.getElementById('docs');
  if (!docs || docs.dataset.wired === '1') return;
  docs.dataset.wired = '1';
  syncDocsDisclosureState();
  docs.addEventListener('toggle', syncDocsDisclosureState);
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !docs.open) return;
    event.preventDefault();
    closeDocsDisclosure({ returnFocus: true });
  });
  document.addEventListener('pointerdown', (event) => {
    if (!docs.open || docs.contains(event.target)) return;
    event.preventDefault();
    event.stopPropagation();
    closeDocsDisclosure();
  }, true);
}

function navElementFor(target) {
  if (target === 'outputs' && resultDashboardOpen) {
    const spine = document.getElementById('weavemap');
    if (spine && !spine.classList.contains('hidden')) return spine;
    const board = document.getElementById('result-dashboard-section');
    if (board && !board.classList.contains('hidden')) return board;
  }
  const cfg = NAV_TARGETS[target] || NAV_TARGETS.overview;
  let el = document.getElementById(cfg.anchor);
  if (el && el.classList.contains('hidden') && cfg.fallback) {
    el = document.getElementById(cfg.fallback);
  }
  return el || document.getElementById('overview');
}

function focusSection(el, focusId) {
  const focusEl = focusId ? document.getElementById(focusId) : el;
  const target = focusEl || el;
  if (!target) return;
  target.focus({ preventScroll: true });
  const pulseEl = el && !el.classList.contains('hidden') ? el : target;
  pulseEl.classList.remove('section-focus');
  void pulseEl.offsetWidth;
  pulseEl.classList.add('section-focus');
}

function rerenderWorkflowSpineForResults() {
  const helix = document.getElementById('weavemap-helix');
  if (helix) delete helix.dataset.rendered;
  renderWeaveHelix(activeJobMeta);
}

function closeResultDashboardForManagementTarget(target) {
  if (!canUseAdminSurfaces() || !['overview', 'intake', 'runs', 'qa'].includes(target)) return;
  if (!resultDashboardOpen && resultFocusMode === 'overview') return;
  resultDashboardOpen = false;
  activeResultCategory = firstAvailableResultCategory(resultCategoryCounts(activeResultFiles));
  setResultFocusMode('overview');
  document.body.dataset.resultsDashboard = 'closed';
  document.getElementById('completion-callout')?.classList.add('hidden');
  updateResultDashboardVisibility(activeJobMeta?.status || '', activeResultFiles.length);
  rerenderWorkflowSpineForResults();
}

function setManagementViewForTarget(target) {
  const activeWorkflow = String(document.body.dataset.workflowState || 'idle') !== 'idle';
  const opensManagement = canUseAdminSurfaces() && activeWorkflow && ['overview', 'intake', 'runs', 'qa'].includes(target);
  document.body.dataset.managementView = opensManagement ? 'open' : 'closed';
}

function navigateToSection(event, target, focusId = null) {
  if (event) event.preventDefault();
  if (target === 'intake' && document.body.dataset.entryMode === 'existing') switchEntryTab('new');
  closeResultDashboardForManagementTarget(target);
  setManagementViewForTarget(target);
  if (target === 'outputs' && activeJobMeta && !resultDashboardOpen) {
    showResultDashboard();
  }
  if (target === 'qa' && currentUIMode === 'guided') setUIMode('lab', { preserveDisclosure: true });
  const cfg = NAV_TARGETS[target] || NAV_TARGETS.overview;
  const el = navElementFor(target);
  setActiveNav(target);
  closePrimaryNav();
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    window.history.replaceState(null, '', `#${cfg.anchor}`);
    window.setTimeout(() => focusSection(el, focusId || cfg.focus), 220);
  }
}

function syncNavFromHash() {
  const hash = window.location.hash.replace(/^#/, '');
  if (/^\/?job\//i.test(hash)) {
    setActiveNav('outputs');
    return;
  }
  const match = Object.entries(NAV_TARGETS).find(([, cfg]) => cfg.anchor === hash);
  if (match) setActiveNav(match[0]);
}

function parseResultHash() {
  const hash = window.location.hash || '';
  const match = hash.match(/^#\/?job\/([^/\s#?]+)\/([^/\s#?]+)/i);
  if (!match) return null;
  return { jobId: decodeURIComponent(match[1]), token: decodeURIComponent(match[2]) };
}

function runtimeMetricText(value, fallback = 'Not available') {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'number' && Number.isFinite(value)) return value.toLocaleString();
  const raw = String(value).trim();
  if (/^\d+$/.test(raw)) return Number(raw).toLocaleString();
  return raw || fallback;
}

function setRuntimePanelValue(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function updateRuntimeStatusPanel(system = null, counts = {}) {
  const hasSystem = system && typeof system === 'object';
  const fullStatus = isFullSystemStatus(system);
  const server = hasSystem
    ? (system.service || system.state || (system.online === false ? 'offline' : 'online'))
    : runtimeStatusSnapshot.server;
  const submissions = hasSystem
    ? (system.submissions || (system.submissions_open === true ? 'open' : system.submissions_open === false ? 'paused' : runtimeStatusSnapshot.submissions))
    : runtimeStatusSnapshot.submissions;
  const jobsProcessed = hasSystem && Object.prototype.hasOwnProperty.call(system, 'jobs_processed')
    ? system.jobs_processed
    : runtimeStatusSnapshot.jobsProcessed;
  const runningJobs = Object.prototype.hasOwnProperty.call(counts, 'runningJobs')
    ? counts.runningJobs
    : (hasSystem && Object.prototype.hasOwnProperty.call(system, 'running_jobs') ? system.running_jobs : runtimeStatusSnapshot.runningJobs);
  const queuedJobs = Object.prototype.hasOwnProperty.call(counts, 'queuedJobs')
    ? counts.queuedJobs
    : (hasSystem && Object.prototype.hasOwnProperty.call(system, 'queued_jobs') ? system.queued_jobs : runtimeStatusSnapshot.queuedJobs);
  const diagnosticsVisible = canUseAdminSurfaces() && (fullStatus || Object.keys(counts).length > 0);

  runtimeStatusSnapshot = {
    server: runtimeMetricText(server, 'Checking'),
    submissions: runtimeMetricText(submissions, 'Checking'),
    runningJobs,
    queuedJobs,
    jobsProcessed,
    scope: diagnosticsVisible ? 'diagnostics' : 'public',
  };

  setRuntimePanelValue('runtime-server-status', runtimeStatusSnapshot.server);
  setRuntimePanelValue('runtime-submissions-status', runtimeStatusSnapshot.submissions);
  setRuntimePanelValue('runtime-jobs-processed', runtimeMetricText(jobsProcessed));
  setRuntimePanelValue(
    'runtime-running-jobs',
    diagnosticsVisible ? runtimeMetricText(runningJobs, '0') : ''
  );
  setRuntimePanelValue(
    'runtime-queued-jobs',
    diagnosticsVisible ? runtimeMetricText(queuedJobs, '0') : ''
  );
  const note = document.getElementById('runtime-visibility-note');
  if (note) {
    note.textContent = diagnosticsVisible
      ? 'Diagnostics view: queue depth is shown from worker telemetry.'
      : '';
  }
}

function updateRuntimeStatusChip(status, label) {
  const chip = document.getElementById('runtime-status-chip');
  if (!chip) return;
  const safeStatus = String(status || 'unknown').toLowerCase();
  const shown = label || 'Checking';
  chip.className = `status-chip status-${safeStatus}`;
  chip.setAttribute('aria-label', `Runtime: ${shown}. Open status details`);
  chip.innerHTML = `<span class="signal-lamp" aria-hidden="true"></span><span class="runtime-status-label">Runtime: ${escapeHtml(shown)}</span>`;
}

function fmt_size(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/1048576).toFixed(1) + ' MB';
}
function ext(name) { return name.split('.').pop().toLowerCase(); }
function toggleCard(id) {
  const body = document.getElementById(id + '-body');
  const hdr  = document.querySelector('#' + id + ' .card-header');
  body.classList.toggle('hidden');
  hdr.classList.toggle('collapsed');
}

function switchEntryTab(name) {
  const tabs = Array.from(document.querySelectorAll('.entry-tab'));
  const panels = Array.from(document.querySelectorAll('.entry-panel'));
  const names = ['new', 'existing'];
  const idx = Math.max(0, names.indexOf(name));
  const selectedName = names[idx];
  document.body.dataset.entryMode = selectedName;
  if (selectedName === 'new') document.body.dataset.existingRunLoaded = 'false';
  tabs.forEach((tab, tabIdx) => {
    const active = tabIdx === idx;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
    tab.tabIndex = active ? 0 : -1;
  });
  panels.forEach(panel => {
    const active = panel.id === 'entry-panel-' + selectedName;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
  const marker = document.querySelector('#upload-card .card-marker');
  if (marker) marker.textContent = selectedName === 'existing' ? 'Lookup' : 'New run';
}

function handleEntryInputSourceSelect(source) {
  const selected = String(source || 'manual');
  const select = document.getElementById('entry-input-source-select');
  if (select && select.value !== selected) select.value = selected;
  if (selected === 'manual') {
    navigateToSection(null, 'intake', 'manual-accessions');
    return;
  }
  navigateToSection(null, 'intake', 'drop-zone');
}

function handleEntryTabKeydown(event) {
  const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
  if (!keys.includes(event.key)) return;
  event.preventDefault();
  const names = ['new', 'existing'];
  const tabs = Array.from(document.querySelectorAll('.entry-tab'));
  const currentIdx = tabs.indexOf(event.currentTarget);
  let nextIdx = currentIdx;
  if (event.key === 'ArrowLeft') nextIdx = (currentIdx + tabs.length - 1) % tabs.length;
  if (event.key === 'ArrowRight') nextIdx = (currentIdx + 1) % tabs.length;
  if (event.key === 'Home') nextIdx = 0;
  if (event.key === 'End') nextIdx = tabs.length - 1;
  switchEntryTab(names[nextIdx]);
  tabs[nextIdx].focus();
}

function switchTab(name, options = {}) {
  const tabs = Array.from(document.querySelectorAll('.tab'));
  const panels = Array.from(document.querySelectorAll('.tab-panel'));
  const names = ['viz','files'];
  const idx = Math.max(0, names.indexOf(name));
  const selectedName = names[idx];
  const preserveCategory = !!(options && options.preserveCategory);
  if (!preserveCategory) {
    activeResultCategory = selectedName === 'files' ? 'downloads' : 'figures';
  }
  tabs.forEach((tab, tabIdx) => {
    const active = tabIdx === idx;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
    tab.tabIndex = active ? 0 : -1;
  });
  panels.forEach(panel => {
    const active = panel.id === 'tab-' + selectedName;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
  if (!preserveCategory && activeJobId && activeResultFiles.length) {
    if (selectedName === 'files') renderFileTable(activeJobId, activeResultFiles, { category: activeResultCategory });
    renderResultBubblePanel(activeResultFiles, activeJobMeta?.status || '');
  }
}

function handleResultTabKeydown(event) {
  const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
  if (!keys.includes(event.key)) return;
  event.preventDefault();
  const names = ['viz', 'files'];
  const tabs = Array.from(document.querySelectorAll('.tab'));
  const currentIdx = tabs.indexOf(event.currentTarget);
  let nextIdx = currentIdx;
  if (event.key === 'ArrowLeft') nextIdx = (currentIdx + tabs.length - 1) % tabs.length;
  if (event.key === 'ArrowRight') nextIdx = (currentIdx + 1) % tabs.length;
  if (event.key === 'Home') nextIdx = 0;
  if (event.key === 'End') nextIdx = tabs.length - 1;
  switchTab(names[nextIdx]);
  tabs[nextIdx].focus();
}

function boolToFlag(value) { return value ? '1' : '0'; }

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[ch]));
}

function escapeJsString(value) {
  return String(value ?? '')
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")
    .replace(/\r/g, '\\r')
    .replace(/\n/g, '\\n');
}

function updateAccessTokenStatus(message = '') {
  const submitInput = document.getElementById('submit-token');
  const adminInput = document.getElementById('admin-token');
  if (submitInput && document.activeElement !== submitInput) submitInput.value = submitToken() ? '••••••••' : '';
  if (adminInput && document.activeElement !== adminInput) adminInput.value = adminToken() ? '••••••••' : '';
  const status = document.getElementById('access-token-status');
  if (!status) return;
  if (message) {
    status.textContent = message;
    return;
  }
  const bits = [];
  if (submitToken()) bits.push('submission code saved');
  if (adminToken()) bits.push('diagnostics code saved');
  status.textContent = bits.length ? bits.join(', ') : 'No access code saved for this tab.';
}

function saveAccessTokens() {
  const submitInput = document.getElementById('submit-token');
  const adminInput = document.getElementById('admin-token');
  const submitValue = submitInput && !/^•+$/.test(submitInput.value) ? submitInput.value.trim() : submitToken();
  const adminValue = adminInput && !/^•+$/.test(adminInput.value) ? adminInput.value.trim() : adminToken();
  sessionSet(STORAGE_KEYS.submitToken, submitValue);
  sessionSet(STORAGE_KEYS.adminToken, adminValue);
  updateAccessTokenStatus('Access saved for this browser tab.');
  fetchSystemStatus().then(system => {
    if (isFullSystemStatus(system)) {
      refreshJobHistory();
      startSystemConsolePolling();
    } else if (adminValue) {
      stopSystemConsolePolling();
      updateAccessTokenStatus('Diagnostics code was not accepted; standard view is active.');
    }
  });
}

function clearAccessTokens() {
  sessionSet(STORAGE_KEYS.submitToken, '');
  sessionSet(STORAGE_KEYS.adminToken, '');
  setAccessMode('public');
  updateAccessTokenStatus('Access codes cleared.');
}

function updateEmailNotificationPanel() {
  const panel = document.getElementById('email-notification-panel');
  const input = document.getElementById('notify-email');
  if (!panel) return;
  panel.classList.toggle('hidden', !smtpEnabled);
  if (!smtpEnabled && input) input.value = '';
}

function parseExistingRunInput() {
  const raw = (document.getElementById('existing-run-link')?.value || '').trim();
  const explicitToken = (document.getElementById('existing-run-token')?.value || '').trim();
  if (!raw) return null;

  let text = raw;
  try {
    const url = new URL(raw, window.location.href);
    text = url.hash || url.pathname || raw;
  } catch (e) {}
  const fragmentMatch = text.match(/#?\/?job\/([^/\s#?]+)\/([^/\s#?]+)/i);
  if (fragmentMatch) return { jobId: decodeURIComponent(fragmentMatch[1]), token: decodeURIComponent(fragmentMatch[2]) };

  const parts = raw.split(/[\s,]+/).filter(Boolean);
  if (parts.length >= 2) return { jobId: parts[0], token: parts[1] };
  if (parts.length === 1 && explicitToken) return { jobId: parts[0], token: explicitToken };
  return null;
}

async function unlockExistingRun() {
  const status = document.getElementById('existing-run-status');
  const parsed = parseExistingRunInput();
  if (!parsed) {
    if (status) status.textContent = 'Enter a private result link, or a job ID plus result access code.';
    document.body.dataset.existingRunLoaded = 'false';
    return;
  }
  if (status) status.textContent = 'Opening private results...';
  const job = await loadJob(parsed.jobId, true, { readToken: parsed.token, source: 'existing-run', deferResultsShell: true });
  if (status) status.textContent = job ? 'Results opened in this tab.' : 'No run matched that job ID and result access code.';
  document.body.dataset.existingRunLoaded = job ? 'true' : 'false';
  if (job) navigateToSection(null, 'outputs');
}

function renderOpenedRuns() {
  const panel = document.getElementById('opened-runs-panel');
  const select = document.getElementById('opened-runs-select');
  if (!panel || !select) return;
  const runs = loadOpenedRuns();
  panel.classList.toggle('hidden', runs.length === 0);
  select.innerHTML = runs.length
    ? `<option value="">Select recent result</option>${runs.map(run => `<option value="${escapeHtml(run.id)}">${escapeHtml(run.name || run.id)} (${escapeHtml(run.id)})</option>`).join('')}`
    : '<option value="">No recent results</option>';
  if (activeJobId) select.value = activeJobId;
}

async function loadSelectedOpenedRun() {
  const select = document.getElementById('opened-runs-select');
  const status = document.getElementById('existing-run-status');
  const jobId = select ? select.value : '';
  if (!jobId) return;
  if (status) status.textContent = 'Opening remembered result...';
  if (select) select.disabled = true;
  const job = await loadJob(jobId, true, { readToken: readTokenForJob(jobId), source: 'opened-run-select', deferResultsShell: true });
  document.body.dataset.existingRunLoaded = job ? 'true' : 'false';
  if (status) status.textContent = job ? 'Results opened in this tab.' : 'That remembered result could not be opened. Enter its result access code again.';
  renderOpenedRuns();
  if (select) {
    select.disabled = false;
    if (job) select.value = jobId;
  }
  if (job) navigateToSection(null, 'outputs');
}

function forgetOpenedRuns() {
  saveOpenedRuns([]);
  renderOpenedRuns();
  if (activeJobId && !canUseAdminSurfaces()) {
    activeJobId = null;
    activeJobMeta = null;
    stopPolling();
    showEmptyResults();
  }
}

function defaultApiBaseUrl() {
  const url = new URL(window.location.href);
  url.search = '';
  url.hash = '';
  if (url.pathname.endsWith('/')) return url.toString();
  if (/\.[^/]+$/.test(url.pathname)) {
    url.pathname = url.pathname.replace(/[^/]+$/, '');
  } else {
    url.pathname = `${url.pathname}/`;
  }
  return url.toString();
}

function apiUrl(path) {
  const cleanPath = String(path || '').replace(/^\/+/, '');
  const configuredBase = window.CLUSTERWEAVE_API_BASE || '';
  const base = configuredBase ? new URL(configuredBase, window.location.href).toString() : defaultApiBaseUrl();
  return new URL(cleanPath, base).toString();
}

function resultHref(jobId, relPath, options = {}) {
  const base = apiUrl(`api/jobs/${encodeURIComponent(jobId)}/files/${normalizedResultPath(relPath).split('/').map(encodeURIComponent).join('/')}`);
  return options.download ? `${base}?download=1` : base;
}

function privateResultLink(jobId, token, serverUrl = '') {
  if (serverUrl) return serverUrl;
  return `${defaultApiBaseUrl()}#/job/${encodeURIComponent(jobId)}/${encodeURIComponent(token)}`;
}

function sessionGet(key) {
  try { return sessionStorage.getItem(key) || ''; }
  catch (e) { return ''; }
}

function sessionSet(key, value) {
  try {
    if (value) sessionStorage.setItem(key, value);
    else sessionStorage.removeItem(key);
  } catch (e) {}
}

function submitToken() { return sessionGet(STORAGE_KEYS.submitToken); }
function adminToken() { return sessionGet(STORAGE_KEYS.adminToken); }

function loadOpenedRuns() {
  try {
    const parsed = JSON.parse(sessionGet(STORAGE_KEYS.openedRuns) || '[]');
    return Array.isArray(parsed) ? parsed.filter(r => r && r.id && r.token) : [];
  } catch (e) {
    return [];
  }
}

function saveOpenedRuns(runs) {
  sessionSet(STORAGE_KEYS.openedRuns, JSON.stringify(runs.slice(0, 20)));
}

function readTokenForJob(jobId) {
  const id = String(jobId || '');
  if (!id) return '';
  const pending = pendingReadTokens.get(id);
  if (pending) return pending;
  const run = loadOpenedRuns().find(r => String(r.id) === id);
  return run ? run.token : '';
}

function rememberOpenedRun(jobId, token, meta = {}) {
  const id = String(jobId || '');
  if (!id || !token) return;
  const runs = loadOpenedRuns().filter(r => String(r.id) !== id);
  runs.unshift({
    id,
    token,
    name: meta.name || meta.project_name || meta.projectName || jobId,
    status: meta.status || '',
    updatedAt: new Date().toISOString(),
  });
  saveOpenedRuns(runs);
  pendingReadTokens.delete(id);
  renderOpenedRuns();
}

async function copyTextToClipboard(text, successMessage) {
  const status = document.getElementById('submission-confirmation-status');
  if (!text) {
    if (status) status.textContent = 'Nothing to copy yet.';
    return;
  }
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
    } else {
      const helper = document.createElement('textarea');
      helper.value = text;
      helper.setAttribute('readonly', '');
      helper.style.position = 'fixed';
      helper.style.top = '-1000px';
      document.body.appendChild(helper);
      helper.select();
      document.execCommand('copy');
      helper.remove();
    }
    if (status) status.textContent = successMessage || 'Copied.';
  } catch (err) {
    if (status) status.textContent = 'Copy failed; select the field and copy manually.';
  }
}

function renderSubmissionConfirmation(payload) {
  resultDashboardOpen = false;
  const panel = document.getElementById('submission-confirmation');
  if (!panel || !payload || !payload.jobId || !payload.readToken) return;
  const resultUrl = privateResultLink(payload.jobId, payload.readToken, payload.resultUrl || '');
  lastSubmittedRun = {
    ...payload,
    resultUrl,
  };
  const title = document.getElementById('submission-confirmation-title');
  const copy = document.getElementById('submission-confirmation-copy');
  const linkInput = document.getElementById('submitted-result-link');
  const jobInput = document.getElementById('submitted-job-id');
  const tokenInput = document.getElementById('submitted-result-token');
  const status = document.getElementById('submission-confirmation-status');
  const project = payload.projectName || 'ClusterWeave run';
  const expires = payload.expiresAt ? ` Results expire ${new Date(payload.expiresAt).toLocaleDateString()}.` : '';
  const email = payload.notifyEmail ? ` A completion email will include a private result link for ${payload.notifyEmail}.` : '';
  if (title) title.textContent = 'Initiating sequence. Launching ClusterWeave.';
  if (copy) copy.textContent = `${project} is queued. Save this private result link, or save the job ID with its result access code.${expires}${email}`;
  if (linkInput) linkInput.value = resultUrl;
  if (jobInput) jobInput.value = payload.jobId;
  if (tokenInput) tokenInput.value = payload.readToken;
  if (status) status.textContent = 'Result access is saved in this browser tab.';
  panel.classList.remove('hidden');
}

function renderActiveRunAccessPanel(job) {
  const panel = document.getElementById('submission-confirmation');
  if (!panel || !job || !job.id) return;
  const title = document.getElementById('submission-confirmation-title');
  const copy = document.getElementById('submission-confirmation-copy');
  const linkInput = document.getElementById('submitted-result-link');
  const jobInput = document.getElementById('submitted-job-id');
  const tokenInput = document.getElementById('submitted-result-token');
  const status = document.getElementById('submission-confirmation-status');
  const token = readTokenForJob(job.id);
  const link = token ? privateResultLink(job.id, token, job.result_url || '') : '';
  const project = job.project_name || job.settings?.project_name || job.id;
  const expires = job.expires_at ? ` Results expire ${new Date(job.expires_at).toLocaleDateString()}.` : '';
  const statusValue = String(job.status || '').toLowerCase();
  const isSubmittedRun = lastSubmittedRun && lastSubmittedRun.jobId === job.id && ['pending', 'running'].includes(statusValue);
  if (title) title.textContent = isSubmittedRun ? 'Initiating sequence. Launching ClusterWeave.' : 'Result access';
  if (copy) {
    copy.textContent = isSubmittedRun
      ? `${project} is queued. Save this private result link, or save the job ID with its result access code.${expires}`
      : `${project} is loaded in this browser tab. Keep the private result link, or keep the job ID with its result access code, to return later.${expires}`;
  }
  if (linkInput) linkInput.value = link;
  if (jobInput) jobInput.value = job.id;
  if (tokenInput) tokenInput.value = token || (canUseAdminSurfaces() ? 'Diagnostics access active' : '');
  if (status) status.textContent = token ? 'Result access is saved for this browser tab.' : 'Diagnostics access is being used for this job.';
  panel.classList.remove('hidden');
}

function dismissSubmissionConfirmation() {
  document.getElementById('submission-confirmation')?.classList.add('hidden');
}

function copySubmittedResultLink() {
  copyTextToClipboard(lastSubmittedRun?.resultUrl || document.getElementById('submitted-result-link')?.value, 'Private result link copied.');
}

function copySubmittedJobId() {
  copyTextToClipboard(lastSubmittedRun?.jobId || document.getElementById('submitted-job-id')?.value, 'Job ID copied.');
}

function copySubmittedResultCode() {
  copyTextToClipboard(lastSubmittedRun?.readToken || document.getElementById('submitted-result-token')?.value, 'Result access code copied.');
}

function openSubmittedRun() {
  if (!lastSubmittedRun) return;
  loadJob(lastSubmittedRun.jobId, true, { readToken: lastSubmittedRun.readToken, source: 'submission-confirmation' });
}

function authHeadersFor(kind, jobId = null) {
  const headers = {};
  if (kind === 'job' && jobId) {
    const token = readTokenForJob(jobId);
    if (token) {
      headers.Authorization = `Bearer ${token}`;
      return headers;
    }
  }
  if (kind === 'submit') {
    const token = submitToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
      return headers;
    }
  }
  const admin = adminToken();
  if (admin) {
    headers.Authorization = `Bearer ${admin}`;
  }
  return headers;
}

function mergeAuthHeaders(options = {}, auth = {}) {
  const headers = new Headers(options.headers || {});
  const tokenHeaders = authHeadersFor(auth.kind || 'none', auth.jobId || null);
  Object.entries(tokenHeaders).forEach(([key, value]) => {
    if (value && !headers.has(key)) headers.set(key, value);
  });
  return { ...options, headers };
}

function apiFetch(path, options = {}, auth = {}) {
  return fetch(apiUrl(path), mergeAuthHeaders(options, auth));
}

function resultNeedsAuth(jobId) {
  return !!adminToken() || (accessMode === 'public' && !!readTokenForJob(jobId));
}

function canOpenRichHtmlArtifacts(jobId = activeJobId) {
  return canUseAdminSurfaces() || !!readTokenForJob(jobId);
}

function inlineResultMime(relPath, fallback = '') {
  const name = fileNameFromPath(relPath).toLowerCase();
  const ext = name.includes('.') ? name.split('.').pop() : '';
  const mimeMap = {
    svg: 'image/svg+xml',
    png: 'image/png',
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    gif: 'image/gif',
    webp: 'image/webp',
    pdf: 'application/pdf',
    html: 'text/html;charset=utf-8',
    htm: 'text/html;charset=utf-8',
    txt: 'text/plain;charset=utf-8',
    log: 'text/plain;charset=utf-8',
    md: 'text/markdown;charset=utf-8',
    csv: 'text/csv;charset=utf-8',
    tsv: 'text/tab-separated-values;charset=utf-8',
    json: 'application/json',
    db: 'application/vnd.sqlite3',
    sqlite: 'application/vnd.sqlite3',
    sqlite3: 'application/vnd.sqlite3',
    yaml: 'text/yaml;charset=utf-8',
    yml: 'text/yaml;charset=utf-8',
    gbk: 'text/plain;charset=utf-8',
    gb: 'text/plain;charset=utf-8',
    gbff: 'text/plain;charset=utf-8',
    gff: 'text/plain;charset=utf-8',
    gff3: 'text/plain;charset=utf-8',
    fasta: 'text/plain;charset=utf-8',
    fa: 'text/plain;charset=utf-8',
    fna: 'text/plain;charset=utf-8',
  };
  if (mimeMap[ext]) return mimeMap[ext];
  if (fallback && fallback !== 'application/octet-stream') return fallback;
  return 'text/plain;charset=utf-8';
}

function resultUrlShouldStayExternal(rawUrl) {
  const value = String(rawUrl || '').trim();
  return !value ||
    value.startsWith('#') ||
    /^(?:[a-z][a-z0-9+.-]*:)?\/\//i.test(value) ||
    /^(?:data|blob|mailto|tel|javascript):/i.test(value) ||
    value.startsWith('/');
}

function resultRelativeAssetPath(ownerPath, rawUrl) {
  const value = String(rawUrl || '').trim();
  if (resultUrlShouldStayExternal(value)) return '';
  try {
    const ownerParts = normalizedResultPath(ownerPath).split('/').filter(Boolean);
    ownerParts.pop();
    const basePath = ownerParts.map(part => encodeURIComponent(part)).join('/');
    const base = `https://clusterweave.invalid/${basePath}${basePath ? '/' : ''}`;
    const parsed = new URL(value, base);
    if (parsed.origin !== 'https://clusterweave.invalid') return '';
    return decodeURIComponent(parsed.pathname.replace(/^\/+/, ''));
  } catch (e) {
    return '';
  }
}

function splitResultAssetUrl(rawUrl) {
  const value = String(rawUrl || '').trim();
  const match = value.match(/^([^?#]*)([?#].*)?$/);
  return { path: match ? match[1] : value, suffix: match && match[2] ? match[2] : '' };
}

function resultAssetHashSuffix(rawUrl) {
  const value = String(rawUrl || '').trim();
  const hashIndex = value.indexOf('#');
  return hashIndex >= 0 ? value.slice(hashIndex) : '';
}

async function resultAssetObjectUrl(jobId, ownerPath, rawUrl, cache) {
  const parts = splitResultAssetUrl(rawUrl);
  const assetPath = resultRelativeAssetPath(ownerPath, parts.path);
  if (!assetPath) return '';
  const cacheKey = normalizedResultPath(assetPath);
  if (cache.has(cacheKey)) return cache.get(cacheKey);
  const promise = (async () => {
    const resp = await resultFetch(jobId, cacheKey);
    if (!resp.ok) return '';
    const contentType = resp.headers.get('Content-Type') || '';
    let blob;
    if (resultPathExt(cacheKey) === 'css' || /^text\/css\b/i.test(contentType)) {
      const cssText = await resp.text();
      const rewrittenCss = await rewriteCssResultUrls(cssText, jobId, cacheKey, cache);
      blob = new Blob([rewrittenCss], { type: inlineResultMime(cacheKey, 'text/css;charset=utf-8') });
    } else {
      const sourceBlob = await resp.blob();
      blob = new Blob([sourceBlob], { type: inlineResultMime(cacheKey, sourceBlob.type || contentType) });
    }
    const url = URL.createObjectURL(blob);
    resultHelperObjectUrls.push(url);
    return url;
  })();
  cache.set(cacheKey, promise);
  return promise;
}

async function rewriteCssResultUrls(cssText, jobId, ownerPath, cache) {
  const source = String(cssText || '');
  const regex = /url\(\s*([\'\"]?)([^\'\")]+)\1\s*\)/gi;
  let output = '';
  let lastIndex = 0;
  for (const match of source.matchAll(regex)) {
    output += source.slice(lastIndex, match.index);
    const quote = match[1] || '';
    const rawUrl = match[2] || '';
    let rewritten = '';
    if (!resultUrlShouldStayExternal(rawUrl)) {
      rewritten = await resultAssetObjectUrl(jobId, ownerPath, rawUrl, cache);
    }
    output += rewritten ? `url(${quote}${rewritten}${resultAssetHashSuffix(rawUrl)}${quote})` : match[0];
    lastIndex = match.index + match[0].length;
  }
  return output + source.slice(lastIndex);
}

async function rewriteHtmlResultAssets(htmlText, jobId, htmlPath) {
  const source = String(htmlText || '');
  const doc = new DOMParser().parseFromString(source, 'text/html');
  const cache = new Map();
  const assetAttrs = [
    ['link[href]', 'href'],
    ['script[src]', 'src'],
    ['img[src]', 'src'],
    ['source[src]', 'src'],
    ['video[poster]', 'poster'],
    ['audio[src]', 'src'],
    ['video[src]', 'src'],
    ['object[data]', 'data'],
    ['embed[src]', 'src'],
    ['iframe[src]', 'src'],
    ['input[src]', 'src'],
    ['track[src]', 'src'],
  ];
  for (const [selector, attr] of assetAttrs) {
    for (const el of Array.from(doc.querySelectorAll(selector))) {
      const value = el.getAttribute(attr) || '';
      if (resultUrlShouldStayExternal(value)) continue;
      const rewritten = await resultAssetObjectUrl(jobId, htmlPath, value, cache);
      if (rewritten) el.setAttribute(attr, rewritten + resultAssetHashSuffix(value));
    }
  }
  for (const styleEl of Array.from(doc.querySelectorAll('style'))) {
    styleEl.textContent = await rewriteCssResultUrls(styleEl.textContent || '', jobId, htmlPath, cache);
  }
  for (const el of Array.from(doc.querySelectorAll('[style]'))) {
    const value = el.getAttribute('style') || '';
    const rewritten = await rewriteCssResultUrls(value, jobId, htmlPath, cache);
    if (rewritten !== value) el.setAttribute('style', rewritten);
  }
  const doctype = source.match(/^\s*<!doctype[^>]*>/i);
  return `${doctype ? doctype[0] : '<!doctype html>'}
${doc.documentElement.outerHTML}`;
}

async function buildHtmlResultObjectUrl(jobId, htmlPath, htmlText, options = {}) {
  const transform = options && typeof options.transform === 'function' ? options.transform : null;
  const transformedHtml = transform ? transform(String(htmlText || '')) : String(htmlText || '');
  const rewrittenHtml = await rewriteHtmlResultAssets(transformedHtml, jobId, htmlPath);
  const url = URL.createObjectURL(new Blob([rewrittenHtml], { type: inlineResultMime(htmlPath, 'text/html;charset=utf-8') }));
  resultHelperObjectUrls.push(url);
  return url;
}

async function openHtmlResultWithAssets(event, jobId, relPath, previewWindow = null) {
  event?.preventDefault?.();
  const ownsWindow = !previewWindow;
  const targetWindow = previewWindow || window.open('', '_blank');
  if (!targetWindow) return false;
  targetWindow.opener = null;
  targetWindow.document.title = fileNameFromPath(relPath);
  targetWindow.document.body.textContent = 'Loading preview...';
  try {
    const resp = await resultFetch(jobId, relPath);
    if (!resp.ok) throw new Error('Result HTML could not be opened with the saved result access code.');
    const htmlText = await resp.text();
    const url = await buildHtmlResultObjectUrl(jobId, relPath, htmlText);
    targetWindow.location.href = url;
  } catch (err) {
    if (ownsWindow) targetWindow.close();
    alert(err.message || String(err));
  }
  return false;
}

function resultFetch(jobId, relPath, options = {}) {
  const { download = false, ...fetchOptions } = options;
  const path = `api/jobs/${encodeURIComponent(jobId)}/files/${normalizedResultPath(relPath).split('/').map(encodeURIComponent).join('/')}${download ? '?download=1' : ''}`;
  return apiFetch(path, fetchOptions, { kind: 'job', jobId });
}

async function handleResultLinkClick(event, jobId, relPath, download = false) {
  if (!download && isHtmlAsset(relPath)) {
    if (canOpenRichHtmlArtifacts(jobId)) return openHtmlResultWithAssets(event, jobId, relPath);
    return handleResultLinkClick(event, jobId, relPath, true);
  }
  const shouldDownloadViaClient = download && resultNeedsAuth(jobId);
  const shouldOpenInline = !download;
  if (!shouldDownloadViaClient && !shouldOpenInline) return true;
  event.preventDefault();
  let previewWindow = null;
  if (shouldOpenInline) {
    previewWindow = window.open('', '_blank');
    if (previewWindow) {
      previewWindow.opener = null;
      previewWindow.document.title = fileNameFromPath(relPath);
      previewWindow.document.body.textContent = 'Loading preview...';
    }
  }
  try {
    const resp = await resultFetch(jobId, relPath, { download: shouldDownloadViaClient });
    if (!resp.ok) throw new Error('Result file could not be opened with the saved result access code.');
    const sourceBlob = await resp.blob();
    const blob = shouldOpenInline
      ? new Blob([sourceBlob], { type: inlineResultMime(relPath, sourceBlob.type) })
      : sourceBlob;
    const url = URL.createObjectURL(blob);
    resultObjectUrls.push(url);
    if (shouldDownloadViaClient) {
      const link = document.createElement('a');
      link.href = url;
      link.download = fileNameFromPath(relPath);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } else if (previewWindow) {
      previewWindow.location.href = url;
    } else {
      window.open(url, '_blank', 'noopener');
    }
  } catch (err) {
    if (previewWindow) previewWindow.close();
    alert(err.message || String(err));
  }
  return false;
}

function envToBool(value, defaultValue = false) {
  if (value === undefined || value === null || value === '') return defaultValue;
  return String(value).trim().toLowerCase() === '1' ||
    ['true','yes','on'].includes(String(value).trim().toLowerCase());
}

function parseEnvProfile(text) {
  const out = {};
  const lines = text.split(/\r?\n/);
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const idx = line.indexOf('=');
    if (idx < 1) continue;
    const key = line.slice(0, idx).trim();
    let value = line.slice(idx + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

function applyEnvProfileValues(cfg) {
  const setText = (id, key) => {
    if (cfg[key] !== undefined) document.getElementById(id).value = cfg[key];
  };
  const setNum = (id, key) => {
    if (cfg[key] !== undefined) document.getElementById(id).value = parseInt(cfg[key] || '0', 10) || document.getElementById(id).value;
  };
  const setBool = (id, key, defaultVal) => {
    if (cfg[key] !== undefined) document.getElementById(id).checked = envToBool(cfg[key], defaultVal);
  };

  setText('project-name', 'PROJECT_NAME');
  setNum('cpus', 'CPUS');
  setText('target-genome', 'TARGET_GENOME');
  setBool('run-genome-prep', 'RUN_GENOME_PREP', true);
  setBool('run-annotation', 'RUN_STAGE_ANNOTATION', true);
  setBool('run-bigscape', 'RUN_STAGE_BIGSCAPE', true);
  setBool('run-summary', 'RUN_STAGE_SUMMARY', true);
  setBool('run-clinker', 'RUN_CLINKER', true);
  setBool('execute-clinker', 'RUN_CLINKER', true);
  setBool('run-figures', 'RUN_FIGURES', true);
  setBool('figures-required', 'FIGURES_REQUIRED', false);
  setBool('run-nplinker', 'RUN_NPLINKER', false);
  setBool('run-ecology', 'RUN_ECOLOGY_ANALYSIS', false);
  setText('ecology-field', 'ECOLOGY_FIELD');
  setText('focus-ecology-label', 'FOCUS_ECOLOGY_LABEL');
  setText('metadata-tsv', 'METADATA_TSV');
  setBool('force-rerun', 'FORCE', false);
  setNum('workers', 'WORKERS');
  setNum('anno-cpus', 'ANNO_CPUS');
  setText('annotation-fallback-order', 'ANNOTATION_FALLBACK_ORDER');
  setText('funannotate-busco-db', 'FUNANNOTATE_BUSCO_DB');
  setText('funannotate-organism-name', 'FUNANNOTATE_ORGANISM_NAME');
  setText('clinker-mode', 'CLINKER_MODE');
  setText('panel-target-set', 'PANEL_TARGET_SET');
  setNum('atlas-min-records', 'ATLAS_MIN_RECORDS');
  setNum('shared-family-stage-limit', 'SHARED_FAMILY_STAGE_LIMIT');
  setNum('shared-family-min-records', 'SHARED_FAMILY_MIN_RECORDS');
  setNum('shortlist-limit', 'SHORTLIST_LIMIT');
  setNum('max-comparators', 'MAX_COMPARATORS');
  setNum('max-same-ecology', 'MAX_SAME_ECOLOGY');
  setNum('max-other-ecology', 'MAX_OTHER_ECOLOGY');
  setBool('capture-external-artifacts', 'CAPTURE_EXTERNAL_ARTIFACTS', true);
  setBool('auto-normalize-metadata', 'AUTO_NORMALIZE_METADATA', true);
  setText('auto-pull-images', 'AUTO_PULL_IMAGES');
  setBool('auto-build-funbgcex-sif', 'AUTO_BUILD_FUNBGCEX_SIF', true);
  setBool('auto-pull-bigscape-sif', 'AUTO_PULL_BIGSCAPE_SIF', true);
  setBool('auto-download-pfam', 'AUTO_DOWNLOAD_PFAM', true);
  setBool('auto-download-fasttree', 'AUTO_DOWNLOAD_FASTTREE', true);
  setBool('mibig-auto-download', 'MIBIG_AUTO_DOWNLOAD', true);
  setText('clinker-docker-image', 'CLINKER_DOCKER_IMAGE');
  setText('clinker-docker-data-volume', 'CLINKER_DOCKER_DATA_VOLUME');
  setBool('clinker-use-docker-image', 'CLINKER_USE_DOCKER_IMAGE', true);
  setNum('clinker-max-regions', 'ATLAS_STAGE_LIMIT');
  setText('nplinker-run-mode', 'RUN_MODE');
  setText('target-strain', 'TARGET_STRAIN');
  setText('nplinker-podp-id', 'PODP_ID');
  setText('massive-dataset-id', 'MASSIVE_DATASET_ID');
  setText('gnps-version', 'GNPS_VERSION');
  setBool('auto-pull-nplinker-sif', 'AUTO_PULL_NPLINKER_SIF', true);
  setBool('nplinker-bootstrap-env', 'NPLINKER_BOOTSTRAP_ENV', true);
  syncControlState();
}

function currentEnvProfileText() {
  const lines = [
    `PROJECT_NAME=${document.getElementById('project-name').value.trim() || 'my_project'}`,
    `CPUS=${document.getElementById('cpus').value || '4'}`,
    `TARGET_GENOME=${document.getElementById('target-genome').value.trim()}`,
    `RUN_GENOME_PREP=${document.getElementById('run-genome-prep').checked ? '1' : '0'}`,
    `RUN_STAGE_ANNOTATION=${document.getElementById('run-annotation').checked ? '1' : '0'}`,
    `RUN_STAGE_BIGSCAPE=${document.getElementById('run-bigscape').checked ? '1' : '0'}`,
    `RUN_STAGE_SUMMARY=${document.getElementById('run-summary').checked ? '1' : '0'}`,
    `RUN_CLINKER=${document.getElementById('run-clinker').checked ? '1' : '0'}`,
    `RUN_FIGURES=${document.getElementById('run-figures').checked ? '1' : '0'}`,
    `FIGURES_REQUIRED=${document.getElementById('figures-required').checked ? '1' : '0'}`,
    `RUN_NPLINKER=${document.getElementById('run-nplinker').checked ? '1' : '0'}`,
    `RUN_ECOLOGY_ANALYSIS=${document.getElementById('run-ecology').checked ? '1' : '0'}`,
    `FORCE=${document.getElementById('force-rerun').checked ? '1' : '0'}`,
    `WORKERS=${document.getElementById('workers').value || '2'}`,
    `ANNO_CPUS=${document.getElementById('anno-cpus').value || document.getElementById('cpus').value || '4'}`,
    `ANNOTATION_FALLBACK_ORDER=${document.getElementById('annotation-fallback-order').value.trim()}`,
    `FUNANNOTATE_BUSCO_DB=${document.getElementById('funannotate-busco-db').value.trim() || 'dikarya'}`,
    `FUNANNOTATE_ORGANISM_NAME=${document.getElementById('funannotate-organism-name').value.trim() || 'Fungal_sp'}`,
    `CLINKER_MODE=${document.getElementById('clinker-mode').value}`,
    `PANEL_TARGET_SET=${document.getElementById('panel-target-set').value}`,
    `ECOLOGY_FIELD=${document.getElementById('ecology-field').value.trim()}`,
    `FOCUS_ECOLOGY_LABEL=${document.getElementById('focus-ecology-label').value.trim()}`,
    `AUTO_NORMALIZE_METADATA=${document.getElementById('auto-normalize-metadata').checked ? '1' : '0'}`,
    `METADATA_TSV=${document.getElementById('metadata-tsv').value.trim()}`,
    `CAPTURE_EXTERNAL_ARTIFACTS=${document.getElementById('capture-external-artifacts').checked ? '1' : '0'}`,
    `AUTO_PULL_IMAGES=${document.getElementById('auto-pull-images').value}`,
    `AUTO_BUILD_FUNBGCEX_SIF=${document.getElementById('auto-build-funbgcex-sif').checked ? '1' : '0'}`,
    `AUTO_PULL_BIGSCAPE_SIF=${document.getElementById('auto-pull-bigscape-sif').checked ? '1' : '0'}`,
    `AUTO_DOWNLOAD_PFAM=${document.getElementById('auto-download-pfam').checked ? '1' : '0'}`,
    `AUTO_DOWNLOAD_FASTTREE=${document.getElementById('auto-download-fasttree').checked ? '1' : '0'}`,
    `MIBIG_AUTO_DOWNLOAD=${document.getElementById('mibig-auto-download').checked ? '1' : '0'}`,
    `ATLAS_MIN_RECORDS=${document.getElementById('atlas-min-records').value || '2'}`,
    `SHORTLIST_LIMIT=${document.getElementById('shortlist-limit').value || '12'}`,
    `SHARED_FAMILY_STAGE_LIMIT=${document.getElementById('shared-family-stage-limit').value || '12'}`,
    `SHARED_FAMILY_MIN_RECORDS=${document.getElementById('shared-family-min-records').value || '4'}`,
    `MAX_COMPARATORS=${document.getElementById('max-comparators').value || '50'}`,
    `MAX_SAME_ECOLOGY=${document.getElementById('max-same-ecology').value || '20'}`,
    `MAX_OTHER_ECOLOGY=${document.getElementById('max-other-ecology').value || '20'}`,
    `CLINKER_USE_DOCKER_IMAGE=${document.getElementById('clinker-use-docker-image').checked ? '1' : '0'}`,
    `CLINKER_DOCKER_IMAGE=${document.getElementById('clinker-docker-image').value.trim()}`,
    `CLINKER_DOCKER_DATA_VOLUME=${document.getElementById('clinker-docker-data-volume').value.trim()}`,
    `ATLAS_STAGE_LIMIT=${document.getElementById('clinker-max-regions').value || '12'}`,
    `RUN_MODE=${document.getElementById('nplinker-run-mode').value}`,
    `TARGET_STRAIN=${document.getElementById('target-strain').value.trim()}`,
    `PODP_ID=${document.getElementById('nplinker-podp-id').value.trim()}`,
    `MASSIVE_DATASET_ID=${document.getElementById('massive-dataset-id').value.trim()}`,
    `GNPS_VERSION=${document.getElementById('gnps-version').value}`,
    `AUTO_PULL_NPLINKER_SIF=${document.getElementById('auto-pull-nplinker-sif').checked ? '1' : '0'}`,
    `NPLINKER_BOOTSTRAP_ENV=${document.getElementById('nplinker-bootstrap-env').checked ? '1' : '0'}`,
  ];
  return lines.join('\n') + '\n';
}

function exportEnvProfile() {
  const status = document.getElementById('profile-load-status');
  const projectName = (document.getElementById('project-name').value.trim() || 'clusterweave').replace(/[^a-zA-Z0-9._-]+/g, '_');
  const blob = new Blob([currentEnvProfileText()], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${projectName}.env`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  status.textContent = `Exported profile: ${projectName}.env`;
}

function checkedLabel(id, label, publicDefault = null) {
  const enabled = publicDefault === null
    ? !!document.getElementById(id)?.checked
    : effectiveCheckboxValue(id, publicDefault);
  return { label, enabled };
}

function yesNo(value) {
  return value ? 'Yes' : 'No';
}

function renderStageChips() {
  const chips = [
    checkedLabel('run-genome-prep', 'NCBI prep', true),
    checkedLabel('run-annotation', 'Annotation', true),
    checkedLabel('run-bigscape', 'BiG-SCAPE', true),
    checkedLabel('run-summary', 'Summary', true),
    checkedLabel('run-clinker', 'clinker', true),
    checkedLabel('run-figures', 'Figures', true),
    checkedLabel('run-ecology', 'Ecology'),
    checkedLabel('run-nplinker', 'NPLinker', false),
  ].filter(c => canUseAdminSurfaces() || c.label !== 'NPLinker');
  return `<div class="summary-chips">${chips.map(c => `<span class="summary-chip ${c.enabled ? '' : 'off'}">${c.label}</span>`).join('')}</div>`;
}

function updateRunSummary() {
  const summary = document.getElementById('run-summary-content');
  if (!summary || summary.classList.contains('hidden')) return;
  const manualCount = manualAccessionLines().length;
  const inputLabels = selectedFiles.map(f => f.name);
  if (manualCount) inputLabels.push(`${MANUAL_ACCESSIONS_FILENAME} generated (${manualCount} accession${manualCount === 1 ? '' : 's'})`);
  const shownInputs = inputLabels.slice(0, 3).join(', ');
  const moreCount = Math.max(0, inputLabels.length - 3);
  const selectedLabel = inputLabels.length
    ? `${inputLabels.length} input source(s)${shownInputs ? `: ${shownInputs}` : ''}${moreCount ? ` +${moreCount} more` : ''}`
    : 'No inputs selected';
  const targetGenome = document.getElementById('target-genome').value.trim() || 'None';
  const projectName = document.getElementById('project-name').value.trim() || 'my_project';
  const cpus = effectiveCpuCount();
  const annotationStrategy = effectiveAnnotationStrategy();
  const computeLabel = publicWorkflowLocked()
    ? `Hosted canonical workflow (${cpus} CPU threads)`
    : `${cpus} CPU thread(s), annotation: ${annotationStrategy}`;
  const clinkerMode = publicWorkflowLocked()
    ? 'Hosted runtime'
    : (document.getElementById('clinker-use-docker-image').checked ? 'Docker image' : 'Local/runtime');
  const ecologyRows = currentEcologyMetadataRows();
  const ecologyLabeled = ecologyRows.filter(row => row.primary || row.secondary).length;
  const ecology = document.getElementById('run-ecology').checked
    ? `${ecologyRows.length} input row${ecologyRows.length === 1 ? '' : 's'}, ${ecologyLabeled} labeled`
    : 'Disabled';
  const clinkerLimit = effectiveCheckboxValue('run-clinker', true)
    ? (document.getElementById('clinker-max-regions').value || '0')
    : 'Off';
  const artifactsLabel = publicWorkflowLocked()
    ? 'Managed by the hosted service'
    : `Capture artifacts: ${yesNo(document.getElementById('capture-external-artifacts').checked)}, auto-normalize metadata: ${yesNo(document.getElementById('auto-normalize-metadata').checked)}`;

  summary.innerHTML = `
    <div class="summary-item">
      <div class="summary-label">Project</div>
      <div class="summary-value">${escapeHtml(projectName)}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">Input sources</div>
      <div class="summary-value">${escapeHtml(selectedLabel)}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">Compute</div>
      <div class="summary-value">${escapeHtml(computeLabel)}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">Target genome / accession ID</div>
      <div class="summary-value">${escapeHtml(targetGenome)}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">Workflow stages</div>
      <div class="summary-value">${renderStageChips()}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">clinker runtime</div>
      <div class="summary-value">${escapeHtml(clinkerMode)}; atlas panels: ${escapeHtml(clinkerLimit)}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">Ecology</div>
      <div class="summary-value">${escapeHtml(ecology)}</div>
    </div>
    <div class="summary-item">
      <div class="summary-label">Artifacts and metadata</div>
      <div class="summary-value">${escapeHtml(artifactsLabel)}</div>
    </div>
  `;
}

function stageAvailable(stage) {
  const stages = runtimeCapabilities && runtimeCapabilities.stages;
  if (!stages || !stages[stage]) return true;
  return !!stages[stage].available;
}

function stageUnavailableReason(stage) {
  const stages = runtimeCapabilities && runtimeCapabilities.stages;
  const payload = stages && stages[stage];
  if (!payload) return '';
  const missing = Array.isArray(payload.missing) && payload.missing.length
    ? ` Missing: ${payload.missing.join(', ')}.`
    : '';
  return `${payload.detail || 'Runtime unavailable.'}${missing}`;
}

function renderRuntimeBanner() {
  const banner = document.getElementById('runtime-banner');
  if (!banner) return;
  if (!runtimeCapabilities) {
    banner.className = 'runtime-banner hidden';
    banner.textContent = '';
    return;
  }
  const unavailable = ['annotation','bigscape','clinker','nplinker']
    .filter(stage => !stageAvailable(stage));
  const mode = runtimeCapabilities.mode || 'unknown';
  const engine = runtimeCapabilities.engine || 'auto';
  if (!unavailable.length) {
    banner.className = 'runtime-banner ok';
    banner.textContent = `Runtime ready: ${mode} using ${engine}.`;
    return;
  }
  banner.className = 'runtime-banner warn';
  banner.textContent = `Runtime mode ${mode} using ${engine}: ${unavailable.join(', ')} unavailable. ${unavailable.map(stageUnavailableReason).join(' ')}`;
}

function currentStageControlJob() {
  return {
    settings: {
      run_annotation: effectiveCheckboxValue('run-annotation', true),
      run_bigscape: effectiveCheckboxValue('run-bigscape', true),
      run_summary: effectiveCheckboxValue('run-summary', true),
      run_crosswalk: effectiveCheckboxValue('run-summary', true),
      run_clinker: effectiveCheckboxValue('run-clinker', true),
      run_figures: effectiveCheckboxValue('run-figures', true),
      run_nplinker: effectiveCheckboxValue('run-nplinker', false),
    },
  };
}

function syncControlState() {
  applyPublicCanonicalDefaults();
  const runBigscape = document.getElementById('run-bigscape');
  const runSummary = document.getElementById('run-summary');
  const runClinker = document.getElementById('run-clinker');
  const runEcology = document.getElementById('run-ecology');
  const runNplinker = document.getElementById('run-nplinker');

  const stageControls = [
    ['run-annotation', 'annotation'],
    ['run-bigscape', 'bigscape'],
    ['run-clinker', 'clinker'],
    ['run-nplinker', 'nplinker'],
  ];
  for (const [id, stage] of stageControls) {
    const el = document.getElementById(id);
    if (!el || el.dataset.publicLocked === 'true') continue;
    const available = stageAvailable(stage);
    el.disabled = !available;
    el.title = available ? '' : stageUnavailableReason(stage);
    if (!available) el.checked = false;
  }

  if (!runBigscape.checked && runSummary.checked) {
    // Summary can still run from existing outputs, so keep it enabled.
  }

  const clinkerFields = [
    'clinker-max-regions',
    'execute-clinker',
    'clinker-mode',
    'panel-target-set',
    'clinker-use-docker-image',
    'clinker-docker-image',
    'clinker-docker-data-volume',
  ];
  for (const id of clinkerFields) {
    const el = document.getElementById(id);
    if (el) el.disabled = !runClinker.checked;
  }

  const ecologyFields = ['ecology-field', 'focus-ecology-label', 'metadata-tsv', 'auto-normalize-metadata'];
  for (const id of ecologyFields) {
    const el = document.getElementById(id);
    if (el) el.disabled = !runEcology.checked;
  }
  syncEcologyMetadataPanel();

  const nplinkerFields = [
    'nplinker-run-mode',
    'target-strain',
    'nplinker-podp-id',
    'massive-dataset-id',
    'gnps-version',
    'auto-pull-nplinker-sif',
    'nplinker-bootstrap-env',
  ];
  for (const id of nplinkerFields) {
    const el = document.getElementById(id);
    if (el) el.disabled = !runNplinker.checked;
  }

  updateRunSummary();
  renderRuntimeBanner();
  if (!activeJobId) initializeStageState(currentStageControlJob());
}

function applyPreset(name) {
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.type === 'checkbox') el.checked = !!val;
    else el.value = String(val);
  };

  if (name === 'beginner') {
    set('run-genome-prep', true);
    set('run-annotation', true);
    set('run-bigscape', false);
    set('run-summary', true);
    set('run-clinker', true);
    set('run-figures', true);
    set('run-nplinker', false);
    set('figures-required', false);
    set('clinker-max-regions', 6);
    set('bigscape-mix-mode', 1);
  } else if (name === 'full') {
    set('run-genome-prep', true);
    set('run-annotation', true);
    set('run-bigscape', true);
    set('run-summary', true);
    set('run-clinker', true);
    set('run-figures', true);
    set('figures-required', false);
    set('clinker-max-regions', 24);
    set('bigscape-mix-mode', 1);
  } else if (name === 'repro') {
    set('run-genome-prep', true);
    set('run-annotation', true);
    set('run-bigscape', true);
    set('run-summary', true);
    set('run-clinker', true);
    set('run-figures', true);
    set('figures-required', false);
    set('capture-external-artifacts', true);
    set('auto-normalize-metadata', true);
  } else {
    set('run-genome-prep', true);
    set('run-annotation', true);
    set('run-bigscape', true);
    set('run-summary', true);
    set('run-clinker', true);
    set('run-figures', true);
    set('run-nplinker', false);
    set('figures-required', false);
    set('clinker-max-regions', 12);
    set('bigscape-mix-mode', 1);
  }
  syncControlState();
}

// ── File selection ─────────────────────────────────────────────────────────
const dropZone  = document.getElementById('drop-zone');
const fileInput = document.getElementById('file-input');
const manualAccessionsInput = document.getElementById('manual-accessions');
const MANUAL_ACCESSIONS_FILENAME = 'manual_accessions.txt';
const NCBI_ASSEMBLY_ACCESSION_RE = /^(?:GCA|GCF)_\d{9}\.\d+$/i;
const NCBI_ASSEMBLY_ACCESSION_HELP = 'Use current fungal NCBI assembly accessions like GCA_000011425.1 or GCA_030770425.1.';
const PUBLIC_FILE_EXTENSIONS = new Set(['gbk','gb','gbff','fasta','fa','fna','fsa','txt']);
const ADMIN_FILE_EXTENSIONS = new Set(['gbk','gb','gbff','fasta','fa','fna','fsa','txt','tsv','csv','json','gff','gff3','faa','mgf','zip']);
const PUBLIC_FASTA_EXTENSIONS = new Set(['fasta','fa','fna','fsa']);
const PUBLIC_GENBANK_EXTENSIONS = new Set(['gb','gbk','gbff']);
const PUBLIC_GENOME_STEM_RE = /^[A-Za-z0-9._-]{1,120}$/;
const PUBLIC_NUCLEOTIDE_CHARS = new Set('ACGTRYSWKMBDHVNU-.'.split(''));
const ECOLOGY_LABELS = [
  'soil',
  'plant_associated',
  'endophyte',
  'mycorrhiza',
  'plant_pathogen',
  'saprotroph',
  'marine',
  'freshwater',
  'lichen_associated',
  'insect_associated',
  'animal_associated',
  'human_associated',
  'food_fermentation',
  'unknown',
  'other',
];

fileInput.addEventListener('change', async () => {
  await addFiles([...fileInput.files]);
  fileInput.value = '';
});
manualAccessionsInput.addEventListener('input', () => {
  updateManualAccessionsStatus();
  renderFileList();
});
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
dropZone.addEventListener('keydown', e => {
  if (!['Enter', ' '].includes(e.key)) return;
  e.preventDefault();
  fileInput.click();
});
dropZone.addEventListener('drop', async e => {
  e.preventDefault();
  dropZone.classList.remove('drag-over');
  await addFiles([...e.dataTransfer.files]);
});

function parseAccessionText(raw) {
  const seen = new Set();
  const accessions = [];
  const invalid = [];
  let duplicateCount = 0;
  raw.split(/\r?\n/).forEach((line, lineIndex) => {
    const cleanLine = line.trim();
    if (!cleanLine) return;
    if (/^accession$/i.test(cleanLine)) {
      invalid.push({ token: cleanLine, line: lineIndex + 1, kind: 'header' });
      return;
    }
    if (/[\s,;]+/.test(cleanLine)) {
      invalid.push({ token: cleanLine, line: lineIndex + 1, kind: 'multiple' });
      return;
    }
    const accession = cleanLine.toUpperCase();
    if (!NCBI_ASSEMBLY_ACCESSION_RE.test(accession)) {
      invalid.push({ token: cleanLine, line: lineIndex + 1, kind: 'invalid' });
      return;
    }
    if (seen.has(accession)) {
      duplicateCount += 1;
      return;
    }
    seen.add(accession);
    accessions.push(accession);
  });
  return { accessions, invalid, duplicateCount };
}

function parseManualAccessions() {
  return parseAccessionText(manualAccessionsInput ? manualAccessionsInput.value : '');
}

function mergedAcceptedAccessions() {
  const seen = new Set();
  const merged = [];
  const add = (accession) => {
    const normalized = String(accession || '').trim().toUpperCase();
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    merged.push(normalized);
  };
  acceptedManualAccessions.forEach(add);
  accessionFileSources.forEach(source => source.accessions.forEach(add));
  return merged;
}

function manualAccessionLines() {
  return mergedAcceptedAccessions();
}

function manualAccessionErrorMessage(parsed) {
  if (!parsed.invalid.length) return '';
  const first = parsed.invalid[0];
  const more = parsed.invalid.length > 1 ? ` and ${parsed.invalid.length - 1} more` : '';
  if (first.kind === 'multiple') {
    return `Line ${first.line} has multiple values${more}. Enter one NCBI assembly accession per line.`;
  }
  if (first.kind === 'header') {
    return `Header row "accession" on line ${first.line} is not allowed. Enter one NCBI assembly accession per line.`;
  }
  return `Invalid accession "${first.token}" on line ${first.line}${more}. ${NCBI_ASSEMBLY_ACCESSION_HELP}`;
}

function publicQuotaLimits() {
  return {
    max_accessions: Number(publicQuota.max_accessions) || 25,
    max_genome_files: Number(publicQuota.max_genome_files) || 25,
    max_upload_file_mb: Number(publicQuota.max_upload_file_mb) || 250,
    max_upload_total_mb: Number(publicQuota.max_upload_total_mb) || 1024,
  };
}

function formatQuotaMb(value) {
  const mb = Number(value) || 0;
  if (mb >= 1024 && mb % 1024 === 0) return `${mb / 1024} GB`;
  return `${mb} MB`;
}

function genomeFileCheckKey(file) {
  return `${file.name}|${file.size}|${file.lastModified || 0}`;
}

function publicGenomeStem(name) {
  return String(name || '').replace(/\.(gbk|gb|gbff|fasta|fa|fna|fsa)$/i, '').trim();
}

function classifyClientFastaText(name, text) {
  const lines = String(text || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (!lines.length) return { readiness: 'invalid', reason: `FASTA genome ${name} is empty.` };
  if (!lines[0].startsWith('>')) {
    return { readiness: 'invalid', reason: `FASTA genome ${name} must start with a FASTA header beginning with >.` };
  }
  const sequenceChars = [];
  let sequenceLines = 0;
  lines.forEach((line) => {
    if (line.startsWith('>')) return;
    const clean = line.replace(/\s+/g, '').toUpperCase();
    if (!clean) return;
    sequenceLines += 1;
    sequenceChars.push(...clean);
  });
  if (!sequenceLines || !sequenceChars.length) {
    return { readiness: 'invalid', reason: `FASTA genome ${name} needs at least one nucleotide sequence line.` };
  }
  const nucleotideCount = sequenceChars.filter(char => PUBLIC_NUCLEOTIDE_CHARS.has(char)).length;
  if (nucleotideCount / sequenceChars.length < 0.85) {
    return { readiness: 'invalid', reason: 'Looks like protein FASTA or arbitrary text; upload a nucleotide fungal genome assembly FASTA.' };
  }
  return {
    readiness: 'raw_fasta_requires_annotation',
    reason: 'Nucleotide FASTA accepted; funannotate must predict CDS/protein translations before downstream BGC tools can run, and may fail if the assembly is not annotatable.',
  };
}

function classifyClientGenbankText(name, text) {
  const raw = String(text || '');
  if (!raw.trim()) return { readiness: 'invalid', reason: `GenBank genome ${name} is empty.` };
  const markers = [
    ['LOCUS', /^LOCUS\s+/m],
    ['FEATURES', /^FEATURES\b/m],
    ['ORIGIN', /^ORIGIN\b/m],
    ['//', /^\/\/\s*$/m],
  ];
  const missing = markers.filter(([, pattern]) => !pattern.test(raw)).map(([label]) => label);
  if (missing.length) {
    return { readiness: 'invalid', reason: `GenBank genome ${name} is missing ${missing.join(', ')}.` };
  }
  const hasCds = /^\s+CDS\b/m.test(raw);
  const hasTranslation = /\/translation\s*=/.test(raw);
  if (hasCds && hasTranslation) {
    return { readiness: 'annotated_genbank_ready', reason: 'Annotated GenBank with CDS translations is ready for antiSMASH and FunBGCeX.' };
  }
  return {
    readiness: 'genbank_requires_fallback_or_translations',
    reason: 'GenBank structure is present, but CDS translations were not detected; submit a same-stem nucleotide FASTA or translated GenBank so funannotate can produce proteins before downstream BGC tools run.',
  };
}

function publicGenomeUploadKind(fileExt) {
  return PUBLIC_FASTA_EXTENSIONS.has(fileExt) ? 'fasta' : 'genbank';
}

function classifyClientGenomeText(file, text) {
  const fileExt = ext(file.name);
  if (PUBLIC_FASTA_EXTENSIONS.has(fileExt)) return classifyClientFastaText(file.name, text);
  if (PUBLIC_GENBANK_EXTENSIONS.has(fileExt)) return classifyClientGenbankText(file.name, text);
  return { readiness: 'invalid', reason: `Unsupported public genome extension .${fileExt}.` };
}

async function cacheGenomeFileCheck(file) {
  const key = genomeFileCheckKey(file);
  if (genomeCheckCache.has(key)) return genomeCheckCache.get(key);
  const quota = publicQuotaLimits();
  if (file.size > quota.max_upload_file_mb * 1048576) {
    const result = { readiness: 'invalid', reason: `File exceeds the ${formatQuotaMb(quota.max_upload_file_mb)} public upload limit.` };
    genomeCheckCache.set(key, result);
    return result;
  }
  try {
    const text = await file.text();
    const result = classifyClientGenomeText(file, text);
    genomeCheckCache.set(key, result);
    return result;
  } catch (err) {
    const result = { readiness: 'invalid', reason: 'Could not read this genome file in the browser.' };
    genomeCheckCache.set(key, result);
    return result;
  }
}

function updateManualAccessionsStatus() {
  const status = document.getElementById('manual-accessions-status');
  if (!status) return;
  const draft = manualAccessionsInput ? manualAccessionsInput.value.trim() : '';
  if (draft) {
    status.textContent = 'Draft ready to screen. Press Add accessions.';
    return;
  }
  const count = manualAccessionLines().length;
  status.innerHTML = count ? `<span class="accession-check">&#10003;</span> ${count} accepted accession${count === 1 ? '' : 's'}` : '';
}

function renderAcceptedAccessions() {
  const list = document.getElementById('accepted-accessions-list');
  if (!list) return;
  const accessions = manualAccessionLines();
  if (!accessions.length) {
    list.innerHTML = '<div class="accession-accepted-empty">No accepted accessions yet.</div>';
    return;
  }
  list.innerHTML = accessions.map(accession => `
    <div class="accession-accepted-row">
      <span class="accession-check">&#10003;</span>
      <span>${escapeHtml(accession)}</span>
    </div>
  `).join('');
}

function normalizeManualAccessions() {
  const parsed = parseManualAccessions();
  if (parsed.invalid.length) {
    const status = document.getElementById('manual-accessions-status');
    if (status) status.textContent = manualAccessionErrorMessage(parsed);
    return;
  }
  if (!parsed.accessions.length) {
    const status = document.getElementById('manual-accessions-status');
    if (status) status.textContent = 'Enter one NCBI assembly accession per line.';
    return;
  }
  const existing = new Set(manualAccessionLines());
  const newAccessions = parsed.accessions.filter(accession => !existing.has(accession));
  acceptedManualAccessions.push(...newAccessions);
  if (manualAccessionsInput) manualAccessionsInput.value = '';
  renderAcceptedAccessions();
  renderFileList();
  const status = document.getElementById('manual-accessions-status');
  if (status) {
    const duplicateText = parsed.duplicateCount ? ` ${parsed.duplicateCount} duplicate${parsed.duplicateCount === 1 ? '' : 's'} skipped.` : '';
    status.innerHTML = newAccessions.length
      ? `<span class="accession-check">&#10003;</span> ${newAccessions.length} accession${newAccessions.length === 1 ? '' : 's'} accepted.${duplicateText}`
      : 'No new accessions added; duplicates already accepted.';
  }
}

function clearManualAccessions() {
  if (manualAccessionsInput) manualAccessionsInput.value = '';
  updateManualAccessionsStatus();
  renderFileList();
}

function clearAcceptedAccessions() {
  acceptedManualAccessions = [];
  accessionFileSources = [];
  renderAcceptedAccessions();
  updateManualAccessionsStatus();
  renderFileList();
}

function clearAcceptedManualAccessions() {
  acceptedManualAccessions = [];
  renderAcceptedAccessions();
  updateManualAccessionsStatus();
  renderFileList();
}

function loadDemoAccessions(event) {
  if (event) event.preventDefault();
  const demoAccessions = ['GCA_000011425.1', 'GCA_030770425.1'];
  acceptedManualAccessions = demoAccessions.slice();
  if (manualAccessionsInput) manualAccessionsInput.value = '';
  const projectName = document.getElementById('project-name');
  if (projectName && (!projectName.value.trim() || projectName.value.trim() === 'my_project')) {
    projectName.value = 'clusterweave_demo';
  }
  renderAcceptedAccessions();
  renderFileList();
  const status = document.getElementById('upload-status');
  if (status) status.textContent = 'Demo accessions accepted; review settings before starting.';
  navigateToSection(event, 'intake', 'manual-accessions');
}

async function addAccessionFileSource(file) {
  if (accessionFileSources.some(source => source.name === file.name)) {
    alert(`Accession list already added: ${file.name}`);
    return false;
  }
  let text = '';
  try {
    text = await file.text();
  } catch (err) {
    alert(`Could not read accession list: ${file.name}`);
    return false;
  }
  const parsed = parseAccessionText(text);
  if (parsed.invalid.length) {
    alert(`Accession list ${file.name}: ${manualAccessionErrorMessage(parsed)}`);
    return false;
  }
  if (!parsed.accessions.length) {
    alert(`Accession list ${file.name} does not contain any accessions.`);
    return false;
  }
  const existing = new Set(manualAccessionLines());
  const newAccessions = parsed.accessions.filter(accession => !existing.has(accession));
  if (!newAccessions.length) {
    alert(`Accession list ${file.name} contains only duplicate accessions already accepted.`);
    return false;
  }
  accessionFileSources.push({
    id: ++accessionFileSourceSerial,
    name: file.name,
    accessions: newAccessions,
  });
  const skipped = parsed.accessions.length - newAccessions.length + parsed.duplicateCount;
  const status = document.getElementById('upload-status');
  if (status) {
    status.textContent = skipped
      ? `${newAccessions.length} accession${newAccessions.length === 1 ? '' : 's'} accepted from ${file.name}; ${skipped} duplicate${skipped === 1 ? '' : 's'} skipped.`
      : `${newAccessions.length} accession${newAccessions.length === 1 ? '' : 's'} accepted from ${file.name}.`;
  }
  return true;
}

function inputCheckLevel(readiness) {
  if (readiness === 'invalid') return 'blocked';
  if (readiness === 'annotated_genbank_ready') return 'ready';
  return 'warning';
}

function inputCheckBadge(level) {
  if (level === 'ready') return 'Ready';
  if (level === 'warning') return 'Warning';
  return 'Blocked';
}

function addInputCheckRow(rows, level, type, label, reason) {
  rows.push({ level, type, label, reason });
}

function renderInputCheckerRow(row) {
  return `
    <div class="input-check-row ${escapeHtml(row.level)}">
      <div class="input-check-badge">${escapeHtml(inputCheckBadge(row.level))}</div>
      <div class="input-check-source">
        <div class="input-check-type">${escapeHtml(row.type)}</div>
        <div class="input-check-label">${escapeHtml(row.label)}</div>
      </div>
      <div class="input-check-reason">${escapeHtml(row.reason)}</div>
    </div>`;
}

function updateInputCheckerLimits(quota) {
  const limits = document.getElementById('input-checker-limits');
  if (!limits) return;
  limits.textContent = `Limits: ${quota.max_accessions} accessions, ${quota.max_genome_files} genome files, ${formatQuotaMb(quota.max_upload_file_mb)} per file, ${formatQuotaMb(quota.max_upload_total_mb)} total`;
}

function renderInputChecker() {
  const list = document.getElementById('input-checker-list');
  const quota = publicQuotaLimits();
  updateInputCheckerLimits(quota);
  const rows = [];
  const draft = manualAccessionsInput ? manualAccessionsInput.value.trim() : '';
  const acceptedAccessions = manualAccessionLines();
  const maxFileBytes = quota.max_upload_file_mb * 1048576;
  const maxTotalBytes = quota.max_upload_total_mb * 1048576;
  const publicGenomeFiles = selectedFiles.filter(file => {
    const fileExt = ext(file.name);
    return PUBLIC_FASTA_EXTENSIONS.has(fileExt) || PUBLIC_GENBANK_EXTENSIONS.has(fileExt);
  });
  const totalUploadBytes = selectedFiles.reduce((sum, file) => sum + (Number(file.size) || 0), 0);

  if (draft) {
    const parsed = parseManualAccessions();
    const label = parsed.accessions.length
      ? `${parsed.accessions.length} draft accession${parsed.accessions.length === 1 ? '' : 's'}`
      : 'Manual accession draft';
    const reason = parsed.invalid.length
      ? manualAccessionErrorMessage(parsed)
      : 'Draft accessions must be accepted before this run can start.';
    addInputCheckRow(rows, 'blocked', 'NCBI accession', label, reason);
  }

  acceptedManualAccessions.forEach((accession) => {
    addInputCheckRow(rows, 'ready', 'NCBI accession', accession, 'Accepted fungal assembly accession; NCBI genome FASTA is checked before job creation and can route through funannotate if translations are missing.');
  });
  accessionFileSources.forEach((source) => {
    source.accessions.forEach((accession) => {
      addInputCheckRow(rows, 'ready', 'NCBI accession', accession, `Accepted from ${source.name}; NCBI fungal assembly metadata is checked before job creation, then FASTA can feed funannotate if translations are missing.`);
    });
  });

  const genomeStemKinds = new Map();
  selectedFiles.forEach((file) => {
    const fileExt = ext(file.name);
    const isPublicGenome = PUBLIC_FASTA_EXTENSIONS.has(fileExt) || PUBLIC_GENBANK_EXTENSIONS.has(fileExt);
    const stem = publicGenomeStem(file.name);
    if (!isPublicGenome || !stem || !PUBLIC_GENOME_STEM_RE.test(stem)) return;
    const stemKey = stem.toLowerCase();
    const kinds = genomeStemKinds.get(stemKey) || new Set();
    kinds.add(publicGenomeUploadKind(fileExt));
    genomeStemKinds.set(stemKey, kinds);
  });

  const seenStemKinds = new Map();
  selectedFiles.forEach((file) => {
    const fileExt = ext(file.name);
    const isPublicGenome = PUBLIC_FASTA_EXTENSIONS.has(fileExt) || PUBLIC_GENBANK_EXTENSIONS.has(fileExt);
    if (!isPublicGenome) {
      const level = canUseAdminSurfaces() ? 'ready' : 'blocked';
      const reason = canUseAdminSurfaces()
        ? 'Admin/local auxiliary input; not part of public fungal-genome intake.'
        : 'This file type is not supported by the public fungal-genome intake.';
      addInputCheckRow(rows, level, 'Auxiliary file', file.name, reason);
      return;
    }

    const stem = publicGenomeStem(file.name);
    const uploadKind = publicGenomeUploadKind(fileExt);
    const check = genomeCheckCache.get(genomeFileCheckKey(file)) || {
      readiness: 'invalid',
      reason: 'Genome content check has not completed yet.',
    };
    let level = inputCheckLevel(check.readiness);
    let reason = check.reason;

    if (file.size > maxFileBytes) {
      level = 'blocked';
      reason = `File exceeds the ${formatQuotaMb(quota.max_upload_file_mb)} public upload limit.`;
    } else if (!stem || !PUBLIC_GENOME_STEM_RE.test(stem)) {
      level = 'blocked';
      reason = 'Filename stem must use 1-120 letters, numbers, dots, underscores, or hyphens; avoid spaces, parentheses, slashes, and shell-like characters.';
    } else {
      const stemKey = stem.toLowerCase();
      const seenKinds = seenStemKinds.get(stemKey) || new Set();
      if (seenKinds.has(uploadKind)) {
        level = 'blocked';
        reason = `Duplicate ${uploadKind.toUpperCase()} file for this genome stem; submit at most one FASTA and one GenBank file per assembly.`;
      } else {
        seenKinds.add(uploadKind);
        seenStemKinds.set(stemKey, seenKinds);
      }
      if (check.readiness === 'genbank_requires_fallback_or_translations') {
        const pairedKinds = genomeStemKinds.get(stemKey) || new Set();
        if (pairedKinds.has('fasta')) {
          level = 'warning';
          reason = 'GenBank lacks CDS translations; same-stem FASTA is present, so funannotate can create proteins before downstream BGC tools run.';
        } else {
          level = 'blocked';
          reason = `GenBank lacks CDS translations and no same-stem FASTA was submitted. Upload translated GenBank or pair this file with ${stem}.fna for funannotate.`;
        }
      }
    }

    const type = PUBLIC_GENBANK_EXTENSIONS.has(fileExt) ? 'GenBank genome' : 'FASTA genome';
    addInputCheckRow(rows, level, type, stem || file.name, reason);
  });

  if (acceptedAccessions.length > quota.max_accessions) {
    addInputCheckRow(rows, 'blocked', 'Quota', `${acceptedAccessions.length} accessions`, `Public runs accept at most ${quota.max_accessions} NCBI assembly accessions.`);
  }
  if (publicGenomeFiles.length > quota.max_genome_files) {
    addInputCheckRow(rows, 'blocked', 'Quota', `${publicGenomeFiles.length} genome files`, `Public runs accept at most ${quota.max_genome_files} genome files.`);
  }
  if (totalUploadBytes > maxTotalBytes) {
    addInputCheckRow(rows, 'blocked', 'Quota', fmt_size(totalUploadBytes), `Total upload size exceeds the ${formatQuotaMb(quota.max_upload_total_mb)} public job limit.`);
  }

  if (list) {
    list.innerHTML = rows.length
      ? rows.map(renderInputCheckerRow).join('')
      : '<div class="input-check-empty">No accepted intake sources yet.</div>';
  }

  return {
    blocked: rows.filter(row => row.level === 'blocked').length,
    warning: rows.filter(row => row.level === 'warning').length,
    ready: rows.filter(row => row.level === 'ready').length,
  };
}

async function addFiles(files) {
  const allowed = canUseAdminSurfaces() ? ADMIN_FILE_EXTENSIONS : PUBLIC_FILE_EXTENSIONS;
  const allowedCopy = canUseAdminSurfaces()
    ? '.gbk, .gb, .gbff, .fasta, .fa, .fna, .fsa, .txt, .tsv, .csv, .json, .gff, .gff3, .faa, .mgf, .zip'
    : '.gbk, .gb, .gbff, .fasta, .fa, .fna, .fsa, .txt';
  for (const f of files) {
    const fileExt = ext(f.name);
    if (!allowed.has(fileExt)) {
      alert(`Unsupported file type: ${f.name}\nAllowed: ${allowedCopy}`);
      continue;
    }
    if (fileExt === 'txt') {
      await addAccessionFileSource(f);
      continue;
    }
    if (!selectedFiles.find(x => x.name === f.name)) {
      if (PUBLIC_FASTA_EXTENSIONS.has(fileExt) || PUBLIC_GENBANK_EXTENSIONS.has(fileExt)) await cacheGenomeFileCheck(f);
      selectedFiles.push(f);
    }
  }
  renderAcceptedAccessions();
  renderFileList();
}

function removeFile(index) {
  selectedFiles.splice(index, 1);
  renderFileList();
}

function removeAccessionFileSource(index) {
  accessionFileSources.splice(index, 1);
  renderAcceptedAccessions();
  renderFileList();
}

function renderFileList() {
  const list = document.getElementById('file-list');
  const btn  = document.getElementById('run-btn');
  const stat = document.getElementById('upload-status');
  const accessionLines = manualAccessionLines();
  const manualItem = acceptedManualAccessions.length ? `
    <div class="file-item">
      <span class="file-icon" aria-hidden="true"></span>
      <span class="file-name">Manual entry &rarr; ${MANUAL_ACCESSIONS_FILENAME}</span>
      <span class="file-size">${acceptedManualAccessions.length} accession${acceptedManualAccessions.length === 1 ? '' : 's'}</span>
      <button class="file-remove" onclick="clearAcceptedManualAccessions()" title="Remove">✕</button>
    </div>` : '';
  const accessionFileItems = accessionFileSources.map((source, idx) => `
    <div class="file-item">
      <span class="file-icon" aria-hidden="true"></span>
      <span class="file-name">${escapeHtml(source.name)} &rarr; ${MANUAL_ACCESSIONS_FILENAME}</span>
      <span class="file-size">${source.accessions.length} accession${source.accessions.length === 1 ? '' : 's'}</span>
      <button class="file-remove" onclick="removeAccessionFileSource(${idx})" title="Remove">✕</button>
    </div>`).join('');
  list.innerHTML = selectedFiles.map((f, idx) => `
    <div class="file-item">
      <span class="file-icon" aria-hidden="true"></span>
      <span class="file-name">${escapeHtml(f.name)}</span>
      <span class="file-size">${fmt_size(f.size)}</span>
      <button class="file-remove" onclick="removeFile(${idx})" title="Remove">✕</button>
    </div>`).join('') + manualItem + accessionFileItems;
  const draftPending = !!(manualAccessionsInput && manualAccessionsInput.value.trim());
  const inputSourceCount = selectedFiles.length + (accessionLines.length ? 1 : 0);
  const dataUseAck = document.getElementById('data-use-ack');
  const ackMissing = !canUseAdminSurfaces() && dataUseAck && !dataUseAck.checked;
  const checkerState = renderInputChecker();
  const checkerBlocked = !canUseAdminSurfaces() && checkerState.blocked > 0;
  btn.disabled = inputSourceCount === 0 || draftPending || ackMissing || checkerBlocked;
  if (draftPending) {
    stat.textContent = 'Press Add accessions to accept the draft before starting.';
  } else if (inputSourceCount && ackMissing) {
    stat.textContent = 'Confirm the data-use statement before starting.';
  } else if (inputSourceCount && checkerBlocked) {
    stat.textContent = `${checkerState.blocked} blocked input source${checkerState.blocked === 1 ? '' : 's'} must be fixed before starting.`;
  } else if (inputSourceCount && checkerState.warning) {
    stat.textContent = `${inputSourceCount} input source(s) ready for workflow with ${checkerState.warning} warning${checkerState.warning === 1 ? '' : 's'}`;
  } else {
    stat.textContent = inputSourceCount ? `${inputSourceCount} input source(s) ready for workflow` : '';
  }
  updateManualAccessionsStatus();
  syncEcologyMetadataPanel();
  updateRunSummary();
}

function genomeStemFromName(name) {
  return name.replace(/\.(gbk|gb|gbff|fasta|fa|fna|fsa)$/i, '');
}

function isGenomeUploadName(name) {
  return /\.(gbk|gb|gbff|fasta|fa|fna|fsa)$/i.test(name);
}

function ecologyInputRows() {
  const seen = new Set();
  const rows = [];
  const addRow = (input, kind, accession = '') => {
    const key = String(input || '').trim();
    if (!key || seen.has(key)) return;
    seen.add(key);
    rows.push({ key, kind, accession });
  };
  manualAccessionLines().forEach(accession => addRow(accession, 'NCBI accession', accession));
  selectedFiles.forEach((file) => {
    if (!isGenomeUploadName(file.name)) return;
    addRow(genomeStemFromName(file.name), 'Genome file', '');
  });
  return rows;
}

function collectEcologyRowValues() {
  const values = new Map();
  document.querySelectorAll('#metadata-table-body tr[data-ecology-key]').forEach((row) => {
    const key = row.dataset.ecologyKey || '';
    if (!key) return;
    values.set(key, {
      primary: row.querySelector('.metadata-primary')?.value || '',
      primaryOther: row.querySelector('.metadata-primary-other')?.value.trim() || '',
      secondary: row.querySelector('.metadata-secondary')?.value || '',
      secondaryOther: row.querySelector('.metadata-secondary-other')?.value.trim() || '',
    });
  });
  return values;
}

function ecologySelectOptions(selected) {
  const all = [''].concat(ECOLOGY_LABELS);
  return all.map((value) => {
    const label = value || 'blank';
    return `<option value="${escapeHtml(value)}" ${value === selected ? 'selected' : ''}>${escapeHtml(label)}</option>`;
  }).join('');
}

function ecologyLabelCellHtml(key, field, saved = {}) {
  const selected = saved[field] || '';
  const otherValue = saved[`${field}Other`] || '';
  const selectClass = field === 'primary' ? 'metadata-primary' : 'metadata-secondary';
  const otherClass = field === 'primary' ? 'metadata-primary-other' : 'metadata-secondary-other';
  const otherHidden = selected === 'other' ? '' : ' hidden';
  return `
    <div class="ecology-label-cell">
      <select class="${selectClass}" data-field="${field}" onchange="handleEcologyLabelChange(this)">
        ${ecologySelectOptions(selected)}
      </select>
      <input type="text" class="ecology-other-input ${otherClass}${otherHidden}" maxlength="40" value="${escapeHtml(otherValue)}" placeholder="Custom label" oninput="updateEcologyLabelStatus(); updateRunSummary()" />
    </div>`;
}

function renderEcologyMetadataRows(inputRows, savedValues) {
  const body = document.getElementById('metadata-table-body');
  if (!body) return;
  if (!inputRows.length) {
    body.innerHTML = '<tr><td colspan="3" class="text-muted">Add NCBI accessions or genome files to label ecology.</td></tr>';
    return;
  }
  body.innerHTML = inputRows.map((row) => {
    const saved = savedValues.get(row.key) || {};
    return `
      <tr data-ecology-key="${escapeHtml(row.key)}" data-accession="${escapeHtml(row.accession)}">
        <td>
          <span class="ecology-input-key">${escapeHtml(row.key)}</span>
          <span class="ecology-input-kind">${escapeHtml(row.kind)}</span>
        </td>
        <td>${ecologyLabelCellHtml(row.key, 'primary', saved)}</td>
        <td>${ecologyLabelCellHtml(row.key, 'secondary', saved)}</td>
      </tr>`;
  }).join('');
}

function handleEcologyLabelChange(el) {
  const row = el.closest('tr');
  if (!row) return;
  const field = el.dataset.field || '';
  const other = row.querySelector(field === 'primary' ? '.metadata-primary-other' : '.metadata-secondary-other');
  if (other) other.classList.toggle('hidden', el.value !== 'other');
  updateEcologyLabelStatus();
  updateRunSummary();
}

function ecologyLabelValue(row, field) {
  const select = row.querySelector(field === 'primary' ? '.metadata-primary' : '.metadata-secondary');
  const selected = select ? select.value : '';
  if (selected !== 'other') return selected;
  const other = row.querySelector(field === 'primary' ? '.metadata-primary-other' : '.metadata-secondary-other');
  return (other && other.value.trim()) || 'other';
}

function currentEcologyMetadataRows() {
  return [...document.querySelectorAll('#metadata-table-body tr[data-ecology-key]')].map((row) => ({
    input: row.dataset.ecologyKey || '',
    accession: row.dataset.accession || '',
    primary: ecologyLabelValue(row, 'primary'),
    secondary: ecologyLabelValue(row, 'secondary'),
  })).filter(row => row.input);
}

function updateEcologyLabelStatus() {
  const status = document.getElementById('ecology-label-status');
  if (!status) return;
  const enabled = !!document.getElementById('run-ecology')?.checked;
  if (!enabled) {
    status.textContent = 'Optional';
    return;
  }
  const rows = currentEcologyMetadataRows();
  if (!rows.length) {
    status.textContent = 'Add accessions or genome files to create label rows.';
    return;
  }
  const unlabeled = rows.filter(row => !row.primary && !row.secondary).length;
  if (unlabeled) {
    status.textContent = `${unlabeled} unlabeled input${unlabeled === 1 ? '' : 's'}; unlabeled inputs may reduce ranking usefulness.`;
    return;
  }
  status.textContent = `${rows.length} ecology label row${rows.length === 1 ? '' : 's'} ready.`;
}

function syncEcologyMetadataPanel() {
  const enabled = !!document.getElementById('run-ecology')?.checked;
  const panel = document.getElementById('ecology-label-panel');
  const body = document.getElementById('ecology-label-body');
  if (panel) panel.classList.toggle('hidden', !enabled);
  if (body) body.classList.toggle('hidden', !enabled);
  const savedValues = collectEcologyRowValues();
  renderEcologyMetadataRows(ecologyInputRows(), savedValues);
  updateEcologyLabelStatus();
}

function metadataProfileText() {
  if (!document.getElementById('run-ecology')?.checked) return '';
  const rows = currentEcologyMetadataRows();
  if (!rows.length) return '';
  const tsvCell = value => String(value || '').replace(/[\t\r\n]+/g, ' ').trim();
  const lines = ['accession\tgenome_id_current\ttaxonomy_id\tgenome_size_mb\tgenome_id_original_if_different\tecofun_primary\tecofun_secondary'];
  for (const row of rows) {
    lines.push([
      tsvCell(row.accession),
      tsvCell(row.input),
      '',
      '',
      '',
      tsvCell(row.primary),
      tsvCell(row.secondary),
    ].join('\t'));
  }
  return lines.join('\n') + '\n';
}

// ── Start Analysis ─────────────────────────────────────────────────────────
async function startAnalysis() {
  const manualLines = manualAccessionLines();
  if (manualAccessionsInput && manualAccessionsInput.value.trim()) {
    document.getElementById('upload-status').textContent = 'Press Add accessions to accept the draft before starting.';
    renderFileList();
    return;
  }
  const dataUseAck = document.getElementById('data-use-ack');
  if (!canUseAdminSurfaces() && dataUseAck && !dataUseAck.checked) {
    document.getElementById('upload-status').textContent = 'Confirm the data-use statement before starting.';
    renderFileList();
    return;
  }
  if (selectedFiles.length === 0 && manualLines.length === 0) return;
  const checkerState = renderInputChecker();
  if (!canUseAdminSurfaces() && checkerState.blocked > 0) {
    document.getElementById('upload-status').textContent = `${checkerState.blocked} blocked input source${checkerState.blocked === 1 ? '' : 's'} must be fixed before starting.`;
    renderFileList();
    return;
  }

  const name = document.getElementById('project-name').value.trim() || 'my_project';
  const publicFixed = publicWorkflowLocked();
  const cpus = effectiveCpuCount();
  const annotationStrategy = effectiveAnnotationStrategy();
  const fallbackOrder = publicFixed
    ? 'funannotate'
    : annotationStrategy === 'auto'
    ? document.getElementById('annotation-fallback-order').value.trim()
    : annotationStrategy;

  const fd = new FormData();
  for (const f of selectedFiles) fd.append('files', f);
  if (manualLines.length) {
    const manualAccessionText = manualLines.join('\n') + '\n';
    fd.append('files', new File([manualAccessionText], MANUAL_ACCESSIONS_FILENAME, { type: 'text/plain' }));
  }
  syncEcologyMetadataPanel();
  const metadataText = metadataProfileText();
  if (metadataText) {
    fd.append('files', new File([metadataText], 'ecofun_metadata_normalized.tsv', { type: 'text/tab-separated-values' }));
  }
  fd.append('project_name', name);
  fd.append('data_use_ack', boolToFlag(canUseAdminSurfaces() || !!document.getElementById('data-use-ack')?.checked));
  fd.append('cpus', cpus);
  fd.append('target_genome', document.getElementById('target-genome').value.trim());
  fd.append('run_ncbi_install', boolToFlag(effectiveCheckboxValue('run-ncbi-install', false)));
  fd.append('run_genome_prep', boolToFlag(effectiveCheckboxValue('run-genome-prep', true)));
  fd.append('run_annotation', boolToFlag(effectiveCheckboxValue('run-annotation', true)));
  fd.append('run_bigscape', boolToFlag(effectiveCheckboxValue('run-bigscape', true)));
  fd.append('run_summary', boolToFlag(effectiveCheckboxValue('run-summary', true)));
  fd.append('run_crosswalk', boolToFlag(effectiveCheckboxValue('run-summary', true)));
  fd.append('run_clinker', boolToFlag(effectiveCheckboxValue('run-clinker', true)));
  fd.append('execute_clinker', boolToFlag(effectiveCheckboxValue('execute-clinker', true)));
  fd.append('run_figures', boolToFlag(effectiveCheckboxValue('run-figures', true)));
  fd.append('figures_required', boolToFlag(effectiveCheckboxValue('figures-required', false)));
  fd.append('run_nplinker', boolToFlag(effectiveCheckboxValue('run-nplinker', false)));
  fd.append('run_ecology_analysis', boolToFlag(document.getElementById('run-ecology').checked));
  fd.append('ecology_field', document.getElementById('ecology-field').value.trim());
  fd.append('focus_ecology_label', document.getElementById('focus-ecology-label').value.trim());
  fd.append('genefinding_mode', annotationStrategy);
  fd.append('bigscape_mix_mode', document.getElementById('bigscape-mix-mode').value);
  fd.append('force', boolToFlag(effectiveCheckboxValue('force-rerun', false)));
  fd.append('workers', document.getElementById('workers').value || '2');
  fd.append('threads', String(cpus));
  fd.append('anno_cpus', publicFixed ? String(cpus) : (document.getElementById('anno-cpus').value || String(cpus)));
  fd.append('annotation_fallback_order', fallbackOrder);
  fd.append('funannotate_busco_db', document.getElementById('funannotate-busco-db').value.trim());
  fd.append('funannotate_organism_name', document.getElementById('funannotate-organism-name').value.trim());
  fd.append('clinker_mode', document.getElementById('clinker-mode').value);
  fd.append('panel_target_set', document.getElementById('panel-target-set').value);
  fd.append('clinker_use_docker_image', boolToFlag(document.getElementById('clinker-use-docker-image').checked));
  fd.append('clinker_docker_image', document.getElementById('clinker-docker-image').value.trim());
  fd.append('clinker_docker_data_volume', document.getElementById('clinker-docker-data-volume').value.trim());
  fd.append('clinker_max_regions', document.getElementById('clinker-max-regions').value || '0');
  fd.append('atlas_stage_limit', document.getElementById('clinker-max-regions').value || '12');
  fd.append('atlas_min_records', document.getElementById('atlas-min-records').value || '2');
  fd.append('shortlist_limit', document.getElementById('shortlist-limit').value || '12');
  fd.append('shared_family_stage_limit', document.getElementById('shared-family-stage-limit').value || '12');
  fd.append('shared_family_min_records', document.getElementById('shared-family-min-records').value || '4');
  fd.append('max_comparators', document.getElementById('max-comparators').value || '50');
  fd.append('max_same_ecology', document.getElementById('max-same-ecology').value || '20');
  fd.append('max_other_ecology', document.getElementById('max-other-ecology').value || '20');
  fd.append('capture_external_artifacts', boolToFlag(document.getElementById('capture-external-artifacts').checked));
  fd.append('auto_normalize_metadata', boolToFlag(document.getElementById('auto-normalize-metadata').checked));
  fd.append('metadata_tsv', document.getElementById('metadata-tsv').value.trim());
  fd.append('auto_pull_images', document.getElementById('auto-pull-images').value);
  fd.append('auto_build_funbgcex_sif', boolToFlag(document.getElementById('auto-build-funbgcex-sif').checked));
  fd.append('auto_pull_bigscape_sif', boolToFlag(document.getElementById('auto-pull-bigscape-sif').checked));
  fd.append('auto_download_pfam', boolToFlag(document.getElementById('auto-download-pfam').checked));
  fd.append('auto_download_fasttree', boolToFlag(document.getElementById('auto-download-fasttree').checked));
  fd.append('mibig_auto_download', boolToFlag(document.getElementById('mibig-auto-download').checked));
  fd.append('nplinker_run_mode', document.getElementById('nplinker-run-mode').value);
  fd.append('target_strain', document.getElementById('target-strain').value.trim());
  fd.append('nplinker_podp_id', document.getElementById('nplinker-podp-id').value.trim());
  fd.append('massive_dataset_id', document.getElementById('massive-dataset-id').value.trim());
  fd.append('gnps_version', document.getElementById('gnps-version').value);
  fd.append('auto_pull_nplinker_sif', boolToFlag(document.getElementById('auto-pull-nplinker-sif').checked));
  fd.append('nplinker_bootstrap_env', boolToFlag(document.getElementById('nplinker-bootstrap-env').checked));
  fd.append('env_overrides', document.getElementById('env-overrides').value);
  const notifyEmail = smtpEnabled ? (document.getElementById('notify-email')?.value.trim() || '') : '';
  if (smtpEnabled) {
    if (notifyEmail) fd.append('notify_email', notifyEmail);
  }

  document.getElementById('run-btn').disabled = true;
  document.getElementById('upload-status').textContent = 'Uploading…';

  try {
    const resp = await apiFetch('api/jobs', { method: 'POST', body: fd }, { kind: 'submit' });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Upload failed');
    }
    const { job_id, read_token, expires_at, result_url } = await resp.json();
    if (read_token) rememberOpenedRun(job_id, read_token, { name, status: 'pending' });
    selectedFiles = [];
    acceptedManualAccessions = [];
    accessionFileSources = [];
    if (manualAccessionsInput) manualAccessionsInput.value = '';
    renderAcceptedAccessions();
    renderFileList();
    document.getElementById('upload-status').textContent = expires_at ? `Run submitted. Results expire ${new Date(expires_at).toLocaleDateString()}.` : 'Run submitted.';
    renderSubmissionConfirmation({
      projectName: name,
      jobId: job_id,
      readToken: read_token || '',
      resultUrl: result_url || '',
      expiresAt: expires_at || '',
      notifyEmail,
    });
    lockSubmittedIntake();
    await loadJob(job_id, true, { readToken: read_token || '' });
    if (canUseAdminSurfaces()) refreshJobHistory();
  } catch (err) {
    document.getElementById('upload-status').textContent = 'Upload failed: ' + err.message;
    document.getElementById('run-btn').disabled = false;
  }
}

// ── Job history ────────────────────────────────────────────────────────────
async function refreshJobHistory() {
  if (!canUseAdminSurfaces()) {
    renderOpenedRuns();
    return;
  }
  if (jobHistoryInFlight) return;
  jobHistoryInFlight = true;
  try {
    const resp = await apiFetch('api/jobs', {}, { kind: 'admin' });
    if (!resp.ok) return;
    const jobs = await resp.json();
    renderJobHistory(jobs);
  } catch (err) {
    console.warn('Job history refresh failed', err);
  } finally {
    jobHistoryInFlight = false;
  }
}

function jobHistoryRenderKey(jobs) {
  return JSON.stringify(jobs.map(j => [
    j.id,
    j.name,
    j.project_name,
    j.status,
    j.stage,
    jobStageSignature(j),
    j.rerun_count || 0,
    Array.isArray(j.result_files) ? j.result_files.length : 0,
    j.id === activeJobId,
  ]));
}

function jobStageSignature(job) {
  return STAGES.map(stage => jobStageEnabled(job, stage.key) ? '1' : '0').join('');
}

function jobProjectName(job) {
  return String((job && (job.project_name || job.name)) || 'Untitled run');
}

function jobStageDisplay(job) {
  const raw = String((job && job.stage) || 'queued').trim();
  if (!raw) return 'Queued';
  const labels = {
    queued: 'Queued',
    complete: 'Complete',
    'Preparing ClusterWeave project layout': 'Project layout',
    'Installing NCBI CLI': 'NCBI CLI install',
    'Preparing genomes from accessions': 'Genome prep',
    'Running canonical ClusterWeave workflow': 'Canonical workflow',
    'Running annotation / BGC detection': 'Annotation / BGC detection',
    'Running BiG-SCAPE family graph': 'BiG-SCAPE family graph',
    'Building summary tables': 'Summary tables',
    'Staging synteny panels': 'Synteny panels',
    'Rendering summary figures': 'Summary figures',
    'Running optional NPLinker follow-up': 'NPLinker follow-up',
  };
  return labels[raw] || raw;
}

function jobCurrentStageKey(job) {
  const status = String((job && job.status) || '').toLowerCase();
  const stage = String((job && job.stage) || '').toLowerCase();
  if (!stage || stage === 'queued' || stage === 'complete' || status === 'success') return null;
  if (/nplinker/.test(stage)) return 'nplinker';
  if (/figure|rendering summary/.test(stage)) return 'figures';
  if (/clinker|synteny/.test(stage)) return 'clinker';
  if (/summary|crosswalk|shortlist|atlas|summarize/.test(stage)) return 'summary';
  if (/big[-\s]?scape|family graph/.test(stage)) return 'bigscape';
  if (/annotation|antismash|funbgcex|canonical clusterweave workflow/.test(stage)) return 'annotation';
  if (/prep|accession|layout|ncbi|installing/.test(stage)) return 'prep';
  return null;
}

function jobStagePipState(job, key) {
  if (!jobStageEnabled(job, key)) return 'disabled';
  const status = String((job && job.status) || 'pending').toLowerCase();
  const current = jobCurrentStageKey(job);
  const currentIdx = current ? stageIndex(current) : -1;
  const pipIdx = stageIndex(key);
  if (status === 'success') return 'done';
  if (status === 'failed') {
    if (current && key === current) return 'failed';
    if (currentIdx >= 0 && pipIdx >= 0 && pipIdx < currentIdx) return 'done';
    return 'upcoming';
  }
  if (status === 'running') {
    if (current && key === current) return 'current';
    if (currentIdx >= 0 && pipIdx >= 0 && pipIdx < currentIdx) return 'done';
  }
  return 'upcoming';
}

function renderJobStagePips(job) {
  const stateLabels = {
    done: 'complete',
    current: 'current',
    failed: 'failed',
    disabled: 'skipped',
    upcoming: 'queued',
  };
  const pips = STAGES.map(stage => {
    const state = jobStagePipState(job, stage.key);
    const label = `${stage.label}: ${stateLabels[state] || state}`;
    return `<span class="job-stage-pip ${state}" role="listitem" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}"></span>`;
  }).join('');
  return `<div class="job-stage-pips" role="list" aria-label="Run stage status">${pips}</div>`;
}

function statusLabel(status) {
  const labels = {
    pending: 'Pending',
    running: 'Running',
    success: 'Complete',
    failed: 'Failed',
  };
  return labels[String(status || '').toLowerCase()] || String(status || 'Pending');
}

function jobCanRerun(job) {
  if (!canUseAdminSurfaces() || !job) return false;
  const status = String(job.status || '').toLowerCase();
  return status === 'success' || status === 'failed';
}

function rerunStageKeysForJob(job) {
  const status = String((job && job.status) || '').toLowerCase();
  return STAGES.filter(stage => {
    if (!jobStageEnabled(job, stage.key) || !rerunStageAllowed(stage.key)) return false;
    if (status === 'success') return true;
    const pipState = jobStagePipState(job, stage.key);
    return pipState !== 'done' && pipState !== 'disabled';
  }).map(stage => stage.key);
}

function rerunPayloadFromStages(stageKeys, force = false) {
  const selected = new Set(stageKeys || []);
  return {
    run_genome_prep: selected.has('prep'),
    run_annotation: selected.has('annotation'),
    run_bigscape: selected.has('bigscape'),
    run_summary: selected.has('summary'),
    run_crosswalk: selected.has('summary'),
    run_clinker: selected.has('clinker'),
    execute_clinker: selected.has('clinker'),
    run_figures: selected.has('figures'),
    run_nplinker: selected.has('nplinker'),
    force,
  };
}

function rerunPayloadHasStages(payload) {
  return ['run_genome_prep', 'run_annotation', 'run_bigscape', 'run_summary', 'run_clinker', 'run_figures', 'run_nplinker']
    .some(key => !!(payload && payload[key]));
}

async function queueJobRerun(jobId, payload) {
  const resp = await apiFetch(`api/jobs/${encodeURIComponent(jobId)}/rerun`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }, { kind: 'admin' });
  if (!resp.ok) {
    const err = await resp.json();
    throw new Error(err.detail || 'Rerun failed');
  }
  return resp.json();
}

async function rerunJobFromHistory(event, jobId) {
  event?.preventDefault?.();
  event?.stopPropagation?.();
  if (!canUseAdminSurfaces()) return;
  const job = jobHistoryById.get(String(jobId || ''));
  if (!job || !jobCanRerun(job)) return;
  const button = event && event.currentTarget ? event.currentTarget : null;
  const originalLabel = button ? button.textContent : '';
  const payload = rerunPayloadFromStages(rerunStageKeysForJob(job));
  if (!rerunPayloadHasStages(payload)) {
    if (button) {
      button.textContent = 'Choose';
      button.title = 'Open the run and choose at least one rerun stage.';
    }
    await loadJob(jobId, true);
    return;
  }
  if (button) {
    button.disabled = true;
    button.textContent = 'Queueing';
  }
  try {
    await queueJobRerun(jobId, payload);
    if (button) button.textContent = 'Queued';
    await loadJob(jobId, true);
    refreshJobHistory();
  } catch (err) {
    if (button) {
      button.disabled = false;
      button.textContent = 'Failed';
      button.title = err.message || String(err);
      window.setTimeout(() => {
        if (button.textContent === 'Failed') button.textContent = originalLabel || 'Rerun';
      }, 2200);
    }
  }
}

function renderJobHistory(jobs) {
  const el = document.getElementById('job-history');
  jobHistoryById = new Map(jobs.map(job => [String(job.id || ''), job]).filter(([id]) => id));
  const renderKey = jobHistoryRenderKey(jobs);
  if (renderKey === lastJobHistoryRenderKey) return;
  lastJobHistoryRenderKey = renderKey;
  if (jobs.length === 0) {
    el.innerHTML = '<div class="empty-state">No runs yet. Add sources and start a workflow above.</div>';
    return;
  }
  el.innerHTML = jobs.map(j => {
    const jobId = String(j.id || '');
    const jsJobId = escapeJsString(jobId);
    const projectName = jobProjectName(j);
    const stageLabel = jobStageDisplay(j);
    const statusText = statusLabel(j.status);
    const cardLabel = `Load run ${projectName}. Status ${statusText}. Current stage ${stageLabel}.`;
    const attrJobId = escapeHtml(jsJobId);
    const rerunCount = Number(j.rerun_count || 0);
    const rerunNote = rerunCount
      ? `<div class="job-card-rerun-note">Rerun ${escapeHtml(String(rerunCount))} / same workspace</div>`
      : '';
    const rerunButton = jobCanRerun(j)
      ? `<button class="job-rerun" type="button" title="Rerun this job" aria-label="Rerun job ${escapeHtml(jobId)}" onclick="rerunJobFromHistory(event,'${attrJobId}')">Rerun</button>`
      : '';
    return `
    <div class="job-card ${jobId === activeJobId ? 'active-job' : ''}" data-job-id="${escapeHtml(jobId)}" role="button" tabindex="0" aria-label="${escapeHtml(cardLabel)}" onclick="loadJob('${attrJobId}')" onkeydown="handleJobCardKeydown(event,'${attrJobId}')">
      <div class="job-card-main">
        <div class="job-card-topline">
          <div class="job-card-name">${escapeHtml(projectName)}</div>
          <div class="job-card-status">${statusBadge(j.status)}</div>
        </div>
        <div class="job-card-id-row">
          <span class="job-card-label">Run</span>
          <span class="job-card-id">${escapeHtml(jobId)}</span>
        </div>
        <div class="job-card-stage" title="${escapeHtml(String(j.stage || 'queued'))}">
          <span class="job-card-stage-label">Stage</span>
          <span class="job-card-stage-text">${escapeHtml(stageLabel)}</span>
        </div>
        ${renderJobStagePips(j)}
        ${rerunNote}
      </div>
      <div class="job-card-actions">
        ${rerunButton}
        <button class="job-delete" type="button" title="Delete run" aria-label="Delete run ${escapeHtml(jobId)}" onclick="deleteJob(event,'${attrJobId}')">&times;</button>
      </div>
    </div>`;
  }).join('');
}

function statusBadge(status) {
  const map = {
    pending: 'pending',
    running: 'running',
    success: 'success',
    failed:  'failed',
  };
  const cls = map[String(status || '').toLowerCase()] || 'pending';
  return `<span class="badge badge-${cls}"><span class="badge-dot"></span>${escapeHtml(statusLabel(status))}</span>`;
}

function handleJobCardKeydown(event, jobId) {
  if (event.target.closest('button')) return;
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    loadJob(jobId);
  }
}

function markActiveJobCard(jobId) {
  document.querySelectorAll('.job-card').forEach(card => {
    card.classList.toggle('active-job', card.dataset.jobId === jobId);
  });
}

function placeWorkflowSpineInLaunch() {
  const launch = document.getElementById('overview');
  const command = document.querySelector('.launch-command');
  const spine = document.getElementById('weavemap');
  if (!launch || !command || !spine) return;
  if (spine.parentElement !== launch) launch.insertBefore(spine, command);
  spine.classList.remove('hidden');
  spine.classList.add('spine-field');
}

function moveWorkflowProgressIntoResults() {
  const live = document.querySelector('.weavemap-live');
  const spine = document.getElementById('weavemap');
  if (spine && live && live.parentElement !== spine) spine.appendChild(live);
  if (spine) spine.classList.remove('spine-live-detached');
  const helix = document.getElementById('weavemap-helix');
  if (helix) delete helix.dataset.rendered;
  renderWeaveHelix(activeJobMeta);
}

function setResultsLoaded(loaded) {
  moveWorkflowProgressIntoResults(loaded);
  if (!loaded) {
    resultDashboardOpen = false;
    activeResultArtifacts = null;
    setResultFocusMode('overview');
    document.body.dataset.resultsDashboard = 'closed';
  }
  document.getElementById('results-empty-state')?.classList.toggle('hidden', loaded);
  document.getElementById('workflow-progress-panel')?.classList.toggle('hidden', !loaded);
  document.querySelectorAll('.results-loaded-only').forEach(el => el.classList.toggle('hidden', !loaded));
  if (loaded) updateResultDashboardVisibility(activeJobMeta?.status || '');
  else document.querySelectorAll('.result-dashboard-surface').forEach(el => el.classList.add('hidden'));
  updateArchiveButton();
}

function showEmptyResults() {
  activeStageState = null;
  document.body.dataset.workflowState = 'idle';
  document.body.dataset.existingRunLoaded = 'false';
  lastSubmittedRun = null;
  activeResultCategory = 'figures';
  activeResultFiles = [];
  activeResultArtifacts = null;
  setResultFocusMode('overview');
  document.body.dataset.resultsDashboard = 'closed';
  document.body.dataset.managementView = 'closed';
  dismissSubmissionConfirmation();
  resetWeaveActivity();
  resetStages(currentStageControlJob());
  setResultsLoaded(false);
  const badge = document.getElementById('results-status');
  if (badge) {
    badge.className = 'badge badge-pending ml-auto';
    badge.innerHTML = '<span class="badge-dot"></span> No run loaded';
  }
  renderCompletionCallout('');
  renderResultBubblePanel([], '');
  document.getElementById('viz-container').innerHTML = `
    <div class="viz-placeholder">
      <span class="viz-placeholder-mark" aria-hidden="true"></span>
      <div>Summary figures will appear here once a run is loaded.</div>
    </div>`;
  document.getElementById('files-container').innerHTML = '<div class="empty-state">No result files yet.</div>';
}

function showResultsShell() {
  document.getElementById('results-card')?.classList.remove('hidden');
  setResultsLoaded(true);
  navigateToSection(null, 'outputs', 'results-card');
}

function lockSubmittedIntake() {
  const card = document.getElementById('upload-card');
  document.body.dataset.workflowState = 'launched';
  document.body.dataset.managementView = 'closed';
  if (card) card.classList.add('upload-card-locked');
  setCardCollapsed('upload-card', true);
}

function applyJobStageSnapshot(job) {
  if (!activeStageState) initializeStageState(job);
  const key = jobCurrentStageKey(job);
  if (key) advanceToStage(key);
  const status = String((job && job.status) || '').toLowerCase();
  if (status === 'success' || status === 'failed') finalizeStageState(status);
}

async function deleteJob(e, jobId) {
  e.stopPropagation();
  if (!canUseAdminSurfaces()) return;
  if (!confirm('Delete this job and all its data?')) return;
  await apiFetch(`api/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' }, { kind: 'admin' });
  if (activeJobId === jobId) {
    activeJobId = null;
    stopPolling();
    document.getElementById('progress-card').classList.add('hidden');
    activeStageState = null;
    showEmptyResults();
  }
  refreshJobHistory();
}

// ── Load / watch a job ─────────────────────────────────────────────────────
async function loadJob(jobId, autoScroll = false, options = {}) {
  if (options.readToken) pendingReadTokens.set(String(jobId), options.readToken);
  const deferResultsShell = !!options.deferResultsShell;
  const seq = ++jobLoadSeq;
  cancelActiveArchiveDownload();
  activeJobId = jobId;
  logCursor   = 0;
  stopPolling();
  markActiveJobCard(jobId);
  if (lastSubmittedRun && lastSubmittedRun.jobId !== jobId) dismissSubmissionConfirmation();

  const preferResultsDashboard = shouldPreserveResultsDashboardForJobLoad(jobId, options);
  document.getElementById('progress-card').classList.toggle('hidden', !canUseAdminSurfaces());
  activeJobMeta = null;
  activeStageState = null;
  resultDashboardOpen = preferResultsDashboard;
  activeResultCategory = 'figures';
  activeResultFiles = [];
  activeResultArtifacts = null;
  setResultFocusMode('overview');
  document.body.dataset.resultsDashboard = preferResultsDashboard ? 'open' : 'closed';
  if (preferResultsDashboard) {
    document.body.dataset.managementView = 'closed';
    setResultsPanelCollapsed(true);
  }
  if (!deferResultsShell) showResultsShell();
  document.getElementById('rerun-panel').innerHTML = '';
  document.getElementById('log-terminal').innerHTML = '';
  resetWeaveActivity();
  resetStages();
  if (canUseAdminSurfaces() && currentUIMode === 'guided') setUIMode('lab', { preserveDisclosure: true });

  const job = await pollJobFinal(jobId, autoScroll, seq);
  if (!job || seq !== jobLoadSeq || jobId !== activeJobId) {
    if (seq === jobLoadSeq) {
      activeJobId = null;
      activeJobMeta = null;
      activeStageState = null;
      pendingReadTokens.delete(String(jobId));
      showEmptyResults();
    }
    return null;
  }
  if (job.status === 'running' || job.status === 'pending') {
    pollTimerId = setInterval(() => {
      pollJobFinal(jobId, autoScroll, seq);
    }, 1500);
  }
  return job;
}

async function pollJobFinal(jobId, autoScroll = false, seq = jobLoadSeq) {
  const resp = await apiFetch(`api/jobs/${encodeURIComponent(jobId)}`, {}, { kind: 'job', jobId });
  if (!resp.ok || seq !== jobLoadSeq || jobId !== activeJobId) return null;
  const job = await resp.json();
  if (seq !== jobLoadSeq || jobId !== activeJobId) return null;
  const previousJob = activeJobMeta;
  activeJobMeta = job;
  setWorkflowExperienceState(job);
  rememberOpenedRun(jobId, readTokenForJob(jobId), job);
  recordWeaveActivity(job);
  if (!activeStageState || activeStageState.jobId !== jobId) initializeStageState(job);
  applyJobStageSnapshot(job);
  if (canUseAdminSurfaces()) {
    const logResp = await apiFetch(`api/jobs/${encodeURIComponent(jobId)}/logs?since=${encodeURIComponent(logCursor)}`, {}, { kind: 'job', jobId });
    if (seq !== jobLoadSeq || jobId !== activeJobId) return null;
    if (logResp.ok) {
      const { lines } = await logResp.json();
      if (seq !== jobLoadSeq || jobId !== activeJobId) return null;
      for (const line of lines) {
        appendLogLine(line);
        updateStageBar(line);
        logCursor++;
        if (autoScroll) scrollToBottom();
      }
      document.getElementById('log-count').textContent = `${logCursor} lines`;
    }
  }
  updateProgressBadge(job.status);
  if (job.status !== 'running' && job.status !== 'pending') {
    stopPolling();
    await loadResults(jobId, job.status, seq, job);
  } else {
    await loadResults(jobId, job.status, seq, job);
  }
  if (previousJob && (previousJob.status !== job.status || previousJob.stage !== job.stage)) {
    if (canUseAdminSurfaces()) refreshJobHistory();
  }
  return job;
}

function stopPolling() {
  if (pollTimerId) {
    clearInterval(pollTimerId);
    pollTimerId = null;
  }
}

// ── Log rendering ──────────────────────────────────────────────────────────
function appendLogLine(text) {
  const term = document.getElementById('log-terminal');
  const div  = document.createElement('div');
  div.className = 'log-line';
  if (/error|fatal|failed/i.test(text)) div.classList.add('err');
  else if (/warn/i.test(text)) div.classList.add('warn');
  else if (/=== stage:/i.test(text)) div.classList.add('stage');
  else if (/success|complete|finished/i.test(text)) div.classList.add('ok');
  div.textContent = text;
  term.appendChild(div);
}

function clearLog() { document.getElementById('log-terminal').innerHTML = ''; }
function scrollElementToBottom(el) {
  if (!el) return;
  el.scrollTop = Math.max(0, el.scrollHeight - el.clientHeight);
}
function scrollToBottom() {
  const term = document.getElementById('log-terminal');
  if (!term) return;
  const lastLine = term.lastElementChild;
  scrollElementToBottom(term);
  if (lastLine) lastLine.scrollIntoView({ block: 'end', inline: 'nearest' });
  requestAnimationFrame(() => {
    scrollElementToBottom(term);
    const body = term.closest('.lab-console-body');
    scrollElementToBottom(body);
  });
}

// ── Stage bar ──────────────────────────────────────────────────────────────
function jobStageEnabled(job, key) {
  const settings = (job && job.settings) || {};
  const setting = (name, defaultValue) => {
    if (settings[name] === undefined || settings[name] === null || settings[name] === '') return defaultValue;
    if (typeof settings[name] === 'boolean') return settings[name];
    return envToBool(settings[name], defaultValue);
  };
  if (key === 'prep') return true;
  if (key === 'annotation') return setting('run_annotation', true);
  if (key === 'bigscape') return setting('run_bigscape', true);
  if (key === 'summary') return setting('run_summary', setting('run_crosswalk', true));
  if (key === 'clinker') return setting('run_clinker', true);
  if (key === 'figures') return setting('run_figures', true);
  if (key === 'nplinker') return setting('run_nplinker', false);
  return true;
}

function stageCapabilityKey(key) {
  const map = {
    prep: 'prepare',
    annotation: 'annotation',
    bigscape: 'bigscape',
    summary: 'summary',
    clinker: 'clinker',
    figures: 'figures',
    nplinker: 'nplinker',
  };
  return map[key] || key;
}

function rerunStageAllowed(key) {
  const stageCaps = runtimeCapabilities && runtimeCapabilities.stages;
  if (!stageCaps) return true;
  const cap = stageCaps[stageCapabilityKey(key)];
  return !cap || cap.available !== false;
}

function initializeStageState(job) {
  const enabled = new Set(STAGES.filter(s => jobStageEnabled(job, s.key)).map(s => s.key));
  activeStageState = {
    jobId: job ? job.id : null,
    enabled,
    completed: new Set(),
    current: null,
    failed: null,
    startedAt: {},
    endedAt: {},
  };
  renderStageState();
}

function resetStages(job = null) {
  initializeStageState(job || activeJobMeta || {});
}

function stageIndex(key) {
  return STAGES.findIndex(s => s.key === key);
}

function resetWeaveActivity(job = null) {
  weaveActivity = {
    jobId: job && job.id ? job.id : null,
    lastLogCount: job ? Number(job.log_count || 0) : null,
    lastStatus: job ? String(job.status || '') : null,
    events: [],
  };
  const helix = document.getElementById('weavemap-helix');
  if (helix) delete helix.dataset.rendered;
}

function workflowStageList(job = activeJobMeta) {
  return STAGES.filter(stage => {
    if (stage.key === 'nplinker' && !canUseAdminSurfaces() && !jobStageEnabled(job || {}, stage.key)) return false;
    return true;
  });
}

function finalEnabledStageKey(job = activeJobMeta) {
  const stages = workflowStageList(job).filter(stage => activeStageState
    ? activeStageState.enabled.has(stage.key)
    : jobStageEnabled(job || {}, stage.key));
  return stages.length ? stages[stages.length - 1].key : null;
}

function stageVisualState(key) {
  if (!activeStageState || !activeStageState.enabled.has(key)) return { cls: 'disabled', label: 'Skipped' };
  if (activeStageState.failed === key) return { cls: 'failed', label: 'Failed' };
  if (activeStageState.completed.has(key)) {
    const status = String((activeJobMeta && activeJobMeta.status) || '').toLowerCase();
    return status === 'success' && finalEnabledStageKey(activeJobMeta) === key
      ? { cls: 'complete', label: 'Complete' }
      : { cls: 'done', label: 'Past' };
  }
  if (activeStageState.current === key) return { cls: 'active', label: 'Current' };
  return { cls: 'upcoming', label: 'Future' };
}

function formatWorkflowTime(value) {
  if (!value) return 'time pending';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'time pending';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDuration(ms) {
  const total = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours) return `${hours}h ${String(minutes).padStart(2, '0')}m`;
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
}

function parseTimestampMs(value) {
  if (!value) return null;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : ms;
}

function jobElapsedText(job = activeJobMeta) {
  if (!job) return 'Not started';
  const start = parseTimestampMs(job.started_at || job.created_at);
  if (!start) return 'Not started';
  const status = String(job.status || '').toLowerCase();
  const end = (status === 'running' || status === 'pending')
    ? Date.now()
    : (parseTimestampMs(job.completed_at || job.finished_at || job.failed_at || job.updated_at) || Date.now());
  return formatDuration(end - start);
}

function stageRuntimeHint(key) {
  return STAGE_RUNTIME_HINTS[key] || 'Run dependent';
}

function stageEstimateText(key) {
  return `Estimated range ${stageRuntimeHint(key)}`;
}

function compactRuntimeHint(key) {
  const hint = stageRuntimeHint(key);
  return hint.length > 18 ? 'varies' : hint;
}

function dnaStageMetaText(key, visual) {
  if (visual.cls === 'disabled') return 'Skipped';
  return `${visual.label} / est. ${compactRuntimeHint(key)}`;
}

function stageElapsedText(key, visualCls) {
  if (!activeStageState || !activeStageState.enabled.has(key)) return 'Skipped';
  const start = activeStageState.startedAt && activeStageState.startedAt[key];
  const end = activeStageState.endedAt && activeStageState.endedAt[key];
  const status = String((activeJobMeta && activeJobMeta.status) || '').toLowerCase();
  if (visualCls === 'active') return jobElapsedText(activeJobMeta);
  if (visualCls === 'failed' && status === 'failed') return jobElapsedText(activeJobMeta);
  if (visualCls === 'complete' && status === 'success') return jobElapsedText(activeJobMeta);
  if ((visualCls === 'done' || visualCls === 'complete' || visualCls === 'failed') && start && end) return formatDuration(end - start);
  if (visualCls === 'done' || visualCls === 'complete') return 'Finished';
  if (visualCls === 'failed') return 'Stopped';
  return 'Not started';
}

function currentWorkflowStage() {
  if (!activeStageState) return null;
  if (activeStageState.failed) return activeStageState.failed;
  if (activeStageState.current) return activeStageState.current;
  if (activeJobMeta && String(activeJobMeta.status || '').toLowerCase() === 'success') return finalEnabledStageKey(activeJobMeta) || 'figures';
  return null;
}

function setWorkflowExperienceState(job = activeJobMeta) {
  const status = String((job && job.status) || '').toLowerCase();
  let state = 'idle';
  if (status === 'success') state = 'complete';
  else if (status === 'failed') state = 'failed';
  else if (status === 'running') state = 'running';
  else if (status === 'pending' || activeJobId) state = 'launched';
  document.body.dataset.workflowState = state;
}

function updateStageTelemetry() {
  if (!activeStageState) return;
  let currentKey = currentWorkflowStage();
  document.querySelectorAll('.stage-step').forEach(el => {
    const key = el.dataset.stage;
    const visual = stageVisualState(key);
    const elapsed = el.querySelector('.stage-elapsed');
    const estimate = el.querySelector('.stage-estimate');
    if (elapsed) elapsed.textContent = `Elapsed ${stageElapsedText(key, visual.cls)}`;
    if (estimate) estimate.textContent = stageEstimateText(key);
  });
  const currentStage = currentKey ? STAGES.find(stage => stage.key === currentKey) : null;
  const visual = currentKey ? stageVisualState(currentKey) : null;
  const queued = String((activeJobMeta && activeJobMeta.status) || '').toLowerCase() === 'pending';
  const stageEl = document.getElementById('workflow-current-stage');
  const elapsedEl = document.getElementById('workflow-current-elapsed');
  const estimateEl = document.getElementById('workflow-current-estimate');
  if (stageEl) stageEl.textContent = currentStage ? (STAGE_DETAILS[currentStage.key]?.name || currentStage.label) : (queued ? queueStatusLabel(activeJobMeta) : 'Waiting for run');
  if (elapsedEl) elapsedEl.textContent = currentKey && visual ? stageElapsedText(currentKey, visual.cls) : 'Not started';
  if (estimateEl) estimateEl.textContent = currentKey ? stageEstimateText(currentKey) : (queued ? queueStatusDetail(activeJobMeta) : 'Run dependent');
  refreshDnaTimingNodes();
}

function refreshDnaTimingNodes() {
  if (!activeStageState) return;
  document.querySelectorAll('.dna-base-popover').forEach(popover => {
    const key = popover.dataset.stage;
    if (!key) return;
    const visual = stageVisualState(key);
    const timing = popover.querySelector('[data-node-kind="timing"]');
    if (!timing) return;
    const title = timing.querySelector('.dna-node-title');
    const meta = timing.querySelector('.dna-node-meta');
    if (title) title.textContent = `Elapsed ${stageElapsedText(key, visual.cls)}`;
    if (meta) meta.textContent = stageEstimateText(key);
  });
}

function startStageTicker() {
  if (stageTickerId) return;
  stageTickerId = setInterval(updateStageTelemetry, 1000);
}

function normalizePublicWeaveEvent(event) {
  if (!event || typeof event !== 'object') return null;
  const stage = STAGES.some(item => item.key === event.stage) ? event.stage : 'prep';
  const title = String(event.title || '').trim();
  if (!title) return null;
  return {
    stage,
    title,
    meta: String(event.meta || event.time || '').trim(),
  };
}

function mergeWeaveActivityEvents(events) {
  const incoming = Array.isArray(events)
    ? events.map(normalizePublicWeaveEvent).filter(Boolean)
    : [];
  if (!incoming.length) return 0;
  const keyed = new Map();
  [...weaveActivity.events, ...incoming].forEach(event => {
    keyed.set(`${event.stage}|${event.title}|${event.meta}`, event);
  });
  weaveActivity.events = Array.from(keyed.values()).slice(-24);
  return incoming.length;
}

function recordWeaveActivity(job) {
  if (!job || !job.id) return;
  const currentCount = Number(job.log_count || 0);
  const status = String(job.status || '');
  const stageKey = jobCurrentStageKey(job) || (status === 'success' ? 'figures' : 'prep');
  const publicEventCount = Array.isArray(job.public_events) ? job.public_events.length : 0;
  if (weaveActivity.jobId !== job.id) {
    resetWeaveActivity(job);
    if (!mergeWeaveActivityEvents(job.public_events)) {
      weaveActivity.events.push({
        stage: stageKey,
        title: 'Run state loaded',
        meta: `${jobStageDisplay(job)} at ${formatWorkflowTime(job.updated_at || job.created_at)}`,
      });
    }
    return;
  }
  const delta = weaveActivity.lastLogCount === null ? 0 : currentCount - weaveActivity.lastLogCount;
  mergeWeaveActivityEvents(job.public_events);
  if (delta > 0 && !publicEventCount) {
    weaveActivity.events.push({
      stage: stageKey,
      title: `${delta} internal update${delta === 1 ? '' : 's'} observed`,
      meta: `${jobStageDisplay(job)} at ${formatWorkflowTime(job.updated_at)}`,
    });
  }
  if (status && weaveActivity.lastStatus && status !== weaveActivity.lastStatus) {
    weaveActivity.events.push({
      stage: stageKey,
      title: `Run marked ${status}`,
      meta: formatWorkflowTime(job.updated_at),
    });
  }
  weaveActivity.lastLogCount = currentCount;
  weaveActivity.lastStatus = status;
  if (weaveActivity.events.length > 18) weaveActivity.events = weaveActivity.events.slice(-18);
}

function latestWeaveEventByStage() {
  const latest = new Map();
  (weaveActivity.events || []).forEach(event => {
    if (event && event.stage) latest.set(event.stage, event);
  });
  return latest;
}

function stageTimelineLabel(visual) {
  const cls = visual && visual.cls ? visual.cls : 'upcoming';
  if (cls === 'done' || cls === 'complete') return 'Completed';
  if (cls === 'active') return 'Current';
  if (cls === 'failed') return 'Failed';
  if (cls === 'disabled') return 'Skipped';
  return 'Future';
}

function stageTimelineDetailKey(visual) {
  const cls = visual && visual.cls ? visual.cls : 'upcoming';
  if (cls === 'done' || cls === 'complete') return 'done';
  if (cls === 'upcoming') return 'queued';
  return cls;
}

function eventSummaryText(event) {
  if (!event || !event.title) return '';
  return event.meta ? `${event.title} / ${event.meta}` : event.title;
}

function stageTimelineMeta(stage, visual, event) {
  const details = STAGE_DETAILS[stage.key] || {};
  const cls = visual && visual.cls ? visual.cls : 'upcoming';
  const eventText = ['done', 'complete', 'active', 'failed'].includes(cls) ? eventSummaryText(event) : '';
  if (eventText) return eventText;
  if (cls === 'disabled') return 'Skipped for this run.';
  return details[stageTimelineDetailKey(visual)] || details.queued || 'Waiting for workflow state.';
}

function workflowStageOverviewNodes(job = activeJobMeta) {
  const latestByStage = latestWeaveEventByStage();
  return workflowStageList(job).map(stage => {
    const details = STAGE_DETAILS[stage.key] || stage;
    const visual = stageVisualState(stage.key);
    return {
      kind: `stage-${visual.cls}`,
      stageKey: stage.key,
      title: `${stageTimelineLabel(visual)}: ${details.name || stage.label}`,
      meta: stageTimelineMeta(stage, visual, latestByStage.get(stage.key)),
    };
  });
}

function publicStageNodes(stage, visual, job) {
  const status = String((job && job.status) || 'pending').toLowerCase();
  const nodes = [
    {
      kind: 'timing',
      title: `Run elapsed ${jobElapsedText(job)}`,
      meta: currentWorkflowStage() ? stageEstimateText(currentWorkflowStage()) : 'Run dependent',
    },
    ...workflowStageOverviewNodes(job),
  ];
  const latestForStage = latestWeaveEventByStage().get(stage.key);
  if (latestForStage && visual.cls === 'active') {
    nodes.push({
      kind: 'current-signal',
      title: 'Latest current-stage signal',
      meta: eventSummaryText(latestForStage),
    });
  }
  if (visual.cls === 'failed' || status === 'failed') {
    nodes.push({
      kind: 'failure-context',
      title: 'Failure context',
      meta: job && (job.error_summary || job.error) ? String(job.error_summary || job.error) : 'Review available outputs below.',
    });
  } else if ((visual.cls === 'done' || visual.cls === 'complete') && status === 'success') {
    nodes.push({
      kind: 'result-context',
      title: 'Terminal status reached',
      meta: `${Number((job && job.result_files && job.result_files.length) || 0)} output files indexed`,
    });
  }
  return nodes.slice(0, 10);
}

function dnaLabelLines(stageKey) {
  const labels = {
    prep: ['Prep'],
    annotation: ['Annotation', 'BGC'],
    bigscape: ['BiG-SCAPE'],
    summary: ['Summary'],
    clinker: ['clinker'],
    figures: ['Figures'],
    nplinker: ['NPLinker'],
  };
  return labels[stageKey] || [stageKey];
}

function dnaWave(model, t) {
  const turns = Number(model.turns || 2.85);
  return Math.sin((t * Math.PI * 2 * turns) - Math.PI / 2);
}

function dnaPoint(model, t, strand) {
  const wave = dnaWave(model, t);
  if (model.orientation === 'vertical') {
    const y = model.start + (model.end - model.start) * t;
    const x = model.mid + strand * model.amp * wave;
    return { x, y };
  }
  const x = model.start + (model.end - model.start) * t;
  const y = model.mid + strand * model.amp * wave;
  return { x, y };
}

function dnaPath(model, strand) {
  const points = [];
  for (let i = 0; i <= 144; i++) points.push(dnaPoint(model, i / 144, strand));
  return points.map((p, idx) => `${idx ? 'L' : 'M'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
}

function clampDnaT(value) {
  return Math.max(0, Math.min(1, Number(value) || 0));
}

function dnaSegmentPath(model, strand, startT, endT) {
  const start = clampDnaT(startT);
  const end = clampDnaT(endT);
  if (end <= start) return '';
  const points = [];
  const samples = Math.max(10, Math.ceil((end - start) * 90));
  for (let i = 0; i <= samples; i++) {
    points.push(dnaPoint(model, start + ((end - start) * i / samples), strand));
  }
  return points.map((p, idx) => `${idx ? 'L' : 'M'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
}

function dnaStrandDepthClass(model, strand, startT, endT) {
  const midT = clampDnaT((Number(startT) + Number(endT)) / 2);
  return strand * dnaWave(model, midT) >= 0 ? 'depth-front' : 'depth-back';
}

function dnaRungGeometry(layout, t) {
  const endpoints = [-1, 1].map(strand => ({ ...dnaPoint(layout, t, strand), strand }));
  endpoints.sort((a, b) => a.x - b.x);
  const y = layout.start + (layout.end - layout.start) * clampDnaT(t);
  const left = { ...endpoints[0], y };
  const right = { ...endpoints[1], y };
  return {
    left,
    right,
    x: layout.mid,
    y,
    span: Math.abs(right.x - left.x),
    leftDepth: dnaStrandDepthClass(layout, left.strand, t, t),
    rightDepth: dnaStrandDepthClass(layout, right.strand, t, t),
  };
}

function dnaVisualAtT(models, t) {
  if (!models || !models.length) return { cls: 'upcoming' };
  const value = clampDnaT(t);
  for (let index = 0; index < models.length; index += 1) {
    const region = dnaModelRegion(models, index);
    if (value >= region.start && value <= region.end) return models[index].visual || { cls: 'upcoming' };
  }
  return models[models.length - 1].visual || { cls: 'upcoming' };
}

function renderDnaDecorativeRungs(models, layout) {
  const count = document.body.dataset.resultsDashboard === 'open' ? 34 : 42;
  const rungs = [];
  for (let index = 0; index < count; index += 1) {
    const t = (index + .5) / count;
    if ((models || []).some(model => Math.abs(model.t - t) < .018)) continue;
    const geometry = dnaRungGeometry(layout, t);
    if (geometry.span < 92) continue;
    const cls = (dnaVisualAtT(models, t).cls || 'upcoming');
    const gap = Math.max(18, Math.min(28, geometry.span * .08));
    const leftEnd = geometry.x - gap;
    const rightStart = geometry.x + gap;
    const style = dnaBasePairStyle(`ghost-${index}`, index);
    rungs.push(`
      <g class="dna-ghost-stage dna-${cls}" style="${style}">
        <line class="dna-ghost-rung-shadow ${cls} ${geometry.leftDepth}" x1="${geometry.left.x.toFixed(1)}" y1="${geometry.y.toFixed(1)}" x2="${leftEnd.toFixed(1)}" y2="${geometry.y.toFixed(1)}"></line>
        <line class="dna-ghost-rung-shadow ${cls} ${geometry.rightDepth}" x1="${rightStart.toFixed(1)}" y1="${geometry.y.toFixed(1)}" x2="${geometry.right.x.toFixed(1)}" y2="${geometry.y.toFixed(1)}"></line>
        <line class="dna-ghost-rung dna-ghost-rung-left ${cls} ${geometry.leftDepth}" x1="${geometry.left.x.toFixed(1)}" y1="${geometry.y.toFixed(1)}" x2="${leftEnd.toFixed(1)}" y2="${geometry.y.toFixed(1)}"></line>
        <line class="dna-ghost-rung dna-ghost-rung-right ${cls} ${geometry.rightDepth}" x1="${rightStart.toFixed(1)}" y1="${geometry.y.toFixed(1)}" x2="${geometry.right.x.toFixed(1)}" y2="${geometry.y.toFixed(1)}"></line>
        <line class="dna-ghost-rung-shine ${cls} ${geometry.leftDepth}" x1="${(geometry.left.x + 8).toFixed(1)}" y1="${(geometry.y - 4).toFixed(1)}" x2="${(leftEnd - 8).toFixed(1)}" y2="${(geometry.y - 4).toFixed(1)}"></line>
        <line class="dna-ghost-rung-shine ${cls} ${geometry.rightDepth}" x1="${(rightStart + 8).toFixed(1)}" y1="${(geometry.y - 4).toFixed(1)}" x2="${(geometry.right.x - 8).toFixed(1)}" y2="${(geometry.y - 4).toFixed(1)}"></line>
      </g>`);
  }
  return rungs.join('');
}

function dnaModelRegion(models, index) {
  const current = models[index];
  const previous = models[index - 1];
  const next = models[index + 1];
  return {
    start: previous ? (previous.t + current.t) / 2 : 0,
    end: next ? (current.t + next.t) / 2 : 1,
  };
}

function dnaBackboneSvg(models, layout) {
  const source = models && models.length
    ? models.map((model, index) => ({ model, region: dnaModelRegion(models, index), cls: model.visual.cls, stage: model.stage.key }))
    : [{ model: { visual: { cls: 'upcoming' }, stage: { key: 'idle' } }, region: { start: 0, end: 1 }, cls: 'upcoming', stage: 'idle' }];
  const layers = { shadow: [], body: [], shine: [] };
  source.forEach(entry => {
    [-1, 1].forEach(strand => {
      const start = clampDnaT(entry.region.start);
      const end = clampDnaT(entry.region.end);
      const d = dnaSegmentPath(layout, strand, start, end);
      if (!d) return;
      const depth = dnaStrandDepthClass(layout, strand, start, end);
      const attrs = `data-stage="${escapeHtml(entry.stage)}" data-strand="${strand}" data-ribbon="continuous"`;
      layers.shadow.push(`<path class="dna-strand-shadow ${entry.cls} ${depth}" ${attrs} d="${d}"></path>`);
      layers.body.push(`<path class="dna-strand ${entry.cls} ${depth}" ${attrs} d="${d}"></path>`);
      layers.shine.push(`<path class="dna-strand-highlight ${entry.cls} ${depth}" ${attrs} d="${d}"></path>`);
    });
  });
  return `${layers.shadow.join('')}
        ${layers.body.join('')}
        ${layers.shine.join('')}`;
}

function dnaBasePairStyle(stageKey, index) {
  const pairs = [
    ['#D66EFF', '#FFB454'],
    ['#78A7FF', '#D66EFF'],
    ['#FF8B3D', '#7BCBFF'],
    ['#B972FF', '#F59E0B'],
    ['#70B7FF', '#FF9F43'],
    ['#D86DFF', '#6EC8FF'],
  ];
  const salt = String(stageKey || '').split('').reduce((sum, char) => sum + char.charCodeAt(0), 0);
  const pair = pairs[(salt + index * 2) % pairs.length];
  return `--dna-base-left: ${pair[0]}; --dna-base-right: ${pair[1]};`;
}

function dnaLayout(containerWidth, containerHeight) {
  const visibleHeight = Math.max(620, Number(containerHeight) || window.innerHeight || 760);
  const width = Math.max(720, Math.min(1080, (Number(containerWidth) || 900) * .96));
  const resultMode = document.body.dataset.resultsDashboard === 'open';
  const height = resultMode
    ? Math.max(1120, Math.min(1760, visibleHeight * 1.42))
    : Math.max(1760, Math.min(2800, visibleHeight * 2.18));
  return {
    orientation: 'vertical',
    width,
    height,
    start: Math.max(96, height * .07),
    end: height - Math.max(150, height * .08),
    mid: width * .5,
    amp: Math.max(180, Math.min(resultMode ? 270 : 305, width * .25)),
    baseSpan: Math.max(170, Math.min(280, width * .24)),
    turns: 3,
  };
}

function dnaStageModels(job, layout) {
  const stages = workflowStageList(job);
  return stages.map((stage, index) => {
    const t = stages.length === 1 ? 0 : index / (stages.length - 1);
    const visual = stageVisualState(stage.key);
    const details = STAGE_DETAILS[stage.key] || stage;
    const geometry = dnaRungGeometry(layout, t);
    const { left: a, right: b, x, y } = geometry;
    const panelStyle = '--panel-left: calc(100% + 2.4rem); --panel-top: -1.15rem; --panel-shift: 0%;';
    return {
      stage,
      index,
      visual,
      details,
      nodes: publicStageNodes(stage, visual, job),
      a,
      b,
      x,
      y,
      t,
      xPct: `${(x / layout.width * 100).toFixed(3)}%`,
      yPct: `${(y / layout.height * 100).toFixed(3)}%`,
      panelStyle,
    };
  });
}

function reducedMotionPreferred() {
  return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
}

function dnaTrackOffset(layout, helix, job) {
  const state = String(document.body.dataset.workflowState || 'idle');
  if (state === 'idle') return 0;
  const stages = workflowStageList(job);
  if (!stages.length) return 0;
  const status = String((job && job.status) || '').toLowerCase();
  const key = currentWorkflowStage()
    || activeStageState?.failed
    || (status === 'success' ? finalEnabledStageKey(job) : '')
    || '';
  if (!key) return 0;
  const idx = stages.findIndex(stage => stage.key === key);
  if (idx < 0) return 0;
  if (resultDashboardOpen) return 0;
  const visibleHeight = Math.max(520, helix.clientHeight || window.innerHeight || 760);
  const renderedWidth = Math.max(1, helix.clientWidth || layout.width);
  const svgScale = Math.min(1, renderedWidth / Math.max(1, layout.width));
  const scaledHeight = layout.height * svgScale;
  const minOffset = Math.min(0, visibleHeight - scaledHeight + 40);
  const t = stages.length === 1 ? 0 : idx / (stages.length - 1);
  const y = layout.start + (layout.end - layout.start) * t;
  const scaledY = y * svgScale;
  const focusY = Math.max(380, Math.min(visibleHeight * .56, 560));
  return Math.max(minOffset, Math.min(0, focusY - scaledY));
}

function renderDnaStageSvg(model, layout) {
  const { stage, visual, a, b, x, y } = model;
  const cls = visual.cls;
  const labels = dnaLabelLines(stage.key);
  const labelX = x + Math.min(260, layout.width * .23);
  const labelY = y - 14;
  const metaY = labelY + labels.length * 26 + 12;
  const metaText = dnaStageMetaText(stage.key, visual);
  const leftEnd = x - 25;
  const rightStart = x + 25;
  const leftDepth = dnaStrandDepthClass(layout, a.strand || -1, model.t, model.t);
  const rightDepth = dnaStrandDepthClass(layout, b.strand || 1, model.t, model.t);
  const baseStyle = dnaBasePairStyle(stage.key, model.index);
  const labelLines = labels.map((line, idx) => `
    <text class="dna-label ${cls}" x="${labelX.toFixed(1)}" y="${(labelY + idx * 26).toFixed(1)}" text-anchor="start">${escapeHtml(line)}</text>
  `).join('');
  const pointer = cls === 'active' || cls === 'failed'
    ? `<path class="dna-stage-pointer ${cls}" d="M ${(x + 42).toFixed(1)} ${(y - 42).toFixed(1)} C ${(x + 118).toFixed(1)} ${(y - 92).toFixed(1)}, ${(x + 188).toFixed(1)} ${(y - 78).toFixed(1)}, ${(x + 226).toFixed(1)} ${(y - 30).toFixed(1)}"></path>`
    : '';
  const activeRing = cls === 'active' || cls === 'failed'
    ? `<circle class="dna-active-ring" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="50"></circle>`
    : '';
  return `
    <g class="dna-stage dna-${cls}" data-stage="${escapeHtml(stage.key)}" aria-label="${escapeHtml(stage.label + ': ' + visual.label)}" style="${baseStyle}">
      <line class="dna-rung-shadow ${cls} ${leftDepth}" x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${leftEnd.toFixed(1)}" y2="${y.toFixed(1)}"></line>
      <line class="dna-rung-shadow ${cls} ${rightDepth}" x1="${rightStart.toFixed(1)}" y1="${y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}"></line>
      <line class="dna-rung dna-rung-left ${cls} ${leftDepth}" x1="${a.x.toFixed(1)}" y1="${a.y.toFixed(1)}" x2="${leftEnd.toFixed(1)}" y2="${y.toFixed(1)}"></line>
      <line class="dna-rung dna-rung-right ${cls} ${rightDepth}" x1="${rightStart.toFixed(1)}" y1="${y.toFixed(1)}" x2="${b.x.toFixed(1)}" y2="${b.y.toFixed(1)}"></line>
      <line class="dna-rung-shine ${cls} ${leftDepth}" x1="${(a.x + 10).toFixed(1)}" y1="${(a.y - 7).toFixed(1)}" x2="${(leftEnd - 12).toFixed(1)}" y2="${(y - 7).toFixed(1)}"></line>
      <line class="dna-rung-shine ${cls} ${rightDepth}" x1="${(rightStart + 12).toFixed(1)}" y1="${(y - 7).toFixed(1)}" x2="${(b.x - 10).toFixed(1)}" y2="${(b.y - 7).toFixed(1)}"></line>
      ${pointer}
      ${activeRing}
      <rect class="dna-center-link ${cls}" x="${(x - 19).toFixed(1)}" y="${(y - 33).toFixed(1)}" width="38" height="66" rx="15"></rect>
      <circle class="dna-base-dot dna-base-dot-a" cx="${a.x.toFixed(1)}" cy="${a.y.toFixed(1)}" r="14"></circle>
      <circle class="dna-base-dot dna-base-dot-b" cx="${b.x.toFixed(1)}" cy="${b.y.toFixed(1)}" r="14"></circle>
      <text class="dna-label-meta ${cls}" x="${labelX.toFixed(1)}" y="${metaY.toFixed(1)}" text-anchor="start">${escapeHtml(metaText)}</text>
      ${labelLines}
    </g>`;
}

function cssAttributeValue(value) {
  return String(value || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

function syncDnaPopoverAnchors(stageWrap, helix) {
  if (!stageWrap || !helix) return;
  const wrapRect = stageWrap.getBoundingClientRect();
  stageWrap.querySelectorAll('.dna-base-popover').forEach(popover => {
    const stageKey = popover.dataset.stage || '';
    if (!stageKey) return;
    const stage = helix.querySelector(`.dna-stage[data-stage="${cssAttributeValue(stageKey)}"]`);
    const anchor = stage?.querySelector('.dna-center-link') || stage?.querySelector('.dna-active-ring') || stage;
    if (!anchor) return;
    const rect = anchor.getBoundingClientRect();
    if (!rect.width && !rect.height) return;
    popover.style.setProperty('--x', `${Math.round(rect.left + rect.width / 2 - wrapRect.left)}px`);
    popover.style.setProperty('--y', `${Math.round(rect.top + rect.height / 2 - wrapRect.top)}px`);
  });
}

function syncDnaResultOutputAnchors(stageWrap, helix) {
  if (!stageWrap || !helix) return;
  const wrapRect = stageWrap.getBoundingClientRect();
  const rootFontSize = Number.parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const headerRect = document.querySelector('header')?.getBoundingClientRect();
  const stageDeltas = new Map();
  const measurements = [];
  stageWrap.querySelectorAll('.dna-result-output').forEach(output => {
    const stageKey = output.dataset.stage || '';
    if (!stageKey) return;
    const stage = helix.querySelector(`.dna-stage[data-stage="${cssAttributeValue(stageKey)}"]`);
    if (!stage) return;
    const dots = Array.from(stage.querySelectorAll('.dna-base-dot'));
    const anchor = dots.length
      ? dots.map(dot => ({ dot, rect: dot.getBoundingClientRect() })).sort((a, b) => b.rect.right - a.rect.right)[0]
      : null;
    const rect = anchor ? anchor.rect : (stage.querySelector('.dna-center-link') || stage).getBoundingClientRect();
    if (!rect.width && !rect.height) return;
    const outputOffsetRem = Number.parseFloat(output.style.getPropertyValue('--output-y')) || 0;
    const offsetPx = outputOffsetRem * rootFontSize;
    const rawY = rect.top + rect.height / 2 - wrapRect.top;
    const requiredY = headerRect ? headerRect.bottom - wrapRect.top + 34 - offsetPx : rawY;
    const delta = Math.max(0, requiredY - rawY);
    stageDeltas.set(stageKey, Math.max(stageDeltas.get(stageKey) || 0, delta));
    measurements.push({ output, stageKey, rect, rawY });
  });
  const resultMode = document.body.dataset.resultsDashboard === 'open';
  measurements.forEach(({ output, stageKey, rect, rawY }) => {
    let x = rect.right - wrapRect.left;
    if (resultMode) {
      const edgeReserve = Math.min(275, Math.max(235, wrapRect.width * .27));
      x = Math.min(x, Math.max(0, wrapRect.width - edgeReserve));
    }
    output.style.setProperty('--x', `${Math.round(x)}px`);
    output.style.setProperty('--y', `${Math.round(rawY + (stageDeltas.get(stageKey) || 0))}px`);
  });
}

function applyFixedDnaPopoverTarget(stageKey, panel) {
  const target = dnaPopoverDragTargets.get(stageKey) || null;
  if (!target || !panel) return false;
  panel.style.position = 'fixed';
  panel.style.left = `${Math.round(target.left)}px`;
  panel.style.top = `${Math.round(target.top)}px`;
  if (target.width) panel.style.width = `${Math.round(target.width)}px`;
  panel.style.transform = 'none';
  panel.style.setProperty('--panel-drag-x', '0px');
  panel.style.setProperty('--panel-drag-y', '0px');
  for (let i = 0; i < 2; i += 1) {
    const rect = panel.getBoundingClientRect();
    const adjustX = target.left - rect.left;
    const adjustY = target.top - rect.top;
    if (Math.abs(adjustX) < .5 && Math.abs(adjustY) < .5) break;
    const currentLeft = Number.parseFloat(panel.style.left) || 0;
    const currentTop = Number.parseFloat(panel.style.top) || 0;
    panel.style.left = `${Math.round(currentLeft + adjustX)}px`;
    panel.style.top = `${Math.round(currentTop + adjustY)}px`;
  }
  dnaPopoverDragOffsets.set(stageKey, { x: 0, y: 0 });
  return true;
}

function syncDnaPopoverDragOffsetFromTarget(stageKey, panel) {
  if (applyFixedDnaPopoverTarget(stageKey, panel)) return { x: 0, y: 0 };
  return dnaPopoverDragOffsets.get(stageKey) || { x: 0, y: 0 };
}

function applyDnaPopoverDragOffsets(stageWrap) {
  if (!stageWrap) return;
  stageWrap.querySelectorAll('.dna-base-popover').forEach(popover => {
    const panel = popover.querySelector('.dna-popover-panel');
    const stageKey = popover.dataset.stage || '';
    if (!panel) return;
    const offset = syncDnaPopoverDragOffsetFromTarget(stageKey, panel);
    panel.style.setProperty('--panel-drag-x', `${Math.round(offset.x || 0)}px`);
    panel.style.setProperty('--panel-drag-y', `${Math.round(offset.y || 0)}px`);
  });
}

function updateDnaPopoverConnector(stageWrap) {
  const layer = stageWrap?.querySelector('.dna-popover-connector-layer');
  if (!layer) return;
  const popover = stageWrap.querySelector('.dna-base-popover.active, .dna-base-popover.failed');
  const panel = popover?.querySelector('.dna-popover-panel');
  const trigger = popover?.querySelector('.dna-popover-trigger');
  if (!popover || !panel || !trigger) {
    layer.innerHTML = '';
    return;
  }
  const wrapRect = stageWrap.getBoundingClientRect();
  const panelRect = panel.getBoundingClientRect();
  const triggerRect = trigger.getBoundingClientRect();
  if (!panelRect.width || !panelRect.height || getComputedStyle(panel).visibility === 'hidden') {
    layer.innerHTML = '';
    return;
  }
  const width = Math.max(1, Math.round(stageWrap.clientWidth || wrapRect.width));
  const height = Math.max(1, Math.round(stageWrap.clientHeight || wrapRect.height));
  layer.setAttribute('viewBox', `0 0 ${width} ${height}`);
  const startX = triggerRect.left + triggerRect.width / 2 - wrapRect.left;
  const startY = triggerRect.top + triggerRect.height / 2 - wrapRect.top;
  const endX = panelRect.left + panelRect.width / 2 - wrapRect.left;
  const endY = panelRect.top - wrapRect.top;
  const gap = Math.max(80, Math.min(190, Math.abs(endX - startX) * .42));
  const c1x = startX + gap;
  const c1y = startY - 56;
  const c2x = endX - gap * .55;
  const c2y = endY - 44;
  const cls = popover.classList.contains('failed') ? 'failed' : 'active';
  let path = layer.querySelector('path');
  if (!path) {
    path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    layer.appendChild(path);
  }
  path.setAttribute('class', `dna-popover-connector-path ${cls}`);
  path.setAttribute('d', `M ${startX.toFixed(1)} ${startY.toFixed(1)} C ${c1x.toFixed(1)} ${c1y.toFixed(1)}, ${c2x.toFixed(1)} ${c2y.toFixed(1)}, ${endX.toFixed(1)} ${endY.toFixed(1)}`);
}

function syncAndPositionDnaPopovers(stageWrap, helix) {
  syncDnaPopoverAnchors(stageWrap, helix);
  syncDnaResultOutputAnchors(stageWrap, helix);
  positionDnaPopoverPanels(stageWrap);
  applyDnaPopoverDragOffsets(stageWrap);
  updateDnaPopoverConnector(stageWrap);
  window.requestAnimationFrame(() => updateDnaPopoverConnector(stageWrap));
}

function wireDnaPopoverDrag(stageWrap) {
  if (!stageWrap) return;
  stageWrap.querySelectorAll('.dna-base-popover').forEach(popover => {
    const panel = popover.querySelector('.dna-popover-panel');
    const handle = popover.querySelector('.dna-popover-head');
    const stageKey = popover.dataset.stage || '';
    if (!panel || !handle || !stageKey) return;
    const beginDrag = event => {
      if (panel.classList.contains('dragging')) return;
      if (event.button !== undefined && event.button !== 0) return;
      event.preventDefault();
      const pointerMode = event.type.startsWith('pointer');
      const moveType = pointerMode ? 'pointermove' : 'mousemove';
      const upType = pointerMode ? 'pointerup' : 'mouseup';
      const cancelType = pointerMode ? 'pointercancel' : 'mouseleave';
      const startX = event.clientX;
      const startY = event.clientY;
      const startRect = panel.getBoundingClientRect();
      panel.classList.add('dragging');
      const move = moveEvent => {
        moveEvent.preventDefault();
        const dx = moveEvent.clientX - startX;
        const dy = moveEvent.clientY - startY;
        dnaPopoverDragTargets.set(stageKey, {
          left: startRect.left + dx,
          top: startRect.top + dy,
          width: startRect.width,
        });
        applyFixedDnaPopoverTarget(stageKey, panel);
        updateDnaPopoverConnector(stageWrap);
        window.requestAnimationFrame(() => updateDnaPopoverConnector(stageWrap));
      };
      const done = () => {
        const finalRect = panel.getBoundingClientRect();
        if (finalRect.width || finalRect.height) {
          dnaPopoverDragTargets.set(stageKey, { left: finalRect.left, top: finalRect.top, width: finalRect.width });
        }
        panel.classList.remove('dragging');
        window.removeEventListener(moveType, move);
        window.removeEventListener(upType, done);
        window.removeEventListener(cancelType, done);
        updateDnaPopoverConnector(stageWrap);
        window.setTimeout(() => updateDnaPopoverConnector(stageWrap), 160);
      };
      window.addEventListener(moveType, move, { passive: false });
      window.addEventListener(upType, done, { once: true });
      window.addEventListener(cancelType, done, { once: true });
    };
    handle.addEventListener('pointerdown', beginDrag);
    handle.addEventListener('mousedown', beginDrag);
  });
}

function positionDnaPopoverPanels(helix) {
  const spine = document.querySelector('.spine-field');
  const focusedDrawer = document.body.dataset.resultsDashboard === 'open' && document.body.dataset.resultFocus === 'focused'
    ? document.getElementById('result-dashboard-section')
    : null;
  const rail = focusedDrawer || document.getElementById('results-card');
  const spineRect = spine ? spine.getBoundingClientRect() : null;
  const railStyle = rail ? getComputedStyle(rail) : null;
  const railRect = rail && railStyle && railStyle.position === 'fixed' && railStyle.display !== 'none'
    ? rail.getBoundingClientRect()
    : null;
  const railLeft = railRect && railRect.width > 0 ? railRect.left : window.innerWidth;
  const resultMode = document.body.dataset.resultsDashboard === 'open';
  const pad = 32;
  const resultOutputLane = resultMode && resultFocusMode !== 'focused' && currentResultOutputItems().length && window.innerWidth > 720
    ? Math.min(390, Math.max(330, window.innerWidth * .26))
    : 0;
  const overlayRight = resultMode
    ? Math.min(railLeft - 18, window.innerWidth - 8)
    : Math.min(railLeft - pad, window.innerWidth - pad);
  (helix || document).querySelectorAll('.dna-base-popover').forEach(popover => {
    const panel = popover.querySelector('.dna-popover-panel');
    const trigger = popover.querySelector('.dna-popover-trigger');
    if (!panel || !trigger) return;
    const stageKey = popover.dataset.stage || '';
    if (dnaPopoverDragTargets.has(stageKey)) return;

    panel.style.removeProperty('--panel-width');
    const popoverRect = popover.getBoundingClientRect();
    const triggerRect = trigger.getBoundingClientRect();
    let panelRect = panel.getBoundingClientRect();
    const anchorGap = resultMode ? 56 : 96;
    const minLeft = Math.max(
      triggerRect.right + anchorGap + resultOutputLane,
      resultMode ? pad : (spineRect ? spineRect.right + 36 : triggerRect.right + anchorGap),
      pad
    );
    const availableWidth = Math.max(280, overlayRight - minLeft);
    const panelWidth = Math.max(280, Math.min(resultMode ? 520 : 640, availableWidth));
    panel.style.setProperty('--panel-width', `${Math.round(panelWidth)}px`);
    panelRect = panel.getBoundingClientRect();

    const maxLeft = Math.max(pad, overlayRight - panelRect.width);
    const laneSlack = Math.max(0, availableWidth - panelRect.width);
    const desiredLeft = minLeft + Math.min(64, laneSlack * .35);
    const left = Math.max(pad, Math.min(desiredLeft, maxLeft));
    let panelLeft = Math.round(left - popoverRect.left);
    panel.style.setProperty('--panel-left', `${panelLeft}px`);

    const settledLeft = panel.getBoundingClientRect().left;
    panelLeft += Math.round(left - settledLeft);
    panel.style.setProperty('--panel-left', `${panelLeft}px`);
    for (let i = 0; i < 2; i += 1) {
      panelRect = panel.getBoundingClientRect();
      const overflowRight = panelRect.right - overlayRight;
      const overflowLeft = pad - panelRect.left;
      const adjustment = overflowRight > 0 ? -overflowRight : (overflowLeft > 0 ? overflowLeft : 0);
      if (Math.abs(adjustment) < 1) break;
      panelLeft += Math.round(adjustment);
      panel.style.setProperty('--panel-left', `${panelLeft}px`);
    }
    panel.dataset.positioned = '1';
  });
}

function renderDnaPopover(model) {
  const { stage, visual, details, nodes } = model;
  return `
    <div class="dna-base-popover ${visual.cls}" data-stage="${escapeHtml(stage.key)}" style="--x: ${model.xPct}; --y: ${model.yPct}; ${model.panelStyle}">
      <button class="dna-popover-trigger" type="button" data-stage="${escapeHtml(stage.key)}" aria-describedby="dna-popover-${escapeHtml(stage.key)}" aria-label="${escapeHtml(details.name || stage.label)} activity">
        <span class="sr-only">${escapeHtml(details.name || stage.label)} ${escapeHtml(visual.label)}</span>
      </button>
      <div class="dna-popover-panel" id="dna-popover-${escapeHtml(stage.key)}" role="tooltip">
        <div class="dna-popover-head">
          <span>${escapeHtml(details.name || stage.label)}</span>
          <span class="dna-popover-status">${escapeHtml(visual.label)}</span>
        </div>
        <div class="dna-node-list">
          ${nodes.map(node => `
            <span class="dna-node-item"${node.kind ? ` data-node-kind="${escapeHtml(node.kind)}"` : ''}${node.stageKey ? ` data-node-stage="${escapeHtml(node.stageKey)}"` : ''}>
              <span class="dna-node-title">${escapeHtml(node.title)}</span>
              <span class="dna-node-meta">${escapeHtml(node.meta)}</span>
            </span>
          `).join('')}
        </div>
      </div>
    </div>`;
}

function resultOutputStageKey(key) {
  const map = {
    antismash: 'annotation',
    funbgcex: 'annotation',
    bigscape: 'bigscape',
    summaries: 'summary',
    synteny: 'clinker',
    figures: 'figures',
  };
  return map[resultCategoryKey(key)] || 'figures';
}

function currentResultOutputItems() {
  if (!resultDashboardOpen) return [];
  return resultLollipopItems(activeResultArtifacts || buildResultArtifacts(activeResultFiles));
}

function resultOutputSignature() {
  return currentResultOutputItems().map(item => `${item.key}:${item.count}`).join('|');
}

function renderDnaResultOutput(item, model, offsetRem, order, scale, trackOffset, outputPosition = null) {
  const selected = resultFocusMode === 'focused' && item.key === activeResultCategory;
  const dimmed = resultFocusMode === 'focused' && !selected;
  const countLabel = `${item.count} ${item.unit}${item.count === 1 ? '' : 's'}`;
  const jsKey = escapeJsString(item.key);
  const className = `dna-result-output${selected ? ' is-selected' : ''}${dimmed ? ' is-dimmed' : ''}`;
  const compact = outputPosition && outputPosition.compact;
  const branchRem = compact ? 2.25 + Math.min(.85, order * .14) : 6.4 + Math.min(2.1, order * .32);
  const outputXRem = Math.max(1.6, branchRem - .18);
  const x = outputPosition ? outputPosition.x : model.x * scale;
  const y = outputPosition ? outputPosition.y : model.y * scale + trackOffset;
  return `
    <div class="${className}" data-stage="${escapeHtml(model.stage.key)}" data-output-key="${escapeHtml(item.key)}" data-output-node="${escapeHtml(item.icon)}" style="--x: ${x.toFixed(1)}px; --y: ${y.toFixed(1)}px; --output-y: ${offsetRem.toFixed(2)}rem; --output-x: ${outputXRem.toFixed(2)}rem; --branch-width: ${branchRem.toFixed(2)}rem;">
      <button class="dna-result-output-trigger" type="button" onclick="focusResultCategory('${escapeHtml(jsKey)}', event)" aria-pressed="${selected ? 'true' : 'false'}" aria-controls="result-focus-panel" aria-label="${escapeHtml(item.label)} output, ${escapeHtml(countLabel)}">
        <span class="dna-result-output-title">${escapeHtml(item.label)}</span>
        <span class="sr-only">${escapeHtml(countLabel)}</span>
      </button>
    </div>`;
}

function renderDnaResultOutputs(models, layout, trackOffset, helix) {
  const items = currentResultOutputItems();
  if (!items.length) return '';
  const modelByStage = new Map(models.map(model => [model.stage.key, model]));
  const grouped = new Map();
  items.forEach(item => {
    const stageKey = resultOutputStageKey(item.key);
    const model = modelByStage.get(stageKey);
    if (!model) return;
    if (!grouped.has(stageKey)) grouped.set(stageKey, []);
    grouped.get(stageKey).push({ item, model });
  });
  const entries = Array.from(grouped.values()).flatMap(group => {
    const center = (group.length - 1) / 2;
    return group.map((entry, index) => ({ ...entry, offsetRem: (index - center) * 3.12 }));
  });
  let order = 0;
  const helixRect = helix && helix.getBoundingClientRect ? helix.getBoundingClientRect() : null;
  const renderedWidth = Math.max(1, (helixRect && helixRect.width) || helix?.clientWidth || layout.width);
  const scale = Math.min(1, renderedWidth / Math.max(1, layout.width));
  const xOffset = Math.max(0, (renderedWidth - layout.width * scale) / 2);
  return entries.map(entry => {
    let position = null;
    if (resultDashboardOpen) {
      const rightBaseX = Math.max(entry.model.a.x, entry.model.b.x);
      position = {
        compact: true,
        x: xOffset + rightBaseX * scale,
        y: entry.model.y * scale + trackOffset,
      };
    }
    return renderDnaResultOutput(entry.item, entry.model, entry.offsetRem, order++, scale, trackOffset, position);
  }).join('');
}

function renderWeaveHelix(job = activeJobMeta) {
  const helix = document.getElementById('weavemap-helix');
  if (!helix || !activeStageState) return;
  const layout = dnaLayout(helix.clientWidth || 900, helix.clientHeight || window.innerHeight || 760);
  const trackOffset = dnaTrackOffset(layout, helix, job);
  helix.style.setProperty('--dna-track-height', `${layout.height.toFixed(1)}px`);
  helix.style.setProperty('--dna-track-y', `${trackOffset.toFixed(1)}px`);
  const models = dnaStageModels(job, layout);
  const renderKey = JSON.stringify({
    orientation: layout.orientation,
    width: Math.round(layout.width),
    height: Math.round(layout.height),
    current: activeStageState.current || '',
    failed: activeStageState.failed || '',
    completed: Array.from(activeStageState.completed).join('|'),
    enabled: Array.from(activeStageState.enabled).join('|'),
    visible: workflowStageList(job).map(stage => stage.key).join('|'),
    motion: reducedMotionPreferred() ? 'reduce' : 'motion',
    status: job ? String(job.status || '') : '',
    timing: activeStageState.current ? activeStageState.current : '',
    events: weaveActivity.events.map(event => `${event.stage}|${event.title}|${event.meta}`).join('~'),
    resultsOpen: resultDashboardOpen ? '1' : '0',
    resultFocus: resultFocusMode || 'overview',
    resultCategory: activeResultCategory || '',
    outputs: resultOutputSignature(),
  });
  if (helix.dataset.renderKey === renderKey && helix.dataset.rendered === '1') return;
  const stageWrap = helix.closest('.weavemap-stage-wrap') || helix.parentElement || helix;
  stageWrap.style.setProperty('--dna-track-height', `${layout.height.toFixed(1)}px`);
  stageWrap.style.setProperty('--dna-track-y', `${trackOffset.toFixed(1)}px`);
  const scrollPositions = new Map(
    Array.from(stageWrap.querySelectorAll('.dna-base-popover')).map(popover => [
      popover.dataset.stage,
      popover.querySelector('.dna-node-list')?.scrollTop || 0,
    ])
  );
  const hoveredStage = stageWrap.querySelector('.dna-base-popover:hover')?.dataset.stage || '';
  const focusedStage = document.activeElement?.closest?.('.dna-base-popover')?.dataset.stage || '';
  const focusedOutput = document.activeElement?.closest?.('.dna-result-output')?.dataset.outputKey || '';
  helix.className = `weavemap-helix dna-${layout.orientation}`;
  Array.from(stageWrap.children).forEach(child => {
    if (!child.classList) return;
    if (child.classList.contains('dna-popover-layer') || child.classList.contains('dna-popover-connector-layer') || child.classList.contains('dna-result-output-layer')) child.remove();
  });
  helix.innerHTML = `
    <div class="dna-weave-shell" aria-hidden="true">
      <svg class="dna-helix-svg" viewBox="0 0 ${layout.width} ${layout.height}" preserveAspectRatio="xMidYMin meet" role="img" aria-label="Workflow double helix">
        <defs>
          <linearGradient id="dna-gradient-teal" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#7BF7E8"></stop>
            <stop offset="42%" stop-color="#00BFA5"></stop>
            <stop offset="100%" stop-color="#087C75"></stop>
          </linearGradient>
          <linearGradient id="dna-gradient-teal-active" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#C9FFF8"></stop>
            <stop offset="44%" stop-color="#5BE6D0"></stop>
            <stop offset="100%" stop-color="#00A995"></stop>
          </linearGradient>
          <linearGradient id="dna-gradient-backbone-muted" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#B6BEC1"></stop>
            <stop offset="52%" stop-color="#737A80"></stop>
            <stop offset="100%" stop-color="#333842"></stop>
          </linearGradient>
          <linearGradient id="dna-gradient-backbone-shine" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stop-color="#F4FFFC"></stop>
            <stop offset="58%" stop-color="#91FFF1"></stop>
            <stop offset="100%" stop-color="#1D8E86"></stop>
          </linearGradient>
          <linearGradient id="dna-center-violet" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#D8D3FF"></stop>
            <stop offset="55%" stop-color="#8A73E2"></stop>
            <stop offset="100%" stop-color="#4D456E"></stop>
          </linearGradient>
        </defs>
        ${dnaBackboneSvg(models, layout)}
        ${renderDnaDecorativeRungs(models, layout)}
        ${models.map(model => renderDnaStageSvg(model, layout)).join('')}
      </svg>
    </div>`;
  const connectorLayer = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  connectorLayer.classList.add('dna-popover-connector-layer');
  connectorLayer.setAttribute('aria-hidden', 'true');
  stageWrap.appendChild(connectorLayer);
  const popoverLayer = document.createElement('div');
  popoverLayer.className = 'dna-popover-layer';
  popoverLayer.innerHTML = models.map(model => renderDnaPopover(model)).join('');
  stageWrap.appendChild(popoverLayer);
  const resultOutputHtml = renderDnaResultOutputs(models, layout, trackOffset, helix);
  if (resultOutputHtml) {
    const resultOutputLayer = document.createElement('div');
    resultOutputLayer.className = 'dna-result-output-layer';
    resultOutputLayer.setAttribute('aria-label', 'Completed result outputs');
    resultOutputLayer.innerHTML = resultOutputHtml;
    stageWrap.appendChild(resultOutputLayer);
  }
  if (resultDashboardOpen) {
    const liveStage = activeStageState.failed || activeStageState.current || '';
    if (liveStage) scrollResultSpineToStage(liveStage);
  }
  wireDnaPopoverDrag(stageWrap);
  models.forEach(model => {
    const list = stageWrap.querySelector(`.dna-base-popover[data-stage="${model.stage.key}"] .dna-node-list`);
    if (list && scrollPositions.has(model.stage.key)) list.scrollTop = scrollPositions.get(model.stage.key) || 0;
  });
  syncAndPositionDnaPopovers(stageWrap, helix);
  window.requestAnimationFrame(() => syncAndPositionDnaPopovers(stageWrap, helix));
  window.setTimeout(() => syncAndPositionDnaPopovers(stageWrap, helix), 650);
  if (focusedStage) {
    stageWrap.querySelector(`.dna-popover-trigger[data-stage="${focusedStage}"]`)?.focus({ preventScroll: true });
  } else if (focusedOutput) {
    stageWrap.querySelector(`.dna-result-output[data-output-key="${cssAttributeValue(focusedOutput)}"] .dna-result-output-trigger`)?.focus({ preventScroll: true });
  }
  const restoredStage = focusedStage || hoveredStage;
  if (restoredStage) {
    const restoredPopover = stageWrap.querySelector(`.dna-base-popover[data-stage="${restoredStage}"]`);
    if (restoredPopover) {
      restoredPopover.classList.add('hover-restored');
      window.setTimeout(() => restoredPopover.classList.remove('hover-restored'), 300);
    }
  }
  helix.dataset.rendered = '1';
  helix.dataset.renderKey = renderKey;
}

function stageFromLine(line) {
  if (/=== Stage: (Preparing ClusterWeave project layout|Installing NCBI CLI|Preparing genomes from accessions)/i.test(line)) return 'prep';
  if (/Stage 1\/4: running run_annotation_and_detection\.sh/i.test(line)) return 'annotation';
  if (/Stage 2\/4: running run_bigscape\.sh/i.test(line)) return 'bigscape';
  if (/Stage 3\/4: running summarize_clusterweave\.sh/i.test(line)) return 'summary';
  if (/Stage 4\/4: running run_clinker\.sh/i.test(line)) return 'clinker';
  if (/=== Stage: Rendering summary figures/i.test(line)) return 'figures';
  if (/=== Stage: Running optional NPLinker follow-up/i.test(line)) return 'nplinker';
  return null;
}

function advanceToStage(key) {
  if (!activeStageState || !activeStageState.enabled.has(key)) return;
  const nextIdx = stageIndex(key);
  if (activeStageState.current && activeStageState.current !== key) {
    const currentIdx = stageIndex(activeStageState.current);
    if (currentIdx >= 0 && currentIdx < nextIdx) activeStageState.completed.add(activeStageState.current);
    if (!activeStageState.endedAt[activeStageState.current]) activeStageState.endedAt[activeStageState.current] = Date.now();
  }
  for (let i = 0; i < nextIdx; i++) {
    const prior = STAGES[i].key;
    if (activeStageState.enabled.has(prior)) activeStageState.completed.add(prior);
  }
  if (!activeStageState.startedAt[key]) activeStageState.startedAt[key] = Date.now();
  activeStageState.current = key;
  activeStageState.failed = null;
  startStageTicker();
  renderStageState();
}

function sanitizeWeaveLogTitle(line) {
  let title = String(line || '')
    .replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '')
    .replace(/^\[\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\]\s*/, '')
    .replace(/^\[(INFO|WARN|ERROR|WORK)\]\s*/i, '')
    .replace(/^\$\s*/, '')
    .trim();
  title = title
    .replace(/\/data\/jobs\/[^\s)]+/g, 'job workspace')
    .replace(/\/clusterweave\/[^\s)]+/g, 'workflow helper')
    .replace(/\s+/g, ' ')
    .trim();
  return title.length > 96 ? `${title.slice(0, 93)}...` : title;
}

function recordWeaveLogActivity(line, stageKey = '') {
  if (!activeJobMeta || !weaveActivity || !weaveActivity.jobId) return;
  const title = sanitizeWeaveLogTitle(line);
  if (!title || /^New version of client/i.test(title)) return;
  if (!/antiSMASH|genome|Stage|flags|process|staged|complete|queued|running|prepared|input/i.test(title)) return;
  const stage = stageKey || activeStageState?.current || jobCurrentStageKey(activeJobMeta) || 'prep';
  const timeMatch = String(line || '').match(/^\[(\d{2}:\d{2}:\d{2})\]/);
  const meta = timeMatch ? timeMatch[1] : formatWorkflowTime(activeJobMeta.updated_at || activeJobMeta.created_at);
  const key = `${stage}|${title}|${meta}`;
  if (weaveActivity.events.some(event => `${event.stage}|${event.title}|${event.meta}` === key)) return;
  weaveActivity.events.push({ stage, title, meta });
  if (weaveActivity.events.length > 18) weaveActivity.events = weaveActivity.events.slice(-18);
}

function updateStageBar(line) {
  const key = stageFromLine(line);
  if (key) advanceToStage(key);
  recordWeaveLogActivity(line, key);
  if (/FATAL:|ERROR:|failed with exit code/i.test(line) && activeStageState && activeStageState.current) {
    activeStageState.failed = activeStageState.current;
    renderStageState();
  }
}

function finalizeStageState(status) {
  if (!activeStageState) return;
  if (status === 'success') {
    const now = Date.now();
    if (activeStageState.current && !activeStageState.endedAt[activeStageState.current]) activeStageState.endedAt[activeStageState.current] = now;
    for (const key of activeStageState.enabled) activeStageState.completed.add(key);
    activeStageState.current = null;
    activeStageState.failed = null;
  } else if (status === 'failed' && activeStageState.current) {
    activeStageState.failed = activeStageState.current;
    if (!activeStageState.endedAt[activeStageState.current]) activeStageState.endedAt[activeStageState.current] = Date.now();
  }
  renderStageState();
}

function renderStageState() {
  if (!activeStageState) return;
  document.querySelectorAll('.stage-step').forEach(el => {
    const key = el.dataset.stage;
    const stageLabel = (STAGES.find(s => s.key === key) || {}).label || key;
    const stateEl = el.querySelector('.stage-state');
    let stateLabel = 'Queued';
    el.classList.remove('active','done','upcoming','disabled','failed','complete');
    const visual = stageVisualState(key);
    el.classList.add(visual.cls);
    stateLabel = visual.label;
    if (visual.cls === 'active' || visual.cls === 'failed') el.setAttribute('aria-current', 'step');
    else el.removeAttribute('aria-current');
    if (stateEl) stateEl.textContent = stateLabel;
    el.setAttribute('aria-label', `${stageLabel}: ${stateLabel}`);
  });
  renderWeaveHelix(activeJobMeta);
  updateStageTelemetry();
}


function updateProgressBadge(status) {
  setStatusBadge(document.getElementById('progress-badge'), status, activeJobMeta);
  finalizeStageState(status);
}

// ── Results ────────────────────────────────────────────────────────────────
function queueStatusForJob(job = activeJobMeta) {
  const queue = job && job.queue_status;
  return queue && typeof queue === 'object' ? queue : null;
}

function queueStatusLabel(job = activeJobMeta) {
  const queue = queueStatusForJob(job);
  if (!queue) return 'Queued';
  if (queue.state === 'running') return 'Running';
  if (queue.state === 'claiming') return 'Claiming worker slot';
  const position = Number(queue.position || 0);
  return position > 0 ? `Queued #${position}` : 'Queued';
}

function queueStatusDetail(job = activeJobMeta) {
  const queue = queueStatusForJob(job);
  if (!queue) return 'Waiting for a worker slot.';
  return String(queue.detail || 'Waiting for a worker slot.');
}

function statusBadgeModel(status, job = activeJobMeta) {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'success') return ['badge-success', 'Complete'];
  if (normalized === 'failed') return ['badge-failed', 'Failed'];
  if (normalized === 'running') return ['badge-running', 'Running'];
  if (normalized === 'pending') return ['badge-pending', queueStatusLabel(job)];
  return ['badge-pending', status || 'Pending'];
}

function setStatusBadge(el, status, job = activeJobMeta) {
  if (!el) return;
  const [cls, label] = statusBadgeModel(status, job);
  el.className = 'badge ' + cls;
  el.innerHTML = `<span class="badge-dot"></span> ${escapeHtml(label)}`;
}

function pendingQueueNote(job = activeJobMeta) {
  const status = String((job && job.status) || '').toLowerCase();
  if (status !== 'pending') return '';
  return `<div class="queue-wait-note">${escapeHtml(queueStatusDetail(job))}</div>`;
}

function renderCompletionCallout(status) {
  const callout = document.getElementById('completion-callout');
  if (!callout) return;
  callout.classList.add('hidden');
  callout.setAttribute('aria-hidden', 'true');
}

function setResultFocusMode(mode) {
  resultFocusMode = mode === 'focused' ? 'focused' : 'overview';
  document.body.dataset.resultFocus = resultFocusMode;
}

function setResultsPanelCollapsed(collapsed) {
  const shouldCollapse = collapsed !== false;
  document.body.dataset.resultsPanel = shouldCollapse ? 'collapsed' : 'open';
  const toggle = document.getElementById('results-panel-toggle');
  if (!toggle) return;
  toggle.setAttribute('aria-expanded', shouldCollapse ? 'false' : 'true');
  toggle.title = shouldCollapse ? 'Show results access panel' : 'Collapse results access panel';
  const icon = toggle.querySelector('[data-results-toggle-icon]');
  const label = toggle.querySelector('[data-results-toggle-label]');
  if (icon) icon.textContent = shouldCollapse ? '‹' : '›';
  if (label) label.textContent = shouldCollapse ? 'Show results access panel' : 'Collapse results access panel';
}

function toggleResultsPanel() {
  setResultsPanelCollapsed(document.body.dataset.resultsPanel === 'open');
}

function resultCategoryKey(category) {
  const key = String(category || '').toLowerCase();
  const aliases = {
    summary: 'summaries',
    summaries: 'summaries',
    antismash: 'antismash',
    funbgcex: 'funbgcex',
    bigscape: 'bigscape',
    figures: 'figures',
    synteny: 'synteny',
    other: 'other',
    downloads: 'downloads',
    files: 'downloads',
  };
  return aliases[key] || 'downloads';
}

function resultPathExt(path) {
  const name = fileNameFromPath(path).toLowerCase();
  return name.includes('.') ? name.split('.').pop() : '';
}

function isHtmlAsset(path) {
  return ['html', 'htm'].includes(resultPathExt(path));
}

function isDataResultsZip(path) {
  const normalized = normalizedResultPath(path);
  return /^downloads\/[^/]+_public_results\.zip$/i.test(normalized) || /\/downloads\/[^/]+_public_results\.zip$/i.test(normalized);
}

function isAntiSmashArtifact(path) {
  return /(^|\/)antismash(\/|$)/i.test(normalizedResultPath(path));
}

function isAntiSmashHtmlArtifact(path) {
  return isAntiSmashArtifact(path) && isHtmlAsset(path);
}

function isFunbgcexArtifact(path) {
  return /(^|\/)funbgcex(\/|$)/i.test(normalizedResultPath(path));
}

function isFunbgcexHtmlArtifact(path) {
  return isFunbgcexArtifact(path) && isHtmlAsset(path);
}

function isBigscapeArtifact(path) {
  return /(^|\/)(big_scape|bigscape|big-s[c]?ape)(\/|$)/i.test(normalizedResultPath(path));
}

function isBigscapeHtmlArtifact(path) {
  return isBigscapeArtifact(path) && isHtmlAsset(path);
}

function isBigscapeDatabaseArtifact(path) {
  return isBigscapeArtifact(path) && ['db', 'sqlite', 'sqlite3'].includes(resultPathExt(path));
}

function isSummaryArtifact(path) {
  const normalized = normalizedResultPath(path);
  if (!/(^|\/)(summary|summary_tables)(\/|$)/i.test(normalized)) return false;
  if (isDataResultsZip(normalized)) return false;
  const ext = resultPathExt(normalized);
  return ['html', 'htm', 'md', 'tsv', 'csv', 'txt'].includes(ext);
}

function isAtlasShortlistArtifact(path) {
  const normalized = normalizedResultPath(path);
  if (!isSummaryArtifact(normalized)) return false;
  return /^family_atlas_shortlist\.(md|tsv|csv|txt|html?)$/i.test(fileNameFromPath(normalized));
}

function isSyntenyArtifact(path) {
  return /(^|\/)(clinker|synteny)(\/|$)|\/panel\.html$|\/panels?\//i.test(normalizedResultPath(path));
}

function isPrimaryResultCategory(path) {
  return isFigureAsset(path)
    || isAntiSmashArtifact(path)
    || isFunbgcexArtifact(path)
    || isBigscapeArtifact(path)
    || isSummaryArtifact(path)
    || isSyntenyArtifact(path)
    || isDataResultsZip(path);
}

function resultCategoryMatches(category, path) {
  const key = resultCategoryKey(category);
  if (key === 'figures') return isFigureAsset(path);
  if (key === 'antismash') return isAntiSmashArtifact(path);
  if (key === 'funbgcex') return isFunbgcexArtifact(path);
  if (key === 'bigscape') return isBigscapeArtifact(path);
  if (key === 'summaries') return isSummaryArtifact(path);
  if (key === 'synteny') return isSyntenyArtifact(path);
  if (key === 'other') return !isPrimaryResultCategory(path);
  return true;
}

function resultPathParts(path) {
  return normalizedResultPath(path).split('/').filter(Boolean);
}

function toolSegmentIndex(path, matcher) {
  return resultPathParts(path).findIndex(part => matcher.test(part));
}

function readableArtifactLabel(value, fallback = 'artifact') {
  const raw = String(value || fallback || '').trim() || fallback;
  try { return decodeURIComponent(raw).replace(/[_]+/g, ' '); }
  catch (e) { return raw.replace(/[_]+/g, ' '); }
}

function titleCaseArtifactLabel(value, fallback = 'artifact') {
  return readableArtifactLabel(value, fallback)
    .replace(/[-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b([a-z])/g, ch => ch.toUpperCase());
}

function fileStemFromPath(path) {
  const name = fileNameFromPath(path);
  return name.includes('.') ? name.slice(0, name.lastIndexOf('.')) : name;
}

function summaryArtifactLabel(path) {
  const name = fileNameFromPath(path).toLowerCase();
  const ext = resultPathExt(path).toUpperCase();
  if (/^family_atlas_shortlist\./i.test(name)) return `Family atlas shortlist ${ext}`.trim();
  if (/priority|shortlist/i.test(name)) return `${titleCaseArtifactLabel(fileStemFromPath(path), 'Summary')} ${ext}`.trim();
  return `${titleCaseArtifactLabel(fileStemFromPath(path), 'Summary')} ${ext}`.trim();
}

function syntenyArtifactLabel(path) {
  const parts = resultPathParts(path);
  const idx = parts.findIndex(part => /^(clinker|synteny|clinker_shared_family)$/i.test(part));
  const filename = fileNameFromPath(path);
  const artifact = /^panel\.html$/i.test(filename) ? 'synteny panel.html' : readableArtifactLabel(filename, 'synteny artifact');
  const ignored = /^(panels?|html|assets?|static|scripts?|styles?|css|js|atlas|priority|prioritized?|shared[-_]?family|shared|family|track|tracks)$/i;
  let compound = '';
  for (let i = Math.max(0, idx + 1); i < parts.length - 1; i += 1) {
    if (!ignored.test(parts[i])) {
      compound = titleCaseArtifactLabel(parts[i], 'clinker');
      break;
    }
  }
  return compound ? `${compound} - ${artifact}` : artifact;
}

function artifactMetaLabel(path, category = '') {
  const key = resultCategoryKey(category);
  if (key === 'antismash') return `${toolGenomeLabel(path, 'antismash')} HTML view`;
  if (key === 'funbgcex') return `${toolGenomeLabel(path, 'funbgcex')} HTML view`;
  if (key === 'bigscape') return isBigscapeDatabaseArtifact(path)
    ? `BiG-SCAPE database ${fileNameFromPath(path)}`
    : 'BiG-SCAPE web view';
  if (key === 'summaries') return summaryArtifactLabel(path);
  if (key === 'synteny') return isHtmlAsset(path) ? 'clinker synteny HTML panel' : 'clinker synteny artifact';
  if (key === 'figures') return figureCaption(path);
  return readableArtifactLabel(fileNameFromPath(path), 'artifact');
}

function toolGenomeLabel(path, toolKey) {
  const parts = resultPathParts(path);
  const matcher = toolKey === 'antismash' ? /^antismash$/i : /^funbgcex$/i;
  const idx = parts.findIndex(part => matcher.test(part));
  const after = idx >= 0 ? parts[idx + 1] : '';
  if (after && !/\.html?$/i.test(after)) return readableArtifactLabel(after, fileNameFromPath(path));
  const parent = parts.length > 1 ? parts[parts.length - 2] : '';
  if (parent && !matcher.test(parent)) return readableArtifactLabel(parent, fileNameFromPath(path));
  return toolKey === 'antismash' ? 'antiSMASH index' : 'FunBGCeX index';
}

function toolHtmlSortKey(path) {
  const name = fileNameFromPath(path).toLowerCase();
  const normalized = normalizedResultPath(path).toLowerCase();
  const priority = name === 'index.html' ? 0 : /overview|results?|knowncluster/.test(name) ? 1 : 2;
  return `${priority}:${normalized}`;
}

function uniqueToolHtmlArtifacts(files, toolKey) {
  const predicate = toolKey === 'antismash' ? isAntiSmashHtmlArtifact : isFunbgcexHtmlArtifact;
  const grouped = new Map();
  (files || []).filter(predicate).sort((a, b) => toolHtmlSortKey(a).localeCompare(toolHtmlSortKey(b))).forEach(path => {
    const label = toolGenomeLabel(path, toolKey);
    if (!grouped.has(label)) grouped.set(label, { label, path });
  });
  return Array.from(grouped.values()).sort((a, b) => a.label.localeCompare(b.label));
}

function sharedPathPrefixScore(a, b) {
  const left = resultPathParts(a);
  const right = resultPathParts(b);
  let score = 0;
  for (let i = 0; i < Math.min(left.length, right.length); i += 1) {
    if (left[i] !== right[i]) break;
    score += 1;
  }
  return score;
}

function bigscapeHtmlSortKey(path) {
  const name = fileNameFromPath(path).toLowerCase();
  const priority = name === 'index.html' ? 0 : /visual|network|bigscape|app/.test(name) ? 1 : 2;
  return `${priority}:${normalizedResultPath(path).toLowerCase()}`;
}

function chooseBigscapeDatabase(htmlPath, databaseFiles) {
  if (!htmlPath || !databaseFiles.length) return '';
  return databaseFiles.slice().sort((a, b) => {
    const scoreDelta = sharedPathPrefixScore(b, htmlPath) - sharedPathPrefixScore(a, htmlPath);
    if (scoreDelta) return scoreDelta;
    return normalizedResultPath(a).localeCompare(normalizedResultPath(b));
  })[0] || '';
}

function summarySortKey(path) {
  const normalized = normalizedResultPath(path).toLowerCase();
  const name = fileNameFromPath(path).toLowerCase();
  const preferred = [
    'family_atlas_shortlist.md',
    'family_atlas_shortlist.tsv',
    'priority_shortlist.md',
    'priority_shortlist.tsv',
    'targeted_candidate_ranking.tsv',
    'bigscape_family_atlas.tsv',
    'all_tools_shared_unshared_summary.csv',
  ];
  const idx = preferred.indexOf(name);
  return `${idx === -1 ? preferred.length : idx}:${normalized}`;
}

function buildResultArtifacts(files) {
  const normalized = (files || []).map(normalizedResultPath).filter(Boolean);
  const bigscapeHtmlFiles = normalized.filter(isBigscapeHtmlArtifact).sort((a, b) => bigscapeHtmlSortKey(a).localeCompare(bigscapeHtmlSortKey(b)));
  const bigscapeDatabaseFiles = normalized.filter(isBigscapeDatabaseArtifact).sort((a, b) => normalizedResultPath(a).localeCompare(normalizedResultPath(b)));
  const bigscapeHtml = bigscapeHtmlFiles[0] || '';
  const bigscapeDatabase = chooseBigscapeDatabase(bigscapeHtml, bigscapeDatabaseFiles);
  return {
    files: normalized,
    antismash: uniqueToolHtmlArtifacts(normalized, 'antismash'),
    funbgcex: uniqueToolHtmlArtifacts(normalized, 'funbgcex'),
    bigscape: {
      html: bigscapeHtml,
      database: bigscapeDatabase,
      htmlFiles: bigscapeHtmlFiles,
      databaseFiles: bigscapeDatabaseFiles,
    },
    summaries: normalized.filter(isAtlasShortlistArtifact).sort((a, b) => summarySortKey(a).localeCompare(summarySortKey(b))),
    synteny: normalized.filter(isSyntenyArtifact).sort((a, b) => normalizedResultPath(a).localeCompare(normalizedResultPath(b))),
    figures: normalized.filter(isFigureAsset).sort((a, b) => figureSortKey(a).localeCompare(figureSortKey(b))),
  };
}

function resultArtifacts(files = activeResultFiles) {
  activeResultArtifacts = buildResultArtifacts(files);
  return activeResultArtifacts;
}

function resultCategoryCounts(files) {
  const normalized = (files || []).map(normalizedResultPath).filter(Boolean);
  const artifacts = buildResultArtifacts(normalized);
  const other = normalized.filter(path => resultCategoryMatches('other', path)).length;
  return {
    figures: artifacts.figures.length,
    antismash: artifacts.antismash.length,
    funbgcex: artifacts.funbgcex.length,
    bigscape: artifacts.bigscape.html && artifacts.bigscape.database ? 1 : 0,
    summaries: artifacts.summaries.length,
    synteny: artifacts.synteny.length,
    other,
    downloads: normalized.length,
  };
}

function resultCategoryAvailable(category, counts) {
  const key = resultCategoryKey(category);
  return Number((counts || {})[key] || 0) > 0;
}

function firstAvailableResultCategory(counts) {
  return ['antismash', 'funbgcex', 'bigscape', 'summaries', 'synteny', 'figures', 'downloads']
    .find(key => resultCategoryAvailable(key, counts)) || 'downloads';
}

function resultFilesForCategory(category, files) {
  const key = resultCategoryKey(category);
  const normalized = (files || []).map(normalizedResultPath).filter(Boolean);
  if (key === 'downloads') return normalized;
  return normalized.filter(path => resultCategoryMatches(key, path));
}

function resultCategoryLabel(category) {
  const labels = {
    figures: 'Figures',
    antismash: 'antiSMASH',
    funbgcex: 'FunBGCeX',
    bigscape: 'BiG-SCAPE',
    summaries: 'Summary atlas',
    synteny: 'Synteny panels',
    other: 'Other artifacts',
    downloads: 'Files',
  };
  return labels[resultCategoryKey(category)] || labels.downloads;
}

function resultCategoryCopy(category) {
  const copy = {
    figures: 'Generated figures with zoomable previews.',
    antismash: 'Genome-level antiSMASH result views.',
    funbgcex: 'Genome-level FunBGCeX result views.',
    bigscape: 'BiG-SCAPE web view paired with its database file.',
    summaries: 'ClusterWeave atlas and priority summary documents.',
    synteny: 'clinker synteny panels with compound context.',
    other: 'Additional indexed files from this run.',
    downloads: 'Every available file, shown as download-only rows.',
  };
  return copy[resultCategoryKey(category)] || copy.downloads;
}

function resultCategoryIcon(category) {
  const icons = { antismash: '06', funbgcex: '07', bigscape: '08', summaries: '09', figures: '10', synteny: 'SYN', other: 'OUT', downloads: 'ZIP' };
  return icons[resultCategoryKey(category)] || 'OUT';
}

function resultLollipopItems(artifacts = activeResultArtifacts || buildResultArtifacts(activeResultFiles)) {
  const items = [];
  if (artifacts.antismash.length) {
    items.push({ key: 'antismash', count: artifacts.antismash.length, unit: 'view', label: resultCategoryLabel('antismash'), copy: resultCategoryCopy('antismash'), icon: resultCategoryIcon('antismash') });
  }
  if (artifacts.funbgcex.length) {
    items.push({ key: 'funbgcex', count: artifacts.funbgcex.length, unit: 'view', label: resultCategoryLabel('funbgcex'), copy: resultCategoryCopy('funbgcex'), icon: resultCategoryIcon('funbgcex') });
  }
  if (artifacts.bigscape.html && artifacts.bigscape.database) {
    items.push({ key: 'bigscape', count: 2, unit: 'file', label: resultCategoryLabel('bigscape'), copy: resultCategoryCopy('bigscape'), icon: resultCategoryIcon('bigscape') });
  }
  if (artifacts.summaries.length) {
    items.push({ key: 'summaries', count: artifacts.summaries.length, unit: 'file', label: resultCategoryLabel('summaries'), copy: resultCategoryCopy('summaries'), icon: resultCategoryIcon('summaries') });
  }
  if (artifacts.synteny.length) {
    items.push({ key: 'synteny', count: artifacts.synteny.length, unit: 'panel', label: resultCategoryLabel('synteny'), copy: resultCategoryCopy('synteny'), icon: resultCategoryIcon('synteny') });
  }
  if (artifacts.figures.length) {
    items.push({ key: 'figures', count: artifacts.figures.length, unit: 'figure', label: resultCategoryLabel('figures'), copy: resultCategoryCopy('figures'), icon: resultCategoryIcon('figures') });
  }
  return items;
}

function resultCategoryItems(counts) {
  return resultLollipopItems(activeResultArtifacts || buildResultArtifacts(activeResultFiles)).filter(item => resultCategoryAvailable(item.key, counts));
}

function renderResultOverviewPanel(items, counts) {
  const panel = document.getElementById('result-overview-panel');
  if (!panel) return;
  if (!items.length) {
    const fallback = Number((counts || {}).downloads || 0) > 0
      ? 'No tool-specific output nodes were found in this run. Use the full package download for the indexed files.'
      : 'No web-facing result artifacts were indexed for this run.';
    panel.innerHTML = `<div class="empty-state">${escapeHtml(fallback)}</div>`;
    return;
  }
  const nodeList = items.map(item => {
    const countLabel = `${item.count} ${item.unit}${item.count === 1 ? '' : 's'}`;
    return `${item.icon} ${item.label} (${countLabel})`;
  }).join(' · ');
  panel.innerHTML = `<div class="result-overview-copy">Output choices are generated from matching result files only. ${escapeHtml(nodeList)}</div>`;
}

function updateResultDashboardVisibility(status, fileCount = null) {
  const panel = document.getElementById('result-bubble-panel');
  if (!panel) return;
  const loaded = !!activeJobMeta;
  const files = fileCount === null ? Number(panel.dataset.fileCount || 0) : Number(fileCount || 0);
  const shouldShow = loaded && resultDashboardOpen;
  const board = document.getElementById('result-dashboard-section');
  panel.classList.toggle('hidden', !shouldShow);
  if (board) board.classList.toggle('hidden', !shouldShow);
  document.querySelectorAll('.result-dashboard-surface').forEach(el => {
    if (el.id === 'result-dashboard-section') return;
    el.classList.toggle('hidden', !shouldShow);
  });
  setStatusBadge(document.getElementById('result-flow-status'), status || panel.dataset.status || '', activeJobMeta);
  const focusLabel = document.getElementById('result-focus-label');
  if (focusLabel && resultFocusMode === 'overview') focusLabel.textContent = files ? 'Choose an output' : 'No output nodes indexed';
  updateArchiveButton();
}

function renderResultBubblePanel(files, status) {
  const panel = document.getElementById('result-bubble-panel');
  if (!panel) return;
  activeResultFiles = (files || []).map(normalizedResultPath).filter(Boolean);
  const artifacts = resultArtifacts(activeResultFiles);
  const counts = resultCategoryCounts(activeResultFiles);
  const items = resultLollipopItems(artifacts);
  if (resultFocusMode === 'focused' && !resultCategoryAvailable(activeResultCategory, counts)) {
    setResultFocusMode('overview');
    activeResultCategory = firstAvailableResultCategory(counts);
  }
  panel.dataset.status = String(status || '');
  panel.dataset.fileCount = String(counts.downloads);
  panel.innerHTML = items.map(item => {
    const selected = resultFocusMode === 'focused' && item.key === activeResultCategory;
    const countLabel = `${item.count} ${item.unit}${item.count === 1 ? '' : 's'}`;
    const jsKey = escapeJsString(item.key);
    return `
    <button class="result-bubble result-lollipop${selected ? ' active is-selected' : ''}${resultFocusMode === 'focused' && !selected ? ' is-dimmed' : ''}" type="button" data-output-key="${escapeHtml(item.key)}" data-output-node="${escapeHtml(item.icon)}" onclick="focusResultCategory('${escapeHtml(jsKey)}', event)" aria-pressed="${selected ? 'true' : 'false'}" aria-controls="result-focus-panel">
      <span class="result-bubble-icon" aria-hidden="true">${escapeHtml(item.icon)}</span>
      <span class="result-bubble-label">${escapeHtml(item.label)}</span>
      <span class="result-bubble-count">${escapeHtml(countLabel)}</span>
      <span class="result-bubble-copy">${escapeHtml(item.copy)}</span>
    </button>`;
  }).join('');
  renderResultOverviewPanel(items, counts);
  updateResultDashboardVisibility(status, counts.downloads);
  rerenderWorkflowSpineForResults();
}

function updateArchiveButton() {
  const btn = document.getElementById('download-package-btn');
  if (!btn) return;
  const inFlight = !!(activeArchiveDownload && activeArchiveDownload.jobId === activeJobId);
  btn.disabled = !activeJobId || !activeResultFiles.length || inFlight;
  btn.textContent = inFlight ? 'Preparing package...' : 'Download full package';
}

function cancelActiveArchiveDownload() {
  resultArchiveRequestSeq += 1;
  if (activeArchiveDownload?.controller) {
    try { activeArchiveDownload.controller.abort(); } catch (err) {}
  }
  activeArchiveDownload = null;
  updateArchiveButton();
}

async function downloadResultArchive(event) {
  event?.preventDefault?.();
  if (!activeJobId || activeArchiveDownload) return false;
  const requestJobId = activeJobId;
  const requestId = ++resultArchiveRequestSeq;
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  activeArchiveDownload = { jobId: requestJobId, requestId, controller };
  updateArchiveButton();
  try {
    const options = controller ? { signal: controller.signal } : {};
    const resp = await apiFetch(`api/jobs/${encodeURIComponent(requestJobId)}/archive`, options, { kind: 'job', jobId: requestJobId });
    if (!resp.ok) throw new Error('Full package download is not available for this run yet.');
    const blob = await resp.blob();
    if (activeJobId !== requestJobId || activeArchiveDownload?.requestId !== requestId) return false;
    if (resultArchiveObjectUrl) URL.revokeObjectURL(resultArchiveObjectUrl);
    resultArchiveObjectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = resultArchiveObjectUrl;
    a.download = `${requestJobId}_clusterweave_results.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } catch (err) {
    if (err?.name !== 'AbortError' && activeJobId === requestJobId && activeArchiveDownload?.requestId === requestId) {
      const btn = document.getElementById('download-package-btn');
      if (btn) btn.textContent = err.message || 'Package unavailable';
      setTimeout(() => {
        if (activeJobId === requestJobId) updateArchiveButton();
      }, 2600);
    }
  } finally {
    if (activeArchiveDownload?.requestId === requestId) activeArchiveDownload = null;
    updateArchiveButton();
  }
  return false;
}


function scrollResultSpineToStage(stageKey) {
  if (document.body.dataset.resultsDashboard !== 'open') return;
  const spine = document.getElementById('weavemap');
  const stage = document.querySelector(`.dna-stage[data-stage="${cssAttributeValue(stageKey)}"]`);
  if (!spine || !stage) return;
  const spineRect = spine.getBoundingClientRect();
  const stageRect = stage.getBoundingClientRect();
  if (!stageRect.width && !stageRect.height) return;
  const maxScroll = Math.max(0, spine.scrollHeight - spine.clientHeight);
  const target = spine.scrollTop
    + (stageRect.top + stageRect.height / 2)
    - (spineRect.top + spine.clientHeight * .52);
  spine.scrollTop = clampNumber(target, 0, maxScroll);
}

function focusResultCategory(category, event = null) {
  const key = resultCategoryKey(category);
  const counts = resultCategoryCounts(activeResultFiles);
  if (!resultCategoryAvailable(key, counts)) return;
  activeResultCategory = key;
  setResultFocusMode('focused');
  renderResultBubblePanel(activeResultFiles, activeJobMeta?.status || '');
  renderFocusedResultCategory(key);
  const stageKey = resultOutputStageKey(key);
  const alignStage = () => {
    scrollResultSpineToStage(stageKey);
    scheduleDnaOverlaySync();
  };
  window.requestAnimationFrame(alignStage);
  window.setTimeout(alignStage, 180);
  const pointerClick = event && event.type === 'click' && Number(event.detail || 0) > 0;
  if (!pointerClick) {
    const target = document.getElementById('result-focus-panel') || document.getElementById('result-dashboard-section');
    target?.focus({ preventScroll: true });
  }
}

function clearResultFocus() {
  setResultFocusMode('overview');
  renderResultBubblePanel(activeResultFiles, activeJobMeta?.status || '');
  const firstOutput = document.querySelector('.dna-result-output-trigger');
  (firstOutput || document.getElementById('weavemap'))?.focus({ preventScroll: true });
}

function setResultFocusLabel(category) {
  const label = document.getElementById('result-focus-label');
  if (!label) return;
  label.textContent = resultFocusMode === 'focused'
    ? `${resultCategoryLabel(category)} selected`
    : 'Choose an output';
}

function renderResultFileSurface(jobId, files) {
  if (resultFocusMode === 'focused') {
    renderFocusedResultCategory(activeResultCategory);
    return;
  }
  renderFileTable(jobId, files);
}

function renderFocusedResultCategory(category) {
  const key = resultCategoryKey(category);
  const artifacts = resultArtifacts(activeResultFiles);
  setResultFocusLabel(key);
  if (key === 'figures') {
    switchTab('viz', { preserveCategory: true });
    if (activeJobId) renderViz(activeJobId, activeResultFiles);
    return;
  }
  switchTab('files', { preserveCategory: true });
  if (!activeJobId) return;
  if (key === 'antismash') {
    renderToolHtmlReader(activeJobId, 'antismash', artifacts.antismash);
    return;
  }
  if (key === 'funbgcex') {
    renderToolHtmlReader(activeJobId, 'funbgcex', artifacts.funbgcex);
    return;
  }
  if (key === 'bigscape') {
    renderBigscapeReader(activeJobId, artifacts.bigscape);
    return;
  }
  if (key === 'summaries') {
    renderSummaryReader(activeJobId, artifacts.summaries);
    return;
  }
  if (key === 'synteny') {
    renderSyntenyReader(activeJobId, artifacts.synteny);
    return;
  }
  renderFileTable(activeJobId, activeResultFiles, { category: key });
}

function artifactReaderHead(category, countLabel) {
  return `
    <div class="artifact-reader-head">
      <div>
        <div class="artifact-reader-title">${escapeHtml(resultCategoryLabel(category))}</div>
        <div class="artifact-reader-copy">${escapeHtml(resultCategoryCopy(category))}</div>
      </div>
      <span class="ext-badge">${escapeHtml(countLabel)}</span>
    </div>`;
}

function resultOpenLink(jobId, path, label = 'Open') {
  if (isHtmlAsset(path) && !canOpenRichHtmlArtifacts(jobId)) {
    return resultDownloadLink(jobId, path, 'Download HTML');
  }
  const href = resultHref(jobId, path);
  const jsJobId = escapeJsString(jobId);
  const jsPath = escapeJsString(path);
  return `<a class="btn btn-ghost text-sm" href="${escapeHtml(href)}" target="_blank" onclick="return handleResultLinkClick(event,'${escapeHtml(jsJobId)}','${escapeHtml(jsPath)}',false)">${escapeHtml(label)}</a>`;
}

function resultDownloadLink(jobId, path, label = 'Download') {
  const href = resultHref(jobId, path, { download: true });
  const name = fileNameFromPath(path);
  const jsJobId = escapeJsString(jobId);
  const jsPath = escapeJsString(path);
  return `<a class="btn btn-ghost text-sm" href="${escapeHtml(href)}" download="${escapeHtml(name)}" onclick="return handleResultLinkClick(event,'${escapeHtml(jsJobId)}','${escapeHtml(jsPath)}',true)">${escapeHtml(label)}</a>`;
}

function renderToolHtmlReader(jobId, toolKey, items) {
  const container = document.getElementById('files-container');
  if (!container) return;
  const category = toolKey === 'antismash' ? 'antismash' : 'funbgcex';
  if (!items.length) {
    container.innerHTML = `<div class="empty-state">No ${escapeHtml(resultCategoryLabel(category))} HTML views were found for this run.</div>`;
    return;
  }
  const rows = items.map(item => `
    <div class="artifact-row">
      <div>
        <div class="artifact-row-name">${escapeHtml(item.label)}</div>
        <div class="artifact-row-meta">${escapeHtml(artifactMetaLabel(item.path, category))}</div>
      </div>
      <div class="artifact-row-actions">${resultOpenLink(jobId, item.path, 'Open HTML')}</div>
    </div>`).join('');
  container.innerHTML = `
    <div class="artifact-reader">
      ${artifactReaderHead(category, `${items.length} ${items.length === 1 ? 'view' : 'views'}`)}
      <div class="artifact-list">${rows}</div>
    </div>`;
}

function renderSyntenyReader(jobId, items) {
  const container = document.getElementById('files-container');
  if (!container) return;
  const syntenyFiles = (items || []).map(normalizedResultPath).filter(Boolean);
  if (!syntenyFiles.length) {
    container.innerHTML = '<div class="empty-state">No synteny panel artifacts were found for this run.</div>';
    return;
  }
  const rows = syntenyFiles.map(path => {
    const label = syntenyArtifactLabel(path);
    const action = isHtmlAsset(path) ? resultOpenLink(jobId, path, 'Open panel') : resultDownloadLink(jobId, path);
    return `
    <div class="artifact-row">
      <div>
        <div class="artifact-row-name">${escapeHtml(label)}</div>
        <div class="artifact-row-meta">${escapeHtml(artifactMetaLabel(path, 'synteny'))}</div>
      </div>
      <div class="artifact-row-actions">${action}</div>
    </div>`;
  }).join('');
  container.innerHTML = `
    <div class="artifact-reader">
      ${artifactReaderHead('synteny', `${syntenyFiles.length} ${syntenyFiles.length === 1 ? 'panel' : 'panels'}`)}
      <div class="artifact-list">${rows}</div>
    </div>`;
}

function jsonForInlineScript(value) {
  return JSON.stringify(value).replace(/</g, '\\u003c');
}

function injectBigscapeDatabaseContract(htmlText, dbUrl, dbName, dbPath) {
  const headScript = `<script>window.CLUSTERWEAVE_BIGSCAPE_DATABASE_URL=${jsonForInlineScript(dbUrl)};window.CLUSTERWEAVE_BIGSCAPE_DATABASE_NAME=${jsonForInlineScript(dbName)};window.CLUSTERWEAVE_BIGSCAPE_DATABASE_PATH=${jsonForInlineScript(dbPath)};<\/script>`;
  const loaderScript = `<script>(function(){
  const url = window.CLUSTERWEAVE_BIGSCAPE_DATABASE_URL;
  const name = window.CLUSTERWEAVE_BIGSCAPE_DATABASE_NAME || 'data_sqlite.db';
  const path = window.CLUSTERWEAVE_BIGSCAPE_DATABASE_PATH || name;
  let loadPromise = null;
  let bufferPromise = null;

  function setStatus(message) {
    try { if (typeof window.showLoading === 'function') window.showLoading(message); } catch (e) {}
    const status = document.getElementById('status');
    if (status) status.textContent = message;
  }

  function fail(err) {
    const message = err && err.message ? err.message : 'ClusterWeave could not load the paired BiG-SCAPE database.';
    try { if (typeof window.sendError === 'function') window.sendError(message); } catch (e) {}
    const status = document.getElementById('status');
    if (status) status.textContent = message;
    throw err;
  }

  function waitForFunction(label, timeoutMs) {
    const started = Date.now();
    return new Promise((resolve, reject) => {
      function tick() {
        if (typeof window[label] === 'function') {
          resolve(window[label]);
          return;
        }
        if (Date.now() - started > timeoutMs) {
          reject(new Error(label + ' did not load before the database autoload timed out.'));
          return;
        }
        window.setTimeout(tick, 80);
      }
      tick();
    });
  }

  function fetchBuffer() {
    if (!bufferPromise) {
      bufferPromise = fetch(url).then(resp => {
        if (!resp.ok) throw new Error('BiG-SCAPE database fetch failed: HTTP ' + resp.status);
        return resp.arrayBuffer();
      });
    }
    return bufferPromise;
  }

  function attachInputFile(buffer) {
    const picker = document.querySelector('#db-selector, input[type="file"]');
    if (!picker || typeof File !== 'function' || typeof DataTransfer !== 'function') return;
    try {
      const file = new File([buffer], name, { type: 'application/vnd.sqlite3' });
      const transfer = new DataTransfer();
      transfer.items.add(file);
      picker.files = transfer.files;
      window.CLUSTERWEAVE_BIGSCAPE_DATABASE_FILE = file;
    } catch (e) {}
  }

  function emitReady() {
    const detail = { name: name, path: path, url: url };
    try { window.dispatchEvent(new CustomEvent('clusterweave:bigscape-database-ready', { detail: detail })); } catch (e) {}
    try { document.dispatchEvent(new CustomEvent('clusterweave:bigscape-database-ready', { detail: detail })); } catch (e) {}
  }

  async function autoloadDatabase() {
    if (!url) return null;
    if (loadPromise) return loadPromise;
    loadPromise = (async function(){
      setStatus('Loading BiG-SCAPE database: ' + name);
      const initSqlJs = await waitForFunction('initSqlJs', 24000);
      const dataLoaded = await waitForFunction('dataLoaded', 24000);
      const buffer = await fetchBuffer();
      attachInputFile(buffer);
      const SQL = await initSqlJs();
      window.db = new SQL.Database(new Uint8Array(buffer));
      window.CLUSTERWEAVE_BIGSCAPE_DATABASE_LOADED = true;
      const status = document.getElementById('status');
      if (status) status.textContent = 'Loaded ' + name;
      emitReady();
      dataLoaded();
      return window.db;
    })().catch(fail);
    return loadPromise;
  }

  window.CLUSTERWEAVE_BIGSCAPE_AUTOLOAD_DATABASE = autoloadDatabase;
  function scheduleAutoload() { window.setTimeout(function(){ autoloadDatabase().catch(function(){}); }, 0); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scheduleAutoload, { once: true });
  else scheduleAutoload();
  window.addEventListener('load', scheduleAutoload, { once: true });
})();<\/script>`;
  const withHead = /<head[^>]*>/i.test(htmlText)
    ? htmlText.replace(/<head([^>]*)>/i, `<head$1>${headScript}`)
    : `${headScript}${htmlText}`;
  if (/<\/body\s*>/i.test(withHead)) return withHead.replace(/<\/body\s*>/i, `${loaderScript}</body>`);
  return `${withHead}${loaderScript}`;
}

async function openBigscapeResult(event, jobId, htmlPath, databasePath) {
  event?.preventDefault?.();
  if (!jobId || !htmlPath || !databasePath) return false;
  let previewWindow = window.open('', '_blank');
  if (!previewWindow) {
    window.alert('Allow pop-ups for this site to open the paired BiG-SCAPE HTML and database view.');
    return false;
  }
  previewWindow.opener = null;
  previewWindow.document.title = 'BiG-SCAPE';
  previewWindow.document.body.textContent = 'Loading BiG-SCAPE result...';
  try {
    const [htmlResp, dbResp] = await Promise.all([
      resultFetch(jobId, htmlPath),
      resultFetch(jobId, databasePath),
    ]);
    if (!htmlResp.ok) throw new Error('BiG-SCAPE HTML view could not be opened with this result access code.');
    if (!dbResp.ok) throw new Error('BiG-SCAPE database artifact could not be opened with this result access code.');
    const [htmlText, dbBlob] = await Promise.all([htmlResp.text(), dbResp.blob()]);
    const dbName = fileNameFromPath(databasePath);
    const dbUrl = URL.createObjectURL(new Blob([dbBlob], { type: inlineResultMime(databasePath, dbResp.headers.get('Content-Type') || '') }));
    resultHelperObjectUrls.push(dbUrl);
    const htmlUrl = await buildHtmlResultObjectUrl(jobId, htmlPath, htmlText, {
      transform: text => injectBigscapeDatabaseContract(text, dbUrl, dbName, databasePath),
    });
    const hash = `#clusterweave-db=${encodeURIComponent(dbUrl)}&clusterweave-db-name=${encodeURIComponent(dbName)}&clusterweave-db-path=${encodeURIComponent(databasePath)}`;
    previewWindow.location.href = `${htmlUrl}${hash}`;
  } catch (err) {
    const message = err && err.message ? err.message : 'BiG-SCAPE result could not be opened.';
    previewWindow.document.body.innerHTML = `<pre style="white-space:pre-wrap;font:14px system-ui,sans-serif;color:#111">${escapeHtml(message)}</pre>`;
  }
  return false;
}

function renderBigscapeReader(jobId, bigscape) {
  const container = document.getElementById('files-container');
  if (!container) return;
  if (!bigscape || !bigscape.html || !bigscape.database) {
    container.innerHTML = '<div class="empty-state">BiG-SCAPE needs both a web HTML view and a database artifact before it can be opened here.</div>';
    return;
  }
  const jsJobId = escapeJsString(jobId);
  const jsHtml = escapeJsString(bigscape.html);
  const jsDb = escapeJsString(bigscape.database);
  const href = resultHref(jobId, bigscape.html);
  container.innerHTML = `
    <div class="artifact-reader">
      ${artifactReaderHead('bigscape', 'HTML + database')}
      <div class="artifact-row">
        <div>
          <div class="artifact-row-name">${escapeHtml(artifactMetaLabel(bigscape.html, 'bigscape'))}</div>
          <div class="artifact-row-meta">Web view paired with the selected database artifact</div>
        </div>
        <div class="artifact-row-actions">
          <a class="btn btn-primary text-sm" href="${escapeHtml(href)}" target="_blank" onclick="return openBigscapeResult(event,'${escapeHtml(jsJobId)}','${escapeHtml(jsHtml)}','${escapeHtml(jsDb)}')">Open BiG-SCAPE</a>
        </div>
      </div>
      <div class="artifact-row">
        <div>
          <div class="artifact-row-name">${escapeHtml(artifactMetaLabel(bigscape.database, 'bigscape'))}</div>
          <div class="artifact-row-meta">SQLite database for the BiG-SCAPE viewer</div>
        </div>
        <div class="artifact-row-actions">${resultDownloadLink(jobId, bigscape.database, 'Download DB')}</div>
      </div>
      <div class="bigscape-contract">Database contract: the launcher preloads the matched SQLite database into the bundled BiG-SCAPE viewer before the result graph starts.</div>
    </div>`;
}

function renderSummaryReader(jobId, summaryFiles) {
  const container = document.getElementById('files-container');
  if (!container) return;
  const atlasFiles = (summaryFiles || []).filter(isAtlasShortlistArtifact).sort((a, b) => summarySortKey(a).localeCompare(summarySortKey(b)));
  if (!atlasFiles.length) {
    container.innerHTML = '<div class="empty-state">No atlas shortlist artifact was found for this run.</div>';
    return;
  }
  const preferred = atlasFiles[0];
  container.innerHTML = `
    <div class="summary-reader">
      ${artifactReaderHead('summaries', 'Atlas shortlist')}
      <div class="summary-reader-source" id="summary-reader-source"></div>
      <div class="summary-reader-doc" id="summary-reader-doc"><div class="viz-placeholder text-sm">Loading summary document...</div></div>
    </div>`;
  loadSummaryReaderFile(preferred);
}

function parseDelimitedLine(line, delimiter) {
  const cells = [];
  let value = '';
  let quoted = false;
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i];
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') {
        value += '"';
        i += 1;
      } else {
        quoted = !quoted;
      }
    } else if (ch === delimiter && !quoted) {
      cells.push(value);
      value = '';
    } else {
      value += ch;
    }
  }
  cells.push(value);
  return cells;
}

function preferredSummaryColumnIndexes(headers) {
  const preferred = [
    'atlas_rank', 'manual_review_bucket', 'selection_track', 'bigscape_cc', 'genome',
    'ecology_group', 'antismash_region', 'funbgcex_cluster', 'antismash_class',
    'priority_score', 'priority_tier', 'recommended_followup', 'ranking_rationale', 'safe_claim_text',
  ];
  const lowered = headers.map(h => String(h || '').toLowerCase());
  const selected = [];
  preferred.forEach(name => {
    const idx = lowered.indexOf(name);
    if (idx >= 0 && !selected.includes(idx)) selected.push(idx);
  });
  if (!selected.length) {
    headers.slice(0, 8).forEach((_, idx) => selected.push(idx));
  }
  return selected.slice(0, 8);
}

function renderDelimitedSummary(path, text) {
  const delimiter = resultPathExt(path) === 'csv' ? ',' : '\t';
  const lines = String(text || '').split(/\r?\n/).filter(line => line.trim());
  if (!lines.length) return '<div class="empty-state">Summary file is empty.</div>';
  const headers = parseDelimitedLine(lines[0], delimiter);
  const indexes = preferredSummaryColumnIndexes(headers);
  const bodyRows = lines.slice(1).map(line => parseDelimitedLine(line, delimiter));
  const head = indexes.map(idx => `<th>${escapeHtml(headers[idx] || `Column ${idx + 1}`)}</th>`).join('');
  const body = bodyRows.map(row => `<tr>${indexes.map(idx => `<td>${escapeHtml(row[idx] || '')}</td>`).join('')}</tr>`).join('');
  return `
    <div class="summary-reader-source">${escapeHtml(summaryArtifactLabel(path))} · ${bodyRows.length} atlas shortlist ${bodyRows.length === 1 ? 'row' : 'rows'}</div>
    <div class="summary-table-wrap"><table class="summary-reader-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function renderMarkdownSummary(text) {
  const lines = String(text || '').split(/\r?\n/);
  const html = [];
  let listOpen = false;
  const closeList = () => {
    if (listOpen) html.push('</ul>');
    listOpen = false;
  };
  lines.forEach(line => {
    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      return;
    }
    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      closeList();
      html.push(`<h3>${escapeHtml(heading[2])}</h3>`);
      return;
    }
    const bullet = trimmed.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      if (!listOpen) {
        html.push('<ul>');
        listOpen = true;
      }
      html.push(`<li>${escapeHtml(bullet[1])}</li>`);
      return;
    }
    closeList();
    html.push(`<p>${escapeHtml(trimmed)}</p>`);
  });
  closeList();
  return html.join('') || '<div class="empty-state">Summary file is empty.</div>';
}

function renderTextSummary(path, text) {
  const ext = resultPathExt(path);
  if (ext === 'tsv' || ext === 'csv') return renderDelimitedSummary(path, text);
  if (ext === 'md') return renderMarkdownSummary(text);
  const doc = new DOMParser().parseFromString(String(text || ''), ext === 'html' || ext === 'htm' ? 'text/html' : 'text/plain');
  if (ext === 'html' || ext === 'htm') {
    doc.querySelectorAll('script, style, iframe, object, embed').forEach(el => el.remove());
    return renderMarkdownSummary((doc.body && doc.body.textContent) || '');
  }
  return renderMarkdownSummary(text);
}

async function loadSummaryReaderFile(path) {
  if (!activeJobId || !path) return;
  const seq = ++summaryReaderSeq;
  const source = document.getElementById('summary-reader-source');
  const doc = document.getElementById('summary-reader-doc');
  if (source) source.textContent = summaryArtifactLabel(path);
  if (doc) doc.innerHTML = '<div class="viz-placeholder text-sm">Loading summary document...</div>';
  try {
    const resp = await resultFetch(activeJobId, path);
    if (seq !== summaryReaderSeq) return;
    if (!resp.ok) throw new Error('Summary document could not be opened with this result access code.');
    const text = await resp.text();
    if (doc) doc.innerHTML = renderTextSummary(path, text);
  } catch (err) {
    if (doc) doc.innerHTML = `<div class="empty-state">${escapeHtml(err.message || 'Summary document unavailable.')}</div>`;
  }
}

function showResultDashboard() {
  if (!activeJobMeta && !activeJobId) return;
  resultDashboardOpen = true;
  document.body.dataset.managementView = 'closed';
  setResultFocusMode('overview');
  document.body.dataset.resultsDashboard = 'open';
  setResultsPanelCollapsed(true);
  const counts = resultCategoryCounts(activeResultFiles);
  activeResultCategory = firstAvailableResultCategory(counts);
  const status = activeJobMeta?.status || 'pending';
  renderCompletionCallout(status);
  renderResultBubblePanel(activeResultFiles, status);
  updateResultDashboardVisibility(status, counts.downloads);
  rerenderWorkflowSpineForResults();
  const spine = document.getElementById('weavemap');
  if (spine) spine.scrollTop = 0;
  const firstOutput = document.querySelector('.dna-result-output-trigger');
  const board = document.getElementById('result-dashboard-section');
  const focusTarget = firstOutput || spine || board || document.getElementById('results-card');
  focusTarget?.focus({ preventScroll: true });
  const pulseTarget = spine || board || focusTarget;
  pulseTarget?.classList.remove('section-focus');
  void pulseTarget?.offsetWidth;
  pulseTarget?.classList.add('section-focus');
}

async function loadResults(jobId, status, seq = jobLoadSeq, job = activeJobMeta) {
  if (seq !== jobLoadSeq || jobId !== activeJobId) return;
  const card = document.getElementById('results-card');
  card.classList.remove('hidden');
  setResultsLoaded(true);
  if (!job) {
    const jobResp = await apiFetch(`api/jobs/${encodeURIComponent(jobId)}`, {}, { kind: 'job', jobId });
    if (seq !== jobLoadSeq || jobId !== activeJobId) return;
    job = jobResp.ok ? await jobResp.json() : activeJobMeta;
  }
  activeJobMeta = job || activeJobMeta;
  setWorkflowExperienceState(activeJobMeta);

  setStatusBadge(document.getElementById('results-status'), status, activeJobMeta);
  renderActiveRunAccessPanel(activeJobMeta);

  renderCompletionCallout(status);
  if (canUseAdminSurfaces()) renderRerunPanel(jobId, activeJobMeta);
  else document.getElementById('rerun-panel').innerHTML = '';

  const resp = await apiFetch(`api/jobs/${encodeURIComponent(jobId)}/files`, {}, { kind: 'job', jobId });
  if (seq !== jobLoadSeq || jobId !== activeJobId) return;
  if (!resp.ok) return;
  const { files } = await resp.json();
  if (seq !== jobLoadSeq || jobId !== activeJobId) return;
  const normalizedFiles = (files || []).map(normalizedResultPath).filter(Boolean);
  const counts = resultCategoryCounts(normalizedFiles);
  const openDashboard = shouldOpenResultDashboardDuringRefresh(normalizedFiles, activeJobMeta);
  resultDashboardOpen = openDashboard;
  document.body.dataset.resultsDashboard = openDashboard ? 'open' : 'closed';
  if (openDashboard) {
    document.body.dataset.managementView = 'closed';
    if (resultFocusMode === 'overview' || !resultCategoryAvailable(activeResultCategory, counts)) {
      activeResultCategory = firstAvailableResultCategory(counts);
    }
  }

  renderResultBubblePanel(normalizedFiles, status);
  updateArchiveButton();
  const hasFigureFiles = normalizedFiles.some(isFigureAsset);
  if (status === 'success' || hasFigureFiles) renderViz(jobId, normalizedFiles);
  else if (status === 'pending' || status === 'running') {
    const pendingCopy = status === 'pending'
      ? `${escapeHtml(queueStatusLabel(activeJobMeta))}. Figures will appear after the worker starts producing output.${pendingQueueNote(activeJobMeta)}`
      : 'Workflow is running. Figures will appear when the run produces output.';
    document.getElementById('viz-container').innerHTML = `
      <div class="viz-placeholder">
        <span class="viz-placeholder-mark" aria-hidden="true"></span>
        <div>${pendingCopy}</div>
      </div>`;
  }
  else {
    document.getElementById('viz-container').innerHTML = `
      <div class="viz-placeholder">
        <span class="viz-placeholder-mark" aria-hidden="true"></span>
        <div>This job did not finish, but partial outputs and logs remain available.</div>
        <div class="mt1 text-sm text-muted">${canUseAdminSurfaces() ? 'Use the rerun controls above to resume selected stages in the same job workspace.' : 'Check the Files tab for any partial outputs, or submit a new run after fixing the input.'}</div>
      </div>`;
  }
  renderResultFileSurface(jobId, normalizedFiles);
  if (String(status || '').toLowerCase() !== 'success' && activeResultCategory !== 'figures' && normalizedFiles.length) {
    switchTab('files', { preserveCategory: true });
  }
}

function rerunDefaultChecked(job, key) {
  if (!job || job.status === 'success') return false;
  if (!rerunStageAllowed(key)) return false;
  if (!activeStageState || !activeStageState.enabled.has(key)) return false;
  return !activeStageState.completed.has(key);
}

function renderRerunPanel(jobId, job) {
  const panel = document.getElementById('rerun-panel');
  if (!panel || !job) return;
  if (job.status === 'pending' || job.status === 'running') {
    panel.innerHTML = '';
    return;
  }
  const stageRows = STAGES.map(stage => {
    const enabled = rerunStageAllowed(stage.key);
    const checked = rerunDefaultChecked(job, stage.key);
    return `
      <label class="form-group-inline ${enabled ? '' : 'disabled'}">
        <input type="checkbox" class="rerun-stage" data-stage="${stage.key}" ${checked ? 'checked' : ''} ${enabled ? '' : 'disabled'} />
        ${escapeHtml(stage.label)}
      </label>`;
  }).join('');
  panel.innerHTML = `
    <details class="summary-panel rerun-summary">
      <summary class="summary-head">Rerun Selected Stages</summary>
      <div class="rerun-panel-body">
        <div class="help-note">Reuses this job workspace and existing staged inputs/results. Leave completed stages unchecked to resume after a failure. A rerun that failed after preserving earlier outputs keeps those files visible below.</div>
        <div class="rerun-grid">${stageRows}</div>
        <label class="form-group-inline"><input type="checkbox" id="rerun-force" /> Force selected stages to overwrite existing outputs</label>
        <div class="flex-gap">
          <button class="btn btn-primary text-sm" type="button" onclick="rerunActiveJob()">Rerun selected stages</button>
          <span class="text-muted text-sm" id="rerun-status"></span>
        </div>
      </div>
    </details>`;
}

async function rerunActiveJob() {
  if (!activeJobId) return;
  if (!canUseAdminSurfaces()) return;
  const statusEl = document.getElementById('rerun-status');
  const selected = new Set([...document.querySelectorAll('.rerun-stage:checked')].map(el => el.dataset.stage));
  if (!selected.size) {
    if (statusEl) statusEl.textContent = 'Choose at least one stage.';
    return;
  }
  const payload = rerunPayloadFromStages(
    selected,
    !!document.getElementById('rerun-force')?.checked,
  );
  if (statusEl) statusEl.textContent = 'Queueing rerun...';
  try {
    await queueJobRerun(activeJobId, payload);
    if (statusEl) statusEl.textContent = 'Rerun queued.';
    document.getElementById('results-card').classList.add('hidden');
    loadJob(activeJobId, true);
    refreshJobHistory();
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message || String(err);
  }
}

function normalizedResultPath(path) {
  return String(path || '').replace(/\\/g, '/');
}

function fileNameFromPath(path) {
  const parts = normalizedResultPath(path).split('/');
  return parts[parts.length - 1] || normalizedResultPath(path);
}

function isFigureAsset(path) {
  return /^data\/results\/[^/]+\/figures\/[^/]+\.(svg|png|jpe?g|webp)$/i.test(normalizedResultPath(path));
}

function isSvgFigureAsset(path) {
  return /^data\/results\/[^/]+\/figures\/[^/]+\.svg$/i.test(normalizedResultPath(path));
}

function fileTypeLabel(path) {
  const name = fileNameFromPath(path);
  if (!name.includes('.')) return 'file';
  const extStr = name.split('.').pop().toLowerCase();
  return extStr ? `.${extStr}` : 'file';
}

function fileRowLabel(path) {
  const normalized = normalizedResultPath(path);
  const lower = normalized.toLowerCase();
  if (lower === 'downloads/public_results_manifest.tsv') return 'Public results manifest';
  if (/^downloads\/[^/]+_public_results\.zip$/i.test(normalized)) return 'Generated public results package';
  if (isFigureAsset(normalized)) return figureCaption(normalized);
  if (isSummaryArtifact(normalized)) return summaryArtifactLabel(normalized);
  if (isSyntenyArtifact(normalized)) return syntenyArtifactLabel(normalized);
  if (isAntiSmashArtifact(normalized)) return `${toolGenomeLabel(normalized, 'antismash')} antiSMASH file`;
  if (isFunbgcexArtifact(normalized)) return `${toolGenomeLabel(normalized, 'funbgcex')} FunBGCeX file`;
  if (isBigscapeArtifact(normalized)) return artifactMetaLabel(normalized, 'bigscape');
  return titleCaseArtifactLabel(fileStemFromPath(normalized), fileNameFromPath(normalized));
}

function makeFileTreeNode(name, path) {
  return { name, path, count: 0, folders: new Map(), files: [] };
}

function buildFileTree(files) {
  const root = makeFileTreeNode('', '');
  const index = new Map([['', root]]);
  files.map(normalizedResultPath).filter(Boolean).sort((a, b) => a.localeCompare(b)).forEach(path => {
    const parts = path.split('/').filter(Boolean);
    if (!parts.length) return;
    let node = root;
    node.count += 1;
    parts.slice(0, -1).forEach(part => {
      const childPath = node.path ? `${node.path}/${part}` : part;
      if (!node.folders.has(part)) {
        const child = makeFileTreeNode(part, childPath);
        node.folders.set(part, child);
        index.set(childPath, child);
      }
      node = node.folders.get(part);
      node.count += 1;
    });
    node.files.push(path);
  });
  root.index = index;
  return root;
}

function defaultFolderOpen(path, depth) {
  const normalized = normalizedResultPath(path);
  const category = resultCategoryKey(activeResultCategory);
  if (normalized === 'downloads') return true;
  if (/^Data(\/results(\/[^/]+)?)?$/i.test(normalized)) return true;
  if (category !== 'downloads' && /^data\/results\/[^/]+$/i.test(normalized)) return true;
  if (/^data\/results\/[^/]+\/figures$/i.test(normalized)) return true;
  if (category === 'antismash' && isAntiSmashArtifact(normalized)) return true;
  if (category === 'funbgcex' && isFunbgcexArtifact(normalized)) return true;
  if (category === 'bigscape' && isBigscapeArtifact(normalized)) return true;
  if (category === 'summaries' && isSummaryArtifact(normalized)) return true;
  if (category === 'synteny' && isSyntenyArtifact(normalized)) return true;
  if (category === 'other' && depth <= 2) return true;
  return false;
}

function folderSortKey(node) {
  if (node.path === 'downloads') return '0-downloads';
  if (node.path === 'Data') return '1-Data';
  return `2-${node.path.toLowerCase()}`;
}

function renderFileRow(jobId, f) {
  const name = fileNameFromPath(f);
  const label = fileRowLabel(f);
  const path = normalizedResultPath(f);
  const downloadHref = resultHref(jobId, f, { download: true });
  const jsJobId = escapeJsString(jobId);
  const jsPath = escapeJsString(f);
  return `<tr>
    <td><span class="ext-badge">${escapeHtml(fileTypeLabel(f))}</span></td>
    <td>
      <span class="file-row-main">
        <span class="file-display-name">${escapeHtml(label)}</span>
        <span class="file-path-link">${escapeHtml(path)}</span>
      </span>
    </td>
    <td class="file-actions">
      <div class="file-actions-inner">
        <a class="btn btn-ghost text-sm" href="${escapeHtml(downloadHref)}" download="${escapeHtml(name)}" onclick="return handleResultLinkClick(event,'${escapeHtml(jsJobId)}','${escapeHtml(jsPath)}',true)">Download</a>
      </div>
    </td>
  </tr>`;
}

function renderFileRows(jobId, files) {
  if (!files.length) return '';
  return `
    <table class="file-table file-tree-table">
      <thead><tr><th>Type</th><th>File / Result path</th><th></th></tr></thead>
      <tbody>${files.map(f => renderFileRow(jobId, f)).join('')}</tbody>
    </table>`;
}

function renderFileFolder(jobId, node, depth = 0) {
  const shouldRenderOpen = defaultFolderOpen(node.path, depth);
  const openAttr = shouldRenderOpen ? ' open' : '';
  const body = shouldRenderOpen ? renderFileTreeChildren(jobId, node, depth + 1) : '';
  return `
    <details class="file-folder" data-folder-path="${escapeHtml(node.path)}" data-depth="${depth}" data-rendered="${shouldRenderOpen ? '1' : '0'}" ontoggle="handleFileFolderToggle(this)"${openAttr}>
      <summary class="file-folder-summary">
        <span class="file-folder-name">${escapeHtml(node.path)}</span>
        <span class="file-folder-count">${node.count} file${node.count === 1 ? '' : 's'}</span>
      </summary>
      <div class="file-folder-body">
        ${body}
      </div>
    </details>`;
}

function renderFileTreeChildren(jobId, node, depth = 0) {
  const folders = Array.from(node.folders.values()).sort((a, b) => folderSortKey(a).localeCompare(folderSortKey(b)));
  return `${folders.map(child => renderFileFolder(jobId, child, depth)).join('')}${renderFileRows(jobId, node.files)}`;
}

function handleFileFolderToggle(detailsEl) {
  if (!detailsEl.open || detailsEl.dataset.rendered === '1') return;
  const node = activeFileTreeIndex.get(detailsEl.dataset.folderPath || '');
  if (!node || !activeFileTreeJobId) return;
  const body = Array.from(detailsEl.children).find(child => child.classList && child.classList.contains('file-folder-body'));
  if (!body) return;
  const depth = Number(detailsEl.dataset.depth || 0) + 1;
  body.innerHTML = renderFileTreeChildren(activeFileTreeJobId, node, depth);
  detailsEl.dataset.rendered = '1';
}

function figureSortKey(path) {
  const name = fileNameFromPath(path).toLowerCase();
  const preferred = [
    'big_scape_multipanel.svg',
    'big_scape_multipanel.png',
    'bgc_overlap.svg',
    'bgc_overlap.png',
  ];
  const idx = preferred.indexOf(name);
  return `${idx === -1 ? preferred.length : idx}:${name}`;
}

function figureCaption(path) {
  const name = fileNameFromPath(path).toLowerCase();
  if (name === 'big_scape_multipanel.svg' || name === 'big_scape_multipanel.png') {
    return 'Multipanel BiG-SCAPE figure combining BGC/GCF count bars and network context.';
  }
  if (name === 'bgc_overlap.svg' || name === 'bgc_overlap.png') {
    return 'Shared and tool-specific BGC scaffold overlap between antiSMASH and FunBGCeX by genome.';
  }
  return 'Rendered ClusterWeave figure output.';
}

function figureZoomKeyFromWrap(wrap) {
  return `${wrap.dataset.resultJob || ''}|${wrap.dataset.resultPath || ''}`;
}

function figureZoomRecord(wrap) {
  const key = figureZoomKeyFromWrap(wrap);
  if (!figureZoomState.has(key)) {
    figureZoomState.set(key, { scale: 1, x: 0, y: 0 });
  }
  return figureZoomState.get(key);
}

function clampNumber(value, min, max) {
  if (max < min) return min;
  return Math.max(min, Math.min(max, value));
}

function readSvgBaseViewBox(svg) {
  const raw = (svg.getAttribute('viewBox') || '').trim();
  const values = raw.split(/[\s,]+/).map(Number).filter(Number.isFinite);
  if (values.length === 4 && values[2] > 0 && values[3] > 0) {
    return { x: values[0], y: values[1], width: values[2], height: values[3] };
  }
  const parseSize = value => {
    const match = String(value || '').match(/^[\d.]+/);
    return match ? Number(match[0]) : 0;
  };
  let width = parseSize(svg.getAttribute('width'));
  let height = parseSize(svg.getAttribute('height'));
  if ((!width || !height) && typeof svg.getBBox === 'function') {
    try {
      const box = svg.getBBox();
      width = width || box.width;
      height = height || box.height;
    } catch (e) {}
  }
  const base = { x: 0, y: 0, width: width || 1000, height: height || 640 };
  svg.setAttribute('viewBox', `${base.x} ${base.y} ${base.width} ${base.height}`);
  return base;
}

function applySvgFigureZoom(wrap, svg, state) {
  const base = wrap._svgBaseViewBox || readSvgBaseViewBox(svg);
  wrap._svgBaseViewBox = base;
  const box = svg.getBoundingClientRect();
  const viewportWidth = Math.max(1, box.width || wrap.getBoundingClientRect().width);
  const viewportHeight = Math.max(1, box.height || wrap.getBoundingClientRect().height);
  const visibleWidth = base.width / state.scale;
  const visibleHeight = base.height / state.scale;
  const x = clampNumber(
    base.x + (-state.x * base.width) / (viewportWidth * state.scale),
    base.x,
    base.x + base.width - visibleWidth
  );
  const y = clampNumber(
    base.y + (-state.y * base.height) / (viewportHeight * state.scale),
    base.y,
    base.y + base.height - visibleHeight
  );
  svg.setAttribute('viewBox', `${x} ${y} ${visibleWidth} ${visibleHeight}`);
  svg.style.transform = '';
}

function applyFigureZoom(wrap) {
  if (!wrap) return;
  const preview = wrap.querySelector('.figure-preview');
  if (!preview) return;
  const state = figureZoomRecord(wrap);
  const svg = preview.matches('svg') ? preview : null;
  if (svg) {
    applySvgFigureZoom(wrap, svg, state);
  } else {
    preview.style.transform = `translate(${state.x.toFixed(1)}px, ${state.y.toFixed(1)}px) scale(${state.scale.toFixed(3)})`;
  }
  wrap.classList.toggle('is-zoomed', state.scale > 1.01);
  const reset = wrap.querySelector('.figure-zoom-reset');
  if (reset) reset.textContent = `${Math.round(state.scale * 100)}%`;
}

function setFigureZoom(wrap, nextScale, originX, originY) {
  const state = figureZoomRecord(wrap);
  const scale = Math.max(1, Math.min(8, nextScale));
  if (Math.abs(scale - 1) < 0.01) {
    state.scale = 1;
    state.x = 0;
    state.y = 0;
    applyFigureZoom(wrap);
    return;
  }
  const previous = state.scale || 1;
  const ratio = scale / previous;
  state.x = originX - (originX - state.x) * ratio;
  state.y = originY - (originY - state.y) * ratio;
  state.scale = scale;
  applyFigureZoom(wrap);
}

function zoomFigureAt(wrap, factor, originX = null, originY = null) {
  if (!wrap) return;
  const rect = wrap.getBoundingClientRect();
  const x = originX === null ? rect.width / 2 : originX;
  const y = originY === null ? rect.height / 2 : originY;
  setFigureZoom(wrap, figureZoomRecord(wrap).scale * factor, x, y);
}

function handleFigureWheel(event, wrap) {
  event.preventDefault();
  const rect = wrap.getBoundingClientRect();
  const factor = Math.exp(-event.deltaY * 0.0015);
  zoomFigureAt(wrap, factor, event.clientX - rect.left, event.clientY - rect.top);
}

function handleFigurePointerDown(event, wrap) {
  if (event.button !== undefined && event.button !== 0) return;
  const state = figureZoomRecord(wrap);
  if (state.scale <= 1.01) return;
  event.preventDefault();
  activeFigurePan = {
    wrap,
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    originX: state.x,
    originY: state.y,
  };
  wrap.classList.add('is-panning');
  wrap.setPointerCapture?.(event.pointerId);
}

function handleFigurePointerMove(event, wrap) {
  if (!activeFigurePan || activeFigurePan.wrap !== wrap || activeFigurePan.pointerId !== event.pointerId) return;
  const state = figureZoomRecord(wrap);
  state.x = activeFigurePan.originX + event.clientX - activeFigurePan.startX;
  state.y = activeFigurePan.originY + event.clientY - activeFigurePan.startY;
  applyFigureZoom(wrap);
}

function handleFigurePointerEnd(event, wrap) {
  if (!activeFigurePan || activeFigurePan.wrap !== wrap || activeFigurePan.pointerId !== event.pointerId) return;
  wrap.classList.remove('is-panning');
  wrap.releasePointerCapture?.(event.pointerId);
  activeFigurePan = null;
}

function zoomFigureControl(event, button, factor) {
  event.preventDefault();
  event.stopPropagation();
  zoomFigureAt(button.closest('.figure-preview-wrap'), factor);
}

function resetFigureZoomControl(event, button) {
  event.preventDefault();
  event.stopPropagation();
  const wrap = button.closest('.figure-preview-wrap');
  const state = figureZoomRecord(wrap);
  state.scale = 1;
  state.x = 0;
  state.y = 0;
  applyFigureZoom(wrap);
}

function handleFigureZoomKeydown(event, wrap) {
  if (event.key === '+' || event.key === '=') {
    event.preventDefault();
    zoomFigureAt(wrap, 1.2);
  } else if (event.key === '-' || event.key === '_') {
    event.preventDefault();
    zoomFigureAt(wrap, 1 / 1.2);
  } else if (event.key === '0' || event.key === 'Escape') {
    event.preventDefault();
    const state = figureZoomRecord(wrap);
    state.scale = 1;
    state.x = 0;
    state.y = 0;
    applyFigureZoom(wrap);
  }
}

function initializeFigureZoomCards() {
  document.querySelectorAll('.figure-preview-wrap[data-result-path]').forEach(wrap => applyFigureZoom(wrap));
}

function sanitizeInlineSvg(svg) {
  svg.querySelectorAll('script, foreignObject, foreignobject, iframe, object, embed, link, meta, base').forEach(el => el.remove());
  [svg, ...svg.querySelectorAll('*')].forEach(el => {
    Array.from(el.attributes).forEach(attr => {
      const name = attr.name.toLowerCase();
      const value = String(attr.value || '').trim().toLowerCase();
      if (name.startsWith('on')) {
        el.removeAttribute(attr.name);
      } else if ((name === 'href' || name === 'src' || name.endsWith(':href')) && /^(javascript:|data:text\/html)/i.test(value)) {
        el.removeAttribute(attr.name);
      }
    });
  });
  return svg;
}

async function hydrateSvgFigures(jobId) {
  const stages = Array.from(document.querySelectorAll('.figure-svg-stage'))
    .filter(stage => stage.dataset.resultJob === jobId);
  for (const stage of stages) {
    const path = stage.dataset.resultPath || '';
    if (!path) continue;
    try {
      const resp = await resultFetch(jobId, path);
      if (!resp.ok) throw new Error('SVG unavailable');
      const text = await resp.text();
      const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
      if (doc.querySelector('parsererror')) throw new Error('SVG could not be parsed');
      const parsed = doc.documentElement;
      if (!parsed || parsed.nodeName.toLowerCase() !== 'svg') throw new Error('File is not an SVG');
      const svg = sanitizeInlineSvg(document.importNode(parsed, true));
      svg.classList.add('figure-preview', 'figure-svg-preview');
      svg.setAttribute('role', 'img');
      if (!svg.getAttribute('aria-label')) svg.setAttribute('aria-label', fileNameFromPath(path));
      if (!svg.getAttribute('preserveAspectRatio')) svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
      stage.innerHTML = '';
      stage.appendChild(svg);
      const wrap = stage.closest('.figure-preview-wrap');
      if (wrap) {
        wrap._svgBaseViewBox = readSvgBaseViewBox(svg);
        applyFigureZoom(wrap);
      }
    } catch (err) {
      stage.innerHTML = `<div class="viz-placeholder text-sm">${escapeHtml(err.message || 'SVG preview unavailable.')}</div>`;
    }
  }
}

function renderViz(jobId, files) {
  const figureFiles = files.filter(isFigureAsset).sort((a, b) => figureSortKey(a).localeCompare(figureSortKey(b)));
  const container = document.getElementById('viz-container');
  if (!figureFiles.length) {
    const detail = canUseAdminSurfaces()
      ? 'Check the figure-stage logs or rerun the Figures stage after Rscript is available.'
      : 'No figure outputs were found for this run yet.';
    container.innerHTML = `
      <div class="viz-placeholder">
        <span class="viz-placeholder-mark" aria-hidden="true"></span>
        <div>No figure SVG/PNG outputs were indexed for this run yet.</div>
        <div class="mt1 text-sm text-muted">${escapeHtml(detail)}</div>
      </div>`;
    return;
  }

  resultObjectUrls.forEach(url => URL.revokeObjectURL(url));
  resultObjectUrls = [];
  const cards = figureFiles.map(f => {
    const name = fileNameFromPath(f);
    const href = resultHref(jobId, f);
    const downloadHref = resultHref(jobId, f, { download: true });
    const jsJobId = escapeJsString(jobId);
    const jsPath = escapeJsString(f);
    const isSvg = isSvgFigureAsset(f);
    const imgSrc = resultNeedsAuth(jobId) ? '' : escapeHtml(href);
    const preview = isSvg
      ? `<div class="figure-svg-stage" data-result-path="${escapeHtml(f)}" data-result-job="${escapeHtml(jobId)}"><div class="viz-placeholder text-sm">Loading vector preview...</div></div>`
      : `<img class="figure-preview" src="${imgSrc}" data-result-path="${escapeHtml(f)}" data-result-job="${escapeHtml(jobId)}" alt="${escapeHtml(name)}" draggable="false" />`;
    return `
      <div class="figure-panel">
        <div class="figure-panel-head">
          <div class="figure-copy">
            <div class="figure-name">${escapeHtml(name)}</div>
            <div class="figure-caption">${escapeHtml(figureCaption(f))}</div>
          </div>
          <div class="figure-actions">
            <span class="ext-badge">${escapeHtml(fileTypeLabel(f))}</span>
            <a class="btn btn-ghost text-sm" href="${escapeHtml(href)}" target="_blank" onclick="return handleResultLinkClick(event,'${escapeHtml(jsJobId)}','${escapeHtml(jsPath)}',false)">Open</a>
            <a class="btn btn-ghost text-sm" href="${escapeHtml(downloadHref)}" download="${escapeHtml(name)}" onclick="return handleResultLinkClick(event,'${escapeHtml(jsJobId)}','${escapeHtml(jsPath)}',true)">Download</a>
          </div>
        </div>
        <div class="figure-preview-wrap"
          data-result-path="${escapeHtml(f)}"
          data-result-job="${escapeHtml(jobId)}"
          tabindex="0"
          onwheel="handleFigureWheel(event,this)"
          onkeydown="handleFigureZoomKeydown(event,this)"
          onpointerdown="handleFigurePointerDown(event,this)"
          onpointermove="handleFigurePointerMove(event,this)"
          onpointerup="handleFigurePointerEnd(event,this)"
          onpointercancel="handleFigurePointerEnd(event,this)">
          ${preview}
          <div class="figure-zoom-controls" aria-label="Figure zoom controls" onpointerdown="event.stopPropagation()" onwheel="event.stopPropagation()">
            <button type="button" title="Zoom out" aria-label="Zoom out" onclick="zoomFigureControl(event,this,0.833)">-</button>
            <button class="figure-zoom-reset" type="button" title="Reset zoom" aria-label="Reset zoom" onclick="resetFigureZoomControl(event,this)">100%</button>
            <button type="button" title="Zoom in" aria-label="Zoom in" onclick="zoomFigureControl(event,this,1.2)">+</button>
          </div>
        </div>
      </div>`;
  }).join('');
  container.innerHTML = `<div class="figure-grid">${cards}</div>`;
  initializeFigureZoomCards();
  hydrateSvgFigures(jobId);
  hydrateAuthenticatedFigures(jobId);
}

async function hydrateAuthenticatedFigures(jobId) {
  if (!resultNeedsAuth(jobId)) return;
  const images = Array.from(document.querySelectorAll('img.figure-preview'))
    .filter(img => img.dataset.resultJob === jobId);
  for (const img of images) {
    const path = img.dataset.resultPath || '';
    if (!path) continue;
    try {
      const resp = await resultFetch(jobId, path);
      if (!resp.ok) throw new Error('Figure unavailable');
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      resultObjectUrls.push(url);
      img.src = url;
    } catch (err) {
      img.replaceWith(Object.assign(document.createElement('div'), {
        className: 'viz-placeholder',
        textContent: 'Figure preview requires a valid result access code.',
      }));
    }
  }
}

function renderResultCategorySummary(category, visibleCount, totalCount) {
  const key = resultCategoryKey(category);
  const label = resultCategoryLabel(key);
  const scope = key === 'downloads'
    ? `${visibleCount} total ${visibleCount === 1 ? 'file' : 'files'}`
    : `${visibleCount} of ${totalCount} ${totalCount === 1 ? 'file' : 'files'}`;
  return `
    <div class="result-category-summary" id="result-category-summary">
      <div>
        <div class="result-category-title">${escapeHtml(label)}</div>
        <div class="result-category-copy">${escapeHtml(resultCategoryCopy(key))}</div>
      </div>
      <span class="ext-badge">${escapeHtml(scope)}</span>
    </div>`;
}

function renderFileTable(jobId, files, options = {}) {
  const container = document.getElementById('files-container');
  activeResultFiles = (files || []).map(normalizedResultPath).filter(Boolean);
  const category = resultCategoryKey(options.category || activeResultCategory || 'downloads');
  const visibleFiles = resultFilesForCategory(category, activeResultFiles);
  const summary = renderResultCategorySummary(category, visibleFiles.length, activeResultFiles.length);
  if (!visibleFiles.length) {
    activeFileTree = null;
    activeFileTreeIndex = new Map();
    activeFileTreeJobId = null;
    const emptyCopy = category === 'downloads'
      ? 'No result files.'
      : `No ${resultCategoryLabel(category).toLowerCase()} files were found for this run.`;
    container.innerHTML = `${summary}<div class="empty-state">${escapeHtml(emptyCopy)}</div>`;
    return;
  }
  const tree = buildFileTree(visibleFiles);
  activeFileTree = tree;
  activeFileTreeIndex = tree.index || new Map();
  activeFileTreeJobId = jobId;
  container.innerHTML = `${summary}<div class="file-tree">${renderFileTreeChildren(jobId, tree)}</div>`;
}

// ── System Console (Worker Status) ──────────────────────────────────────────
function startSystemConsolePolling() {
  if (!canUseAdminSurfaces()) {
    stopSystemConsolePolling();
    return;
  }
  if (systemPollTimer) return;
  updateWorkerTelemetryBadge('unknown', 'Monitoring');
  appendSystemLog('[System] ClusterWeave initialization complete. Monitoring worker...');
  systemPollTimer = setInterval(() => {
    pollSystemStatus();
  }, 2000);
  // Initial poll
  pollSystemStatus();
}

function stopSystemConsolePolling() {
  if (systemPollTimer) {
    clearInterval(systemPollTimer);
    systemPollTimer = null;
  }
}

async function pollSystemStatus() {
  if (!canUseAdminSurfaces()) return;
  let jobs;
  let system;
  try {
    const [jobsResp, systemPayload] = await Promise.all([
      apiFetch('api/jobs', {}, { kind: 'admin' }),
      fetchSystemStatus(),
    ]);
    if (!jobsResp.ok) return;
    jobs = await jobsResp.json();
    system = systemPayload || {};
  } catch (err) {
    updateWorkerTelemetryBadge('unknown', 'No signal');
    return;
  }

  const pendingCount = jobs.filter(j => j.status === 'pending').length;
  const runningCount = jobs.filter(j => j.status === 'running').length;
  const worker = system.worker || {};
  const concurrency = worker.concurrency || 1;
  const activeCount = worker.active_count || runningCount;
  const systemState = String(system.state || '').toLowerCase();
  updateRuntimeStatusPanel(system, { runningJobs: runningCount, queuedJobs: pendingCount });

  if (systemState === 'error') {
    const newStatus = 'error';
    updateWorkerTelemetryBadge(newStatus, 'Error');
    if (newStatus !== workerStatus) {
      workerStatus = newStatus;
      appendSystemLog(`[Worker] ERROR: ${system.detail || 'Worker reported an error'}`);
    }
    return;
  }

  // Determine worker status based on pending jobs
  if (runningCount > 0) {
    const newStatus = 'processing';
    updateWorkerTelemetryBadge(newStatus, 'Processing');
    if (newStatus !== workerStatus) {
      workerStatus = newStatus;
      appendSystemLog(`[Worker] Processing ${activeCount} job(s); ${pendingCount} queued`);
    }
  } else if (pendingCount > 0 && activeJobId === null) {
    const newStatus = 'ready';
    updateWorkerTelemetryBadge(newStatus, 'Ready');
    if (newStatus !== workerStatus) {
      workerStatus = newStatus;
      appendSystemLog(`[Worker] Ready - ${pendingCount} queued, concurrency ${concurrency}`);
    }
  } else if (pendingCount === 0 && runningCount === 0) {
    const newStatus = 'idle';
    updateWorkerTelemetryBadge(newStatus, 'Idle');
    if (newStatus !== workerStatus) {
      workerStatus = newStatus;
      appendSystemLog('[Worker] Idle - waiting for uploads');
    }
  }
}

function updateWorkerTelemetryBadge(status, label) {
  const badge = document.getElementById('worker-telemetry-badge');
  updateRuntimeStatusChip(status, label);
  if (!badge) return;
  const map = {
    unknown: ['badge-pending', 'Monitoring'],
    idle: ['badge-pending', 'Idle'],
    ready: ['badge-success', 'Ready'],
    processing: ['badge-running', 'Processing'],
    error: ['badge-failed', 'Error'],
  };
  const [cls, fallback] = map[status] || map.unknown;
  badge.className = `badge ${cls} ml-auto`;
  badge.innerHTML = `<span class="badge-dot"></span> ${escapeHtml(label || fallback)}`;
}

function appendSystemLog(text) {
  const term = document.getElementById('system-console');
  const div = document.createElement('div');
  div.className = 'log-line';
  if (/error|failed/i.test(text)) div.classList.add('err');
  else if (/warn/i.test(text)) div.classList.add('warn');
  else if (/ready/i.test(text)) div.classList.add('ok');
  else if (/processing/i.test(text)) div.classList.add('stage');
  div.textContent = text;
  term.appendChild(div);
  term.scrollTop = term.scrollHeight;
}

// ── Bootstrap Management ──────────────────────────────────────────────────────
let bootstrapComplete = false;
const bootstrapSteps = [
  { key: 'antismash', label: 'antiSMASH databases' },
  { key: 'pfam', label: 'Pfam database' },
  { key: 'clinker_image', label: 'clinker image pre-pull' },
  { key: 'bigscape_image', label: 'BiG-SCAPE image pre-pull' },
  { key: 'funbgcex_image', label: 'FunBGCeX image build' },
  { key: 'starting_worker', label: 'Worker startup' },
];

const bootstrapPhaseOrder = ['prepare', ...bootstrapSteps.map(s => s.key), 'ready', 'idle', 'processing', 'error'];

function phaseToLabel(phase) {
  const map = {
    prepare: 'Preparing bootstrap',
    antismash: 'Downloading antiSMASH databases',
    pfam: 'Downloading Pfam database',
    funbgcex_image: 'Preparing FunBGCeX image',
    clinker_image: 'Pulling clinker image',
    bigscape_image: 'Pulling BiG-SCAPE image',
    starting_worker: 'Starting worker process',
    ready: 'Worker ready',
    idle: 'Worker idle',
    processing: 'Worker processing jobs',
    error: 'Worker error',
  };
  return map[String(phase || '')] || 'Bootstrapping';
}

function updateBootstrapProgress(progress, phaseLabel) {
  const pct = Math.max(0, Math.min(100, Number(progress) || 0));
  const fill = document.getElementById('bootstrap-progress-fill');
  const pctEl = document.getElementById('bootstrap-progress-pct');
  const phaseEl = document.getElementById('bootstrap-phase-label');
  const track = fill ? fill.parentElement : null;

  if (fill) fill.style.width = `${pct}%`;
  if (pctEl) pctEl.textContent = `${Math.round(pct)}%`;
  if (phaseEl) phaseEl.textContent = phaseLabel || 'Bootstrapping';
  if (track) track.setAttribute('aria-valuenow', String(Math.round(pct)));
}

function isFullSystemStatus(system) {
  return !!(system && (
    Object.prototype.hasOwnProperty.call(system, 'ready') ||
    Object.prototype.hasOwnProperty.call(system, 'worker') ||
    Object.prototype.hasOwnProperty.call(system, 'runtime') ||
    Object.prototype.hasOwnProperty.call(system, 'capabilities')
  ));
}

async function fetchSystemStatus() {
  try {
    const resp = await apiFetch('api/system/status', {}, { kind: 'admin' });
    if (!resp.ok) return null;
    const payload = await resp.json();
    authChecked = true;
    smtpEnabled = !!payload.smtp_enabled;
    if (payload.public_quota && typeof payload.public_quota === 'object') {
      publicQuota = { ...publicQuota, ...payload.public_quota };
      renderInputChecker();
    }
    updateEmailNotificationPanel();
    if (isFullSystemStatus(payload)) {
      setAccessMode(adminToken() ? 'admin' : 'local');
      runtimeCapabilities = payload.capabilities || {};
      renderRuntimeBanner();
    } else {
      setAccessMode('public');
      runtimeCapabilities = null;
      renderRuntimeBanner();
    }
    updateRuntimeStatusPanel(payload);
    return payload;
  } catch (e) {
    return null;
  }
}

function updateBootstrapSteps(system) {
  const phase = String((system && system.phase) || (system && system.state) || 'prepare');
  const phaseIdx = bootstrapPhaseOrder.indexOf(phase);

  const stepsList = document.getElementById('bootstrap-steps');
  stepsList.innerHTML = bootstrapSteps.map((s) => {
    const idx = bootstrapPhaseOrder.indexOf(s.key);
    const done = phaseIdx > idx || (system && system.ready === true);
    const running = !done && phase === s.key;
    const cls = done ? 'done' : (running ? 'running' : '');
    return `
    <div class="bootstrap-step ${cls}">
      <span class="bootstrap-step-icon" aria-hidden="true"></span>
      <div>${s.label}</div>
    </div>
  `;
  }).join('');
}

async function waitForWorkerReady() {
  const splash = document.getElementById('bootstrap-splash');
  const statusEl = document.getElementById('bootstrap-status');
  const substepEl = document.getElementById('bootstrap-substep');
  let lastPhase = 'prepare';
  let lastProgress = 0;

  while (true) {
    const system = await fetchSystemStatus();

    if (!system) {
      statusEl.textContent = 'Waiting for web API...';
      if (substepEl) substepEl.textContent = 'Connecting to status endpoint';
      updateBootstrapProgress(0, 'Connecting to web API');
      updateBootstrapSteps({ phase: 'prepare', ready: false });
      await new Promise(r => setTimeout(r, 1000));
      continue;
    }

    if (!isFullSystemStatus(system) && system.online) {
      const submissionsLabel = system.submissions || (system.submissions_open ? 'open' : 'paused');
      updateBootstrapProgress(100, 'Interface ready');
      statusEl.textContent = 'Interface ready.';
      if (substepEl) substepEl.textContent = `Submissions ${submissionsLabel}`;
      updateRuntimeStatusChip(system.submissions_open ? 'ready' : 'unknown', `Submissions ${submissionsLabel}`);
      bootstrapComplete = true;
      await new Promise(r => setTimeout(r, 250));
      splash.classList.add('hidden');
      return true;
    }

    const state = String(system.state || 'bootstrapping');
    const phase = String(system.phase || state);
    const detail = String(system.detail || '').trim();
    const substep = String(system.substep || '').trim();

    if (phase !== lastPhase) {
      lastPhase = phase;
      lastProgress = 0;
    }

    const progress = Math.max(0, Math.min(100, Number(system.progress) || 0));
    lastProgress = progress;

    updateBootstrapProgress(progress, phaseToLabel(phase));
    updateBootstrapSteps(system);
    if (substepEl) substepEl.textContent = substep || 'Working...';

    if (state === 'bootstrapping') {
      statusEl.textContent = detail || 'Bootstrapping worker dependencies...';
    } else if (state === 'error') {
      statusEl.textContent = detail ? `Worker error: ${detail}` : 'Worker reported an error';
    } else if (detail) {
      statusEl.textContent = detail;
    } else {
      statusEl.textContent = 'Finalizing worker setup...';
    }

    if (system.ready) {
      updateBootstrapProgress(100, 'Worker ready');
      statusEl.textContent = 'Worker ready. Loading interface...';
      if (substepEl) substepEl.textContent = 'Bootstrap complete';
      statusEl.classList.add('ok');
      bootstrapComplete = true;

      await new Promise(r => setTimeout(r, 500));
      splash.classList.add('hidden');
      return true;
    }

    await new Promise(r => setTimeout(r, 1000));
  }
}

// ── Init ───────────────────────────────────────────────────────────────────
async function initializeApp() {
  window.addEventListener('hashchange', syncNavFromHash);
  window.addEventListener('resize', () => {
    applyStoredPanelWidths();
    const helix = document.getElementById('weavemap-helix');
    if (helix) delete helix.dataset.rendered;
    renderWeaveHelix(activeJobMeta);
  });
  startStageTicker();
  wirePanelResizers();
  applyStoredPanelWidths();
  placeWorkflowSpineInLaunch();
  moveWorkflowProgressIntoResults(false);
  updateAccessTokenStatus();
  updateEmailNotificationPanel();
  renderOpenedRuns();
  renderAcceptedAccessions();
  switchEntryTab('new');
  showEmptyResults();
  wireDocsDisclosure();
  syncNavFromHash();
  setUIMode('guided', { preserveDisclosure: true });

  // Wait for worker bootstrap to complete
  await waitForWorkerReady();

  // Now initialize the main UI
  refreshJobHistory();
  setInterval(refreshJobHistory, 5000);
  applyPreset('balanced');

  // Start system console polling (worker status)
  if (canUseAdminSurfaces()) startSystemConsolePolling();

  document.getElementById('run-bigscape').addEventListener('change', syncControlState);
  document.getElementById('run-clinker').addEventListener('change', syncControlState);
  document.getElementById('run-ecology').addEventListener('change', syncControlState);
  document.getElementById('run-nplinker').addEventListener('change', syncControlState);
  [
    'project-name',
    'cpus',
    'target-genome',
    'genefinding-mode',
    'run-genome-prep',
    'run-annotation',
    'run-bigscape',
    'run-summary',
    'run-clinker',
    'execute-clinker',
    'run-figures',
    'figures-required',
    'run-nplinker',
    'run-ncbi-install',
    'force-rerun',
    'workers',
    'anno-cpus',
    'annotation-fallback-order',
    'funannotate-busco-db',
    'funannotate-organism-name',
    'clinker-mode',
    'panel-target-set',
    'bigscape-mix-mode',
    'clinker-use-docker-image',
    'clinker-docker-image',
    'clinker-docker-data-volume',
    'clinker-max-regions',
    'auto-pull-images',
    'auto-build-funbgcex-sif',
    'auto-pull-bigscape-sif',
    'auto-download-pfam',
    'auto-download-fasttree',
    'mibig-auto-download',
    'env-overrides',
    'capture-external-artifacts',
    'auto-normalize-metadata',
    'ecology-field',
    'focus-ecology-label',
    'metadata-tsv',
    'atlas-min-records',
    'shortlist-limit',
    'shared-family-stage-limit',
    'shared-family-min-records',
    'max-comparators',
    'max-same-ecology',
    'max-other-ecology',
    'nplinker-run-mode',
    'target-strain',
    'nplinker-podp-id',
    'massive-dataset-id',
    'gnps-version',
    'auto-pull-nplinker-sif',
    'nplinker-bootstrap-env',
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', updateRunSummary);
    el.addEventListener('change', updateRunSummary);
  });
  document.getElementById('profile-file-input').addEventListener('change', async (e) => {
    const status = document.getElementById('profile-load-status');
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    try {
      const text = await file.text();
      const cfg = parseEnvProfile(text);
      applyEnvProfileValues(cfg);
      status.textContent = `Loaded profile: ${file.name}`;
    } catch (err) {
      status.textContent = `Failed to load profile: ${err.message || err}`;
    }
  });
  updateRunSummary();
  const hashRun = parseResultHash();
  if (hashRun) {
    switchEntryTab('existing');
    const job = await loadJob(hashRun.jobId, true, { readToken: hashRun.token, source: 'result-link', deferResultsShell: true });
    document.body.dataset.existingRunLoaded = job ? 'true' : 'false';
    if (job) navigateToSection(null, 'outputs');
  }
}

// Start the app initialization
initializeApp().catch(err => console.error('Initialization failed:', err));
