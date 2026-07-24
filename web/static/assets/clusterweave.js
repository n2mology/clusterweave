// ── State ──────────────────────────────────────────────────────────────────
let selectedFiles = [];
let acceptedManualAccessions = [];
let accessionFileSources = [];
let accessionFileSourceSerial = 0;
let genomeCheckCache = new Map();
let genbankTaxonomyAuthorityCache = new Map();
let brutalInputNotices = new Map();
let stagedAnalysisScope = 'fungi';
let stagedTaxonAssignments = new Map();
let stagedTaxonAssignmentSources = new Map();
let taxonAssignmentSidecar = null;
let taxonAssignmentSidecarIssues = [];
let activeSavedAnalysisContext = null;
let activeJobId   = null;
let pendingReadTokens = new Map();
let jobLoadSeq = 0;
let pollTimerId = null;
let logCursor     = 0;
let logWindowStart = 0;
let logTotal = 0;
let logGeneration = '';
let logHydratedJobId = '';
let logHydrationInFlight = null;
const QA_LOG_PAGE_SIZE = 500;
let systemLogCursor = 0;
let workerStatus = 'unknown'; // unknown, starting, ready, processing
let lastWorkerTelemetry = { runningCount: 0, pendingCount: 0, activeCount: 0, concurrency: 0, status: 'unknown' };
let systemPollTimer = null;
let publicImpactPollTimer = null;
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
let activeOpsTab = 'jobs';
let rerunScopeOpenJobId = '';
let lastOpsPanelFocus = null;
let opsPanelKeyboardWired = false;
let currentUIMode = 'guided';
let accessMode = 'public'; // public, admin, local
let authChecked = false;
let resultObjectUrls = [];
let smtpEnabled = false;
let lastSubmittedRun = null;
let submittedRunReceipt = null;
let runSetupAccessCollapsed = false;
let stageTickerId = null;
let resultDashboardOpen = false;
let resultFocusMode = 'overview';
let activeResultCategory = 'figures';
let activeResultFiles = [];
let activeResultPackageFileCount = 0;
let activeResultArtifacts = null;
// Public result surfaces use opaque run and artifact identifiers. The
// presentation keys below are generated in-memory from server descriptors so
// legacy reader/classifier code never receives a storage-relative path.
let activePublicRunId = '';
let activeResultArtifactByKey = new Map();
let activeResultArtifactById = new Map();
let publicResultRunIds = new Set();
let resultArchiveObjectUrl = '';
let resultArchiveRequestSeq = 0;
let activeArchiveDownload = null;
let archiveDownloadStatus = null;
let archiveDownloadDismissTimer = null;
let validatedIntakeSignature = '';
let resultHelperObjectUrls = [];
let summaryReaderSeq = 0;
let summaryReaderJobId = '';
let activeSummaryView = 'all_bgcs';
let allBgcTableState = null;
let syntenyReaderJobId = '';
let activeSyntenyTaxon = '';
let figureReaderJobId = '';
let activeFigureView = '';
let resultAccessCollapsed = false;
let runStackOpen = false;
let runStackDismissalWired = false;
let publicQuota = {
  max_accessions: 50,
  max_genome_files: 50,
  max_upload_file_mb: 500,
  max_upload_total_mb: 1024,
};
let gsapMotion = {
  promise: null,
  gsap: null,
  fallbackReason: '',
  timelines: new Map(),
  lastJobLoadSource: '',
  lastWeaveMotionKey: '',
  lastDashboardMotionKey: '',
};
let motionLifecycleWired = false;
let bgcWorkflowDna = null;
let bgcWorkflowDnaLoading = false;
let bgcWorkflowPendingPayload = null;
let clusterweaveGameEpoch = 0;
let clusterweaveGameDnaSuspended = false;
let bgcWorkflowDnaGenomeLayerSuspended = false;
let clusterweaveGameAdapterWired = false;
let genomeProgressSnapshotKey = '';
let genomeProgressSnapshot = new Map();

const GSAP_BROWSER_PATH = 'vendor/gsap-3.15.0/gsap.min.js';
const WORKFLOW_DNA_MODULE_PATH = new URL('assets/workflow-dna-progress.js?v=20260713-fanout-ui1', window.location.href).toString();
const JOB_POLL_BASE_DELAY_MS = 1500;
const JOB_POLL_RETRY_DELAY_MS = 3000;
const JOB_POLL_LONG_LOG_DELAY_MS = 3000;
const JOB_POLL_LONG_LOG_THRESHOLD = 5000;
const JOB_POLL_TIMEOUT_MS = 12000;
const JOB_INITIAL_LOAD_TIMEOUT_MS = 45000;
const TRANSIENT_JOB_POLL = Object.freeze({ status: 'pending', transient: true });
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

const RETIRED_MOTION_STORAGE_KEYS = [
  'clusterweave.richMotionDisabled',
  'clusterweave.threeWeavemapEnabled',
];

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

const WORKFLOW_PROGRESS_WEIGHTS = {
  prep: 0.05,
  annotation: 0.58,
  bigscape: 0.18,
  summary: 0.07,
  clinker: 0.08,
  figures: 0.04,
  nplinker: 0.04,
};

const GENOME_PROGRESS_TERMINAL_STATES = new Set([
  'complete', 'completed', 'done', 'success', 'succeeded',
  'complete_with_warning',
  'warning', 'dropped', 'failed', 'error', 'skipped',
  'not_applicable', 'not_applicable_taxon', 'not-applicable', 'not applicable',
]);
const GENOME_PROGRESS_WARNING_STATES = new Set([
  'complete_with_warning', 'warning', 'dropped', 'failed', 'error',
]);
const GENOME_PROGRESS_ACTIVE_STATES = new Set([
  'running', 'active', 'processing',
]);

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
  qa: { anchor: 'progress-card', focus: 'progress-card' },
  docs: { anchor: 'docs', focus: 'docs' },
};


/* Repo-layout string-contract compatibility for hidden/Alt06-adapted surfaces:
   class="stage-card bgc-stage-card ${escapeHtml(step.status)}"
   data-bgc-stage="${escapeHtml(step.id)}"
   class="job-rerun${rerunOpen ? ' active' : ''}"
*/

// ── Helpers ────────────────────────────────────────────────────────────────
function setCardCollapsed(id, collapsed) {
  const body = document.getElementById(id + '-body');
  const hdr = document.querySelector('#' + id + ' .card-header');
  if (body) body.classList.toggle('hidden', collapsed);
  if (hdr) hdr.classList.toggle('collapsed', collapsed);
}

const OPS_TABS = ['jobs', 'worker', 'qa'];
const OPS_TAB_PANEL_IDS = { jobs: 'jobs-card', worker: 'console-card', qa: 'progress-card' };

function setOpsPanelCollapsed(collapsed) {
  const isCollapsed = !!collapsed;
  document.body.dataset.opsPanel = isCollapsed ? 'collapsed' : 'open';
  const panel = document.getElementById('ops-side-panel');
  if (panel) panel.setAttribute('aria-hidden', isCollapsed ? 'true' : 'false');
  const toggle = document.getElementById('ops-panel-toggle');
  if (!toggle) return;
  const label = isCollapsed ? 'Open diagnostics drawer' : 'Close diagnostics drawer';
  toggle.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
  toggle.setAttribute('aria-label', label);
  toggle.setAttribute('title', label);
  const icon = toggle.querySelector('[data-ops-toggle-icon]');
  if (icon) icon.textContent = '▲';
  const srLabel = toggle.querySelector('[data-ops-toggle-label]');
  if (srLabel) srLabel.textContent = label;
}

function ensureOpsPanelToggle() {
  if (document.getElementById('ops-panel-toggle')) return;
  const panel = document.getElementById('ops-side-panel');
  if (!panel?.parentElement) return;
  if (panel.parentElement !== document.body) document.body.appendChild(panel);
  const toggle = document.createElement('button');
  toggle.className = 'ops-panel-toggle admin-only';
  toggle.id = 'ops-panel-toggle';
  toggle.type = 'button';
  toggle.setAttribute('aria-controls', 'ops-side-panel');
  toggle.innerHTML = '<span class="ops-panel-toggle-icon" data-ops-toggle-icon>▲</span>';
  toggle.addEventListener('click', toggleOpsPanel);
  document.body.insertBefore(toggle, panel);
  setOpsPanelCollapsed(document.body.dataset.opsPanel !== 'open');
  syncOpsTabs();
}

function removeOpsPanelToggle() {
  document.getElementById('ops-panel-toggle')?.remove();
  setOpsPanelCollapsed(true);
}

function activeOpsPanelElement() {
  return document.getElementById(OPS_TAB_PANEL_IDS[activeOpsTab] || OPS_TAB_PANEL_IDS.jobs);
}

function syncOpsTabs() {
  const selectedTab = OPS_TABS.includes(activeOpsTab) ? activeOpsTab : 'jobs';
  activeOpsTab = selectedTab;
  document.body.dataset.opsTab = selectedTab;
  document.querySelectorAll('.ops-nav-button[data-ops-tab]').forEach(button => {
    const active = button.dataset.opsTab === selectedTab;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
    button.tabIndex = active ? 0 : -1;
  });
  OPS_TABS.forEach(tab => {
    const panel = document.getElementById(OPS_TAB_PANEL_IDS[tab]);
    if (!panel) return;
    const active = tab === selectedTab;
    panel.hidden = !active;
    panel.classList.toggle('ops-tab-active', active);
    if (tab === 'qa') panel.classList.toggle('hidden', !active || !canUseAdminSurfaces());
  });
}

function switchOpsTab(tab, options = {}) {
  if (!canUseAdminSurfaces()) return;
  const next = OPS_TABS.includes(tab) ? tab : 'jobs';
  activeOpsTab = next;
  syncOpsTabs();
  if (next === 'qa') {
    void hydrateQaLogs({ tail: logHydratedJobId !== activeJobId, autoScroll: true });
  }
  if (next === 'jobs') refreshJobHistory();
  if (next === 'worker') pollSystemStatus();
  if (next === 'rerun') renderRerunPanel(activeJobId, activeJobMeta);
  if (options.focus !== false) {
    const target = options.focusPanel ? activeOpsPanelElement() : document.querySelector(`.ops-nav-button[data-ops-tab="${cssAttributeValue(next)}"]`);
    window.requestAnimationFrame(() => target?.focus?.({ preventScroll: true }));
  }
}

function handleOpsTabKeydown(event) {
  const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
  if (!keys.includes(event.key)) return;
  event.preventDefault();
  const current = OPS_TABS.indexOf(activeOpsTab);
  let next = current >= 0 ? current : 0;
  if (event.key === 'ArrowLeft') next = (next + OPS_TABS.length - 1) % OPS_TABS.length;
  if (event.key === 'ArrowRight') next = (next + 1) % OPS_TABS.length;
  if (event.key === 'Home') next = 0;
  if (event.key === 'End') next = OPS_TABS.length - 1;
  switchOpsTab(OPS_TABS[next]);
}

function openOpsPanel(options = {}) {
  if (!canUseAdminSurfaces()) return;
  lastOpsPanelFocus = options.returnFocus || document.activeElement || document.getElementById('ops-panel-toggle');
  setOpsPanelCollapsed(false);
  if (options.tab) activeOpsTab = OPS_TABS.includes(options.tab) ? options.tab : activeOpsTab;
  syncOpsTabs();
  animateOpsPanelToggle(true);
  const focusTarget = options.focusPanel ? activeOpsPanelElement() : document.querySelector(`.ops-nav-button[data-ops-tab="${cssAttributeValue(activeOpsTab)}"]`);
  window.requestAnimationFrame(() => focusTarget?.focus?.({ preventScroll: true }));
}

function closeOpsPanel(options = {}) {
  setOpsPanelCollapsed(true);
  animateOpsPanelToggle(false);
  if (options.returnFocus !== false) {
    const fallback = document.getElementById('ops-panel-toggle');
    const target = lastOpsPanelFocus && lastOpsPanelFocus.isConnected ? lastOpsPanelFocus : fallback;
    window.requestAnimationFrame(() => target?.focus?.({ preventScroll: true }));
  }
}

function toggleOpsPanel() {
  if (!canUseAdminSurfaces()) return;
  if (document.body.dataset.opsPanel === 'collapsed') openOpsPanel({ returnFocus: document.getElementById('ops-panel-toggle') });
  else closeOpsPanel({ returnFocus: true });
}

function wireOpsPanelKeyboard() {
  if (opsPanelKeyboardWired) return;
  opsPanelKeyboardWired = true;
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (!canUseAdminSurfaces() || document.body.dataset.opsPanel !== 'open') return;
    event.preventDefault();
    closeOpsPanel({ returnFocus: true });
  });
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
  // Alt06 mounts workflow progress through BGC WORKFLOW STATION.
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
  const hadAdminSurfaces = canUseAdminSurfaces();
  accessMode = ['public', 'admin', 'local'].includes(mode) ? mode : 'public';
  document.body.dataset.access = accessMode;
  if (canUseAdminSurfaces()) {
    ensureOpsPanelToggle();
    if (!hadAdminSurfaces) setOpsPanelCollapsed(true);
    syncOpsTabs();
  } else {
    rerunScopeOpenJobId = '';
    removeOpsPanelToggle();
  }
  if (accessMode === 'public') {
    document.body.dataset.managementView = 'closed';
    setUIMode('guided', { preserveDisclosure: true });
    document.getElementById('rerun-panel').innerHTML = '';
    if (!activeJobId && !document.getElementById('upload-card')?.classList.contains('upload-card-locked')) {
      setCardCollapsed('upload-card', false);
    }
  }
  syncOpsTabs();
  updateAccessTokenStatus();
  renderOpenedRuns();
  renderQaDrawer();
  if (document.getElementById('run-btn')) {
    syncControlState();
    renderFileList();
  }
  if (!hadAdminSurfaces && canUseAdminSurfaces()) {
    refreshJobHistory();
    startSystemConsolePolling();
    window.requestAnimationFrame(animateDiagnosticsReveal);
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
  const listed = Array.isArray(job?.result_files)
    ? job.result_files.map(normalizedResultPath).filter(Boolean).length : 0;
  return listed > 0 || Number(job?.result_file_count || 0) > 0;
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
  // Alt06 has no primary navigation drawer.
}

function togglePrimaryNav() {
  // Compatibility no-op for cached inline calls.
}

function syncDocsDisclosureState() {
  const docs = document.getElementById('docs');
  const isOpen = !!(docs && docs.open);
  document.body.dataset.docsDisclosure = isOpen ? 'open' : 'closed';
  const summary = docs?.querySelector('.docs-summary');
  if (summary) {
    summary.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    summary.setAttribute('aria-label', isOpen ? 'Close upstream tool credit' : 'Open upstream tool credit');
    summary.setAttribute('title', isOpen ? 'Close upstream tool credit' : 'Open upstream tool credit');
  }
  if (isOpen) {
    const runtimeStatus = document.getElementById('runtime-status-menu');
    if (runtimeStatus) runtimeStatus.open = false;
  }
}

function closeDocsDisclosure(options = {}) {
  const docs = document.getElementById('docs');
  if (!docs || !docs.open) return;
  const finish = () => {
    docs.open = false;
    syncDocsDisclosureState();
    if (options.returnFocus) docs.querySelector('.docs-summary')?.focus();
  };
  if (options.animate !== false && animateDocsDisclosureClose(docs, finish)) return;
  finish();
}

function focusDocsDisclosurePanel() {
  const docs = document.getElementById('docs');
  const panel = docs?.querySelector('.docs-panel');
  if (!docs?.open || !panel) return;
  window.setTimeout(() => panel.focus({ preventScroll: true }), 0);
}

function wireDocsDisclosure() {
  const openButton = document.getElementById('tool-credit-open');
  const overlay = document.getElementById('tool-credit-overlay');
  const closeButton = document.getElementById('tool-credit-close');
  if (openButton && overlay) {
    if (overlay.dataset.wired === '1') return;
    overlay.dataset.wired = '1';
    let lastFocus = null;
    const setOpen = (open, returnFocus = true) => {
      if (open) {
        lastFocus = document.activeElement;
        overlay.hidden = false;
        document.body.dataset.docsDisclosure = 'open';
        openButton.setAttribute('aria-expanded', 'true');
        window.requestAnimationFrame(() => closeButton?.focus?.({ preventScroll: true }));
        return;
      }
      overlay.hidden = true;
      document.body.dataset.docsDisclosure = 'closed';
      openButton.setAttribute('aria-expanded', 'false');
      if (returnFocus && lastFocus && typeof lastFocus.focus === 'function') {
        window.requestAnimationFrame(() => lastFocus.focus({ preventScroll: true }));
      }
    };
    openButton.setAttribute('aria-expanded', 'false');
    openButton.addEventListener('click', () => setOpen(true));
    closeButton?.addEventListener('click', () => setOpen(false));
    overlay.addEventListener('click', event => {
      if (event.target === overlay) setOpen(false);
    });
    document.addEventListener('keydown', event => {
      if (event.key !== 'Escape' || overlay.hidden) return;
      event.preventDefault();
      setOpen(false);
    });
    return;
  }

  const docs = document.getElementById('docs');
  if (!docs || docs.dataset.wired === '1') return;
  docs.dataset.wired = '1';
  syncDocsDisclosureState();
  const summary = docs.querySelector('.docs-summary');
  summary?.addEventListener('click', event => {
    event.preventDefault();
    if (docs.open) {
      closeDocsDisclosure({ returnFocus: true });
      return;
    }
    docs.open = true;
    syncDocsDisclosureState();
    animateDocsDisclosureOpen();
    focusDocsDisclosurePanel();
  });
  docs.addEventListener('toggle', () => {
    syncDocsDisclosureState();
    if (docs.open) {
      animateDocsDisclosureOpen();
      focusDocsDisclosurePanel();
    } else clearDocsMotionVars(docs);
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || !docs.open) return;
    event.preventDefault();
    closeDocsDisclosure({ returnFocus: true });
  });
  document.addEventListener('pointerdown', (event) => {
    if (!docs.open) return;
    const panel = docs.querySelector('.docs-panel');
    if (summary?.contains(event.target) || panel?.contains(event.target)) return;
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

function rerenderWorkflowSpineForResults(options = {}) {
  if (options.force) {
    const helix = document.getElementById('weavemap-helix');
    if (helix) delete helix.dataset.rendered;
  }
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
  if (canUseAdminSurfaces() && target === 'runs') {
    openOpsPanel({ tab: 'jobs', focusPanel: !!focusId });
    return;
  }
  if (canUseAdminSurfaces() && target === 'qa') {
    if (currentUIMode === 'guided') setUIMode('lab', { preserveDisclosure: true });
    openOpsPanel({ tab: 'qa', focusPanel: true });
    return;
  }
  if (target === 'intake' && document.body.dataset.entryMode === 'existing') switchEntryTab('new');
  closeResultDashboardForManagementTarget(target);
  setManagementViewForTarget(target);
  if (target === 'outputs' && activeJobMeta && !resultDashboardOpen) {
    showResultDashboard();
  }
  const cfg = NAV_TARGETS[target] || NAV_TARGETS.overview;
  const el = navElementFor(target);
  setActiveNav(target);
  closePrimaryNav();
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const outputRunId = activePublicRunId || publicRunIdFromJob(activeJobMeta, '');
    const route = target === 'outputs' && outputRunId
      ? `#/results/${encodeURIComponent(outputRunId)}`
      : `#${cfg.anchor}`;
    window.history.replaceState(null, '', route);
    window.setTimeout(() => focusSection(el, focusId || cfg.focus), 220);
  }
}

function syncNavFromHash() {
  const hash = window.location.hash.replace(/^#/, '');
  if (/^\/?(?:job|results)\//i.test(hash)) {
    setActiveNav('outputs');
    return;
  }
  const match = Object.entries(NAV_TARGETS).find(([, cfg]) => cfg.anchor === hash);
  if (match) setActiveNav(match[0]);
}

function parseResultHash() {
  const hash = window.location.hash || '';
  const match = hash.match(/^#\/?(job|results)\/([^/\s#?]+)(?:\/([^/\s#?]+))?\/?$/i);
  if (!match) return null;
  const routeKind = String(match[1] || '').toLowerCase();
  const jobId = decodeURIComponent(match[2]);
  const token = match[3] ? decodeURIComponent(match[3]) : readTokenForJob(jobId);
  if (!token && !canUseAdminSurfaces()) return null;
  if (routeKind === 'results') publicResultRunIds.add(jobId);
  return { jobId, token, publicResult: routeKind === 'results' };
}

function captureInitialResultHash() {
  const hash = window.location.hash || '';
  const match = hash.match(/^#\/?(job|results)\/([^/\s#?]+)(?:\/([^/\s#?]+))?\/?$/i);
  const parsed = parseResultHash();
  if (!parsed || !match?.[3]) return parsed;
  const token = String(parsed.token || '');
  if (!token) return parsed;
  pendingReadTokens.set(parsed.jobId, token);
  if (parsed.publicResult) {
    const runs = loadOpenedRuns().filter(run => String(run.id || '') !== parsed.jobId);
    runs.unshift({ id: parsed.jobId, token, name: parsed.jobId, status: '', updatedAt: new Date().toISOString() });
    saveOpenedRuns(runs);
  }
  const routeKind = parsed.publicResult ? 'results' : 'job';
  window.history.replaceState(null, '', `#/${routeKind}/${encodeURIComponent(parsed.jobId)}`);
  return parsed;
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

  setRuntimePanelValue('public-impact-server', runtimeStatusSnapshot.server);
  setRuntimePanelValue('public-impact-running', runtimeMetricText(runningJobs, '0'));
  setRuntimePanelValue('public-impact-queued', runtimeMetricText(queuedJobs, '0'));
  setRuntimePanelValue('public-impact-completed', runtimeMetricText(jobsProcessed, '0'));
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

function setDrawerText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function pluralizeCount(count, noun) {
  const n = Number(count || 0);
  return `${n.toLocaleString()} ${noun}${n === 1 ? '' : 's'}`;
}

function capabilityEnabled(value) {
  if (value === false || value === null || value === undefined) return false;
  if (typeof value === 'object') {
    if (value.enabled === false || value.available === false || value.disabled === true) return false;
  }
  return true;
}

function capabilityStageSummary(capabilities = runtimeCapabilities) {
  const stages = capabilities && typeof capabilities === 'object' ? capabilities.stages : null;
  if (!stages || typeof stages !== 'object') return 'Stage policy pending';
  const entries = Object.entries(stages);
  const enabled = entries.filter(([, value]) => capabilityEnabled(value));
  return `${enabled.length}/${entries.length || enabled.length} stages available`;
}

function runtimePolicyLabel(system = null) {
  const runtime = (system && system.runtime) || {};
  const caps = (system && system.capabilities) || runtimeCapabilities || {};
  const mode = runtime.mode || caps.mode || system?.mode || 'hosted';
  const engine = runtime.engine || caps.engine || system?.engine || 'auto';
  return `${mode} / ${engine}`;
}

function renderWorkerDrawer(system = null, jobs = null, meta = {}) {
  const summary = document.getElementById('worker-drawer-summary');
  if (!summary) return;
  const list = Array.isArray(jobs) ? jobs : [];
  const hasMeta = key => Object.prototype.hasOwnProperty.call(meta, key);
  const listRunning = list.filter(job => ['running', 'processing'].includes(String(job.status || job.state || job.pipeline_state || '').toLowerCase())).length;
  const listPending = list.filter(job => String(job.status || job.state || '').toLowerCase() === 'pending').length;
  const runningCount = hasMeta('runningCount') ? Number(meta.runningCount || 0) : Math.max(listRunning, Number(system?.running_jobs || 0), Number(lastWorkerTelemetry.runningCount || 0));
  const pendingCount = hasMeta('pendingCount') ? Number(meta.pendingCount || 0) : Math.max(listPending, Number(system?.queued_jobs || 0), Number(lastWorkerTelemetry.pendingCount || 0));
  const worker = (system && system.worker) || {};
  const status = String(meta.status || lastWorkerTelemetry.status || workerStatus || system?.state || 'unknown').toLowerCase();
  const statusLabels = {
    unknown: 'Monitoring',
    idle: 'Idle',
    ready: 'Ready',
    processing: 'Processing',
    error: 'Error',
    starting: 'Starting',
  };
  const stateLabel = statusLabels[status] || statusLabel(status);
  const concurrency = Number(meta.concurrency || worker.concurrency || system?.concurrency || lastWorkerTelemetry.concurrency || 0);
  const activeCount = Number(meta.activeCount || worker.active_count || runningCount || lastWorkerTelemetry.activeCount || 0);
  const submissions = runtimeStatusSnapshot.submissions || runtimeMetricText(system?.submissions || system?.submissions_open, 'Checking');
  const stageSummary = capabilityStageSummary((system && system.capabilities) || runtimeCapabilities);
  summary.textContent = `${stateLabel} · ${runningCount.toLocaleString()} running · ${pendingCount.toLocaleString()} queued`;
  setDrawerText('worker-drawer-state', stateLabel);
  setDrawerText('worker-drawer-detail', status === 'error'
    ? String(system?.detail || 'Worker reported an error.')
    : `Signal ${runtimeStatusSnapshot.server || 'checking'}; submissions ${submissions}.`);
  setDrawerText('worker-drawer-queue', `${runningCount} running / ${pendingCount} queued`);
  setDrawerText('worker-drawer-queue-detail', concurrency
    ? `${activeCount} active worker slot${activeCount === 1 ? '' : 's'} of ${concurrency}.`
    : 'Worker concurrency pending.');
  setDrawerText('worker-drawer-policy', runtimePolicyLabel(system));
  setDrawerText('worker-drawer-policy-detail', stageSummary);
}

function renderQaDrawer(job = activeJobMeta, files = activeResultFiles) {
  const summary = document.getElementById('qa-drawer-summary');
  if (!summary) return;
  const selectedId = String((job && job.id) || activeJobId || '');
  const fileList = Array.isArray(files) && files.length
    ? files
    : (Array.isArray(job?.result_files) ? job.result_files.map(normalizedResultPath).filter(Boolean) : []);
  const statusText = job ? statusLabel(job.status) : (selectedId ? 'Loading' : 'Idle');
  const stageText = job ? jobStageDisplay(job) : 'No active workflow stage';
  const project = job ? jobProjectName(job) : 'Open a job from the Jobs tab.';
  const updatedRaw = job && (job.updated_at || job.updatedAt || job.created_at || job.createdAt);
  const updatedDate = updatedRaw ? new Date(updatedRaw) : null;
  const updatedText = updatedDate && !Number.isNaN(updatedDate.getTime())
    ? updatedDate.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
    : 'No timestamp yet';
  const rerunJobId = String(rerunScopeOpenJobId || '');
  const rerunJob = rerunJobId && (jobHistoryById.get(rerunJobId) || (activeJobId === rerunJobId ? activeJobMeta : null));
  let rerunDetail = 'Use a Jobs card rerun control after a job finishes or fails.';
  if (rerunJobId && rerunJob) {
    const rerunStatus = String(rerunJob.status || '').toLowerCase();
    const availableStages = rerunStageKeysForJob(rerunJob).length;
    rerunDetail = (rerunStatus === 'pending' || rerunStatus === 'running')
      ? 'Rerun unlocks after the selected job finishes or fails.'
      : `${availableStages} stage option${availableStages === 1 ? '' : 's'} available.`;
  } else if (rerunJobId) {
    rerunDetail = 'Waiting for selected job details.';
  }
  summary.textContent = selectedId ? `${selectedId} · ${statusText}` : 'No job selected';
  setDrawerText('qa-job-id', selectedId || 'No job loaded');
  setDrawerText('qa-job-project', project);
  setDrawerText('qa-job-state', statusText);
  setDrawerText('qa-job-stage', stageText);
  setDrawerText('qa-log-count-card', `${Number(logCursor || 0).toLocaleString()} lines`);
  setDrawerText('qa-log-detail', selectedId ? `Updated ${updatedText}.` : 'Logs attach after a job is opened.');
  setDrawerText('qa-file-count', pluralizeCount(fileList.length, 'file'));
  setDrawerText('qa-file-detail', fileList.length ? 'Manifest indexed for the selected run.' : 'Result files appear after indexing.');
  setDrawerText('qa-rerun-scope', rerunJobId || 'No job selected');
  setDrawerText('qa-rerun-detail', rerunDetail);
}

function resetToIdleWorkbench() {
  stopPolling();
  activeJobId = null;
  activeJobMeta = null;
  activeSavedAnalysisContext = null;
  activeStageState = null;
  logCursor = 0;
  rerunScopeOpenJobId = '';
  resultDashboardOpen = false;
  activeResultCategory = 'figures';
  activeResultFiles = [];
  activeResultPackageFileCount = 0;
  document.body.dataset.resultsAvailable = 'false';
  activeResultArtifacts = null;
  const logTerminal = document.getElementById('log-terminal');
  if (logTerminal) logTerminal.innerHTML = '';
  setDrawerText('log-count', '0 lines');
  const rerunPanel = document.getElementById('rerun-panel');
  if (rerunPanel) rerunPanel.innerHTML = '';
  resetStagedAnalysisState('fungi');
  markActiveJobCard('');
  showEmptyResults();
  document.getElementById('upload-card')?.classList.remove('upload-card-locked');
  setCardCollapsed('upload-card', false);
  setRunSetupAccessCollapsed(false);
  switchEntryTab('new');
  setUIMode('guided', { preserveDisclosure: true });
  setResultsPanelCollapsed(true);
  closeOpsPanel({ returnFocus: false });
  renderQaDrawer(null, []);
  renderRunStack();
  refreshJobHistory();
  navigateToSection(null, 'overview', 'overview');
}

function returnToIdleHome(event) {
  if (event) event.preventDefault();
  resetToIdleWorkbench();
}


function shortRunId(jobId) {
  const id = String(jobId || '').trim();
  if (!id) return 'pending';
  return id.length > 8 ? id.slice(0, 8) : id;
}

function runStackProjectName(run) {
  return String((run && (run.name || run.project_name || run.projectName)) || run?.id || 'ClusterWeave run');
}

function runStackStatus(run) {
  const id = String((run && run.id) || '');
  if (id && activeJobId === id && activeJobMeta?.status) return activeJobMeta.status;
  return run?.status || '';
}

function setRunStackOpen(open) {
  const shell = document.getElementById('run-stack-shell');
  const menu = document.getElementById('run-stack-menu');
  const toggle = document.getElementById('run-stack-toggle');
  if (!shell || !menu || !toggle) return;
  const hasRuns = loadOpenedRuns().length > 0;
  runStackOpen = !!open && hasRuns;
  shell.dataset.runStackOpen = runStackOpen ? 'true' : 'false';
  menu.hidden = !runStackOpen;
  toggle.setAttribute('aria-expanded', runStackOpen ? 'true' : 'false');
  toggle.setAttribute('aria-label', runStackOpen ? 'Close run stack' : 'Open run stack');
}

function toggleRunStack() {
  setRunStackOpen(!runStackOpen);
}

function renderRunStack(runs = loadOpenedRuns()) {
  const shell = document.getElementById('run-stack-shell');
  const list = document.getElementById('run-stack-list');
  if (!shell || !list) return;
  const hasRuns = Array.isArray(runs) && runs.length > 0;
  shell.hidden = !hasRuns;
  shell.classList.toggle('hidden', !hasRuns);
  shell.toggleAttribute('inert', !hasRuns);
  shell.setAttribute('aria-hidden', hasRuns ? 'false' : 'true');
  if (!hasRuns) {
    list.innerHTML = '';
    setRunStackOpen(false);
    return;
  }
  list.innerHTML = runs.map(run => {
    const id = String(run.id || '');
    const jsId = escapeJsString(id);
    const active = id && id === activeJobId;
    const label = runStackProjectName(run);
    const status = statusLabel(runStackStatus(run));
    return `
      <button class="run-stack-run${active ? ' active' : ''}" type="button" role="menuitem" data-run-stack-job="${escapeHtml(id)}" onclick="loadRunStackJob('${escapeHtml(jsId)}')">
        <b>${escapeHtml(label)}</b>
        <span>${escapeHtml(shortRunId(id))} | ${escapeHtml(status)}</span>
      </button>`;
  }).join('');
  if (runStackOpen) setRunStackOpen(true);
}

async function loadRunStackJob(jobId) {
  const id = String(jobId || '');
  if (!id) return;
  setRunStackOpen(false);
  const job = await loadJob(id, true, { readToken: readTokenForJob(id), source: 'run-stack', deferResultsShell: true });
  document.body.dataset.existingRunLoaded = job ? 'true' : 'false';
  renderRunStack();
  if (job) navigateToSection(null, 'outputs');
}

function addRunFromStack() {
  setRunStackOpen(false);
  resetToIdleWorkbench();
}

function wireRunStackDismissal() {
  if (runStackDismissalWired) return;
  runStackDismissalWired = true;
  document.addEventListener('click', event => {
    if (!runStackOpen) return;
    const shell = document.getElementById('run-stack-shell');
    if (shell?.contains(event.target)) return;
    setRunStackOpen(false);
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !runStackOpen) return;
    event.preventDefault();
    setRunStackOpen(false);
    document.getElementById('run-stack-toggle')?.focus?.({ preventScroll: true });
  });
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

function switchToolCreditTab(name) {
  const selected = name === 'local' ? 'local' : 'web';
  document.querySelectorAll('.tool-credit-tab').forEach(tab => {
    const active = tab.id === `tool-credit-${selected}-tab`;
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
    tab.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll('.tool-credit-group[role="tabpanel"]').forEach(panel => {
    panel.hidden = panel.id !== `tool-credit-${selected}-panel`;
  });
}

function handleToolCreditTabKeydown(event) {
  const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
  if (!keys.includes(event.key)) return;
  event.preventDefault();
  const tabs = Array.from(document.querySelectorAll('.tool-credit-tab'));
  const current = tabs.indexOf(event.currentTarget);
  let next = current;
  if (event.key === 'ArrowLeft') next = (current + tabs.length - 1) % tabs.length;
  if (event.key === 'ArrowRight') next = (current + 1) % tabs.length;
  if (event.key === 'Home') next = 0;
  if (event.key === 'End') next = tabs.length - 1;
  const selected = tabs[next]?.id.includes('-local-') ? 'local' : 'web';
  switchToolCreditTab(selected);
  tabs[next]?.focus();
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
  animateEntryTabTransition(selectedName);
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
  const accessInput = document.getElementById('access-code-input');
  const status = document.getElementById('access-code-status') || document.getElementById('access-token-status');
  const button = document.getElementById('apply-access-code');
  if (button) button.textContent = (submitToken() || adminToken()) ? 'Code accepted' : 'Apply code';
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

async function validateAccessCode(value) {
  sessionSet(STORAGE_KEYS.submitToken, value);
  sessionSet(STORAGE_KEYS.adminToken, value);
  try {
    const resp = await apiFetch('api/access/validate', { cache: 'no-store' }, { kind: 'admin' });
    if (!resp.ok) return { admin: false, submit: false, accepted: false };
    return await resp.json();
  } catch (err) {
    return { admin: false, submit: false, accepted: false, error: err?.message || String(err) };
  }
}

async function saveAccessTokens() {
  const accessInput = document.getElementById('access-code-input');
  const typedValue = accessInput && !/^•+$/.test(accessInput.value) ? accessInput.value.trim() : '';
  const accessValue = typedValue || adminToken() || submitToken();
  if (!accessValue) {
    clearAccessTokens();
    return;
  }

  updateAccessTokenStatus('Checking access code...');
  const access = await validateAccessCode(accessValue);
  if (access?.admin) {
    const system = await fetchSystemStatus({ cache: 'no-store' });
    if (isFullSystemStatus(system)) {
      updateAccessTokenStatus('Diagnostics drawer opened for this tab.');
      openOpsPanel({ tab: 'jobs', focusPanel: true, returnFocus: accessInput || document.getElementById('apply-access-code') });
      refreshJobHistory();
      startSystemConsolePolling();
      return;
    }
  }

  if (access?.submit) {
    sessionSet(STORAGE_KEYS.adminToken, '');
    sessionSet(STORAGE_KEYS.submitToken, accessValue);
    setAccessMode('public');
    stopSystemConsolePolling();
    updateAccessTokenStatus('Submission code saved. Diagnostics require an admin code.');
    return;
  }

  sessionSet(STORAGE_KEYS.submitToken, '');
  sessionSet(STORAGE_KEYS.adminToken, '');
  setAccessMode('public');
  stopSystemConsolePolling();
  updateAccessTokenStatus('Access code was not accepted. Check the code and try again.');
}

function clearAccessTokens() {
  sessionSet(STORAGE_KEYS.submitToken, '');
  sessionSet(STORAGE_KEYS.adminToken, '');
  const accessInput = document.getElementById('access-code-input');
  if (accessInput) accessInput.value = '';
  setAccessMode('public');
  updateAccessTokenStatus('Access codes cleared.');
}

function updateEmailNotificationPanel() {
  const panel = document.getElementById('email-notification-panel');
  const input = document.getElementById('notify-email');
  if (!panel) return;
  panel.classList.remove('hidden');
  panel.classList.toggle('is-disabled', !smtpEnabled);
  panel.setAttribute('aria-disabled', smtpEnabled ? 'false' : 'true');
  if (!input) return;
  input.disabled = !smtpEnabled;
  input.placeholder = smtpEnabled ? 'name@example.com' : 'EMAIL OFF - server mail not configured';
  if (!smtpEnabled) input.value = '';
}

function parseExistingRunInput() {
  const raw = (document.getElementById('result-link-input')?.value || document.getElementById('existing-run-link')?.value || '').trim();
  const explicitToken = (document.getElementById('existing-run-token')?.value || document.getElementById('access-code-input')?.value || '').trim();
  if (!raw) return null;

  let text = raw;
  try {
    const url = new URL(raw, window.location.href);
    text = url.hash || url.pathname || raw;
  } catch (e) {}
  const fragmentMatch = text.match(/#\/?(job|results)\/([^/\s#?]+)\/([^/\s#?]+)/i);
  if (fragmentMatch) return {
    jobId: decodeURIComponent(fragmentMatch[2]),
    token: decodeURIComponent(fragmentMatch[3]),
    publicResult: String(fragmentMatch[1]).toLowerCase() === 'results',
  };

  const parts = raw.split(/[\s,]+/).filter(Boolean);
  if (parts.length >= 2) return {
    jobId: parts[0], token: parts[1], publicResult: !/^[0-9a-f]{8}$/i.test(parts[0]),
  };
  if (parts.length === 1 && explicitToken) return {
    jobId: parts[0], token: explicitToken, publicResult: !/^[0-9a-f]{8}$/i.test(parts[0]),
  };
  return null;
}

async function unlockExistingRun() {
  const status = document.getElementById('result-link-status') || document.getElementById('existing-run-status');
  const parsed = parseExistingRunInput();
  if (!parsed) {
    if (status) status.textContent = 'Enter a private result link, or a job ID plus result access code.';
    document.body.dataset.existingRunLoaded = 'false';
    return;
  }
  if (status) status.textContent = 'Opening private results...';
  const job = await loadJob(parsed.jobId, true, { readToken: parsed.token, publicResult: parsed.publicResult, source: 'existing-run', deferResultsShell: true });
  if (status) status.textContent = job ? 'Results opened in this tab.' : 'No run matched that job ID and result access code.';
  document.body.dataset.existingRunLoaded = job ? 'true' : 'false';
  if (job) {
    animateExistingResultUnlock();
    navigateToSection(null, 'outputs');
  }
}

function renderOpenedRuns() {
  const runs = loadOpenedRuns();
  const panel = document.getElementById('opened-runs-panel');
  const select = document.getElementById('opened-runs-select');
  if (panel && select) {
    panel.classList.toggle('hidden', runs.length === 0);
    select.innerHTML = runs.length
      ? `<option value="">Select recent result</option>${runs.map(run => `<option value="${escapeHtml(run.id)}">${escapeHtml(run.name || run.id)} (${escapeHtml(run.id)})</option>`).join('')}`
      : '<option value="">No recent results</option>';
    if (activeJobId) select.value = activeJobId;
  }
  renderRunStack(runs);
}

async function loadSelectedOpenedRun() {
  const select = document.getElementById('opened-runs-select');
  const status = document.getElementById('result-link-status') || document.getElementById('existing-run-status');
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
  if (job) {
    animateExistingResultUnlock();
    navigateToSection(null, 'outputs');
  }
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

function publicRunIdFromJob(job = activeJobMeta, fallback = activeJobId) {
  const candidate = String(
    job?.public_run_id || job?.publicRunId || job?.run_id || job?.runId || fallback || '',
  ).trim();
  return candidate;
}

function publicRunIdForJob(jobId = activeJobId) {
  const id = String(jobId || '').trim();
  if (id && id === String(activeJobId || '')) {
    return activePublicRunId || publicRunIdFromJob(activeJobMeta, id);
  }
  return publicRunIdFromJob(jobHistoryById.get(id), id);
}

function artifactCategoryFromDescriptor(descriptor) {
  const raw = String(descriptor?.category || descriptor?.family || 'other').toLowerCase();
  return resultCategoryKey(raw);
}

function safeArtifactFilename(value, fallback = 'artifact') {
  const basename = String(value || fallback).replace(/\\/g, '/').split('/').pop() || fallback;
  return basename.replace(/[^A-Za-z0-9._()+ -]/g, '_').slice(0, 240) || fallback;
}

function artifactPresentationKey(descriptor) {
  const id = String(descriptor?.id || '').trim();
  if (!/^[A-Za-z0-9_-]{16,}$/.test(id)) return '';
  const category = artifactCategoryFromDescriptor(descriptor);
  const filename = safeArtifactFilename(descriptor?.filename || descriptor?.name || descriptor?.label);
  return `artifact/${category}/${id}/${filename}`;
}

function resultArtifactMaps(resultContext = null) {
  if (
    resultContext
    && resultContext.byKey instanceof Map
    && resultContext.byId instanceof Map
  ) {
    return { byKey: resultContext.byKey, byId: resultContext.byId };
  }
  return { byKey: activeResultArtifactByKey, byId: activeResultArtifactById };
}

function installResultArtifactDescriptor(rawDescriptor, resultContext = null) {
  if (!rawDescriptor || typeof rawDescriptor !== 'object') return '';
  const id = String(rawDescriptor.id || '').trim();
  const key = artifactPresentationKey(rawDescriptor);
  if (!id || !key) return '';
  const descriptor = Object.freeze({
    ...rawDescriptor,
    id,
    filename: safeArtifactFilename(rawDescriptor.filename || rawDescriptor.name || rawDescriptor.label),
    category: artifactCategoryFromDescriptor(rawDescriptor),
    mime: String(rawDescriptor.mime || rawDescriptor.media_type || 'application/octet-stream'),
  });
  const maps = resultArtifactMaps(resultContext);
  maps.byKey.set(key, descriptor);
  maps.byId.set(id, descriptor);
  return key;
}

function installResultArtifactDescriptors(rawDescriptors, options = {}) {
  if (options.replace !== false) {
    activeResultArtifactByKey = new Map();
    activeResultArtifactById = new Map();
  }
  return (Array.isArray(rawDescriptors) ? rawDescriptors : [])
    .map(installResultArtifactDescriptor)
    .filter(Boolean);
}

function resultArtifactDescriptor(value, resultContext = null) {
  const maps = resultArtifactMaps(resultContext);
  const key = normalizedResultPath(value);
  if (maps.byKey.has(key)) return maps.byKey.get(key);
  const id = String(value || '').trim();
  return maps.byId.get(id) || null;
}

function resultArtifactId(value, resultContext = null) {
  return String(resultArtifactDescriptor(value, resultContext)?.id || '').trim();
}

function resultArtifactName(value, resultContext = null) {
  return resultArtifactDescriptor(value, resultContext)?.filename || fileNameFromPath(value);
}

function createResultArtifactContext(jobId) {
  const runId = String(publicRunIdForJob(jobId) || '').trim();
  if (!runId) throw new Error('The result preview is missing its opaque run identifier.');
  return Object.freeze({
    runId,
    byKey: new Map(activeResultArtifactByKey),
    byId: new Map(activeResultArtifactById),
  });
}

function apiUrl(path) {
  const cleanPath = String(path || '').replace(/^\/+/, '');
  const configuredBase = window.CLUSTERWEAVE_API_BASE || '';
  const base = configuredBase ? new URL(configuredBase, window.location.href).toString() : defaultApiBaseUrl();
  return new URL(cleanPath, base).toString();
}

function resultHref(jobId, artifactKey, options = {}) {
  const resultContext = options.resultContext || null;
  const runId = resultContext?.runId || publicRunIdForJob(jobId);
  const artifactId = resultArtifactId(artifactKey, resultContext);
  const base = apiUrl(`api/results/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId || 'unavailable')}`);
  return options.download ? `${base}/download` : base;
}

function privateResultLink(jobId, token, serverUrl = '') {
  if (serverUrl && /#\/?results\//i.test(serverUrl)) return serverUrl;
  return `${defaultApiBaseUrl()}#/results/${encodeURIComponent(jobId)}${token ? `/${encodeURIComponent(token)}` : ''}`;
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
function adoptPublicRunIdentity(requestedId, job) {
  const requested = String(requestedId || '').trim();
  const publicId = String(
    job?.public_run_id || job?.publicRunId || job?.run_id || job?.runId || '',
  ).trim();
  if (!publicId) return requested;
  activePublicRunId = publicId;
  publicResultRunIds.add(publicId);
  const token = readTokenForJob(requested) || readTokenForJob(publicId);
  if (token) {
    pendingReadTokens.set(publicId, token);
    const runs = loadOpenedRuns()
      .filter(run => ![requested, publicId].includes(String(run.id || '')));
    runs.unshift({
      id: publicId,
      token,
      name: job?.name || job?.project_name || job?.projectName || publicId,
      status: job?.status || '',
      updatedAt: new Date().toISOString(),
    });
    saveOpenedRuns(runs);
  }
  const hash = window.location.hash || '';
  const requestedEncoded = encodeURIComponent(requested);
  if (new RegExp(`^#\\/?(?:job|results)/${requestedEncoded}(?:/|$)`, 'i').test(hash)) {
    window.history.replaceState(null, '', `#/results/${encodeURIComponent(publicId)}`);
  }
  return publicId;
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
  if (!panel || !payload) return;
  const jobId = String(payload.jobId || payload.job_id || payload.id || '').trim();
  const readToken = String(payload.readToken || payload.read_token || payload.token || '').trim();
  if (!jobId) return;
  const resultUrl = privateResultLink(jobId, readToken, payload.resultUrl || payload.result_url || '');
  const projectName = payload.projectName || payload.project_name || 'ClusterWeave run';
  const expiresAt = payload.expiresAt || payload.expires_at || '';
  const notifyEmail = payload.notifyEmail || payload.notify_email || '';
  lastSubmittedRun = {
    ...payload,
    jobId,
    readToken,
    resultUrl,
  };
  const title = document.getElementById('submission-confirmation-title');
  const copy = document.getElementById('submission-confirmation-copy');
  const linkInput = document.getElementById('submitted-result-link');
  const jobInput = document.getElementById('submitted-job-id');
  const tokenInput = document.getElementById('submitted-result-token');
  const status = document.getElementById('submission-confirmation-status');
  const project = projectName;
  const expires = expiresAt ? ` Results expire ${new Date(expiresAt).toLocaleDateString()}.` : '';
  const email = notifyEmail ? ` A completion email will include a private result link for ${notifyEmail}.` : '';
  if (title) title.textContent = 'Initiating sequence. Launching ClusterWeave.';
  if (copy) copy.textContent = `${project} is queued. Save this private result link, or save the job ID with its result access code.${expires}${email}`;
  if (linkInput) linkInput.value = resultUrl;
  if (jobInput) jobInput.value = jobId;
  if (tokenInput) tokenInput.value = readToken;
  if (status) status.textContent = 'Result access is saved in this browser tab.';
  setResultAccessCollapsed(false);
  renderRunSetupAccessPanel({
    ...payload,
    jobId,
    readToken,
    resultUrl,
    projectName,
    expiresAt,
    notifyEmail,
    receipt: payload.receipt,
    jobState: payload.jobState || payload.job_state || payload.status || 'queued',
  });
  panel.classList.add('hidden');
}

function syncResultAccessCollapse() {
  const panel = document.getElementById('submission-confirmation');
  const toggle = document.getElementById('result-access-toggle');
  const details = document.getElementById('submission-confirmation-details');
  if (!panel) return;
  const collapsed = !!resultAccessCollapsed;
  panel.dataset.resultAccessCollapsed = collapsed ? 'true' : 'false';
  if (details) details.hidden = collapsed;
  if (toggle) {
    const label = collapsed ? 'Expand result access details' : 'Collapse result access details';
    toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    toggle.setAttribute('aria-label', label);
    toggle.setAttribute('title', label);
    const icon = toggle.querySelector('[data-result-access-toggle-icon]');
    if (icon) icon.textContent = collapsed ? '▸' : '▾';
    const srLabel = toggle.querySelector('[data-result-access-toggle-label]');
    if (srLabel) srLabel.textContent = label;
  }
}

function setResultAccessCollapsed(collapsed) {
  resultAccessCollapsed = !!collapsed;
  syncResultAccessCollapse();
}

function toggleResultAccessCard() {
  setResultAccessCollapsed(!resultAccessCollapsed);
}

function ecologyReceiptRows() {
  return currentEcologyMetadataRows()
    .filter(row => row.primary || row.secondary)
    .map(row => ({
      input: row.input,
      accession: row.accession || '',
      primary: row.primary || '',
      secondary: row.secondary || '',
    }));
}

function collectRunSetupAcceptedInputs() {
  const rows = [];
  const scope = normalizeAnalysisScope(stagedAnalysisScope);
  const declaredGroup = scope === 'both' ? '' : scope;
  const accessionSource = new Map();
  accessionFileSources.forEach((source) => {
    source.accessions.forEach((accession) => {
      const normalized = normalizeAccessionDraft(accession);
      if (normalized && !accessionSource.has(normalized)) accessionSource.set(normalized, source.name);
    });
  });
  manualAccessionLines().forEach((accession) => {
    rows.push({
      label: accession,
      kind: 'NCBI accession',
      source: accessionSource.get(normalizeAccessionDraft(accession)) || 'manual entry',
      taxonGroup: declaredGroup,
    });
  });
  logicalGenomeInputs().forEach((item) => {
    const decision = logicalGenomeTaxonAssignmentDecision(item);
    rows.push({
      label: item.inputKey,
      kind: 'Genome upload',
      source: item.files.map(file => file.name).join(' + '),
      taxonGroup: scope === 'both'
        ? decision.taxonGroup
        : scope,
    });
  });
  return rows;
}

function currentRunSetupOrganismName() {
  return document.getElementById('funannotate-organism-name')?.value.trim() || '';
}

function currentRunSetupTaxaLabel() {
  const scope = normalizeAnalysisScope(stagedAnalysisScope);
  if (scope === 'bacteria') return 'bacterial genome intake / Prodigal';
  if (scope === 'both') return 'fungi + bacteria genome intake';
  const buscoDb = document.getElementById('funannotate-busco-db')?.value.trim();
  return buscoDb ? `${buscoDb} / fungal genome intake` : 'fungal genome intake';
}

function collectRunSetupAccessReceipt(options = {}) {
  return {
    projectName: options.projectName || document.getElementById('project-name')?.value.trim() || 'my_project',
    accessions: manualAccessionLines(),
    uploadFiles: selectedFiles.map(file => file.name),
    accessionSources: accessionFileSources.map(source => ({
      name: source.name,
      count: source.accessions.length,
      accessions: source.accessions.slice(),
    })),
    acceptedInputs: collectRunSetupAcceptedInputs(),
    targetGenome: document.getElementById('target-genome')?.value.trim() || '',
    ecologyRows: ecologyReceiptRows(),
    organismName: currentRunSetupOrganismName(),
    taxa: currentRunSetupTaxaLabel(),
    analysisScope: normalizeAnalysisScope(stagedAnalysisScope),
    taxonAssignments: taxonAssignmentsPayload(),
  };
}

function setRunSetupAccessCollapsed(collapsed) {
  runSetupAccessCollapsed = !!collapsed;
  const panel = document.getElementById('run-setup-access-panel');
  const body = document.getElementById('run-setup-access-body');
  const toggle = document.getElementById('run-setup-access-toggle');
  if (panel) panel.dataset.runSetupCollapsed = runSetupAccessCollapsed ? 'true' : 'false';
  if (body) body.hidden = runSetupAccessCollapsed;
  if (toggle) {
    const label = runSetupAccessCollapsed ? 'Expand run setup access' : 'Collapse run setup access';
    toggle.setAttribute('aria-expanded', runSetupAccessCollapsed ? 'false' : 'true');
    toggle.setAttribute('aria-label', label);
    toggle.textContent = runSetupAccessCollapsed ? '▾' : '▴';
  }
}

function toggleRunSetupAccessPanel() {
  setRunSetupAccessCollapsed(!runSetupAccessCollapsed);
}

function renderReceiptChip(text) {
  return `<span class="receipt-chip">${escapeHtml(text)}</span>`;
}

function receiptInputKey(value) {
  return String(value || '').trim().toUpperCase();
}

function normalizeReceiptKind(kind, fallback = 'NCBI accession') {
  const value = String(kind || '').trim();
  if (!value) return fallback;
  if (/upload/i.test(value)) return 'Genome upload';
  if (/accession/i.test(value)) return 'NCBI accession';
  return value;
}

function receiptSourceByAccession(receipt) {
  const sources = new Map();
  (receipt.accessionSources || []).forEach((source) => {
    (source.accessions || []).forEach((accession) => {
      const key = receiptInputKey(accession);
      if (!key || sources.has(key)) return;
      sources.set(key, source.name || MANUAL_ACCESSIONS_FILENAME);
    });
  });
  return sources;
}

function receiptAccessionMetadataByInput(receipt) {
  const summary = receipt.inputSummary || receipt.input_summary || {};
  const records = [
    ...(Array.isArray(receipt.accessionMetadata) ? receipt.accessionMetadata : []),
    ...(Array.isArray(receipt.accession_metadata) ? receipt.accession_metadata : []),
    ...(Array.isArray(summary.accession_metadata) ? summary.accession_metadata : []),
  ];
  const metadata = new Map();
  records.forEach((record) => {
    const key = receiptInputKey(record && (record.accession || record.label || record.input));
    if (!key || metadata.has(key)) return;
    metadata.set(key, record);
  });
  return metadata;
}

function receiptAcceptedInputItems(receipt) {
  const sourceByAccession = receiptSourceByAccession(receipt);
  const metadataByInput = receiptAccessionMetadataByInput(receipt);
  const assignmentByInput = new Map();
  const receiptAssignments = receipt.taxonAssignments || receipt.taxon_assignments || {};
  if (receiptAssignments && typeof receiptAssignments === 'object' && !Array.isArray(receiptAssignments)) {
    Object.entries(receiptAssignments).forEach(([key, value]) => {
      const group = normalizeTaxonGroup(value);
      if (group) assignmentByInput.set(receiptInputKey(receiptGenomeStem(key)), group);
    });
  }
  const receiptScope = normalizeAnalysisScope(receipt.analysisScope || receipt.analysis_scope);
  const items = [];
  const seen = new Set();
  const targetKey = receiptInputKey(receipt.targetGenome);
  const addItem = (item, fallbackKind = 'NCBI accession') => {
    const label = String((item && (item.label || item.name || item.accession)) || '').trim();
    if (!label) return;
    const kind = normalizeReceiptKind(item.kind || item.type, fallbackKind);
    const key = `${kind}:${receiptInputKey(label)}`;
    if (seen.has(key)) return;
    seen.add(key);
    const source = String(item.source || sourceByAccession.get(receiptInputKey(label)) || '').trim();
    const labelKey = receiptInputKey(label);
    const metadata = metadataByInput.get(labelKey) || {};
    const taxId = metadata.tax_id || metadata.taxId || item.taxId || item.taxonId || '';
    items.push({
      label,
      kind,
      source,
      isTarget: !!item.isTarget || (!!targetKey && targetKey === labelKey),
      organismName: item.organismName || item.fungusName || metadata.organism_name || metadata.organismName || '',
      taxa: item.taxa || item.taxonomy || item.taxonomyLabel || metadata.taxa || metadata.taxonomy || (taxId ? `NCBI taxon ${taxId}` : ''),
      taxonGroup: normalizeTaxonGroup(
        item.taxonGroup
          || item.taxon_group
          || metadata.taxon_group
          || metadata.taxonGroup
          || assignmentByInput.get(receiptInputKey(receiptGenomeStem(label)))
          || (receiptScope === 'both' ? '' : receiptScope),
      ),
      taxId,
      orderName: item.orderName || item.order_name || metadata.order_name || metadata.orderName || '',
      familyName: item.familyName || item.family_name || metadata.family_name || metadata.familyName || '',
      className: item.className || item.class_name || metadata.class_name || metadata.className || metadata.class || '',
      orderFamily: item.orderFamily || item.order_family || metadata.order_family || metadata.orderFamily || '',
      summary: !!item.summary,
    });
  };

  if (Array.isArray(receipt.acceptedInputs) && receipt.acceptedInputs.length) {
    receipt.acceptedInputs.forEach(item => addItem(item));
  } else {
    (receipt.accessions || []).forEach(accession => addItem({ label: accession }, 'NCBI accession'));
    (receipt.uploadFiles || []).forEach(name => addItem({ label: name }, 'Genome upload'));
  }

  (receipt.accessionSources || []).forEach((source) => {
    if ((source.accessions || []).length) {
      source.accessions.forEach(accession => addItem({
        label: accession,
        kind: 'NCBI accession',
        source: source.name || MANUAL_ACCESSIONS_FILENAME,
      }));
      return;
    }
    if (positiveInteger(source.count)) {
      addItem({
        label: source.name || MANUAL_ACCESSIONS_FILENAME,
        kind: 'Accession list',
        source: `${source.count} accepted accession${source.count === 1 ? '' : 's'}`,
        summary: true,
      }, 'Accession list');
    }
  });

  (receipt.inputNotes || []).forEach(note => addItem({ label: note, kind: 'Loaded job', summary: true }, 'Loaded job'));
  return items;
}

function receiptEcologyRowsForInput(receipt, label) {
  const key = receiptInputKey(label);
  return (receipt.ecologyRows || []).filter((row) => {
    const rowInput = receiptInputKey(row.input);
    const rowAccession = receiptInputKey(row.accession);
    return rowInput === key || rowAccession === key;
  });
}

function receiptGenomeStem(label) {
  return String(label || '').replace(/\.(gbk|gb|gbff|fasta|fa|fna|fsa)$/i, '');
}

function receiptOrganismLine(receipt, item) {
  const itemName = String(item.organismName || '').trim();
  if (itemName) return itemName;
  const receiptName = String(receipt.organismName || receipt.fungusName || receipt.funannotateOrganismName || '').trim();
  if (receiptName && receiptName.toLowerCase() !== 'auto') return receiptName;
  if (item.kind === 'Genome upload') return receiptGenomeStem(item.label) || 'genus_species_strain';
  if (item.summary) return 'stored run input';
  return 'genus_species_strain from accepted input metadata';
}

function receiptTaxaLine(receipt, item) {
  const itemTaxa = String(item.taxa || '').trim();
  if (itemTaxa) return itemTaxa;
  const receiptTaxa = String(receipt.taxa || receipt.taxonomy || receipt.taxonomyLabel || '').trim();
  if (receiptTaxa) return receiptTaxa;
  if (item.taxonGroup === 'bacteria') return item.kind === 'NCBI accession' ? 'bacteria / NCBI taxonomy' : 'bacterial genome intake';
  if (item.taxonGroup === 'fungi') return item.kind === 'NCBI accession' ? 'fungi / NCBI taxonomy' : 'fungal genome intake';
  const scope = normalizeAnalysisScope(receipt.analysisScope || receipt.analysis_scope);
  if (scope === 'bacteria') return item.kind === 'NCBI accession' ? 'bacteria / NCBI taxonomy' : 'bacterial genome intake';
  if (scope === 'both') return item.kind === 'NCBI accession' ? 'NCBI taxonomy pending' : 'mixed genome intake';
  if (item.kind === 'NCBI accession') return 'fungi / NCBI taxonomy';
  if (item.kind === 'Genome upload') return 'fungal genome intake';
  return 'input taxonomy from stored run';
}

function receiptTaxonIdLine(item) {
  const taxId = String(item.taxId || '').trim();
  if (taxId) return `NCBI taxon ${taxId}`;
  const taxa = String(item.taxa || '').trim();
  const match = taxa.match(/NCBI taxon\s+(\d+)/i);
  return match ? `NCBI taxon ${match[1]}` : taxa;
}

function receiptOrderFamilyLine(item) {
  const explicit = String(item.orderFamily || '').trim();
  if (explicit) return explicit;
  const orderName = String(item.orderName || '').trim();
  const familyName = String(item.familyName || '').trim();
  if (orderName && familyName) return `${orderName}:${familyName}`;
  return orderName || familyName;
}

function receiptInlineDisplayLine(receipt, item) {
  if (item.kind !== 'NCBI accession') return item.label;
  const parts = [
    item.label,
    receiptTaxonIdLine(item),
    receiptOrganismLine(receipt, item),
    receiptOrderFamilyLine(item),
    String(item.className || '').trim(),
  ].filter(Boolean);
  return parts.join(' | ');
}

function receiptSourceChipText(source) {
  const value = String(source || '').trim();
  if (!value || value === 'manual entry' || value === MANUAL_ACCESSIONS_FILENAME) return '';
  return `From ${value}`;
}

function renderRunSetupInputReceipt(receipt) {
  if (!receipt || typeof receipt !== 'object') return '<div class="submitted-input-empty">No accepted input captured.</div>';
  const rows = [];
  receiptAcceptedInputItems(receipt).forEach((item) => {
    const ecology = receiptEcologyRowsForInput(receipt, item.label);
    const chips = item.summary ? [renderReceiptChip(item.kind)] : [];
    if (!item.summary && item.kind && item.kind !== 'NCBI accession') chips.push(renderReceiptChip(item.kind));
    if (item.isTarget) chips.push(renderReceiptChip('Target genome'));
    const sourceChip = receiptSourceChipText(item.source);
    if (sourceChip) chips.push(renderReceiptChip(sourceChip));
    ecology.forEach((row) => {
      if (row.primary) chips.push(renderReceiptChip(`ECO 1: ${row.primary}`));
      if (row.secondary) chips.push(renderReceiptChip(`ECO 2: ${row.secondary}`));
    });
    rows.push(`
    <div class="receipt-row${item.isTarget ? ' is-target' : ''}${item.summary ? ' is-summary' : ''}">
      <b class="receipt-line-text" title="${escapeHtml(receiptInlineDisplayLine(receipt, item))}">${escapeHtml(receiptInlineDisplayLine(receipt, item))}</b>
      <span class="receipt-row-status">
        ${item.taxonGroup ? `<span class="receipt-chip receipt-taxon-chip">${escapeHtml(analysisScopeLabel(item.taxonGroup))}</span>` : ''}
        <span class="receipt-dot" role="img" aria-label="Accepted input"></span>
      </span>
      ${chips.length ? `<div class="receipt-eco">${chips.join('')}</div>` : ''}
    </div>`);
  });
  return rows.length ? rows.join('') : '<div class="submitted-input-empty">No accepted input captured.</div>';
}

function receiptListFromValue(value) {
  if (Array.isArray(value)) return value.map(item => String(item || '').trim()).filter(Boolean);
  if (typeof value === 'string') return value.split(/[\n,]+/).map(item => item.trim()).filter(Boolean);
  return [];
}

function positiveInteger(value) {
  const n = Number(value || 0);
  return Number.isFinite(n) && n > 0 ? Math.trunc(n) : 0;
}

function runSetupProjectNameFromJob(job) {
  const settings = (job && (job.submission_settings || job.settings)) || {};
  return String((job && (job.project_name || job.name)) || settings.project_name || settings.projectName || (job && job.id) || 'ClusterWeave run');
}

function runSetupTargetGenomeFromJob(job) {
  const settings = (job && (job.submission_settings || job.settings)) || {};
  return String((job && (job.target_genome || job.targetGenome)) || settings.target_genome || settings.targetGenome || settings.target_strain || '');
}

function runSetupReceiptFromJob(job) {
  const settings = (job && (job.submission_settings || job.settings)) || {};
  const inputSummary = (job && (job.input_summary || job.inputSummary)) || {};
  const context = analysisContextFromJob(job);
  const metadataAccessions = Array.isArray(inputSummary.accession_metadata)
    ? inputSummary.accession_metadata.map(record => record && record.accession)
    : [];
  const accessions = [
    ...receiptListFromValue(job && job.accessions),
    ...receiptListFromValue(settings.accessions),
    ...receiptListFromValue(settings.manual_accessions),
    ...receiptListFromValue(settings.accession_text),
    ...receiptListFromValue(metadataAccessions),
  ].filter((value, index, list) => list.indexOf(value) === index);
  const uploadFiles = [
    ...receiptListFromValue(job && (job.upload_files || job.uploadFiles)),
    ...receiptListFromValue(settings.upload_files || settings.uploadFiles || settings.genome_files || settings.genomeFiles),
  ].filter((value, index, list) => list.indexOf(value) === index);
  const accessionSources = [];
  const accessionCount = positiveInteger(inputSummary.accession_count || inputSummary.accessions || settings.accession_count || settings.accessionCount);
  if (!accessions.length && accessionCount) {
    accessionSources.push({ name: 'NCBI accessions', count: accessionCount, accessions: [] });
  }
  const genomeFileCount = positiveInteger(inputSummary.genome_file_count || inputSummary.upload_file_count || settings.genome_file_count || settings.upload_file_count);
  if (!uploadFiles.length && genomeFileCount) {
    uploadFiles.push(`${genomeFileCount} genome file${genomeFileCount === 1 ? '' : 's'}`);
  }
  const inputNotes = (!accessions.length && !uploadFiles.length && !accessionSources.length)
    ? ['Stored run input']
    : [];
  return {
    projectName: runSetupProjectNameFromJob(job),
    accessions,
    uploadFiles,
    accessionSources,
    targetGenome: runSetupTargetGenomeFromJob(job),
    ecologyRows: [],
    accessionMetadata: Array.isArray(inputSummary.accession_metadata) ? inputSummary.accession_metadata : [],
    inputSummary,
    organismName: String(settings.funannotate_organism_name || settings.funannotateOrganismName || '').trim(),
    taxa: context.scope === 'bacteria'
      ? 'bacterial genome intake / Prodigal'
      : context.scope === 'both'
        ? 'fungi + bacteria genome intake'
        : 'fungal genome intake',
    analysisScope: context.scope,
    taxonCounts: context.taxonCounts,
    taxonAssignments: inputSummary.taxon_assignments || inputSummary.taxonAssignments || {},
    inputNotes,
  };
}

function runSetupReceiptInputCount(receipt) {
  return receiptAcceptedInputItems(receipt || {}).length;
}

function runSetupJobHref(jobId) {
  const id = String(jobId || '').trim();
  return id ? `${defaultApiBaseUrl()}#/results/${encodeURIComponent(id)}` : '';
}

function configureRunSetupResultLink(link, jobId) {
  if (!link) return;
  const id = String(jobId || '').trim();
  if (!id) {
    link.textContent = 'Pending';
    link.removeAttribute('href');
    link.removeAttribute('data-job-id');
    link.removeAttribute('aria-label');
    return;
  }
  const runId = publicRunIdForJob(id);
  const href = runSetupJobHref(runId);
  link.textContent = href;
  link.href = href;
  link.dataset.jobId = runId;
  link.setAttribute('aria-label', `Open results for run ${runId}`);
}

async function openRunSetupResultAccess(event) {
  if (event) event.preventDefault();
  const link = (event && event.currentTarget) || document.getElementById('run-setup-result-link');
  const jobId = String(link?.dataset.jobId || '').trim();
  if (!jobId) return;
  const openCurrentJob = () => {
    navigateToSection(null, 'outputs');
    window.history.replaceState(null, '', `#/results/${encodeURIComponent(publicRunIdForJob(jobId))}`);
  };
  if (activeJobId === jobId && activeJobMeta) {
    openCurrentJob();
    return;
  }
  const job = await loadJob(jobId, true, {
    readToken: readTokenForJob(jobId),
    source: 'run-setup-access',
    deferResultsShell: true,
  });
  if (job) openCurrentJob();
}

function renderRunSetupAccessPanel(payload = {}) {
  const panel = document.getElementById('run-setup-access-panel');
  const jobId = String(payload.jobId || payload.job_id || payload.id || '').trim();
  if (!panel || !jobId) return;
  const existingReceipt = submittedRunReceipt && String(submittedRunReceipt.jobId || '') === jobId
    ? submittedRunReceipt.receipt
    : null;
  const receipt = payload.receipt || existingReceipt || collectRunSetupAccessReceipt({ projectName: payload.projectName });
  submittedRunReceipt = {
    jobId,
    receipt,
    jobState: payload.jobState || payload.status || 'queued',
  };
  const inputList = document.getElementById('run-setup-input-list');
  const inputCount = document.getElementById('run-setup-input-count');
  const project = document.getElementById('run-setup-project');
  const analysisScope = document.getElementById('run-setup-analysis-scope');
  const target = document.getElementById('run-setup-target');
  const link = document.getElementById('run-setup-result-link');
  const job = document.getElementById('run-setup-job-id');
  const state = document.getElementById('run-setup-job-state');
  const expiration = document.getElementById('run-setup-expiration');
  const count = runSetupReceiptInputCount(receipt);
  if (inputList) inputList.innerHTML = renderRunSetupInputReceipt(receipt);
  if (inputCount) inputCount.textContent = String(count);
  if (project) project.textContent = receipt.projectName || payload.projectName || 'ClusterWeave run';
  if (analysisScope) {
    const context = {
      scope: receipt.analysisScope || receipt.analysis_scope || payload.analysisScope || payload.analysis_scope,
      taxonCounts: receipt.taxonCounts || receipt.taxon_counts || payload.taxonCounts || payload.taxon_counts || {},
    };
    const counts = normalizeTaxonCounts(context.taxonCounts);
    const countLabel = counts.known ? ` · ${counts.fungi} fungi / ${counts.bacteria} bacteria` : '';
    analysisScope.textContent = `${analysisScopeLabel(context.scope)}${countLabel}`;
  }
  if (target) target.textContent = receipt.targetGenome || 'Not selected';
  configureRunSetupResultLink(link, jobId);
  if (job) job.textContent = jobId;
  if (state) state.textContent = submittedRunReceipt.jobState;
  const expiresAt = payload.expiresAt || payload.expires_at || '';
  if (expiration) expiration.textContent = expiresAt ? `Results expire ${new Date(expiresAt).toLocaleDateString()}.` : '';
  document.getElementById('submission-confirmation')?.classList.add('hidden');
  panel.classList.remove('hidden');
  document.body.dataset.runSetupAccess = 'open';
  setRunSetupAccessCollapsed(runSetupAccessCollapsed);
}

function updateRunSetupAccessFromJob(job) {
  const jobId = String((job && job.id) || '');
  if (!submittedRunReceipt || !jobId || String(submittedRunReceipt.jobId || '') !== jobId) return false;
  submittedRunReceipt.jobState = job.status || submittedRunReceipt.jobState || 'queued';
  const state = document.getElementById('run-setup-job-state');
  if (state) state.textContent = submittedRunReceipt.jobState;
  return true;
}

function clearRunSetupAccessPanel() {
  submittedRunReceipt = null;
  runSetupAccessCollapsed = false;
  document.getElementById('run-setup-access-panel')?.classList.add('hidden');
  document.body.dataset.runSetupAccess = 'closed';
  setRunSetupAccessCollapsed(false);
  document.getElementById('upload-card')?.classList.remove('upload-card-locked');
}

function renderActiveRunAccessPanel(job) {
  const legacyPanel = document.getElementById('submission-confirmation');
  if (!job || !job.id) {
    if (legacyPanel) legacyPanel.classList.add('hidden');
    return;
  }
  const jobId = String(job.id);
  const token = readTokenForJob(jobId);
  const link = token ? privateResultLink(jobId, token, job.result_url || '') : '';
  const project = runSetupProjectNameFromJob(job);
  const receipt = submittedRunReceipt && String(submittedRunReceipt.jobId || '') === jobId
    ? submittedRunReceipt.receipt
    : runSetupReceiptFromJob(job);
  const linkInput = document.getElementById('submitted-result-link');
  const jobInput = document.getElementById('submitted-job-id');
  const tokenInput = document.getElementById('submitted-result-token');
  const status = document.getElementById('submission-confirmation-status');
  if (linkInput) linkInput.value = link;
  if (jobInput) jobInput.value = jobId;
  if (tokenInput) tokenInput.value = token || (canUseAdminSurfaces() ? 'Diagnostics access active' : '');
  if (status) status.textContent = token ? 'Result access is saved for this browser tab.' : 'Diagnostics access is being used for this job.';
  renderRunSetupAccessPanel({
    jobId,
    projectName: project,
    readToken: token,
    resultUrl: link,
    receipt,
    jobState: job.status || 'loaded',
    status: job.status,
    expiresAt: job.expires_at,
  });
  if (legacyPanel) legacyPanel.classList.add('hidden');
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
  if (kind === 'admin') {
    const admin = adminToken();
    if (admin) headers.Authorization = `Bearer ${admin}`;
    return headers;
  }
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
  return !!adminToken()
    || (accessMode === 'public' && !!readTokenForJob(publicRunIdForJob(jobId)));
}

function canOpenRichHtmlArtifacts(jobId = activeJobId) {
  return canUseAdminSurfaces() || !!readTokenForJob(publicRunIdForJob(jobId));
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

const TOOL_RESULT_RUNTIME_MAX_ACTIVE = 4;
const TOOL_RESULT_RUNTIME_MAX_QUEUE = 64;
const TOOL_RESULT_RUNTIME_MAX_PER_DOCUMENT = 512;
const TOOL_RESULT_RUNTIME_RESOLVE_TIMEOUT_MS = 15000;

function toolResultPreviewChannel() {
  if (typeof window.crypto?.getRandomValues !== 'function') {
    throw new Error('A cryptographically secure result-preview channel is unavailable.');
  }
  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
}

const RESULT_PREVIEW_NAVIGATOR_SCRIPT = String.raw`
(function () {
  const scriptEl = document.currentScript || document.querySelector('script[data-clusterweave-result-preview]');
  if (!scriptEl || scriptEl.dataset.ready === '1') return;
  scriptEl.dataset.ready = '1';
  const channel = scriptEl.dataset.channel || '';
  const owner = scriptEl.dataset.owner || '';
  const pending = new Map();
  const prepared = new WeakMap();
  const maxPending = 64;
  const maxRequests = 512;
  const resolveTimeoutMs = 15000;
  let requestSequence = 0;

  function relativeReference(element) {
    const value = String(element && element.getAttribute('href') || '').trim();
    if (!value || value.startsWith('#')) return null;
    if (value.startsWith('/') || value.includes('\\')
        || /^(?:[a-z][a-z0-9+.-]*:)?\/\//i.test(value)
        || /^(?:data|blob|mailto|tel|javascript):/i.test(value)) {
      return { value: value, supported: false };
    }
    const path = value.split(/[?#]/, 1)[0];
    const match = path.match(/\.([a-z0-9]+)$/i);
    const extension = match ? match[1].toLowerCase() : '';
    return {
      value: value,
      supported: ['html', 'htm', 'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp'].includes(extension),
    };
  }

  function disableLocalLink(element) {
    prepared.delete(element);
    element.removeAttribute('href');
    element.removeAttribute('target');
    element.removeAttribute('rel');
    element.removeAttribute('aria-busy');
    element.removeAttribute('data-clusterweave-result-pending');
    element.removeAttribute('data-clusterweave-result-request');
    element.setAttribute('aria-disabled', 'true');
    element.setAttribute('title', 'This link is outside the generated result bundle.');
  }

  function prepareLocalLink(element) {
    if (!element
        || element.hasAttribute('data-clusterweave-result-artifact')
        || element.hasAttribute('data-clusterweave-result-fragment')
        || element.getAttribute('aria-disabled') === 'true') return;
    const reference = relativeReference(element);
    if (!reference) return;
    if (!reference.supported || !channel || !owner) {
      disableLocalLink(element);
      return;
    }
    const addedRole = !element.hasAttribute('role');
    const addedTabIndex = !element.hasAttribute('tabindex');
    prepared.set(element, {
      value: reference.value,
      addedRole: addedRole,
      addedTabIndex: addedTabIndex,
    });
    element.removeAttribute('href');
    element.removeAttribute('target');
    element.removeAttribute('rel');
    element.setAttribute('data-clusterweave-result-pending', '');
    if (addedRole) element.setAttribute('role', 'link');
    if (addedTabIndex) element.setAttribute('tabindex', '0');
  }

  function finishPreparedLink(element) {
    const state = prepared.get(element);
    prepared.delete(element);
    element.removeAttribute('data-clusterweave-result-pending');
    if (state && state.addedRole) element.removeAttribute('role');
    if (state && state.addedTabIndex) element.removeAttribute('tabindex');
  }

  function requestResolution(element, activate) {
    const existing = element.getAttribute('data-clusterweave-result-request') || '';
    if (existing && pending.has(existing)) {
      if (activate) pending.get(existing).activate = true;
      return;
    }
    const reference = prepared.get(element);
    if (!reference || pending.size >= maxPending || requestSequence >= maxRequests) {
      disableLocalLink(element);
      return;
    }
    const request = 'r' + String(++requestSequence);
    const timer = window.setTimeout(function () {
      const entry = pending.get(request);
      if (!entry) return;
      pending.delete(request);
      disableLocalLink(entry.element);
    }, resolveTimeoutMs);
    pending.set(request, { element: element, activate: !!activate, timer: timer });
    element.setAttribute('data-clusterweave-result-request', request);
    element.setAttribute('aria-busy', 'true');
    window.parent.postMessage({
      type: 'clusterweave:result-bundle-resolve',
      channel: channel,
      owner: owner,
      request: request,
      reference: reference.value,
    }, '*');
  }

  function scan(root) {
    const elements = [];
    if (root && root.matches && root.matches('a[href],area[href]')) elements.push(root);
    if (root && root.querySelectorAll) elements.push.apply(elements, root.querySelectorAll('a[href],area[href]'));
    elements.forEach(prepareLocalLink);
  }

  function navigateArtifact(artifact, fragment) {
    window.parent.postMessage({
      type: 'clusterweave:result-bundle-navigate',
      channel: channel,
      owner: owner,
      artifact: artifact,
      fragment: fragment || '',
    }, '*');
  }

  window.addEventListener('message', function (event) {
    const payload = event && event.data;
    if (event.source !== window.parent || !payload
        || payload.type !== 'clusterweave:result-bundle-resolved'
        || payload.channel !== channel || payload.owner !== owner) return;
    const request = String(payload.request || '');
    const entry = pending.get(request);
    if (!entry) return;
    pending.delete(request);
    window.clearTimeout(entry.timer);
    const element = entry.element;
    element.removeAttribute('data-clusterweave-result-request');
    element.removeAttribute('aria-busy');
    const artifact = String(payload.artifact || '');
    const href = String(payload.href || '');
    const fragment = String(payload.fragment || '');
    if (!/^[A-Za-z0-9_-]{16,}$/.test(artifact) || !href) {
      disableLocalLink(element);
      return;
    }
    finishPreparedLink(element);
    element.setAttribute('href', href);
    element.setAttribute('data-clusterweave-result-artifact', artifact);
    element.setAttribute('data-clusterweave-result-fragment', fragment);
    if (entry.activate) navigateArtifact(artifact, fragment);
  });

  function interactiveTarget(event) {
    return event.target && event.target.closest
      ? event.target.closest('a,area')
      : null;
  }

  function activateTarget(event, target) {
    const pendingRequest = target.getAttribute('data-clusterweave-result-request') || '';
    if (pendingRequest && pending.has(pendingRequest)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      pending.get(pendingRequest).activate = true;
      return;
    }
    const artifact = target.getAttribute('data-clusterweave-result-artifact') || '';
    const fragment = target.getAttribute('data-clusterweave-result-fragment') || '';
    if (!artifact && !fragment) {
      if (!prepared.has(target)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      requestResolution(target, true);
      return;
    }
    if (!artifact && fragment.startsWith('#')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      const anchor = fragment.slice(1);
      const previousHash = window.location.hash;
      if (window.viewer && typeof window.viewer.switchToRegion === 'function') {
        window.viewer.switchToRegion(anchor);
      } else {
        try {
          window.location.hash = anchor;
          const destination = document.getElementById(anchor) || document.querySelector('[name="' + CSS.escape(anchor) + '"]');
          if (destination && typeof destination.scrollIntoView === 'function') destination.scrollIntoView({ block: 'start' });
          if (previousHash === '#' + anchor) {
            window.dispatchEvent(new HashChangeEvent('hashchange'));
          }
        } catch (error) {}
      }
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    navigateArtifact(artifact, fragment);
  }

  function warmLink(event) {
    if (!event.isTrusted) return;
    const target = interactiveTarget(event);
    if (target && prepared.has(target)) requestResolution(target, false);
  }

  document.addEventListener('pointerover', warmLink, true);
  document.addEventListener('focusin', warmLink, true);
  document.addEventListener('click', function (event) {
    if (!event.isTrusted || event.defaultPrevented) return;
    const target = interactiveTarget(event);
    if (target) activateTarget(event, target);
  }, true);
  document.addEventListener('keydown', function (event) {
    if (!event.isTrusted || event.defaultPrevented || event.key !== 'Enter') return;
    const target = interactiveTarget(event);
    if (target && (prepared.has(target) || target.hasAttribute('data-clusterweave-result-artifact'))) {
      activateTarget(event, target);
    }
  }, true);
  const observer = new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      if (mutation.type === 'attributes') scan(mutation.target);
      else Array.prototype.forEach.call(mutation.addedNodes || [], scan);
    });
  });
  observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ['href'],
  });
  scan(document);
})();
`;

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

function resultArtifactFamilyRoot(path) {
  const parts = normalizedResultPath(path).split('/');
  if (
    parts.length < 6
    || parts[0] !== 'data'
    || parts[1] !== 'results'
    || !parts[2]
    || !['antismash', 'funbgcex'].includes(String(parts[3]).toLowerCase())
    || !parts[4]
    || parts.slice(0, 5).some(part => !part || part === '.' || part === '..')
  ) return '';
  return parts.slice(0, 5).join('/');
}

function resultArtifactFamilyAssetPath(ownerPath, rawUrl) {
  const familyRoot = resultArtifactFamilyRoot(ownerPath);
  if (!familyRoot || resultUrlShouldStayExternal(rawUrl)) return '';
  const resolved = normalizedResultPath(resultRelativeAssetPath(ownerPath, rawUrl));
  const parts = resolved.split('/');
  if (
    !resolved.startsWith(`${familyRoot}/`)
    || parts.some(part => !part || part === '.' || part === '..')
  ) return '';
  return resolved;
}

function isToolResultBundleHtml(path, resultContext = null) {
  const descriptor = resultArtifactDescriptor(path, resultContext);
  return ['antismash', 'funbgcex'].includes(String(descriptor?.category || ''))
    && ['html', 'htm'].includes(resultPathExt(path));
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

const TOOL_RESULT_PREVIEW_ASSET_MAX_BYTES = 16 * 1024 * 1024;
const TOOL_RESULT_PREVIEW_TOTAL_ASSET_MAX_BYTES = 64 * 1024 * 1024;
const BIGSCAPE_PREVIEW_ASSET_MAX_BYTES = 16 * 1024 * 1024;
const BIGSCAPE_PREVIEW_TOTAL_ASSET_MAX_BYTES = 64 * 1024 * 1024;
const BIGSCAPE_PORTABLE_ASSET_EXTENSIONS = new Set([
  'css',
  'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico',
  'woff', 'woff2', 'ttf', 'otf', 'eot',
]);

function bigscapeHtmlContentRoot(ownerPath) {
  const parts = normalizedResultPath(ownerPath).split('/');
  if (
    parts.length < 5
    || parts.some(part => !part || part === '.' || part === '..')
    || parts[0] !== 'data'
    || parts[1] !== 'results'
    || !parts[2]
    || !['big_scape', 'bigscape', 'big-scape'].includes(String(parts[3]).toLowerCase())
  ) return '';
  const htmlContentIndex = parts.indexOf('html_content', 4);
  const rootParts = htmlContentIndex >= 0
    ? parts.slice(0, htmlContentIndex)
    : parts.slice(0, -1);
  return rootParts.length >= 4 ? `${rootParts.join('/')}/html_content` : '';
}

function bigscapeHtmlContentAssetPath(ownerPath, rawUrl) {
  const contentRoot = bigscapeHtmlContentRoot(ownerPath);
  if (!contentRoot || resultUrlShouldStayExternal(rawUrl)) return '';
  const resolved = normalizedResultPath(resultRelativeAssetPath(ownerPath, rawUrl));
  const parts = resolved.split('/');
  if (
    !resolved.startsWith(`${contentRoot}/`)
    || parts.some(part => !part || part === '.' || part === '..')
  ) return '';
  return resolved;
}

function bigscapePortableAssetPathAllowed(path) {
  return BIGSCAPE_PORTABLE_ASSET_EXTENSIONS.has(resultPathExt(path));
}

function assertBigscapeAssetDeclaredSize(response, budget = null) {
  const raw = response?.headers?.get?.('Content-Length');
  const declared = Number(raw);
  if (
    raw === null
    || String(raw).trim() === ''
    || !Number.isSafeInteger(declared)
    || declared < 0
    || declared > BIGSCAPE_PREVIEW_ASSET_MAX_BYTES
  ) {
    throw new Error('A BiG-SCAPE preview asset is missing a safe Content-Length or exceeds 16 MiB.');
  }
  if (budget) {
    budget.declaredBytes += declared;
    if (budget.declaredBytes > BIGSCAPE_PREVIEW_TOTAL_ASSET_MAX_BYTES) {
      throw new Error('The BiG-SCAPE preview asset bundle exceeds the 64 MiB browser limit.');
    }
  }
  return declared;
}

function assertBigscapeAssetActualSize(size, budget = null) {
  if (!Number.isSafeInteger(size) || size < 0 || size > BIGSCAPE_PREVIEW_ASSET_MAX_BYTES) {
    throw new Error('A BiG-SCAPE preview asset exceeds the 16 MiB browser limit.');
  }
  if (budget) {
    budget.actualBytes += size;
    if (budget.actualBytes > BIGSCAPE_PREVIEW_TOTAL_ASSET_MAX_BYTES) {
      throw new Error('The BiG-SCAPE preview asset bundle exceeds the 64 MiB browser limit.');
    }
  }
}

function assertToolResultAssetSize(response, actualSize, budget) {
  const raw = response?.headers?.get?.('Content-Length');
  const declared = Number(raw);
  if (
    raw === null
    || String(raw).trim() === ''
    || !Number.isSafeInteger(declared)
    || declared < 0
    || declared > TOOL_RESULT_PREVIEW_ASSET_MAX_BYTES
    || !Number.isSafeInteger(actualSize)
    || actualSize < 0
    || actualSize > TOOL_RESULT_PREVIEW_ASSET_MAX_BYTES
  ) {
    throw new Error('A result preview asset is missing a safe size or exceeds 16 MiB.');
  }
  budget.declaredBytes += declared;
  budget.actualBytes += actualSize;
  if (
    budget.declaredBytes > TOOL_RESULT_PREVIEW_TOTAL_ASSET_MAX_BYTES
    || budget.actualBytes > TOOL_RESULT_PREVIEW_TOTAL_ASSET_MAX_BYTES
  ) {
    throw new Error('The result preview asset bundle exceeds the 64 MiB browser limit.');
  }
}


const STATIC_RESULT_PREVIEW_CSP = "default-src 'none'; img-src data: blob:; style-src 'unsafe-inline' data: blob:; font-src data: blob:; media-src data: blob:; connect-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'";
const TOOL_RESULT_PREVIEW_CSP = "default-src 'none'; script-src 'unsafe-inline'; img-src data: blob:; style-src 'unsafe-inline' data: blob:; font-src data: blob:; media-src data: blob:; connect-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'";
const TOOL_RESULT_PREVIEW_SANDBOX = 'allow-scripts';
const CLINKER_RESULT_PREVIEW_CSP = "default-src 'none'; script-src 'unsafe-inline'; img-src data: blob:; style-src 'unsafe-inline' data: blob:; font-src data: blob:; media-src data: blob:; connect-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'";
const CLINKER_PREVIEW_SANDBOX = 'allow-scripts';
const BIGSCAPE_RESULT_PREVIEW_CSP = "default-src 'none'; script-src 'unsafe-inline'; img-src data: blob:; style-src 'unsafe-inline' data: blob:; font-src data: blob:; media-src data: blob:; connect-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'";
const BIGSCAPE_PREVIEW_SANDBOX = 'allow-scripts';
const BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM = '(1,eval)("this")';
const BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM_COUNT = 2;

function isExactPublicClinkerPanelHtml(path) {
  const descriptor = resultArtifactDescriptor(path);
  return descriptor?.category === 'synteny' && /^panel\.html$/i.test(resultArtifactName(path));
}

function injectResultPreviewNavigator(doc, jobId, htmlPath) {
  // Result HTML is rendered as a static, network-isolated document.  Bearer
  // credentials must never be copied into tool-generated DOM.
  void doc;
  void jobId;
  void htmlPath;
}

function resultBlobDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('Could not read result asset.'));
    reader.readAsDataURL(blob);
  });
}

async function resultAssetObjectUrl(jobId, ownerPath, rawUrl, cache, options = {}) {
  const parts = splitResultAssetUrl(rawUrl);
  const bigscapeMode = options.bigscapeMode === true;
  const toolBundleMode = options.toolBundleMode === true;
  const resultContext = options.resultContext || null;
  const cacheKey = `${resultArtifactId(ownerPath, resultContext)}:${parts.path}`;
  if (cache.has(cacheKey)) return cache.get(cacheKey);
  const promise = (async () => {
    const resolved = await resolveResultArtifact(jobId, ownerPath, parts.path, {
      optional: true,
      resultContext,
    });
    if (!resolved) return '';
    const assetKey = resolved.key;
    if (bigscapeMode && !bigscapePortableAssetPathAllowed(resultArtifactName(assetKey, resultContext))) return '';
    const resp = await resultFetch(jobId, assetKey, { resultContext });
    if (!resp.ok) return '';
    if (bigscapeMode) assertBigscapeAssetDeclaredSize(resp, options.bigscapeAssetBudget);
    const contentType = resp.headers.get('Content-Type') || '';
    let blob;
    if (resultPathExt(assetKey) === 'css' || /^text\/css\b/i.test(contentType)) {
      const cssText = await resp.text();
      const cssSize = new Blob([cssText]).size;
      if (bigscapeMode) assertBigscapeAssetActualSize(cssSize, options.bigscapeAssetBudget);
      if (toolBundleMode) assertToolResultAssetSize(resp, cssSize, options.toolBundleAssetBudget);
      const rewrittenCss = await rewriteCssResultUrls(cssText, jobId, assetKey, cache, options);
      blob = new Blob([rewrittenCss], { type: inlineResultMime(assetKey, 'text/css;charset=utf-8') });
    } else {
      const sourceBlob = await resp.blob();
      if (bigscapeMode) assertBigscapeAssetActualSize(sourceBlob.size, options.bigscapeAssetBudget);
      if (toolBundleMode) assertToolResultAssetSize(resp, sourceBlob.size, options.toolBundleAssetBudget);
      blob = new Blob([sourceBlob], { type: inlineResultMime(assetKey, sourceBlob.type || contentType) });
    }
    const url = options.portableDataUrls === true
      ? await resultBlobDataUrl(blob)
      : URL.createObjectURL(blob);
    if (options.portableDataUrls !== true) resultHelperObjectUrls.push(url);
    return url;
  })();
  cache.set(cacheKey, promise);
  return promise;
}

function stripToolResultCssImports(cssText) {
  const source = String(cssText || '');
  let output = '';
  let cursor = 0;
  let index = 0;
  let quote = '';
  let inComment = false;
  while (index < source.length) {
    const current = source[index];
    const next = source[index + 1] || '';
    if (inComment) {
      if (current === '*' && next === '/') {
        inComment = false;
        index += 2;
      } else {
        index += 1;
      }
      continue;
    }
    if (quote) {
      if (current === '\\') {
        index += 2;
      } else {
        if (current === quote) quote = '';
        index += 1;
      }
      continue;
    }
    if (current === '/' && next === '*') {
      inComment = true;
      index += 2;
      continue;
    }
    if (current === '"' || current === "'") {
      quote = current;
      index += 1;
      continue;
    }
    if (
      current === '@'
      && source.slice(index, index + 7).toLowerCase() === '@import'
      && !/[A-Za-z0-9_-]/.test(source[index + 7] || '')
    ) {
      output += source.slice(cursor, index);
      let ruleIndex = index + 7;
      let ruleQuote = '';
      let ruleComment = false;
      let parenDepth = 0;
      while (ruleIndex < source.length) {
        const ruleCurrent = source[ruleIndex];
        const ruleNext = source[ruleIndex + 1] || '';
        if (ruleComment) {
          if (ruleCurrent === '*' && ruleNext === '/') {
            ruleComment = false;
            ruleIndex += 2;
          } else {
            ruleIndex += 1;
          }
          continue;
        }
        if (ruleQuote) {
          if (ruleCurrent === '\\') {
            ruleIndex += 2;
          } else {
            if (ruleCurrent === ruleQuote) ruleQuote = '';
            ruleIndex += 1;
          }
          continue;
        }
        if (ruleCurrent === '/' && ruleNext === '*') {
          ruleComment = true;
          ruleIndex += 2;
          continue;
        }
        if (ruleCurrent === '"' || ruleCurrent === "'") {
          ruleQuote = ruleCurrent;
          ruleIndex += 1;
          continue;
        }
        if (ruleCurrent === '(') parenDepth += 1;
        if (ruleCurrent === ')' && parenDepth > 0) parenDepth -= 1;
        ruleIndex += 1;
        if (ruleCurrent === ';' && parenDepth === 0) break;
      }
      output += '/* ClusterWeave removed a result-bundle import rule. */';
      index = ruleIndex;
      cursor = ruleIndex;
      quote = '';
      inComment = false;
      continue;
    }
    index += 1;
  }
  return output + source.slice(cursor);
}

async function rewriteCssResultUrls(cssText, jobId, ownerPath, cache, options = {}) {
  const originalSource = String(cssText || '');
  if (options.bigscapeMode && /@import\b/i.test(originalSource)) {
    throw new Error('BiG-SCAPE preview CSS @import rules are not supported.');
  }
  const source = options.toolBundleMode
    ? stripToolResultCssImports(originalSource)
    : originalSource;
  const regex = /url\(\s*([\'\"]?)([^\'\")]+)\1\s*\)/gi;
  let output = '';
  let lastIndex = 0;
  for (const match of source.matchAll(regex)) {
    output += source.slice(lastIndex, match.index);
    const quote = match[1] || '';
    const rawUrl = match[2] || '';
    let rewritten = '';
    if (options.bigscapeMode || !resultUrlShouldStayExternal(rawUrl)) {
      rewritten = await resultAssetObjectUrl(jobId, ownerPath, rawUrl, cache, options);
    }
    output += rewritten
      ? `url(${quote}${rewritten}${resultAssetHashSuffix(rawUrl)}${quote})`
      : options.bigscapeMode || options.toolBundleMode
        ? 'none'
        : match[0];
    lastIndex = match.index + match[0].length;
  }
  return output + source.slice(lastIndex);
}

function isClassicResultScript(script) {
  const type = String(script?.getAttribute?.('type') || '').trim().toLowerCase();
  return !type || [
    'text/javascript',
    'application/javascript',
    'text/ecmascript',
    'application/ecmascript',
  ].includes(type);
}

function rewriteToolResultScriptForSandbox(assetPath, sourceText, resultContext = null) {
  const source = String(sourceText || '');
  if (!/^antismash\.js$/i.test(resultArtifactName(assetPath, resultContext))) return source;
  const getter = 'function T(){const t=window.location.hash.substring(1);return t||"overview"}';
  const switcher = 'function k(){setTimeout((()=>{$(".page").hide()';
  if (source.split(getter).length !== 2 || source.split(switcher).length !== 2) {
    throw new Error('The antiSMASH region navigator does not match the sandbox compatibility profile.');
  }
  return source
    .replace(
      getter,
      'let clusterweaveAnchor="";function T(){const t=clusterweaveAnchor||window.location.hash.substring(1);return t||"overview"}',
    )
    .replace(
      switcher,
      'function k(t){if(t)clusterweaveAnchor=t;setTimeout((()=>{$(".page").hide()',
    );
}

function rewriteBigscapeScriptForSandbox(assetPath, sourceText) {
  const source = String(sourceText || '');
  if (!/^kinetic-v5\.1\.0\.min\.js$/i.test(resultArtifactName(assetPath))) {
    return source;
  }
  const occurrences = source.split(BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM).length - 1;
  if (occurrences !== BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM_COUNT) {
    throw new Error('The bundled BiG-SCAPE Kinetic runtime does not match the CSP-safe compatibility profile.');
  }
  return source.replaceAll(BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM, 'globalThis');
}

async function inlineBigscapeResultScripts(doc, jobId, htmlPath, options = {}) {
  const scripts = Array.from(doc.querySelectorAll('script[src]'));
  await Promise.all(scripts.map(async script => {
    const rawUrl = script.getAttribute('src') || '';
    if (resultUrlShouldStayExternal(rawUrl)) {
      script.remove();
      return;
    }
    if (
      !isClassicResultScript(script)
      || script.hasAttribute?.('async')
      || script.hasAttribute?.('defer')
    ) {
      script.remove();
      throw new Error('BiG-SCAPE preview requires local synchronous classic JavaScript assets.');
    }
    const parts = splitResultAssetUrl(rawUrl);
    const resolved = await resolveResultArtifact(jobId, htmlPath, parts.path, { optional: true });
    const assetKey = resolved?.key || '';
    if (!assetKey || resultArtifactDescriptor(assetKey)?.category !== 'bigscape'
        || resultPathExt(assetKey) !== 'js') {
      script.remove();
      throw new Error('A local BiG-SCAPE script is outside its html_content JavaScript bundle.');
    }
    try {
      const resp = await resultFetch(jobId, assetKey);
      if (!resp.ok) {
        script.remove();
        throw new Error('A required local BiG-SCAPE script could not be loaded.');
      }
      assertBigscapeAssetDeclaredSize(resp, options.bigscapeAssetBudget);
      const source = rewriteBigscapeScriptForSandbox(
        assetKey,
        String(await resp.text()),
      ).replace(/<\/script/gi, '<\\/script');
      assertBigscapeAssetActualSize(new Blob([source]).size, options.bigscapeAssetBudget);
      script.textContent = source;
      for (const attr of [
        'src', 'integrity', 'crossorigin', 'referrerpolicy',
        'nonce', 'async', 'defer',
      ]) {
        script.removeAttribute(attr);
      }
    } catch (error) {
      script.remove();
      throw error instanceof Error
        ? error
        : new Error('A required local BiG-SCAPE script could not be loaded.');
    }
  }));
}

async function inlineToolResultScripts(doc, jobId, htmlPath, options = {}) {
  const scripts = Array.from(doc.querySelectorAll('script[src]'));
  const deferredScripts = [];
  const resultContext = options.resultContext || null;
  for (const script of scripts) {
    const wasDeferred = script.hasAttribute('defer');
    const rawUrl = script.getAttribute('src') || '';
    const resolved = await resolveResultArtifact(
      jobId,
      htmlPath,
      splitResultAssetUrl(rawUrl).path,
      { optional: true, resultContext },
    );
    const assetKey = resolved?.key || '';
    const ownerDescriptor = resultArtifactDescriptor(htmlPath, resultContext);
    const assetDescriptor = resultArtifactDescriptor(assetKey, resultContext);
    if (!assetKey || !isClassicResultScript(script) || resultPathExt(assetKey) !== 'js'
        || assetDescriptor?.category !== ownerDescriptor?.category
        || assetDescriptor?.bundle_id !== ownerDescriptor?.bundle_id) {
      script.remove();
      continue;
    }
    const resp = await resultFetch(jobId, assetKey, { resultContext });
    if (!resp.ok) {
      script.remove();
      throw new Error('A required result-bundle script could not be loaded.');
    }
    const source = rewriteToolResultScriptForSandbox(
      assetKey,
      String(await resp.text()),
      resultContext,
    ).replace(/<\/script/gi, '<\\/script');
    assertToolResultAssetSize(resp, new Blob([source]).size, options.toolBundleAssetBudget);
    script.textContent = source;
    for (const attr of [
      'src', 'integrity', 'crossorigin', 'referrerpolicy',
      'nonce', 'async', 'defer',
    ]) script.removeAttribute(attr);
    if (wasDeferred) deferredScripts.push(script);
  }
  const deferredTarget = doc.body || doc.documentElement;
  deferredScripts.forEach(script => deferredTarget.appendChild(script));
}

async function rewriteHtmlResultAssets(htmlText, jobId, htmlPath, options = {}) {
  const source = String(htmlText || '');
  const doc = new DOMParser().parseFromString(source, 'text/html');
  const cache = new Map();
  const resultContext = options.resultContext || null;
  const allowClinkerInlineScripts = options.allowClinkerInlineScripts === true && isExactPublicClinkerPanelHtml(htmlPath);
  const allowBigscapeScripts = options.allowBigscapeScripts === true && isBigscapeHtmlArtifact(htmlPath);
  const allowToolBundleScripts = options.allowToolBundleScripts === true
    && isToolResultBundleHtml(htmlPath, resultContext);
  const bigscapeAssetBudget = allowBigscapeScripts
    ? { declaredBytes: 0, actualBytes: 0 }
    : null;
  const toolBundleAssetBudget = allowToolBundleScripts
    ? { declaredBytes: 0, actualBytes: 0 }
    : null;
  const assetOptions = {
    portableDataUrls: allowBigscapeScripts || allowToolBundleScripts,
    bigscapeMode: allowBigscapeScripts,
    bigscapeAssetBudget,
    toolBundleMode: allowToolBundleScripts,
    toolBundleAssetBudget,
    resultContext,
  };
  const blockedElements = allowBigscapeScripts
    ? 'iframe,object,embed,base'
    : allowToolBundleScripts
      ? 'iframe,object,embed,base'
      : allowClinkerInlineScripts
        ? 'script[src],iframe,object,embed,base'
        : 'script,iframe,object,embed,base';
  Array.from(doc.querySelectorAll(blockedElements)).forEach(node => node.remove());
  Array.from(doc.querySelectorAll('meta[http-equiv="Content-Security-Policy" i]')).forEach(node => node.remove());
  Array.from(doc.querySelectorAll('meta[http-equiv="refresh" i]')).forEach(node => node.remove());
  Array.from(doc.querySelectorAll('[srcset]')).forEach(node => node.removeAttribute('srcset'));
  Array.from(doc.querySelectorAll('[autofocus]')).forEach(node => node.removeAttribute('autofocus'));
  Array.from(doc.querySelectorAll('form[action], [formaction]')).forEach(node => {
    node.removeAttribute('action');
    node.removeAttribute('formaction');
  });
  const csp = doc.createElement('meta');
  csp.setAttribute('http-equiv', 'Content-Security-Policy');
  csp.setAttribute(
    'content',
    allowBigscapeScripts
      ? BIGSCAPE_RESULT_PREVIEW_CSP
      : allowToolBundleScripts
        ? TOOL_RESULT_PREVIEW_CSP
        : allowClinkerInlineScripts
          ? CLINKER_RESULT_PREVIEW_CSP
          : STATIC_RESULT_PREVIEW_CSP,
  );
  (doc.head || doc.documentElement).prepend(csp);
  const assetAttrs = [
    ['link[href]', 'href'],
    ['img[src]', 'src'],
    ['source[src]', 'src'],
    ['video[poster]', 'poster'],
    ['audio[src]', 'src'],
    ['video[src]', 'src'],
    ['input[src]', 'src'],
    ['track[src]', 'src'],
  ];
  const scriptTask = allowBigscapeScripts
    ? inlineBigscapeResultScripts(doc, jobId, htmlPath, assetOptions)
    : allowToolBundleScripts
      ? inlineToolResultScripts(doc, jobId, htmlPath, assetOptions)
      : Promise.resolve();
  const assetTasks = [];
  for (const [selector, attr] of assetAttrs) {
    for (const el of Array.from(doc.querySelectorAll(selector))) {
      assetTasks.push((async () => {
        const value = el.getAttribute(attr) || '';
        if (/^javascript:/i.test(value)) {
          el.removeAttribute(attr);
          return;
        }
        if (resultUrlShouldStayExternal(value)) {
          el.removeAttribute(attr);
          return;
        }
        const rewritten = await resultAssetObjectUrl(jobId, htmlPath, value, cache, assetOptions);
        if (rewritten) {
          el.setAttribute(attr, rewritten + resultAssetHashSuffix(value));
        } else {
          el.removeAttribute(attr);
        }
      })());
    }
  }
  await Promise.all([scriptTask, ...assetTasks]);
  await Promise.all(Array.from(doc.querySelectorAll('style')).map(async styleEl => {
    styleEl.textContent = await rewriteCssResultUrls(
      styleEl.textContent || '', jobId, htmlPath, cache, assetOptions,
    );
  }));
  await Promise.all(Array.from(doc.querySelectorAll('[style]')).map(async el => {
    const value = el.getAttribute('style') || '';
    const rewritten = await rewriteCssResultUrls(value, jobId, htmlPath, cache, assetOptions);
    if (rewritten !== value) el.setAttribute('style', rewritten);
  }));
  for (const el of Array.from(doc.querySelectorAll('a[href],area[href]'))) {
    const value = el.getAttribute('href') || '';
    if (/^javascript:/i.test(value)) {
      el.removeAttribute('href');
    } else if (allowToolBundleScripts && value.startsWith('#')) {
      el.setAttribute('href', `${resultHref(jobId, htmlPath, { resultContext })}${value}`);
      el.setAttribute('data-clusterweave-result-fragment', value);
    } else if (allowToolBundleScripts && resultUrlShouldStayExternal(value)) {
      el.removeAttribute('href');
      el.removeAttribute('target');
      el.removeAttribute('rel');
      el.setAttribute('aria-disabled', 'true');
      el.setAttribute('title', 'This link is outside the generated result bundle.');
    } else if (!resultUrlShouldStayExternal(value)) {
      if (allowToolBundleScripts) {
        const localReferencePath = splitResultAssetUrl(value).path;
        if (!['html', 'htm'].includes(resultPathExt(localReferencePath))) {
          el.removeAttribute('href');
          el.setAttribute('aria-disabled', 'true');
          el.setAttribute('title', 'This link is outside the generated result bundle.');
          continue;
        }
        const resolved = await resolveResultArtifact(
          jobId,
          htmlPath,
          value,
          { optional: true, resultContext },
        );
        if (resolved && isToolResultBundleHtml(resolved.key, resultContext)) {
          const fragment = resolved.fragment || resultAssetHashSuffix(value);
          const cleanHref = `${resultHref(jobId, resolved.key, { resultContext })}${fragment}`;
          el.setAttribute('href', cleanHref);
          el.setAttribute('data-clusterweave-result-artifact', resolved.descriptor.id);
          el.setAttribute('data-clusterweave-result-fragment', fragment);
        } else {
          el.removeAttribute('href');
          el.setAttribute('aria-disabled', 'true');
          el.setAttribute('title', 'This link is outside the generated result bundle.');
        }
      } else {
        el.removeAttribute('href');
        el.setAttribute('aria-disabled', 'true');
        el.setAttribute('title', 'This link is outside the generated result bundle.');
      }
    } else if (/^(?:[a-z][a-z0-9+.-]*:)?\/\//i.test(value)) {
      if (allowBigscapeScripts) {
        el.removeAttribute('href');
        el.setAttribute('aria-disabled', 'true');
      } else {
        el.setAttribute('rel', 'noopener noreferrer');
        el.setAttribute('target', '_blank');
      }
    } else if (allowBigscapeScripts && !value.startsWith('#')) {
      el.removeAttribute('href');
      el.setAttribute('aria-disabled', 'true');
    }
  }
  if (allowToolBundleScripts) {
    const navigator = doc.createElement('script');
    navigator.setAttribute('data-clusterweave-result-preview', '');
    navigator.setAttribute('data-channel', String(options.toolPreviewChannel || ''));
    navigator.setAttribute('data-owner', resultArtifactId(htmlPath, resultContext));
    navigator.textContent = RESULT_PREVIEW_NAVIGATOR_SCRIPT;
    (doc.body || doc.head || doc.documentElement).appendChild(navigator);
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

function renderSandboxedClinkerPreview(targetWindow, relPath, htmlText) {
  const doc = targetWindow.document;
  const title = fileNameFromPath(relPath) || 'Clinker panel';
  doc.open();
  doc.write(`<!doctype html>
<html><head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-src 'self'; child-src 'self'; connect-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'">
<meta name="referrer" content="no-referrer">
<title>${escapeHtml(title)}</title>
<style>html,body{height:100%;margin:0;background:#fff}iframe{display:block;width:100%;height:100%;border:0}</style>
</head><body></body></html>`);
  doc.close();
  const frame = doc.createElement('iframe');
  frame.id = 'clusterweave-clinker-preview';
  frame.setAttribute('sandbox', CLINKER_PREVIEW_SANDBOX);
  frame.setAttribute('referrerpolicy', 'no-referrer');
  frame.setAttribute('title', title);
  frame.srcdoc = htmlText;
  doc.body.appendChild(frame);
  return frame;
}

function renderSandboxedBigscapePreview(targetWindow, relPath, htmlText, databaseBuffer, channel) {
  const doc = targetWindow.document;
  const title = fileNameFromPath(relPath) || 'BiG-SCAPE';
  doc.open();
  doc.write(`<!doctype html>
<html><head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; img-src data: blob:; style-src 'unsafe-inline' data: blob:; font-src data: blob:; media-src data: blob:; frame-src 'self'; child-src 'self'; connect-src 'none'; object-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'">
<meta name="referrer" content="no-referrer">
<title>${escapeHtml(title)}</title>
<style>html,body{height:100%;margin:0;background:#fff}iframe{display:block;width:100%;height:100%;border:0}</style>
<script>(function(){
  let transferBuffer = null;
  let transferChannel = '';
  let transferFrameId = '';
  let transferTimeout = null;

  function cleanupTransfer() {
    window.removeEventListener('message', transferDatabase);
    window.removeEventListener('pagehide', cleanupTransfer);
    window.removeEventListener('beforeunload', cleanupTransfer);
    if (transferTimeout) window.clearTimeout(transferTimeout);
    transferTimeout = null;
    transferBuffer = null;
    transferChannel = '';
    transferFrameId = '';
    window.CLUSTERWEAVE_BIGSCAPE_INSTALL_TRANSFER = null;
  }

  function transferDatabase(event) {
    const frame = document.getElementById(transferFrameId);
    const payload = event && event.data;
    if (!frame
        || event.source !== frame.contentWindow
        || !payload
        || payload.type !== 'clusterweave:bigscape-database-ready'
        || payload.channel !== transferChannel) return;
    const buffer = transferBuffer;
    const isArrayBuffer = Object.prototype.toString.call(buffer) === '[object ArrayBuffer]';
    if (!isArrayBuffer || !Number.isFinite(buffer.byteLength) || buffer.byteLength <= 0) return;
    const selectedChannel = transferChannel;
    cleanupTransfer();
    try {
      frame.contentWindow.postMessage({
        type: 'clusterweave:bigscape-database',
        channel: selectedChannel,
        buffer,
      }, '*', [buffer]);
    } catch (error) {
      frame.contentWindow.postMessage({
        type: 'clusterweave:bigscape-database-error',
        channel: selectedChannel,
      }, '*');
    }
  }

  window.CLUSTERWEAVE_BIGSCAPE_INSTALL_TRANSFER = function(buffer, channel, frameId) {
    const isArrayBuffer = Object.prototype.toString.call(buffer) === '[object ArrayBuffer]';
    if (!isArrayBuffer || !Number.isFinite(buffer.byteLength) || buffer.byteLength <= 0) {
      throw new Error('The compact BiG-SCAPE viewer transfer buffer is invalid.');
    }
    transferBuffer = buffer;
    transferChannel = String(channel || '');
    transferFrameId = String(frameId || '');
    window.addEventListener('message', transferDatabase);
    window.addEventListener('pagehide', cleanupTransfer, { once: true });
    window.addEventListener('beforeunload', cleanupTransfer, { once: true });
    transferTimeout = window.setTimeout(cleanupTransfer, 120000);
  };
})();<\/script>
</head><body></body></html>`);
  doc.close();
  const frame = doc.createElement('iframe');
  frame.id = 'clusterweave-bigscape-preview';
  frame.setAttribute('sandbox', BIGSCAPE_PREVIEW_SANDBOX);
  frame.setAttribute('referrerpolicy', 'no-referrer');
  frame.setAttribute('title', title);
  const installTransfer = targetWindow.CLUSTERWEAVE_BIGSCAPE_INSTALL_TRANSFER;
  if (typeof installTransfer !== 'function') {
    throw new Error('The compact BiG-SCAPE popup transfer relay could not be installed.');
  }
  // The relay is defined in the popup realm so the sandbox receives the
  // database message from window.parent, never from the application opener.
  installTransfer(databaseBuffer, channel, frame.id);
  databaseBuffer = null;
  frame.srcdoc = htmlText;
  doc.body.appendChild(frame);
  return frame;
}

function renderSandboxedToolResultPreview(
  targetWindow,
  jobId,
  relPath,
  htmlText,
  channel,
  resultContext,
) {
  if (!resultContext?.runId) {
    throw new Error('The result-bundle popup is missing its immutable artifact context.');
  }
  const doc = targetWindow.document;
  const title = resultArtifactName(relPath, resultContext) || 'Result bundle';
  doc.open();
  doc.write(`<!doctype html>
<html><head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; img-src data: blob:; style-src 'unsafe-inline' data: blob:; font-src data: blob:; media-src data: blob:; frame-src blob:; child-src blob:; connect-src 'none'; object-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'">
<meta name="referrer" content="no-referrer">
<title>${escapeHtml(title)}</title>
<style>html,body{height:100%;margin:0;background:#fff}iframe{display:block;width:100%;height:100%;border:0}</style>
<script>(function(){
  window.CLUSTERWEAVE_TOOL_RESULT_POST = function(frameId, payload) {
    const selectedFrame = document.getElementById(String(frameId || ''));
    if (!selectedFrame || !selectedFrame.contentWindow) return;
    selectedFrame.contentWindow.postMessage(payload, '*');
  };
  window.addEventListener('pagehide', function() {
    window.CLUSTERWEAVE_TOOL_RESULT_POST = null;
  }, { once: true });
})();<\/script>
</head><body></body></html>`);
  doc.close();
  const frame = doc.createElement('iframe');
  frame.id = 'clusterweave-tool-result-preview';
  frame.setAttribute('sandbox', TOOL_RESULT_PREVIEW_SANDBOX);
  frame.setAttribute('referrerpolicy', 'no-referrer');
  frame.setAttribute('title', title);
  const postToFrame = targetWindow.CLUSTERWEAVE_TOOL_RESULT_POST;
  if (typeof postToFrame !== 'function') {
    throw new Error('The result-bundle popup relay could not be installed.');
  }
  let currentPath = normalizedResultPath(relPath);
  let currentChannel = String(channel || '');
  let navigating = false;
  let frameDocumentUrl = '';
  let runtimeState = null;

  function closeRuntimeState(state) {
    if (!state || state.closed) return;
    state.closed = true;
    state.queue.length = 0;
    state.pending.clear();
    state.controllers.forEach(controller => controller.abort());
    state.controllers.clear();
  }

  function rotateRuntimeState(nextChannel, nextOwner) {
    closeRuntimeState(runtimeState);
    currentChannel = String(nextChannel || '');
    runtimeState = {
      channel: currentChannel,
      owner: String(nextOwner || ''),
      queue: [],
      pending: new Set(),
      controllers: new Set(),
      active: 0,
      total: 0,
      closed: false,
    };
    return runtimeState;
  }

  function setFrameHtml(value, fragment = '', nextPath = currentPath, nextChannel = currentChannel) {
    currentPath = normalizedResultPath(nextPath);
    rotateRuntimeState(nextChannel, resultArtifactId(currentPath, resultContext));
    const previous = frameDocumentUrl;
    frameDocumentUrl = targetWindow.URL.createObjectURL(new targetWindow.Blob(
      [String(value || '')],
      { type: 'text/html;charset=utf-8' },
    ));
    frame.addEventListener('load', () => {
      if (previous) targetWindow.URL.revokeObjectURL(previous);
    }, { once: true });
    frame.src = `${frameDocumentUrl}${String(fragment || '')}`;
  }

  function sendResolved(source, state, request, payload = {}) {
    if (
      !frame.contentWindow
      || source !== frame.contentWindow
      || state !== runtimeState
      || state.closed
    ) return;
    postToFrame(frame.id, {
      type: 'clusterweave:result-bundle-resolved',
      channel: state.channel,
      owner: state.owner,
      request: String(request || ''),
      artifact: '',
      href: '',
      fragment: '',
      ...payload,
    }, '*');
  }

  async function processRuntimeReference(state, task) {
    if (state.closed || state !== runtimeState) return;
    state.active += 1;
    const controller = new AbortController();
    state.controllers.add(controller);
    const timeout = targetWindow.setTimeout(
      () => controller.abort(),
      TOOL_RESULT_RUNTIME_RESOLVE_TIMEOUT_MS,
    );
    try {
      const resolved = await resolveResultArtifact(
        jobId,
        currentPath,
        task.reference,
        { optional: true, resultContext, signal: controller.signal },
      );
      if (state.closed || state !== runtimeState) return;
      const currentDescriptor = resultArtifactDescriptor(currentPath, resultContext);
      const descriptor = resolved?.descriptor;
      const allowedKind = descriptor?.kind === 'html' || descriptor?.kind === 'image';
      if (
        !resolved
        || !allowedKind
        || !currentDescriptor?.bundle_id
        || descriptor?.bundle_id !== currentDescriptor.bundle_id
        || descriptor?.category !== currentDescriptor.category
      ) {
        sendResolved(task.source, state, task.request);
        return;
      }
      const fragment = resolved.fragment || resultAssetHashSuffix(task.reference);
      sendResolved(task.source, state, task.request, {
        artifact: descriptor.id,
        href: `${resultHref(jobId, resolved.key, { resultContext })}${fragment}`,
        fragment,
      });
    } catch (error) {
      sendResolved(task.source, state, task.request);
    } finally {
      targetWindow.clearTimeout(timeout);
      state.controllers.delete(controller);
      state.pending.delete(task.request);
      state.active = Math.max(0, state.active - 1);
      pumpRuntimeReferences(state);
    }
  }

  function pumpRuntimeReferences(state) {
    if (state.closed || state !== runtimeState) return;
    while (
      state.active < TOOL_RESULT_RUNTIME_MAX_ACTIVE
      && state.queue.length
      && !state.closed
    ) {
      const task = state.queue.shift();
      void processRuntimeReference(state, task);
    }
  }

  function resolveRuntimeReference(event) {
    const state = runtimeState;
    if (
      event.source !== frame.contentWindow
      || !event.data
      || event.data.type !== 'clusterweave:result-bundle-resolve'
      || !state
      || state.closed
      || event.data.channel !== state.channel
      || event.data.owner !== state.owner
    ) return;
    const reference = String(event.data.reference || '');
    const request = String(event.data.request || '');
    if (!/^r[1-9][0-9]{0,8}$/.test(request) || state.pending.has(request)) return;
    state.total += 1;
    if (
      !reference
      || reference.length > 2048
      || state.total > TOOL_RESULT_RUNTIME_MAX_PER_DOCUMENT
      || state.queue.length >= TOOL_RESULT_RUNTIME_MAX_QUEUE
    ) {
      sendResolved(event.source, state, request);
      return;
    }
    state.pending.add(request);
    state.queue.push({
      source: event.source,
      request,
      reference,
    });
    pumpRuntimeReferences(state);
  }

  async function navigate(event) {
    const state = runtimeState;
    if (
      event.source !== frame.contentWindow
      || !event.data
      || event.data.type !== 'clusterweave:result-bundle-navigate'
      || !state
      || state.closed
      || event.data.channel !== state.channel
      || event.data.owner !== state.owner
      || navigating
    ) return;
    const targetDescriptor = resultArtifactDescriptor(event.data.artifact || '', resultContext);
    const targetPath = artifactPresentationKey(targetDescriptor);
    const currentDescriptor = resultArtifactDescriptor(currentPath, resultContext);
    const targetIsHtml = isToolResultBundleHtml(targetPath, resultContext);
    const targetIsImage = targetDescriptor?.kind === 'image'
      && ['antismash', 'funbgcex'].includes(String(targetDescriptor?.category || ''));
    if (!targetPath || (!targetIsHtml && !targetIsImage)) return;
    if (
      !currentDescriptor?.bundle_id
      || !targetDescriptor?.bundle_id
      || currentDescriptor.bundle_id !== targetDescriptor.bundle_id
      || currentDescriptor.category !== targetDescriptor.category
    ) return;
    navigating = true;
    try {
      const response = await resultFetch(jobId, targetPath, { resultContext });
      const contentType = response.headers.get('Content-Type') || '';
      if (!response.ok) throw new Error('The linked result page is unavailable.');
      if (targetIsImage) {
        if (!/^image\//i.test(contentType)) {
          throw new Error('The linked result image has an invalid media type.');
        }
        const blob = await response.blob();
        assertToolResultAssetSize(
          response,
          blob.size,
          { declaredBytes: 0, actualBytes: 0 },
        );
        const dataUrl = await resultBlobDataUrl(blob);
        const imageName = resultArtifactName(targetPath, resultContext) || 'Result image';
        const imageHtml = `<!doctype html>
<html><head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<title>${escapeHtml(imageName)}</title>
<style>html,body{min-height:100%;margin:0;background:#fff}body{display:grid;place-items:center}img{display:block;max-width:100%;height:auto}</style>
</head><body><img src="${escapeHtml(dataUrl)}" alt="${escapeHtml(imageName)}"></body></html>`;
        setFrameHtml(imageHtml, '', targetPath, '');
        targetWindow.document.title = imageName;
        return;
      }
      if (!/^text\/html\b/i.test(contentType)) {
        throw new Error('The linked result page has an invalid media type.');
      }
      const nextChannel = toolResultPreviewChannel();
      const nestedHtml = await rewriteHtmlResultAssets(await response.text(), jobId, targetPath, {
        allowToolBundleScripts: true,
        toolPreviewChannel: nextChannel,
        resultContext,
      });
      if (state.closed || state !== runtimeState) return;
      setFrameHtml(nestedHtml, event.data.fragment || '', targetPath, nextChannel);
      targetWindow.document.title = resultArtifactName(targetPath, resultContext) || title;
    } catch (error) {
      console.error('ClusterWeave result-bundle navigation failed', error);
    } finally {
      navigating = false;
    }
  }

  targetWindow.addEventListener('message', resolveRuntimeReference);
  targetWindow.addEventListener('message', navigate);
  targetWindow.addEventListener('pagehide', () => {
    targetWindow.removeEventListener('message', resolveRuntimeReference);
    targetWindow.removeEventListener('message', navigate);
    closeRuntimeState(runtimeState);
    if (frameDocumentUrl) targetWindow.URL.revokeObjectURL(frameDocumentUrl);
  }, { once: true });
  doc.body.appendChild(frame);
  setFrameHtml(htmlText, '', relPath, channel);
  return frame;
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
    const resultContext = createResultArtifactContext(jobId);
    const resp = await resultFetch(jobId, relPath, { resultContext });
    if (!resp.ok) throw new Error('Result HTML could not be opened with the saved result access code.');
    const htmlText = await resp.text();
    if (isExactPublicClinkerPanelHtml(relPath)) {
      const rewrittenHtml = await rewriteHtmlResultAssets(htmlText, jobId, relPath, { allowClinkerInlineScripts: true });
      renderSandboxedClinkerPreview(targetWindow, relPath, rewrittenHtml);
      return false;
    }
    if (isToolResultBundleHtml(relPath, resultContext)) {
      const channel = toolResultPreviewChannel();
      const rewrittenHtml = await rewriteHtmlResultAssets(htmlText, jobId, relPath, {
        allowToolBundleScripts: true,
        toolPreviewChannel: channel,
        resultContext,
      });
      renderSandboxedToolResultPreview(
        targetWindow,
        jobId,
        relPath,
        rewrittenHtml,
        channel,
        resultContext,
      );
      return false;
    }
    const url = await buildHtmlResultObjectUrl(jobId, relPath, htmlText);
    targetWindow.location.href = url;
  } catch (err) {
    if (ownsWindow) targetWindow.close();
    alert(err.message || String(err));
  }
  return false;
}

function resultFetch(jobId, artifactKey, options = {}) {
  const { download = false, resultContext = null, ...fetchOptions } = options;
  const runId = resultContext?.runId || publicRunIdForJob(jobId);
  const artifactId = resultArtifactId(artifactKey, resultContext);
  const suffix = download ? '/download' : '';
  const path = `api/results/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId || 'unavailable')}${suffix}`;
  return apiFetch(path, fetchOptions, { kind: 'job', jobId: runId });
}

async function resolveResultArtifact(jobId, ownerKey, reference, options = {}) {
  const resultContext = options.resultContext || null;
  const runId = resultContext?.runId || publicRunIdForJob(jobId);
  const ownerId = resultArtifactId(ownerKey, resultContext);
  const rawReference = String(reference || '').trim();
  if (!runId || !ownerId || !rawReference || resultUrlShouldStayExternal(rawReference)) return null;
  const resp = await apiFetch(
    `api/results/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(ownerId)}/resolve`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: options.signal,
      body: JSON.stringify({
        reference: rawReference,
        optional: options.optional === true,
      }),
    },
    { kind: 'job', jobId: runId },
  );
  if (!resp.ok) return null;
  const payload = await resp.json();
  if (Object.prototype.hasOwnProperty.call(payload || {}, 'artifact') && !payload.artifact) {
    return null;
  }
  const descriptor = payload?.artifact || payload;
  const key = installResultArtifactDescriptor(descriptor, resultContext);
  if (!key) return null;
  return {
    key,
    descriptor: resultArtifactDescriptor(key, resultContext),
    fragment: String(payload?.fragment || resultAssetHashSuffix(rawReference) || ''),
  };
}

function bigscapeViewerFetch(jobId, options = {}) {
  const runId = publicRunIdForJob(jobId);
  return apiFetch(
    `api/results/${encodeURIComponent(runId)}/bigscape-viewer-database`,
    options,
    { kind: 'job', jobId: runId },
  );
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
  setNum('genome-parallelism', 'GENOME_PARALLELISM');
  setNum('antismash-record-parallelism', 'ANTISMASH_RECORD_PARALLELISM');
  setNum('antismash-shard-cpus', 'ANTISMASH_SHARD_CPUS');
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
    `GENOME_PARALLELISM=${document.getElementById('genome-parallelism').value || '1'}`,
    `ANTISMASH_RECORD_PARALLELISM=${document.getElementById('antismash-record-parallelism').value || '1'}`,
    `ANTISMASH_SHARD_CPUS=${document.getElementById('antismash-shard-cpus').value || ''}`,
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
    `ATLAS_STAGE_LIMIT=${document.getElementById('clinker-max-regions').value || '20'}`,
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
  if (manualCount) inputLabels.push(`${manualCount} NCBI accession${manualCount === 1 ? '' : 's'}`);
  const shownInputs = inputLabels.slice(0, 3).join(', ');
  const moreCount = Math.max(0, inputLabels.length - 3);
  const selectedLabel = inputLabels.length
    ? `${inputLabels.length} input source(s)${shownInputs ? `: ${shownInputs}` : ''}${moreCount ? ` +${moreCount} more` : ''}`
    : 'No inputs selected';
  const targetGenome = document.getElementById('target-genome').value.trim() || 'None';
  const projectName = document.getElementById('project-name').value.trim() || 'Project required';
  const analysisScope = analysisScopeLabel(stagedAnalysisScope);
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
      <div class="summary-label">Analysis scope</div>
      <div class="summary-value">${escapeHtml(analysisScope)}</div>
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
    set('clinker-max-regions', 20);
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
const CLIENT_GENOME_PRECHECK_BYTES = 4 * 1024 * 1024;
const CLIENT_GENOME_PRECHECK_TAIL_BYTES = 512 * 1024;
const ANALYSIS_SCOPES = new Set(['fungi', 'both', 'bacteria']);
const TAXON_GROUPS = new Set(['fungi', 'bacteria']);
const TAXON_ASSIGNMENTS_FILENAME = 'taxon_assignments.tsv';
const MAX_TAXON_ASSIGNMENT_SIDECAR_BYTES = 256 * 1024;
const MAX_TAXON_ASSIGNMENTS = 500;

function ncbiAssemblyAccessionHelp() {
  const scope = normalizeAnalysisScope(stagedAnalysisScope);
  if (scope === 'bacteria') return 'Use current bacterial NCBI assembly accessions like GCA_000005845.2.';
  if (scope === 'both') return 'Use current fungal or bacterial NCBI assembly accessions; the server resolves authoritative NCBI taxonomy.';
  return NCBI_ASSEMBLY_ACCESSION_HELP;
}

function normalizeAnalysisScope(value, fallback = 'fungi') {
  const scope = String(value || '').trim().toLowerCase();
  return ANALYSIS_SCOPES.has(scope) ? scope : fallback;
}

function analysisScopeLabel(value) {
  const scope = normalizeAnalysisScope(value);
  if (scope === 'bacteria') return 'Bacteria';
  if (scope === 'both') return 'Both';
  return 'Fungi';
}

function normalizeTaxonGroup(value) {
  const group = String(value || '').trim().toLowerCase();
  return TAXON_GROUPS.has(group) ? group : '';
}

function normalizeTaxonCounts(value) {
  const counts = value && typeof value === 'object' ? value : {};
  const fungiValue = counts.fungi ?? counts.fungal ?? counts.fungi_count ?? counts.fungal_count;
  const bacteriaValue = counts.bacteria ?? counts.bacterial ?? counts.bacteria_count ?? counts.bacterial_count;
  const known = fungiValue !== undefined || bacteriaValue !== undefined;
  const finiteCount = raw => {
    const number = Number(raw || 0);
    return Number.isFinite(number) && number > 0 ? Math.trunc(number) : 0;
  };
  return {
    fungi: finiteCount(fungiValue),
    bacteria: finiteCount(bacteriaValue),
    known,
  };
}

function analysisContextFromJob(job) {
  const saved = job && typeof job === 'object' ? job : {};
  const settings = saved.submission_settings || saved.settings || {};
  const inputSummary = saved.input_summary || saved.inputSummary || {};
  const scope = normalizeAnalysisScope(
    saved.analysis_scope
      ?? saved.analysisScope
      ?? settings.analysis_scope
      ?? settings.analysisScope,
    'fungi',
  );
  const taxonCounts = normalizeTaxonCounts(
    saved.taxon_counts
      || saved.taxonCounts
      || inputSummary.taxon_counts
      || inputSummary.taxonCounts
      || inputSummary,
  );
  return { scope, taxonCounts, source: 'saved_job' };
}

function stagedAnalysisContext() {
  return {
    scope: normalizeAnalysisScope(stagedAnalysisScope),
    taxonCounts: normalizeTaxonCounts({}),
    source: 'staged_new_run',
  };
}

function activeAnalysisContext() {
  if (activeJobId && activeSavedAnalysisContext) return activeSavedAnalysisContext;
  return stagedAnalysisContext();
}

function analysisCapabilities(context = activeAnalysisContext()) {
  const scope = normalizeAnalysisScope(context?.scope);
  const counts = normalizeTaxonCounts(context?.taxonCounts);
  const countsKnown = counts.known && (counts.fungi + counts.bacteria > 0);
  const hasFungi = countsKnown ? counts.fungi > 0 : scope !== 'bacteria';
  const hasBacteria = countsKnown ? counts.bacteria > 0 : scope !== 'fungi';
  return Object.freeze({
    scope,
    taxonCounts: counts,
    hasFungi,
    hasBacteria,
    mixedDomain: hasFungi && hasBacteria,
    funannotate: hasFungi,
    funbgcex: hasFungi,
    antismash: hasFungi || hasBacteria,
    bigscape: hasFungi || hasBacteria,
    fungalFigures: hasFungi,
    bacterialFigures: hasBacteria,
    taxonomyTree: hasFungi || hasBacteria,
  });
}

function activeAnalysisCapabilities() {
  return analysisCapabilities(activeAnalysisContext());
}

function setActiveSavedAnalysisContext(jobOrContext) {
  if (!jobOrContext) {
    activeSavedAnalysisContext = null;
  } else if (jobOrContext.scope && jobOrContext.taxonCounts) {
    activeSavedAnalysisContext = {
      scope: normalizeAnalysisScope(jobOrContext.scope),
      taxonCounts: normalizeTaxonCounts(jobOrContext.taxonCounts),
      source: 'saved_job',
    };
  } else {
    activeSavedAnalysisContext = analysisContextFromJob(jobOrContext);
  }
  applyAnalysisCapabilityVisibility();
}

function clearActiveSavedAnalysisContext() {
  activeSavedAnalysisContext = null;
  applyAnalysisCapabilityVisibility();
}

function analysisCapabilityEnabled(key, capabilities = activeAnalysisCapabilities()) {
  if (!key) return true;
  return capabilities[key] !== false;
}

function applyAnalysisCapabilityVisibility() {
  const capabilities = activeAnalysisCapabilities();
  document.body.dataset.analysisScope = capabilities.scope;
  document.querySelectorAll('[data-analysis-capability]').forEach((element) => {
    const visible = analysisCapabilityEnabled(element.dataset.analysisCapability, capabilities);
    element.hidden = !visible;
    element.toggleAttribute('inert', !visible);
    element.setAttribute('aria-hidden', visible ? 'false' : 'true');
  });
  document.querySelectorAll('[data-analysis-both-note]').forEach((element) => {
    element.hidden = !capabilities.mixedDomain;
  });
}

function resultCategoryApplicable(category, capabilities = activeAnalysisCapabilities()) {
  const key = resultCategoryKey(category);
  if (key === 'funbgcex') return capabilities.funbgcex;
  return true;
}

function isLegacyFungalFigure(path) {
  const name = fileNameFromPath(path).toLowerCase();
  return [
    'fungi_big_scape_multipanel.svg',
    'fungi_big_scape_multipanel.png',
    'big_scape_multipanel.svg',
    'big_scape_multipanel.png',
    'bgc_overlap.svg',
    'bgc_overlap.png',
  ].includes(name);
}

function isBacterialMultipanelFigure(path) {
  const name = fileNameFromPath(path).toLowerCase();
  return [
    'bacteria_big_scape_multipanel.svg',
    'bacteria_big_scape_multipanel.png',
    'bacterial_multipanel.svg',
    'bacterial_multipanel.png',
  ].includes(name);
}

function figureApplicableToAnalysis(path, capabilities = activeAnalysisCapabilities()) {
  if (isLegacyFungalFigure(path)) return capabilities.fungalFigures;
  if (isBacterialMultipanelFigure(path)) return capabilities.bacterialFigures;
  if (isTaxonTreeVisualAsset(path)) return capabilities.taxonomyTree;
  return true;
}

function analysisScopeRadioValue() {
  const selected = document.querySelector('input[name="analysis-scope"]:checked');
  return normalizeAnalysisScope(selected?.value, stagedAnalysisScope);
}

function syncAnalysisScopeControls() {
  const scope = normalizeAnalysisScope(stagedAnalysisScope);
  document.querySelectorAll('input[name="analysis-scope"]').forEach((input) => {
    input.checked = input.value === scope;
  });
}

function updateAnalysisScopeCopy() {
  const scope = normalizeAnalysisScope(stagedAnalysisScope);
  const hero = document.querySelector('#overview h1');
  const project = document.getElementById('project-name');
  if (hero) {
    if (scope === 'bacteria') {
      hero.setAttribute('aria-label', 'Discover the hidden potential of bacteria');
      hero.innerHTML = '<span>Discover</span><span>the</span><span>hidden</span><span>potential</span><span>of</span><span>bacteria</span>';
    } else if (scope === 'both') {
      hero.setAttribute('aria-label', 'Discover the hidden potential of microbes');
      hero.innerHTML = '<span>Discover</span><span>the</span><span>hidden</span><span>potential</span><span>of</span><span>microbes</span>';
    } else {
      hero.setAttribute('aria-label', 'Discover the hidden potential of fungi');
      hero.innerHTML = '<span>Discover</span><span>the</span><span>hidden</span><span>potential</span><span>of</span><span>fungi</span>';
    }
  }
  if (project) {
    project.placeholder = scope === 'bacteria' ? 'bacterial_survey' : scope === 'both' ? 'microbial_survey' : 'fungal_survey';
  }
}

function isTaxonAssignmentsSidecarName(name) {
  return String(name || '').trim().toLowerCase() === TAXON_ASSIGNMENTS_FILENAME;
}

function isGenomeUploadFile(file) {
  const fileExt = ext(file?.name || '');
  return PUBLIC_FASTA_EXTENSIONS.has(fileExt) || PUBLIC_GENBANK_EXTENSIONS.has(fileExt);
}

function canonicalGenomeInputKey(value) {
  return publicGenomeStem(value).toLowerCase();
}

function logicalGenomeInputs(files = selectedFiles) {
  const logical = new Map();
  (files || []).forEach((file) => {
    if (!isGenomeUploadFile(file)) return;
    const inputKey = publicGenomeStem(file.name);
    const canonicalKey = canonicalGenomeInputKey(inputKey);
    if (!canonicalKey) return;
    if (!logical.has(canonicalKey)) {
      logical.set(canonicalKey, {
        canonicalKey,
        inputKey,
        files: [],
        kinds: new Set(),
      });
    }
    const row = logical.get(canonicalKey);
    row.files.push(file);
    row.kinds.add(publicGenomeUploadKind(ext(file.name)));
  });
  return Array.from(logical.values());
}

function pruneManualTaxonAssignments() {
  const currentKeys = new Set(logicalGenomeInputs().map(item => item.canonicalKey));
  Array.from(stagedTaxonAssignments.keys()).forEach((key) => {
    if (currentKeys.has(key) || stagedTaxonAssignmentSources.get(key) === 'sidecar') return;
    stagedTaxonAssignments.delete(key);
    stagedTaxonAssignmentSources.delete(key);
  });
}

function stagedTaxonGroupForFileName(name) {
  const scope = normalizeAnalysisScope(stagedAnalysisScope);
  if (scope !== 'both') return scope;
  const canonicalKey = canonicalGenomeInputKey(name);
  const logicalInput = logicalGenomeInputs().find(item => item.canonicalKey === canonicalKey);
  const authority = logicalInput ? logicalGenomeAuthority(logicalInput) : null;
  if (authority?.status === 'resolved') return authority.taxonGroup;
  return normalizeTaxonGroup(stagedTaxonAssignments.get(canonicalKey));
}

function logicalGenomeAuthority(item) {
  const authorities = (item?.files || [])
    .filter(file => PUBLIC_GENBANK_EXTENSIONS.has(ext(file?.name || '')))
    .map(file => clientGenbankAuthorityForFile(file));
  return mergeClientGenbankAuthorities(authorities);
}

function logicalGenomeTaxonAssignmentDecision(item) {
  const assigned = normalizeTaxonGroup(stagedTaxonAssignments.get(item.canonicalKey));
  return clientTaxonAssignmentDecision(logicalGenomeAuthority(item), assigned, item.inputKey);
}

function taxonAssignmentsPayload() {
  if (normalizeAnalysisScope(stagedAnalysisScope) !== 'both') return {};
  const payload = {};
  logicalGenomeInputs().forEach((item) => {
    const decision = logicalGenomeTaxonAssignmentDecision(item);
    if (decision.requiresAssignment && decision.assigned) {
      payload[item.inputKey] = decision.assigned;
    }
  });
  return payload;
}

function taxonAssignmentValidation() {
  const logical = logicalGenomeInputs();
  const decisions = logical.map(item => ({ item, ...logicalGenomeTaxonAssignmentDecision(item) }));
  const assignable = decisions.filter(decision => decision.requiresAssignment);
  const currentKeys = new Set(logical.map(item => item.canonicalKey));
  const unresolved = normalizeAnalysisScope(stagedAnalysisScope) === 'both'
    ? assignable.filter(decision => !decision.assigned).map(decision => decision.item)
    : [];
  const unknownSidecarKeys = [];
  stagedTaxonAssignmentSources.forEach((source, key) => {
    if (source === 'sidecar' && !currentKeys.has(key)) unknownSidecarKeys.push(key);
  });
  const authorityIssues = decisions
    .filter(decision => decision.issue)
    .map(decision => ({ inputKey: decision.item.inputKey, issue: decision.issue }));
  const sidecarIssues = taxonAssignmentSidecarIssues.slice();
  unknownSidecarKeys.forEach(key => sidecarIssues.push(`Unknown taxon assignment key: ${key}.`));
  const generalIssues = [];
  if (logical.length > MAX_TAXON_ASSIGNMENTS) {
    generalIssues.push(`Taxon assignments are limited to ${MAX_TAXON_ASSIGNMENTS} logical genomes.`);
  }
  const issues = [
    ...authorityIssues.map(item => item.issue),
    ...sidecarIssues,
    ...generalIssues,
  ];
  return {
    logical,
    decisions,
    assignable,
    unresolved,
    unknownSidecarKeys,
    authorityIssues,
    sidecarIssues,
    generalIssues,
    issues,
  };
}

function renderTaxonAssignmentPanel() {
  pruneManualTaxonAssignments();
  const panel = document.getElementById('taxon-assignment-panel');
  const list = document.getElementById('taxon-assignment-list');
  const status = document.getElementById('taxon-assignment-status');
  if (!panel || !list || !status) return;
  const validation = taxonAssignmentValidation();
  const visible = normalizeAnalysisScope(stagedAnalysisScope) === 'both' && validation.assignable.length > 0;
  panel.hidden = !visible;
  panel.classList.toggle('hidden', !visible);
  if (!visible) {
    list.innerHTML = '';
    status.textContent = '0 unresolved';
    return;
  }
  list.innerHTML = validation.assignable.map((decision, index) => {
    const item = decision.item;
    const assigned = normalizeTaxonGroup(stagedTaxonAssignments.get(item.canonicalKey));
    const fileSummary = item.files.map(file => file.name).join(' + ');
    const jsKey = escapeJsString(item.canonicalKey);
    const groupName = `taxon-assignment-${index}`;
    return `
      <div class="taxon-assignment-row${assigned ? '' : ' is-unresolved'}" data-input-key="${escapeHtml(item.inputKey)}" role="row">
        <span class="taxon-assignment-genome" role="cell">
          <b title="${escapeHtml(fileSummary)}">${escapeHtml(item.inputKey)}</b>
        </span>
        <label class="taxon-assignment-cell" role="cell"><input type="radio" name="${escapeHtml(groupName)}" value="fungi" aria-label="Assign ${escapeHtml(item.inputKey)} to fungi" ${assigned === 'fungi' ? 'checked' : ''} onchange="setLogicalGenomeTaxonAssignment('${escapeHtml(jsKey)}','fungi')" /><span class="sr-only">Fungi</span></label>
        <label class="taxon-assignment-cell" role="cell"><input type="radio" name="${escapeHtml(groupName)}" value="bacteria" aria-label="Assign ${escapeHtml(item.inputKey)} to bacteria" ${assigned === 'bacteria' ? 'checked' : ''} onchange="setLogicalGenomeTaxonAssignment('${escapeHtml(jsKey)}','bacteria')" /><span class="sr-only">Bacteria</span></label>
      </div>`;
  }).join('');
  const issueCount = validation.issues.length;
  const unresolvedCount = validation.unresolved.length;
  status.textContent = issueCount
    ? `${issueCount} routing issue${issueCount === 1 ? '' : 's'}`
    : `${unresolvedCount} unresolved`;
}

async function refreshSelectedGenomeChecks() {
  const genomeFiles = selectedFiles.filter(isGenomeUploadFile);
  await Promise.all(
    genomeFiles
      .filter(file => PUBLIC_GENBANK_EXTENSIONS.has(ext(file.name)))
      .map(file => cacheGenomeFileCheck(file)),
  );
  await Promise.all(genomeFiles.map(file => cacheGenomeFileCheck(file)));
}

async function setLogicalGenomeTaxonAssignment(canonicalKey, taxonGroup) {
  const key = String(canonicalKey || '').trim().toLowerCase();
  const group = normalizeTaxonGroup(taxonGroup);
  const item = logicalGenomeInputs().find(candidate => candidate.canonicalKey === key);
  if (!group || !item || !logicalGenomeTaxonAssignmentDecision(item).requiresAssignment) return;
  stagedTaxonAssignments.set(key, group);
  stagedTaxonAssignmentSources.set(key, 'user');
  await refreshSelectedGenomeChecks();
  renderFileList();
}

async function markAllTaxonAssignments(taxonGroup) {
  const group = normalizeTaxonGroup(taxonGroup);
  if (!group) return;
  logicalGenomeInputs().forEach((item) => {
    if (!logicalGenomeTaxonAssignmentDecision(item).requiresAssignment) return;
    stagedTaxonAssignments.set(item.canonicalKey, group);
    stagedTaxonAssignmentSources.set(item.canonicalKey, 'user');
  });
  await refreshSelectedGenomeChecks();
  renderFileList();
}

function parseTaxonAssignmentSidecarText(text) {
  const issues = [];
  const assignments = new Map();
  const displayKeys = new Map();
  const lines = String(text || '').replace(/^\uFEFF/, '').split(/\r?\n/);
  const headerLine = lines.shift() || '';
  const header = headerLine.split('\t').map(value => value.trim().toLowerCase());
  const inputIndex = header.indexOf('input_key');
  const taxonIndex = header.indexOf('taxon_group');
  if (inputIndex < 0 || taxonIndex < 0) {
    return { assignments, displayKeys, issues: ['taxon_assignments.tsv requires input_key and taxon_group columns.'] };
  }
  let parsedRows = 0;
  lines.forEach((line, offset) => {
    if (!line.trim()) return;
    parsedRows += 1;
    if (parsedRows > MAX_TAXON_ASSIGNMENTS) return;
    const columns = line.split('\t');
    const rawKey = String(columns[inputIndex] || '').trim();
    const inputKey = publicGenomeStem(rawKey);
    const canonicalKey = canonicalGenomeInputKey(rawKey);
    const taxonGroup = normalizeTaxonGroup(columns[taxonIndex]);
    const lineNumber = offset + 2;
    if (!inputKey || !PUBLIC_GENOME_STEM_RE.test(inputKey)) {
      issues.push(`Invalid input_key on line ${lineNumber}.`);
      return;
    }
    if (!taxonGroup) {
      issues.push(`Unsupported taxon_group on line ${lineNumber}; use fungi or bacteria.`);
      return;
    }
    const previous = assignments.get(canonicalKey);
    if (previous && previous !== taxonGroup) {
      issues.push(`Contradictory duplicate assignment for ${inputKey} on line ${lineNumber}.`);
      return;
    }
    assignments.set(canonicalKey, taxonGroup);
    displayKeys.set(canonicalKey, inputKey);
  });
  if (parsedRows > MAX_TAXON_ASSIGNMENTS) {
    issues.push(`taxon_assignments.tsv exceeds ${MAX_TAXON_ASSIGNMENTS} assignment rows.`);
  }
  return { assignments, displayKeys, issues };
}

async function loadTaxonAssignmentSidecar(file) {
  Array.from(stagedTaxonAssignmentSources.entries()).forEach(([key, source]) => {
    if (source !== 'sidecar') return;
    stagedTaxonAssignments.delete(key);
    stagedTaxonAssignmentSources.delete(key);
  });
  taxonAssignmentSidecar = {
    name: TAXON_ASSIGNMENTS_FILENAME,
    size: Number(file?.size || 0),
    lastModified: Number(file?.lastModified || 0),
  };
  taxonAssignmentSidecarIssues = [];
  if (taxonAssignmentSidecar.size > MAX_TAXON_ASSIGNMENT_SIDECAR_BYTES) {
    taxonAssignmentSidecarIssues.push('taxon_assignments.tsv exceeds the 256 KB browser limit.');
    return;
  }
  let text = '';
  try {
    text = await file.text();
  } catch (error) {
    taxonAssignmentSidecarIssues.push('taxon_assignments.tsv could not be read in this browser.');
    return;
  }
  const parsed = parseTaxonAssignmentSidecarText(text);
  taxonAssignmentSidecarIssues = parsed.issues;
  parsed.assignments.forEach((group, key) => {
    stagedTaxonAssignments.set(key, group);
    stagedTaxonAssignmentSources.set(key, 'sidecar');
  });
}

function removeTaxonAssignmentSidecar() {
  taxonAssignmentSidecar = null;
  taxonAssignmentSidecarIssues = [];
  Array.from(stagedTaxonAssignmentSources.entries()).forEach(([key, source]) => {
    if (source !== 'sidecar') return;
    stagedTaxonAssignments.delete(key);
    stagedTaxonAssignmentSources.delete(key);
  });
  renderFileList();
}

async function handleAnalysisScopeChange() {
  stagedAnalysisScope = analysisScopeRadioValue();
  syncAnalysisScopeControls();
  updateAnalysisScopeCopy();
  await refreshSelectedGenomeChecks();
  applyAnalysisCapabilityVisibility();
  renderFileList();
}

function resetStagedAnalysisState(scope = 'fungi') {
  stagedAnalysisScope = normalizeAnalysisScope(scope);
  stagedTaxonAssignments = new Map();
  stagedTaxonAssignmentSources = new Map();
  taxonAssignmentSidecar = null;
  taxonAssignmentSidecarIssues = [];
  syncAnalysisScopeControls();
  updateAnalysisScopeCopy();
  renderTaxonAssignmentPanel();
  applyAnalysisCapabilityVisibility();
}

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

const BRUTAL_ACCESSION_PLACEHOLDERS = ['GCA_000011425.1', 'GCA_030770425.1'];
const BRUTAL_ACCESSION_PREVIEW_ROWS = 6;
let brutalAccessionDrafts = Array.from({ length: 50 }, () => '');
let brutalAccessionCommitted = new Set();
let brutalSyncingAccepted = false;
let brutalEcoSelections = new Map();
let brutalEcoContext = null;
let brutalRowsInitialized = false;

function accessionLimit() {
  return Math.max(1, Math.min(50, publicQuotaLimits().max_accessions || 50));
}

function normalizeAccessionDraft(value) {
  return String(value || '').replace(/\s+/g, '').toUpperCase();
}

function normalizeShortToken(value, maxLength = 20) {
  return String(value || '')
    .trim()
    .replace(/\s+/g, '_')
    .replace(/[^A-Za-z0-9._-]+/g, '')
    .slice(0, maxLength);
}

function normalizeProjectNameInput() {
  const input = document.getElementById('project-name');
  if (!input) return;
  const normalized = String(input.value || '')
    .replace(/\s+/g, '_')
    .replace(/[^A-Za-z0-9._-]+/g, '')
    .slice(0, 80);
  if (input.value !== normalized) input.value = normalized;
}

function projectNameValue() {
  return document.getElementById('project-name')?.value.trim() || '';
}

function setProjectNameRequiredState(missing) {
  const input = document.getElementById('project-name');
  const card = document.getElementById('project-name-card') || input?.closest?.('.project-name-card');
  const shell = document.getElementById('submit-button-shell');
  const error = document.getElementById('project-name-error');
  if (card) card.classList.toggle('is-project-blank', !!missing);
  if (shell) shell.classList.toggle('is-project-locked', !!missing);
  if (input) input.setAttribute('aria-invalid', 'false');
  if (error) error.textContent = '';
}

function requireProjectNameForSubmit() {
  normalizeProjectNameInput();
  const input = document.getElementById('project-name');
  const name = projectNameValue();
  if (name) {
    setProjectNameRequiredState(false);
    return name;
  }
  setProjectNameRequiredState(true);
  input?.focus();
  return '';
}

function validBrutalAccession(value) {
  return NCBI_ASSEMBLY_ACCESSION_RE.test(String(value || '').trim());
}

function brutalDraftDuplicate(index, value) {
  if (!value) return false;
  return brutalAccessionDrafts.some((draft, draftIndex) => draftIndex !== index && normalizeAccessionDraft(draft) === value);
}

function brutalRowVisible(index) {
  if (index === 0) return true;
  for (let prior = 0; prior < index; prior += 1) {
    const priorAccession = normalizeAccessionDraft(brutalAccessionDrafts[prior]);
    if (!rowIsAccepted(priorAccession, prior)) return false;
  }
  return true;
}

function updateBrutalTargetButton() {
  const targetInput = document.getElementById('target-genome');
  const button = document.getElementById('target-genome-toggle');
  const value = targetInput ? targetInput.value.trim() : '';
  if (button) {
    button.classList.toggle('has-target', !!value);
    button.setAttribute('aria-pressed', value ? 'true' : 'false');
    button.textContent = 'TARGET GENOME';
  }
  document.querySelectorAll('.brutal-accession-line').forEach((row) => {
    const input = row.querySelector('.brutal-accession-input');
    row.classList.toggle('is-target', !!value && input?.value.trim().toUpperCase() === value.toUpperCase());
  });
  document.querySelectorAll('.file-item[data-target-genome]').forEach((row) => {
    const selected = !!value && String(row.dataset.targetGenome || '').toLowerCase() === value.toLowerCase();
    row.classList.toggle('is-target', selected);
  });
}

function setBrutalTarget(value) {
  const targetInput = document.getElementById('target-genome');
  if (!targetInput) return;
  const normalized = normalizeAccessionDraft(value);
  targetInput.value = targetInput.value.trim().toUpperCase() === normalized ? '' : normalized;
  targetInput.dispatchEvent(new Event('input', { bubbles: true }));
  updateBrutalTargetButton();
  updateRunSummary();
}

function setUploadedGenomeTarget(value) {
  const targetInput = document.getElementById('target-genome');
  const normalized = String(value || '').trim();
  if (!targetInput || !normalized) return;
  targetInput.value = targetInput.value.trim().toLowerCase() === normalized.toLowerCase() ? '' : normalized;
  targetInput.dispatchEvent(new Event('input', { bubbles: true }));
  updateBrutalTargetButton();
  updateRunSummary();
}

function targetGenomeCandidates() {
  const values = new Set(acceptedDraftAccessions().map(value => value.toLowerCase()));
  selectedFiles.forEach((file) => {
    if (isGenomeUploadName(file.name)) values.add(genomeStemFromName(file.name).toLowerCase());
  });
  return values;
}

function clearStaleTargetGenome() {
  const targetInput = document.getElementById('target-genome');
  const value = targetInput?.value.trim() || '';
  if (!value || targetGenomeCandidates().has(value.toLowerCase())) return;
  targetInput.value = '';
  targetInput.dispatchEvent(new Event('input', { bubbles: true }));
  updateBrutalTargetButton();
  updateRunSummary();
}

function handleUploadedGenomeTargetClick(event) {
  if (event.target.closest?.('.file-remove')) return;
  const ecoButton = event.target.closest?.('.file-eco-button');
  if (ecoButton) {
    openUploadedGenomeEcoPicker(ecoButton);
    return;
  }
  const row = event.target.closest?.('.file-item[data-target-genome]');
  if (!row) return;
  setUploadedGenomeTarget(row.dataset.targetGenome || '');
}

function ecologySelectionFor(key) {
  const normalized = String(key || '').trim().toUpperCase();
  if (!brutalEcoSelections.has(normalized)) brutalEcoSelections.set(normalized, { primary: '', secondary: '' });
  return brutalEcoSelections.get(normalized);
}

function inputEcologyEnabled() {
  return !!document.getElementById('run-ecology')?.checked;
}

function updateBrutalEcologyToggle() {
  const button = document.getElementById('brutal-ecology-toggle');
  const card = document.getElementById('brutal-accession-card');
  const uploadCard = document.getElementById('genome-upload-card');
  const enabled = inputEcologyEnabled();
  if (button) {
    button.classList.toggle('is-on', enabled);
    button.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    button.textContent = 'ADD ECOLOGY';
  }
  if (card) card.classList.toggle('show-ecology', enabled);
  if (uploadCard) uploadCard.classList.toggle('show-ecology', enabled);
  document.querySelectorAll('.brutal-eco-button').forEach((buttonEl) => {
    buttonEl.disabled = !enabled || !buttonEl.closest('.brutal-accession-line')?.classList.contains('has-valid-accession');
  });
  updateUploadedGenomeEcoButtons();
}

function updateUploadedGenomeEcoButtons() {
  const enabled = inputEcologyEnabled();
  document.querySelectorAll('.file-eco-button').forEach((button) => {
    const row = button.closest('.file-item[data-target-genome]');
    const key = row?.dataset.targetGenome || '';
    const field = button.dataset.ecoField || 'primary';
    const saved = brutalEcoSelections.get(String(key).trim().toUpperCase())?.[field] || '';
    button.disabled = !enabled || !key;
    button.classList.toggle('is-saved', !!saved);
    button.setAttribute('aria-label', `${field === 'primary' ? 'Primary' : 'Secondary'} ecology for ${key}${saved ? `: ${saved}` : ''}`);
  });
}

function setBrutalEcologyEnabled(enabled) {
  const checkbox = document.getElementById('run-ecology');
  if (!checkbox) return;
  checkbox.checked = !!enabled;
  checkbox.dispatchEvent(new Event('change', { bubbles: true }));
  updateBrutalEcologyToggle();
  syncEcologyMetadataPanel();
  renderBrutalAccessionRows();
  updateRunSummary();
}

function savedEcoValue(accession, field) {
  const selection = ecologySelectionFor(accession);
  return selection[field] || '';
}

function rowIsAccepted(accession, index) {
  return validBrutalAccession(accession) && !brutalDraftDuplicate(index, accession);
}

function accessionDraftCommitted(index) {
  return brutalAccessionCommitted.has(Number(index));
}

function brutalAccessionDraftIssues({ committedOnly = true } = {}) {
  const issues = [];
  brutalAccessionDrafts.forEach((draft, index) => {
    const accession = normalizeAccessionDraft(draft);
    if (!accession) return;
    if (committedOnly && !accessionDraftCommitted(index)) return;
    if (!validBrutalAccession(accession)) {
      issues.push({
        index,
        accession,
        message: `Row ${index + 1}: ${accession} is not a current NCBI assembly accession.`,
      });
    } else if (brutalDraftDuplicate(index, accession)) {
      issues.push({
        index,
        accession,
        message: `Row ${index + 1}: ${accession} is duplicated.`,
      });
    }
  });
  return issues;
}

function setBrutalInputNotice(key, message) {
  const normalizedKey = String(key || '').trim();
  if (!normalizedKey) return;
  if (message) brutalInputNotices.set(normalizedKey, String(message));
  else brutalInputNotices.delete(normalizedKey);
  renderBrutalInputLog();
}

function updateBrutalRowState(row, index) {
  const input = row.querySelector('.brutal-accession-input');
  const status = row.querySelector('.status-icon');
  const remove = row.querySelector('.accession-remove');
  const accession = normalizeAccessionDraft(input?.value || '');
  const hasInput = !!accession;
  const valid = rowIsAccepted(accession, index);
  const committed = accessionDraftCommitted(index);
  const showInvalid = hasInput && !valid && committed;
  row.classList.toggle('has-input', hasInput);
  row.classList.toggle('has-valid-accession', valid);
  row.classList.toggle('has-invalid-accession', showInvalid);
  if (input) input.setAttribute('aria-invalid', showInvalid ? 'true' : 'false');
  if (status) {
    status.classList.toggle('waiting', !hasInput || (hasInput && !valid && !committed));
    status.classList.toggle('ok', valid);
    status.classList.toggle('bad', showInvalid);
    status.setAttribute('aria-label', valid ? 'Accepted accession' : showInvalid ? 'Invalid accession' : hasInput ? 'Editing accession' : 'Waiting for accession');
  }
  if (remove) remove.hidden = !hasInput;
  row.querySelectorAll('.brutal-eco-button').forEach((button) => {
    const field = button.dataset.ecoField || 'primary';
    const saved = valid ? savedEcoValue(accession, field) : '';
    button.classList.toggle('is-saved', !!saved);
    button.disabled = !inputEcologyEnabled() || !valid;
  });
}

function updateBrutalRowVisibility() {
  document.querySelectorAll('.brutal-accession-line').forEach((row) => {
    const index = Number(row.dataset.accessionIndex || '0');
    const enabled = index < accessionLimit() && brutalRowVisible(index);
    const presented = index < Math.min(accessionLimit(), BRUTAL_ACCESSION_PREVIEW_ROWS) || enabled;
    row.classList.toggle('is-locked', !enabled);
    row.classList.toggle('is-concealed', !presented);
    row.setAttribute('aria-hidden', presented ? 'false' : 'true');
    row.setAttribute('aria-disabled', enabled ? 'false' : 'true');
    const input = row.querySelector('.brutal-accession-input');
    if (input) input.disabled = !enabled;
  });
}

function acceptedDraftAccessions() {
  const seen = new Set();
  const accessions = [];
  brutalAccessionDrafts.forEach((draft, index) => {
    const accession = normalizeAccessionDraft(draft);
    if (!rowIsAccepted(accession, index) || seen.has(accession)) return;
    seen.add(accession);
    accessions.push(accession);
  });
  return accessions;
}

function syncBrutalAcceptedFromDrafts() {
  const fileOwned = accessionFileOwnedAccessions();
  acceptedManualAccessions = acceptedDraftAccessions().filter(accession => !fileOwned.has(accession));
  clearStaleTargetGenome();
  if (manualAccessionsInput) manualAccessionsInput.value = '';
  brutalSyncingAccepted = true;
  renderAcceptedAccessions();
  brutalSyncingAccepted = false;
  renderFileList();
  syncEcologyMetadataPanel();
  applyBrutalEcologyToMetadataTable();
  updateBrutalTargetButton();
}

function resetBrutalAccessionDrafts() {
  brutalAccessionDrafts = Array.from({ length: 50 }, () => '');
  brutalAccessionCommitted = new Set();
  brutalEcoSelections = new Map();
  renderBrutalAccessionRows();
  updateBrutalTargetButton();
}

function syncBrutalRowsFromAccepted() {
  const rows = document.getElementById('brutal-accession-rows');
  if (!rows || rows.contains(document.activeElement)) return;
  const accepted = manualAccessionLines();
  const nextDrafts = Array.from({ length: 50 }, (_, index) => accepted[index] || '');
  const same = nextDrafts.every((value, index) => value === brutalAccessionDrafts[index]);
  if (!same || !brutalRowsInitialized) {
    brutalAccessionDrafts = nextDrafts;
    brutalAccessionCommitted = new Set(nextDrafts.map((value, index) => normalizeAccessionDraft(value) ? index : -1).filter(index => index >= 0));
    renderBrutalAccessionRows();
  }
}

function renderBrutalAccessionRows() {
  const rows = document.getElementById('brutal-accession-rows');
  if (!rows) return;
  const limit = accessionLimit();
  rows.innerHTML = Array.from({ length: limit }, (_, index) => {
    const value = normalizeAccessionDraft(brutalAccessionDrafts[index] || '');
    const placeholder = BRUTAL_ACCESSION_PLACEHOLDERS[index] || '';
    return `
      <div class="accession-line brutal-accession-line" data-accession-index="${index}">
        <textarea class="accession-target brutal-accession-input" rows="1" inputmode="text" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="${escapeHtml(placeholder)}" aria-label="Accession ${index + 1}">${escapeHtml(value)}</textarea>
        <span class="status-icon waiting" aria-label="Waiting for accession"></span>
        <button class="accession-remove" type="button" data-accession-remove aria-label="Remove accession ${index + 1}" hidden>x</button>
        <span class="eco-cell"><button class="eco-button brutal-eco-button" type="button" data-eco-field="primary" disabled>ECO 1</button></span>
        <span class="eco-cell"><button class="eco-button brutal-eco-button secondary" type="button" data-eco-field="secondary" disabled>ECO 2</button></span>
      </div>`;
  }).join('');
  brutalRowsInitialized = true;
  rows.querySelectorAll('.brutal-accession-line').forEach((row) => {
    const index = Number(row.dataset.accessionIndex || '0');
    updateBrutalRowState(row, index);
  });
  updateBrutalRowVisibility();
  updateBrutalEcologyToggle();
  updateBrutalTargetButton();
}

function handleBrutalAccessionInput(event) {
  const input = event.target.closest?.('.brutal-accession-input');
  if (!input) return;
  const row = input.closest('.brutal-accession-line');
  const index = Number(row?.dataset.accessionIndex || '0');
  const normalized = normalizeAccessionDraft(input.value);
  const prior = normalizeAccessionDraft(brutalAccessionDrafts[index] || '');
  if (input.value !== normalized) input.value = normalized;
  if (prior && prior !== normalized) detachAccessionFromFileSources(prior);
  brutalAccessionDrafts[index] = normalized;
  brutalAccessionCommitted.delete(index);
  updateBrutalRowState(row, index);
  updateBrutalRowVisibility();
  syncBrutalAcceptedFromDrafts();
}

function commitBrutalAccessionRow(row) {
  if (!row) return;
  const index = Number(row.dataset.accessionIndex || '0');
  const accession = normalizeAccessionDraft(row.querySelector('.brutal-accession-input')?.value || '');
  if (accession) brutalAccessionCommitted.add(index);
  else brutalAccessionCommitted.delete(index);
  updateBrutalRowState(row, index);
  renderFileList();
}

function commitAllBrutalAccessionDrafts({ render = true } = {}) {
  brutalAccessionDrafts.forEach((draft, index) => {
    if (normalizeAccessionDraft(draft)) brutalAccessionCommitted.add(index);
    else brutalAccessionCommitted.delete(index);
  });
  document.querySelectorAll('.brutal-accession-line').forEach((row) => updateBrutalRowState(row, Number(row.dataset.accessionIndex || '0')));
  if (render) renderFileList();
}

function removeBrutalAccession(index) {
  const removedAccession = normalizeAccessionDraft(brutalAccessionDrafts[index] || '');
  if (removedAccession) detachAccessionFromFileSources(removedAccession);
  brutalAccessionDrafts.splice(index, 1);
  brutalAccessionDrafts.push('');
  const nextCommitted = new Set();
  brutalAccessionCommitted.forEach((committedIndex) => {
    if (committedIndex < index) nextCommitted.add(committedIndex);
    else if (committedIndex > index) nextCommitted.add(committedIndex - 1);
  });
  brutalAccessionCommitted = nextCommitted;
  clearStaleTargetGenome();
  syncBrutalAcceptedFromDrafts();
  renderBrutalAccessionRows();
}

function handleBrutalAccessionClick(event) {
  const remove = event.target.closest?.('[data-accession-remove]');
  if (remove) {
    const row = remove.closest('.brutal-accession-line');
    removeBrutalAccession(Number(row?.dataset.accessionIndex || '0'));
    return;
  }
  const ecoButton = event.target.closest?.('.brutal-eco-button');
  if (ecoButton) {
    openBrutalEcoPicker(ecoButton);
    return;
  }
  const row = event.target.closest?.('.brutal-accession-line');
  if (!row || event.target.closest?.('.brutal-accession-input') !== event.target) return;
  const index = Number(row.dataset.accessionIndex || '0');
  const accession = normalizeAccessionDraft(row.querySelector('.brutal-accession-input')?.value || '');
  if (rowIsAccepted(accession, index)) setBrutalTarget(accession);
}

function handleBrutalAccessionKeydown(event) {
  const input = event.target.closest?.('.brutal-accession-input');
  if (!input || event.key !== 'Enter') return;
  event.preventDefault();
  const row = input.closest('.brutal-accession-line');
  commitBrutalAccessionRow(row);
  const index = Number(row?.dataset.accessionIndex || '0');
  const next = document.querySelector(`.brutal-accession-line[data-accession-index="${index + 1}"]:not(.is-locked) .brutal-accession-input`);
  next?.focus();
}

function handleBrutalAccessionFocusout(event) {
  const input = event.target.closest?.('.brutal-accession-input');
  if (!input) return;
  commitBrutalAccessionRow(input.closest('.brutal-accession-line'));
}

function openBrutalEcoPicker(button) {
  if (!button || button.disabled) return;
  const row = button.closest('.brutal-accession-line');
  const index = Number(row?.dataset.accessionIndex || '0');
  const accession = normalizeAccessionDraft(row?.querySelector('.brutal-accession-input')?.value || '');
  if (!rowIsAccepted(accession, index)) return;
  openEcoPickerForInput(button, accession, button.dataset.ecoField || 'primary');
}

function openUploadedGenomeEcoPicker(button) {
  if (!button || button.disabled) return;
  const row = button.closest('.file-item[data-target-genome]');
  const accession = String(row?.dataset.targetGenome || '').trim();
  if (!accession) return;
  openEcoPickerForInput(button, accession, button.dataset.ecoField || 'primary');
}

function openEcoPickerForInput(button, accession, field) {
  brutalEcoContext = { accession, field, button };
  const picker = document.getElementById('brutal-eco-picker');
  const title = document.getElementById('brutal-eco-picker-title');
  const options = document.getElementById('brutal-eco-picker-options');
  const otherRow = document.getElementById('brutal-eco-other-row');
  const otherInput = document.getElementById('brutal-eco-other');
  if (!picker || !options) return;
  const current = savedEcoValue(accession, field);
  if (title) title.textContent = `${field === 'primary' ? 'ECO 1' : 'ECO 2'} for ${accession}`;
  options.innerHTML = ECOLOGY_LABELS.map(label => `<button class="eco-option" type="button" data-eco-option="${escapeHtml(label)}" aria-pressed="${current === label ? 'true' : 'false'}">${escapeHtml(label)}</button>`).join('');
  const rect = button.getBoundingClientRect();
  picker.hidden = false;
  picker.style.left = `${Math.min(window.innerWidth - picker.offsetWidth - 8, Math.max(8, rect.right + 18))}px`;
  picker.style.top = `${Math.min(window.innerHeight - picker.offsetHeight - 8, Math.max(8, rect.top - 8))}px`;
  picker.style.setProperty('--connector-y', `${Math.max(18, Math.min(picker.offsetHeight - 18, rect.top + rect.height / 2 - picker.getBoundingClientRect().top))}px`);
  if (otherRow) otherRow.hidden = current !== 'other' && !current.startsWith('other:');
  if (otherInput) {
    otherInput.value = current.startsWith('other:') ? current.slice(6) : '';
    if (!otherRow?.hidden) otherInput.focus();
    else picker.querySelector('.eco-option')?.focus();
  }
}

function closeBrutalEcoPicker(returnFocus = false) {
  const picker = document.getElementById('brutal-eco-picker');
  if (picker) picker.hidden = true;
  if (returnFocus) brutalEcoContext?.button?.focus();
  brutalEcoContext = null;
}

function saveBrutalEcoSelection(rawValue) {
  if (!brutalEcoContext) return;
  let value = String(rawValue || '').trim();
  if (value === 'other') {
    const otherValue = normalizeShortToken(document.getElementById('brutal-eco-other')?.value || '', 20);
    if (!otherValue) return;
    value = `other:${otherValue}`;
  }
  const selection = ecologySelectionFor(brutalEcoContext.accession);
  selection[brutalEcoContext.field] = value;
  syncEcologyMetadataPanel();
  applyBrutalEcologyToMetadataTable();
  renderBrutalAccessionRows();
  closeBrutalEcoPicker(true);
  updateRunSummary();
}

function applyBrutalEcologyToMetadataTable() {
  document.querySelectorAll('#metadata-table-body tr[data-ecology-key]').forEach((row) => {
    const key = String(row.dataset.ecologyKey || '').trim().toUpperCase();
    const saved = brutalEcoSelections.get(key);
    if (!saved) return;
    [['primary', saved.primary], ['secondary', saved.secondary]].forEach(([field, raw]) => {
      const select = row.querySelector(field === 'primary' ? '.metadata-primary' : '.metadata-secondary');
      const other = row.querySelector(field === 'primary' ? '.metadata-primary-other' : '.metadata-secondary-other');
      if (!select || !raw) return;
      if (raw.startsWith('other:')) {
        select.value = 'other';
        if (other) {
          other.classList.remove('hidden');
          other.value = normalizeShortToken(raw.slice(6), 20);
        }
      } else {
        select.value = raw;
        if (other) {
          other.classList.add('hidden');
          other.value = '';
        }
      }
    });
  });
  updateEcologyLabelStatus();
}

function conciseInputNotice(message) {
  return String(message || '')
    .replace(/\s+/g, ' ')
    .replace(/Use current fungal NCBI assembly accessions like/g, 'Use accessions like')
    .trim();
}

function renderBrutalInputLog() {
  const drawer = document.getElementById('input-log-drawer');
  const list = document.getElementById('input-log-list');
  if (!drawer || !list) return;
  const messages = [];
  const seen = new Set();
  const addMessage = (message) => {
    const concise = conciseInputNotice(message);
    if (!concise || seen.has(concise)) return;
    seen.add(concise);
    messages.push(concise);
  };
  const draftMessages = new Set(brutalAccessionDraftIssues().map(issue => conciseInputNotice(issue.message)));
  draftMessages.forEach(addMessage);
  brutalInputNotices.forEach(addMessage);
  document.querySelectorAll('#input-checker-list .input-check-row.blocked').forEach((row) => {
    const label = row.querySelector('.input-check-label')?.textContent?.trim() || 'Input';
    const reason = row.querySelector('.input-check-reason')?.textContent?.trim() || 'Blocked before run.';
    const message = conciseInputNotice(`${label}: ${reason}`);
    if (!draftMessages.has(message) && !label.startsWith('Row ')) addMessage(message);
  });
  drawer.hidden = messages.length === 0;
  list.innerHTML = messages.map(message => `<div class="input-log-note">${escapeHtml(message)}</div>`).join('');
}

function initializeBrutalInputStation() {
  const rows = document.getElementById('brutal-accession-rows');
  const fileList = document.getElementById('file-list');
  if (!rows || rows.dataset.wired === '1') return;
  rows.dataset.wired = '1';
  renderBrutalAccessionRows();
  rows.addEventListener('input', handleBrutalAccessionInput);
  rows.addEventListener('click', handleBrutalAccessionClick);
  rows.addEventListener('keydown', handleBrutalAccessionKeydown);
  rows.addEventListener('focusout', handleBrutalAccessionFocusout);
  if (fileList) {
    fileList.addEventListener('click', handleUploadedGenomeTargetClick);
  }
  document.getElementById('target-genome-toggle')?.addEventListener('click', () => {
    const targetInput = document.getElementById('target-genome');
    if (targetInput?.value) {
      targetInput.value = '';
      targetInput.dispatchEvent(new Event('input', { bubbles: true }));
      updateBrutalTargetButton();
      updateRunSummary();
    }
  });
  document.getElementById('brutal-ecology-toggle')?.addEventListener('click', () => setBrutalEcologyEnabled(!inputEcologyEnabled()));
  document.getElementById('brutal-eco-picker-options')?.addEventListener('click', (event) => {
    const option = event.target.closest?.('[data-eco-option]');
    if (!option) return;
    const value = option.dataset.ecoOption || '';
    const otherRow = document.getElementById('brutal-eco-other-row');
    const otherInput = document.getElementById('brutal-eco-other');
    if (value === 'other') {
      if (otherRow) otherRow.hidden = false;
      if (otherInput) otherInput.focus();
      return;
    }
    saveBrutalEcoSelection(value);
  });
  document.getElementById('brutal-eco-save')?.addEventListener('click', () => saveBrutalEcoSelection('other'));
  document.getElementById('brutal-eco-other')?.addEventListener('input', (event) => {
    const normalized = normalizeShortToken(event.target.value, 20);
    if (event.target.value !== normalized) event.target.value = normalized;
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !document.getElementById('brutal-eco-picker')?.hidden) {
      event.preventDefault();
      closeBrutalEcoPicker(true);
    }
  });
  document.addEventListener('pointerdown', (event) => {
    const picker = document.getElementById('brutal-eco-picker');
    if (!picker || picker.hidden) return;
    if (picker.contains(event.target) || event.target.closest?.('.brutal-eco-button')) return;
    closeBrutalEcoPicker();
  }, true);
  document.getElementById('input-log-close')?.addEventListener('click', () => {
    const drawer = document.getElementById('input-log-drawer');
    if (drawer) drawer.hidden = true;
  });
  document.getElementById('project-name')?.addEventListener('input', () => {
    normalizeProjectNameInput();
    renderFileList();
  });
  document.getElementById('target-genome')?.addEventListener('input', updateBrutalTargetButton);
  document.getElementById('run-ecology')?.addEventListener('change', () => {
    updateBrutalEcologyToggle();
    renderBrutalAccessionRows();
  });
  updateBrutalTargetButton();
  updateBrutalEcologyToggle();
  updateInputLimitGuidance();
}

fileInput.addEventListener('change', async () => {
  await addFiles([...fileInput.files]);
  fileInput.value = '';
});
manualAccessionsInput.addEventListener('input', () => {
  updateManualAccessionsStatus();
  renderFileList();
});
dropZone.addEventListener('click', () => fileInput.click());
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

function accessionFileOwnedAccessions() {
  const owned = new Set();
  accessionFileSources.forEach((source) => {
    (Array.isArray(source.accessions) ? source.accessions : []).forEach((accession) => {
      const normalized = normalizeAccessionDraft(accession);
      if (normalized) owned.add(normalized);
    });
  });
  return owned;
}

function detachAccessionFromFileSources(accession) {
  const normalized = normalizeAccessionDraft(accession);
  if (!normalized) return;
  accessionFileSources.forEach((source) => {
    source.accessions = (Array.isArray(source.accessions) ? source.accessions : [])
      .filter(value => normalizeAccessionDraft(value) !== normalized);
  });
  accessionFileSources = accessionFileSources.filter(source => source.accessions.length > 0);
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
  return `Invalid accession "${first.token}" on line ${first.line}${more}. ${ncbiAssemblyAccessionHelp()}`;
}

function publicQuotaLimits() {
  return {
    max_accessions: Number(publicQuota.max_accessions) || 50,
    max_genome_files: Number(publicQuota.max_genome_files) || 50,
    max_upload_file_mb: Number(publicQuota.max_upload_file_mb) || 500,
    max_upload_total_mb: Number(publicQuota.max_upload_total_mb) || 1024,
  };
}

function formatQuotaMb(value) {
  const mb = Number(value) || 0;
  if (mb >= 1024 && mb % 1024 === 0) return `${mb / 1024} GB`;
  return `${mb} MB`;
}

const PUBLIC_WEB_FAQ_URL = 'https://github.com/n2mology/clusterweave#web-portal-faq';

function publicQuotaSummary(quota = publicQuotaLimits()) {
  return `${formatQuotaMb(quota.max_upload_file_mb)} per file, ${formatQuotaMb(quota.max_upload_total_mb)} total per run, ${quota.max_genome_files} genome files, or ${quota.max_accessions} NCBI accessions`;
}

function localWorkflowPrompt() {
  return 'Larger, private, or custom analyses should use the local GitHub workflow.';
}

function publicFileLimitMessage(quota = publicQuotaLimits()) {
  return `File exceeds the ${formatQuotaMb(quota.max_upload_file_mb)} public upload limit. ${localWorkflowPrompt()}`;
}

function publicTotalLimitMessage(quota = publicQuotaLimits()) {
  return `Total upload size exceeds the ${formatQuotaMb(quota.max_upload_total_mb)} public job limit. ${localWorkflowPrompt()}`;
}

function updateInputLimitGuidance() {
  const quota = publicQuotaLimits();
  const summary = publicQuotaSummary(quota);
  const note = document.getElementById('upload-limit-note');
  if (note) {
    note.innerHTML = `Limits: ${escapeHtml(summary)}. <a href="${PUBLIC_WEB_FAQ_URL}" target="_blank" rel="noopener">FAQ / local workflow</a>`;
  }
}

function genomeFileCheckKey(file) {
  const route = stagedTaxonGroupForFileName(file.name) || `unresolved-${normalizeAnalysisScope(stagedAnalysisScope)}`;
  return `${file.name}|${file.size}|${file.lastModified || 0}|${route}`;
}

function publicGenomeStem(name) {
  return String(name || '').replace(/\.(gbk|gb|gbff|fasta|fa|fna|fsa)$/i, '').trim();
}

// BEGIN CLIENT_GENBANK_TAXONOMY_PURE
function clientLineageHas(lineage, name) {
  const escaped = String(name || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return !!escaped && new RegExp(`(^|[^A-Za-z])${escaped}($|[^A-Za-z])`, 'i').test(String(lineage || ''));
}

function parseClientGenbankTaxonomy(text) {
  const organisms = [];
  const taxids = [];
  const lineageParts = [];
  let inHeaderLineage = false;

  String(text || '').split(/\r?\n/).forEach((line) => {
    const organismMatch = line.match(/^\s{0,4}ORGANISM\s+(.+?)\s*$/);
    if (organismMatch) {
      organisms.push(organismMatch[1].trim());
      inHeaderLineage = true;
      return;
    }

    if (inHeaderLineage) {
      const stripped = line.trim();
      if (line.startsWith('            ') && stripped && !stripped.startsWith('/')) {
        lineageParts.push(stripped);
        return;
      }
      inHeaderLineage = false;
    }

    const qualifierOrganism = line.match(/\/organism\s*=\s*"([^"]+)"/i);
    if (qualifierOrganism) organisms.push(qualifierOrganism[1].trim());
    const taxidPattern = /\/db_xref\s*=\s*"taxon:(\d+)"/ig;
    let taxidMatch = null;
    while ((taxidMatch = taxidPattern.exec(line)) !== null) taxids.push(Number(taxidMatch[1]));
    const qualifierLineage = line.match(/\/lineage\s*=\s*"([^"]+)"/i);
    if (qualifierLineage) lineageParts.push(qualifierLineage[1].trim());
  });

  const lineage = lineageParts.join(' ');
  const hasFungi = taxids.includes(4751) || clientLineageHas(lineage, 'Fungi');
  const hasBacteria = taxids.includes(2) || clientLineageHas(lineage, 'Bacteria');
  const hasArchaea = clientLineageHas(lineage, 'Archaea');
  const hasVirus = clientLineageHas(lineage, 'Viruses') || clientLineageHas(lineage, 'Viroids');
  const hasEukaryota = clientLineageHas(lineage, 'Eukaryota');
  const hasNonfungalEukaryote = ['Metazoa', 'Viridiplantae'].some(name => clientLineageHas(lineage, name));
  const conflicting = (
    (hasFungi && hasBacteria)
    || (hasFungi && (hasArchaea || hasVirus || hasNonfungalEukaryote))
    || (hasBacteria && (hasArchaea || hasVirus || hasEukaryota))
  );
  if (conflicting) {
    return {
      status: 'conflicting',
      taxonGroup: '',
      reason: 'GenBank source taxonomy contains conflicting supported/unsupported lineages',
    };
  }

  let taxonGroup = '';
  if (hasFungi) taxonGroup = 'fungi';
  else if (hasBacteria) taxonGroup = 'bacteria';
  else if (hasArchaea || hasVirus || hasEukaryota || hasNonfungalEukaryote) {
    return {
      status: 'unsupported',
      taxonGroup: 'unsupported',
      reason: 'GenBank source taxonomy is outside the supported Fungi/Bacteria scope',
    };
  }
  if (!taxonGroup) {
    return {
      status: 'ambiguous',
      taxonGroup: '',
      reason: 'GenBank source taxonomy does not resolve to Fungi or Bacteria',
    };
  }
  return {
    status: 'resolved',
    taxonGroup,
    taxonSource: 'genbank_source',
    taxid: taxids.length ? taxids[0] : null,
    organismName: organisms[0] || '',
    lineage,
    reason: `Authoritative GenBank source taxonomy resolved ${taxonGroup}`,
  };
}

function mergeClientGenbankAuthorities(authorities) {
  const values = (authorities || []).filter(authority => authority && authority.status !== 'ambiguous');
  const conflict = values.find(authority => authority.status === 'conflicting');
  if (conflict) return conflict;
  const resolved = values.filter(authority => authority.status === 'resolved');
  const unsupported = values.find(authority => authority.status === 'unsupported');
  const groups = new Set(resolved.map(authority => authority.taxonGroup));
  if (groups.size > 1 || (resolved.length && unsupported)) {
    return {
      status: 'conflicting',
      taxonGroup: '',
      reason: 'Same-stem GenBank inputs contain conflicting authoritative taxonomy',
    };
  }
  if (unsupported) return unsupported;
  if (resolved.length) return resolved[0];
  return {
    status: 'ambiguous',
    taxonGroup: '',
    reason: 'No authoritative GenBank taxonomy is available for this logical genome',
  };
}

function clientTaxonAssignmentDecision(authority, assignedGroup = '', inputKey = 'genome') {
  const assigned = ['fungi', 'bacteria'].includes(String(assignedGroup || '').trim().toLowerCase())
    ? String(assignedGroup).trim().toLowerCase()
    : '';
  const resolvedAuthority = authority && typeof authority === 'object'
    ? authority
    : { status: 'ambiguous', taxonGroup: '' };
  if (resolvedAuthority.status === 'resolved') {
    const conflict = !!assigned && assigned !== resolvedAuthority.taxonGroup;
    return {
      assigned,
      authority: resolvedAuthority,
      issue: conflict
        ? `Taxon assignment for '${inputKey}' conflicts with authoritative GenBank taxonomy`
        : '',
      requiresAssignment: false,
      taxonGroup: resolvedAuthority.taxonGroup,
    };
  }
  if (resolvedAuthority.status === 'unsupported' || resolvedAuthority.status === 'conflicting') {
    return {
      assigned,
      authority: resolvedAuthority,
      issue: `GenBank input '${inputKey}': ${resolvedAuthority.reason}`,
      requiresAssignment: false,
      taxonGroup: '',
    };
  }
  return {
    assigned,
    authority: resolvedAuthority,
    issue: '',
    requiresAssignment: true,
    taxonGroup: assigned,
  };
}
// END CLIENT_GENBANK_TAXONOMY_PURE

function genomeFileIdentityKey(file) {
  return `${String(file?.name || '')}|${Number(file?.size || 0)}|${Number(file?.lastModified || 0)}`;
}

function clientGenbankAuthorityForFile(file) {
  return genbankTaxonomyAuthorityCache.get(genomeFileIdentityKey(file)) || {
    status: 'ambiguous',
    taxonGroup: '',
    reason: 'GenBank taxonomy has not been inspected in this browser',
  };
}

function rememberClientGenbankAuthority(file, result) {
  if (!PUBLIC_GENBANK_EXTENSIONS.has(ext(file?.name || ''))) return;
  const authority = result?.genbankAuthority || {
    status: 'ambiguous',
    taxonGroup: '',
    reason: 'GenBank taxonomy could not be inspected in this browser',
  };
  genbankTaxonomyAuthorityCache.set(genomeFileIdentityKey(file), authority);
}

function clientGenbankAuthorityProblem(authority, declaredGroup) {
  if (authority.status === 'conflicting' || authority.status === 'unsupported') return authority.reason;
  if (authority.status === 'resolved' && declaredGroup && authority.taxonGroup !== declaredGroup) {
    return `Selected ${analysisScopeLabel(declaredGroup)} scope conflicts with authoritative GenBank ${analysisScopeLabel(authority.taxonGroup)} taxonomy`;
  }
  return '';
}

function classifyClientFastaText(name, text, taxonGroup = stagedTaxonGroupForFileName(name)) {
  const lines = String(text || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  if (!lines.length) return { readiness: 'invalid', reason: `FASTA genome ${name} is empty.` };
  if (!lines[0].startsWith('>')) {
    return { readiness: 'invalid', reason: `FASTA genome ${name} must start with a FASTA header beginning with >.` };
  }
  let sequenceChars = 0;
  let nucleotideCount = 0;
  let sequenceLines = 0;
  lines.forEach((line) => {
    if (line.startsWith('>')) return;
    const clean = line.replace(/\s+/g, '').toUpperCase();
    if (!clean) return;
    sequenceLines += 1;
    sequenceChars += clean.length;
    for (const char of clean) {
      if (PUBLIC_NUCLEOTIDE_CHARS.has(char)) nucleotideCount += 1;
    }
  });
  if (!sequenceLines || !sequenceChars) {
    return { readiness: 'invalid', reason: `FASTA genome ${name} needs at least one nucleotide sequence line.` };
  }
  if (nucleotideCount / sequenceChars < 0.85) {
    const domain = taxonGroup === 'bacteria' ? 'bacterial' : taxonGroup === 'fungi' ? 'fungal' : 'genome';
    return { readiness: 'invalid', reason: `Looks like protein FASTA or arbitrary text; upload a nucleotide ${domain} assembly FASTA.` };
  }
  if (taxonGroup === 'bacteria') {
    return {
      readiness: 'raw_fasta_requires_prodigal',
      reason: 'Nucleotide bacterial FASTA accepted; antiSMASH will use Prodigal for predictable bacterial gene finding.',
    };
  }
  if (!taxonGroup) {
    return {
      readiness: 'taxon_assignment_required',
      reason: 'Nucleotide FASTA structure passed. Choose Fungi or Bacteria for this logical genome before submission.',
    };
  }
  return {
    readiness: 'raw_fasta_requires_annotation',
    reason: 'Nucleotide FASTA accepted; funannotate must predict CDS/protein translations before downstream BGC tools can run, and may fail if the assembly is not annotatable.',
  };
}

function classifyClientGenbankText(name, text, taxonGroup = stagedTaxonGroupForFileName(name)) {
  const raw = String(text || '');
  const genbankAuthority = parseClientGenbankTaxonomy(raw);
  if (!raw.trim()) return { readiness: 'invalid', reason: `GenBank genome ${name} is empty.`, genbankAuthority };
  const markers = [
    ['LOCUS', /^LOCUS\s+/m],
    ['FEATURES', /^FEATURES\b/m],
    ['ORIGIN', /^ORIGIN\b/m],
    ['//', /^\/\/\s*$/m],
  ];
  const missing = markers.filter(([, pattern]) => !pattern.test(raw)).map(([label]) => label);
  if (missing.length) {
    return { readiness: 'invalid', reason: `GenBank genome ${name} is missing ${missing.join(', ')}.`, genbankAuthority };
  }
  const authorityProblem = clientGenbankAuthorityProblem(genbankAuthority, taxonGroup);
  if (authorityProblem) return { readiness: 'invalid', reason: authorityProblem, genbankAuthority };
  const effectiveTaxonGroup = genbankAuthority.status === 'resolved' ? genbankAuthority.taxonGroup : taxonGroup;
  const hasCds = /^\s+CDS\b/m.test(raw);
  const hasTranslation = /\/translation\s*=/.test(raw);
  if (effectiveTaxonGroup === 'bacteria') {
    return {
      readiness: 'bacterial_genbank_prodigal_ready',
      reason: genbankAuthority.status === 'resolved'
        ? 'Authoritative bacterial GenBank taxonomy accepted; supplied features will be removed from the antiSMASH work input and Prodigal will predict genes consistently.'
        : hasCds || hasTranslation
          ? 'Bacterial GenBank accepted; supplied features will be removed from the antiSMASH work input and Prodigal will predict genes consistently.'
          : 'Feature-free bacterial GenBank accepted; antiSMASH will use Prodigal for gene finding.',
      genbankAuthority,
    };
  }
  if (!effectiveTaxonGroup) {
    return {
      readiness: 'taxon_assignment_required',
      reason: 'GenBank structure passed. Choose Fungi or Bacteria for this logical genome before submission.',
      genbankAuthority,
    };
  }
  if (hasCds && hasTranslation) {
    return {
      readiness: 'annotated_genbank_ready',
      reason: genbankAuthority.status === 'resolved'
        ? 'Authoritative fungal GenBank taxonomy accepted; CDS translations are ready for antiSMASH and FunBGCeX.'
        : 'Annotated GenBank with CDS translations is ready for antiSMASH and FunBGCeX.',
      genbankAuthority,
    };
  }
  return {
    readiness: 'genbank_requires_fallback_or_translations',
    reason: 'GenBank structure is present, but CDS translations were not detected; submit a same-stem nucleotide FASTA or translated GenBank so funannotate can produce proteins before downstream BGC tools run.',
    genbankAuthority,
  };
}

function publicGenomeUploadKind(fileExt) {
  return PUBLIC_FASTA_EXTENSIONS.has(fileExt) ? 'fasta' : 'genbank';
}

function classifyClientGenomeText(file, text) {
  const fileExt = ext(file.name);
  const taxonGroup = stagedTaxonGroupForFileName(file.name);
  if (PUBLIC_FASTA_EXTENSIONS.has(fileExt)) return classifyClientFastaText(file.name, text, taxonGroup);
  if (PUBLIC_GENBANK_EXTENSIONS.has(fileExt)) return classifyClientGenbankText(file.name, text, taxonGroup);
  return { readiness: 'invalid', reason: `Unsupported public genome extension .${fileExt}.` };
}

function classifyClientGenomePreview(file, text) {
  const fileExt = ext(file.name);
  const taxonGroup = stagedTaxonGroupForFileName(file.name);
  if (PUBLIC_FASTA_EXTENSIONS.has(fileExt)) {
    const fasta = classifyClientFastaText(file.name, text, taxonGroup);
    if (fasta.readiness === 'invalid') return fasta;
    return {
      readiness: 'client_preflight_unconfirmed',
      reason: taxonGroup === 'bacteria'
        ? 'Large bacterial FASTA preview passed; full server validation will confirm sequence structure before the Prodigal route.'
        : !taxonGroup
          ? 'Large FASTA preview passed; choose Fungi or Bacteria, then full server validation runs on submission.'
          : 'Large fungal FASTA preview passed in the browser; full server validation runs when you submit.',
    };
  }
  if (PUBLIC_GENBANK_EXTENSIONS.has(fileExt)) {
    const raw = String(text || '');
    const genbankAuthority = parseClientGenbankTaxonomy(raw);
    if (!raw.trim()) return { readiness: 'invalid', reason: `GenBank genome ${file.name} is empty.`, genbankAuthority };
    const missing = [
      ['LOCUS', /^LOCUS\s+/m],
      ['FEATURES', /^FEATURES\b/m],
    ].filter(([, pattern]) => !pattern.test(raw)).map(([label]) => label);
    if (missing.length) return { readiness: 'invalid', reason: `GenBank genome ${file.name} is missing ${missing.join(', ')}.`, genbankAuthority };
    const authorityProblem = clientGenbankAuthorityProblem(genbankAuthority, taxonGroup);
    if (authorityProblem) return { readiness: 'invalid', reason: authorityProblem, genbankAuthority };
    const effectiveTaxonGroup = genbankAuthority.status === 'resolved' ? genbankAuthority.taxonGroup : taxonGroup;
    return {
      readiness: 'client_preflight_unconfirmed',
      reason: effectiveTaxonGroup === 'bacteria'
        ? genbankAuthority.status === 'resolved'
          ? 'Large GenBank preview contains authoritative bacterial taxonomy; the server will verify every record before feature stripping and Prodigal.'
          : 'Large bacterial GenBank preview passed; full server validation will confirm sequence structure before feature stripping and Prodigal.'
        : !effectiveTaxonGroup
          ? 'Large GenBank preview passed; choose Fungi or Bacteria, then full server validation runs on submission.'
          : genbankAuthority.status === 'resolved'
            ? 'Large GenBank preview contains authoritative fungal taxonomy; the server will verify every record, ORIGIN, and CDS readiness.'
            : 'Large fungal GenBank preview passed; full server validation will confirm ORIGIN, CDS translations, and same-stem FASTA pairing.',
      genbankAuthority,
    };
  }
  return { readiness: 'invalid', reason: `Unsupported public genome extension .${fileExt}.` };
}

async function readClientGenomePreview(file) {
  if (file.size <= CLIENT_GENOME_PRECHECK_BYTES) return { text: await file.text(), partial: false };
  const head = await file.slice(0, CLIENT_GENOME_PRECHECK_BYTES).text();
  const tailStart = Math.max(CLIENT_GENOME_PRECHECK_BYTES, file.size - CLIENT_GENOME_PRECHECK_TAIL_BYTES);
  const tail = tailStart < file.size ? await file.slice(tailStart, file.size).text() : '';
  return { text: `${head}\n${tail}`, partial: true };
}

function browserGenomePrecheckUnavailableReason(file) {
  const name = file?.name ? ` ${file.name}` : ' this genome file';
  return `Browser preview could not inspect${name}. The file may be locked, still syncing, moved after selection, too large for local preview, or not plain-text FASTA/GenBank. Submit will run full server validation and report the exact format problem.`;
}

async function cacheGenomeFileCheck(file) {
  const key = genomeFileCheckKey(file);
  if (genomeCheckCache.has(key)) {
    const cached = genomeCheckCache.get(key);
    rememberClientGenbankAuthority(file, cached);
    return cached;
  }
  const quota = publicQuotaLimits();
  if (file.size > quota.max_upload_file_mb * 1048576) {
    const result = { readiness: 'invalid', reason: publicFileLimitMessage(quota) };
    genomeCheckCache.set(key, result);
    rememberClientGenbankAuthority(file, result);
    return result;
  }
  try {
    const preview = await readClientGenomePreview(file);
    const result = preview.partial ? classifyClientGenomePreview(file, preview.text) : classifyClientGenomeText(file, preview.text);
    genomeCheckCache.set(key, result);
    rememberClientGenbankAuthority(file, result);
    return result;
  } catch (err) {
    const result = { readiness: 'client_preflight_unconfirmed', reason: browserGenomePrecheckUnavailableReason(file) };
    genomeCheckCache.set(key, result);
    rememberClientGenbankAuthority(file, result);
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
  const accessions = manualAccessionLines();
  if (!brutalSyncingAccepted) syncBrutalRowsFromAccepted();
  const list = document.getElementById('accepted-accessions-list');
  if (!list) return;
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
  resetBrutalAccessionDrafts();
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
  resetBrutalAccessionDrafts();
  clearStaleTargetGenome();
  renderAcceptedAccessions();
  updateManualAccessionsStatus();
  renderFileList();
}

function clearAcceptedManualAccessions() {
  acceptedManualAccessions = [];
  resetBrutalAccessionDrafts();
  clearStaleTargetGenome();
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

function importAccessionsToLoader(accessions) {
  const limit = accessionLimit();
  const existing = new Set(manualAccessionLines());
  const nextDrafts = Array.from({ length: 50 }, (_, index) => brutalAccessionDrafts[index] || '');
  const added = [];
  accessions.forEach((raw) => {
    const accession = normalizeAccessionDraft(raw);
    if (!validBrutalAccession(accession) || existing.has(accession)) return;
    const slot = nextDrafts.findIndex((value, index) => index < limit && !normalizeAccessionDraft(value));
    if (slot < 0) return;
    nextDrafts[slot] = accession;
    existing.add(accession);
    added.push(accession);
  });
  if (!added.length) return added;
  brutalAccessionDrafts = nextDrafts;
  acceptedManualAccessions = acceptedDraftAccessions();
  if (manualAccessionsInput) manualAccessionsInput.value = '';
  renderBrutalAccessionRows();
  syncEcologyMetadataPanel();
  applyBrutalEcologyToMetadataTable();
  updateBrutalTargetButton();
  updateRunSummary();
  return added;
}

async function addAccessionFileSource(file) {
  const noticeKey = `accession-file:${file.name}`;
  let text = '';
  try {
    text = await file.text();
  } catch (err) {
    setBrutalInputNotice(noticeKey, `Could not read accession list: ${file.name}`);
    return false;
  }
  const parsed = parseAccessionText(text);
  if (parsed.invalid.length) {
    setBrutalInputNotice(noticeKey, `Accession list ${file.name}: ${manualAccessionErrorMessage(parsed)}`);
    return false;
  }
  if (!parsed.accessions.length) {
    setBrutalInputNotice(noticeKey, `Accession list ${file.name} does not contain any accessions.`);
    return false;
  }
  const existing = new Set(manualAccessionLines());
  const newAccessions = parsed.accessions.filter(accession => !existing.has(accession));
  if (!newAccessions.length) {
    setBrutalInputNotice(noticeKey, `Accession list ${file.name} contains only duplicate accessions already accepted.`);
    return false;
  }
  const imported = importAccessionsToLoader(newAccessions);
  if (!imported.length) {
    setBrutalInputNotice(noticeKey, `Accession list ${file.name} could not fit in the accession loader.`);
    return false;
  }
  accessionFileSources.push({ name: String(file.name || 'accessions.txt'), accessions: imported.slice() });
  const fileOwned = accessionFileOwnedAccessions();
  acceptedManualAccessions = acceptedManualAccessions.filter(accession => !fileOwned.has(normalizeAccessionDraft(accession)));
  setBrutalInputNotice(noticeKey, '');
  const skipped = parsed.accessions.length - imported.length + parsed.duplicateCount;
  const status = document.getElementById('upload-status');
  if (status) {
    status.textContent = skipped
      ? `${imported.length} accession${imported.length === 1 ? '' : 's'} imported to the accession loader from ${file.name}; ${skipped} skipped.`
      : `${imported.length} accession${imported.length === 1 ? '' : 's'} imported to the accession loader from ${file.name}.`;
  }
  return true;
}

function inputCheckLevel(readiness) {
  if (readiness === 'invalid') return 'blocked';
  if (readiness === 'annotated_genbank_ready' || readiness === 'bacterial_genbank_prodigal_ready') return 'ready';
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
  updateInputLimitGuidance();
  const limits = document.getElementById('input-checker-limits');
  if (!limits) return;
  limits.textContent = `Limits: ${quota.max_accessions} accessions, ${quota.max_genome_files} genome files, ${formatQuotaMb(quota.max_upload_file_mb)} per file, ${formatQuotaMb(quota.max_upload_total_mb)} total`;
}

function accessionPreflightPendingReason(sourceName = '') {
  const source = sourceName ? ` from ${sourceName}` : '';
  const scope = normalizeAnalysisScope(stagedAnalysisScope);
  if (scope === 'bacteria') {
    return `FORMAT OK${source} - NCBI CHECK PENDING. Authoritative taxonomy is verified before job creation, then bacterial sequence routes to antiSMASH with Prodigal.`;
  }
  if (scope === 'both') {
    return `FORMAT OK${source} - NCBI CHECK PENDING. Authoritative NCBI taxonomy will route each accepted accession to Fungi or Bacteria.`;
  }
  if (!sourceName) {
    return 'FORMAT OK - NCBI CHECK PENDING. Genome FASTA is verified before job creation and can route through funannotate if translations are missing.';
  }
  return `FORMAT OK from ${sourceName} - NCBI CHECK PENDING. Genome FASTA is verified before job creation and can route through funannotate if translations are missing.`;
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

  brutalAccessionDraftIssues().forEach((issue) => {
    addInputCheckRow(rows, 'blocked', 'NCBI accession', `Row ${issue.index + 1}: ${issue.accession}`, issue.message);
  });

  acceptedManualAccessions.forEach((accession) => {
    addInputCheckRow(rows, 'ready', 'NCBI accession', accession, accessionPreflightPendingReason());
  });
  accessionFileSources.forEach((source) => {
    source.accessions.forEach((accession) => {
      addInputCheckRow(rows, 'ready', 'NCBI accession', accession, accessionPreflightPendingReason(source.name));
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
        ? 'Admin/local auxiliary input; not part of public genome intake.'
        : 'This file type is not supported by the public genome intake.';
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
      reason = publicFileLimitMessage(quota);
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

  const assignmentValidation = taxonAssignmentValidation();
  assignmentValidation.unresolved.forEach((item) => {
    addInputCheckRow(
      rows,
      'blocked',
      'Taxon assignment',
      item.inputKey,
      'Both mode requires a Fungi or Bacteria declaration for this logical genome before submission.',
    );
  });
  assignmentValidation.authorityIssues.forEach(({ inputKey, issue }) => {
    addInputCheckRow(rows, 'blocked', 'GenBank taxonomy', inputKey, issue);
  });
  assignmentValidation.sidecarIssues.forEach((issue) => {
    addInputCheckRow(rows, 'blocked', 'Taxon assignment sidecar', TAXON_ASSIGNMENTS_FILENAME, issue);
  });
  assignmentValidation.generalIssues.forEach((issue) => {
    addInputCheckRow(rows, 'blocked', 'Taxon assignment', 'Both mode', issue);
  });
  if (taxonAssignmentSidecar && !assignmentValidation.issues.length) {
    addInputCheckRow(
      rows,
      'ready',
      'Taxon assignment sidecar',
      TAXON_ASSIGNMENTS_FILENAME,
      `${Object.keys(taxonAssignmentsPayload()).length} assignment row(s) loaded.`,
    );
  }

  if (acceptedAccessions.length > quota.max_accessions) {
    addInputCheckRow(rows, 'blocked', 'Quota', `${acceptedAccessions.length} accessions`, `Public runs accept at most ${quota.max_accessions} NCBI assembly accessions. ${localWorkflowPrompt()}`);
  }
  if (publicGenomeFiles.length > quota.max_genome_files) {
    addInputCheckRow(rows, 'blocked', 'Quota', `${publicGenomeFiles.length} genome files`, `Public runs accept at most ${quota.max_genome_files} genome files. ${localWorkflowPrompt()}`);
  }
  if (totalUploadBytes > maxTotalBytes) {
    addInputCheckRow(rows, 'blocked', 'Quota', fmt_size(totalUploadBytes), publicTotalLimitMessage(quota));
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
    if (isTaxonAssignmentsSidecarName(f.name)) {
      await loadTaxonAssignmentSidecar(f);
      setBrutalInputNotice(`file:${f.name}`, '');
      continue;
    }
    if (!allowed.has(fileExt)) {
      setBrutalInputNotice(`file:${f.name}`, `Unsupported file type: ${f.name}. Allowed: ${allowedCopy}. ${canUseAdminSurfaces() ? '' : localWorkflowPrompt()}`.trim());
      continue;
    }
    setBrutalInputNotice(`file:${f.name}`, '');
    if (fileExt === 'txt') {
      await addAccessionFileSource(f);
      continue;
    }
    if (!selectedFiles.find(x => x.name === f.name)) {
      if (PUBLIC_FASTA_EXTENSIONS.has(fileExt) || PUBLIC_GENBANK_EXTENSIONS.has(fileExt)) await cacheGenomeFileCheck(f);
      selectedFiles.push(f);
    }
  }
  await refreshSelectedGenomeChecks();
  renderAcceptedAccessions();
  renderFileList();
}

async function removeFile(index) {
  const [removed] = selectedFiles.splice(index, 1);
  if (removed) genbankTaxonomyAuthorityCache.delete(genomeFileIdentityKey(removed));
  const targetInput = document.getElementById('target-genome');
  const removedTarget = removed && isGenomeUploadName(removed.name)
    ? genomeStemFromName(removed.name)
    : '';
  const sameTargetRemains = removedTarget && selectedFiles.some((file) => (
    isGenomeUploadName(file.name)
    && genomeStemFromName(file.name).toLowerCase() === removedTarget.toLowerCase()
  ));
  if (targetInput && removedTarget && !sameTargetRemains
      && targetInput.value.trim().toLowerCase() === removedTarget.toLowerCase()) {
    targetInput.value = '';
    targetInput.dispatchEvent(new Event('input', { bubbles: true }));
    updateBrutalTargetButton();
  }
  clearStaleTargetGenome();
  await refreshSelectedGenomeChecks();
  renderFileList();
}

function removeAccessionFileSource(index) {
  const [removed] = accessionFileSources.splice(index, 1);
  if (!removed) return;
  const removedSet = new Set((removed.accessions || []).map(normalizeAccessionDraft));
  const retained = acceptedDraftAccessions().filter(accession => !removedSet.has(accession));
  brutalAccessionDrafts = Array.from({ length: 50 }, (_, draftIndex) => retained[draftIndex] || '');
  brutalAccessionCommitted = new Set(
    retained.map((value, draftIndex) => normalizeAccessionDraft(value) ? draftIndex : -1).filter(draftIndex => draftIndex >= 0),
  );
  removedSet.forEach(accession => brutalEcoSelections.delete(accession));
  acceptedManualAccessions = acceptedManualAccessions.filter(accession => !removedSet.has(normalizeAccessionDraft(accession)));
  renderBrutalAccessionRows();
  syncBrutalAcceptedFromDrafts();
}

function submissionsPausedForPublic() {
  const state = String(runtimeStatusSnapshot.submissions || '').trim().toLowerCase();
  return !canUseAdminSurfaces() && ['paused', 'closed', 'disabled', 'false', '0'].includes(state);
}

function uploadedInputRequiresAcknowledgment() {
  return !canUseAdminSurfaces() && (
    selectedFiles.length > 0
    || accessionFileSources.length > 0
    || !!taxonAssignmentSidecar
  );
}

function syncDataUseAcknowledgment() {
  const panel = document.getElementById('data-use-ack-panel');
  const checkbox = document.getElementById('data-use-ack');
  const required = uploadedInputRequiresAcknowledgment();
  if (panel) {
    panel.hidden = !required;
    panel.toggleAttribute('inert', !required);
    panel.setAttribute('aria-hidden', required ? 'false' : 'true');
  }
  if (!required && checkbox) checkbox.checked = false;
  return required && !checkbox?.checked;
}

function submissionValidationSignature() {
  const files = selectedFiles
    .map(file => [String(file.name || ''), Number(file.size || 0), Number(file.lastModified || 0)])
    .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
  const accessionSources = accessionFileSources
    .map(source => [String(source.name || ''), [...(source.accessions || [])].map(normalizeAccessionDraft).sort()])
    .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
  const taxonAssignments = Object.entries(taxonAssignmentsPayload())
    .sort(([left], [right]) => left.localeCompare(right));
  const ecologyRows = inputEcologyEnabled()
    ? currentEcologyMetadataRows().map(row => ({
      input: String(row.input || ''),
      accession: String(row.accession || ''),
      primary: String(row.primary || ''),
      secondary: String(row.secondary || ''),
    })).sort((a, b) => a.input.localeCompare(b.input))
    : [];
  return JSON.stringify({
    projectName: projectNameValue(),
    analysisScope: normalizeAnalysisScope(stagedAnalysisScope),
    manualAccessions: manualAccessionLines().map(normalizeAccessionDraft).sort(),
    files,
    accessionSources,
    taxonAssignments,
    ecologyEnabled: inputEcologyEnabled(),
    ecologyRows,
  });
}

function syncRunButtonPresentation(button = document.getElementById('run-btn')) {
  if (!button) return;
  const submitReady = !!validatedIntakeSignature
    && validatedIntakeSignature === submissionValidationSignature();
  button.classList.toggle('is-validation-pending', !submitReady);
  button.classList.toggle('is-submit-ready', submitReady);
  button.textContent = submitReady ? 'Submit run' : 'Validate';
}

function renderFileList() {
  const list = document.getElementById('file-list');
  const btn  = document.getElementById('run-btn');
  const stat = document.getElementById('upload-status');
  const submitShell = document.getElementById('submit-button-shell');
  const accessionLines = manualAccessionLines();
  const accessionFileItems = accessionFileSources.map((source, idx) => `
    <div class="file-item">
      <span class="file-icon" aria-hidden="true"></span>
      <span class="file-name">${escapeHtml(source.name)}</span>
      <span class="file-size">${source.accessions.length} accession${source.accessions.length === 1 ? '' : 's'}</span>
      <button class="file-remove" onclick="removeAccessionFileSource(${idx})" title="Remove">✕</button>
    </div>`).join('');
  const sidecarItem = taxonAssignmentSidecar ? `
    <div class="file-item">
      <span class="file-icon" aria-hidden="true"></span>
      <span class="file-name">${TAXON_ASSIGNMENTS_FILENAME}</span>
      <span class="file-size">${taxonAssignmentSidecarIssues.length ? 'Needs review' : `${Object.keys(taxonAssignmentsPayload()).length} assignments`}</span>
      <button class="file-remove" type="button" onclick="removeTaxonAssignmentSidecar()" title="Remove" aria-label="Remove taxon assignments sidecar">✕</button>
    </div>` : '';
  list.innerHTML = selectedFiles.map((f, idx) => {
    const target = isGenomeUploadName(f.name) ? genomeStemFromName(f.name) : '';
    const targetAttrs = target
      ? ` data-target-genome="${escapeHtml(target)}"`
      : '';
    const ecologyControls = target
      ? `<span class="file-eco-cell"><button class="eco-button file-eco-button" type="button" data-eco-field="primary">ECO 1</button></span>
        <span class="file-eco-cell"><button class="eco-button file-eco-button secondary" type="button" data-eco-field="secondary">ECO 2</button></span>`
      : '';
    return `
      <div class="file-item"${targetAttrs}>
        <span class="file-icon" aria-hidden="true"></span>
        <span class="file-name">${escapeHtml(f.name)}</span>
        <span class="file-size">${fmt_size(f.size)}</span>
        ${ecologyControls}
        <button class="file-remove" onclick="removeFile(${idx})" title="Remove" aria-label="Remove ${escapeHtml(f.name)}">✕</button>
      </div>`;
  }).join('') + accessionFileItems + sidecarItem;
  renderTaxonAssignmentPanel();
  const draftPending = !!(manualAccessionsInput && manualAccessionsInput.value.trim());
  const inputSourceCount = selectedFiles.length + (accessionLines.length ? 1 : 0);
  const ackMissing = syncDataUseAcknowledgment();
  const projectMissing = !projectNameValue();
  const queuePaused = inputSourceCount > 0 && submissionsPausedForPublic();
  setBrutalInputNotice('queue-gate', queuePaused ? 'Queue gate: paused before upload.' : '');
  setBrutalInputNotice('data-use', '');
  setBrutalInputNotice('project-name', '');
  setProjectNameRequiredState(projectMissing);
  if (submitShell) submitShell.classList.toggle('is-project-locked', projectMissing);
  const assignmentValidation = taxonAssignmentValidation();
  const assignmentBlocked = normalizeAnalysisScope(stagedAnalysisScope) === 'both'
    && (assignmentValidation.unresolved.length > 0 || assignmentValidation.issues.length > 0);
  const assignmentMessage = assignmentValidation.issues[0]
    || (assignmentValidation.unresolved.length
      ? `${assignmentValidation.unresolved.length} logical genome assignment${assignmentValidation.unresolved.length === 1 ? '' : 's'} required in Both mode.`
      : '');
  setBrutalInputNotice('taxon-assignment', '');
  const checkerState = renderInputChecker();
  const checkerBlocked = !canUseAdminSurfaces() && checkerState.blocked > 0;
  btn.disabled = inputSourceCount === 0 || draftPending || ackMissing || projectMissing || queuePaused || checkerBlocked || assignmentBlocked;
  const currentValidationSignature = submissionValidationSignature();
  if (validatedIntakeSignature && validatedIntakeSignature !== currentValidationSignature) {
    validatedIntakeSignature = '';
  }
  syncRunButtonPresentation(btn);
  if (queuePaused) {
    stat.textContent = 'SUBMISSIONS PAUSED - QUEUE LOCKED BY OPERATOR';
  } else if (draftPending) {
    stat.textContent = 'Press Add accessions to accept the draft before starting.';
  } else if (inputSourceCount && assignmentBlocked) {
    stat.textContent = '';
  } else if (inputSourceCount && checkerBlocked) {
    stat.textContent = `${checkerState.blocked} blocked input source${checkerState.blocked === 1 ? '' : 's'} must be fixed before starting.`;
  } else if (inputSourceCount && checkerState.warning) {
    stat.textContent = `${inputSourceCount} input source(s) ready for workflow with ${checkerState.warning} warning${checkerState.warning === 1 ? '' : 's'}`;
  } else {
    stat.textContent = inputSourceCount ? `${inputSourceCount} input source(s) ready for workflow` : '';
  }
  updateManualAccessionsStatus();
  syncEcologyMetadataPanel();
  applyBrutalEcologyToMetadataTable();
  updateBrutalEcologyToggle();
  updateBrutalTargetButton();
  renderBrutalInputLog();
  applyAnalysisCapabilityVisibility();
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
  applyBrutalEcologyToMetadataTable();
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
  const name = requireProjectNameForSubmit();
  if (!name) return;
  commitAllBrutalAccessionDrafts({ render: false });
  if (manualAccessionsInput && manualAccessionsInput.value.trim()) {
    document.getElementById('upload-status').textContent = 'Press Add accessions to accept the draft before starting.';
    renderFileList();
    return;
  }
  const dataUseAck = document.getElementById('data-use-ack');
  if (uploadedInputRequiresAcknowledgment() && !dataUseAck?.checked) {
    dataUseAck?.focus();
    renderFileList();
    return;
  }
  if (selectedFiles.length === 0 && manualLines.length === 0) return;
  const assignmentValidation = taxonAssignmentValidation();
  if (normalizeAnalysisScope(stagedAnalysisScope) === 'both'
      && (assignmentValidation.unresolved.length || assignmentValidation.issues.length)) {
    const message = assignmentValidation.issues[0]
      || `${assignmentValidation.unresolved.length} logical genome assignment${assignmentValidation.unresolved.length === 1 ? '' : 's'} required in Both mode.`;
    document.getElementById('upload-status').textContent = message;
    renderFileList();
    return;
  }
  const checkerState = renderInputChecker();
  if (!canUseAdminSurfaces() && checkerState.blocked > 0) {
    document.getElementById('upload-status').textContent = `${checkerState.blocked} blocked input source${checkerState.blocked === 1 ? '' : 's'} must be fixed before starting.`;
    renderFileList();
    return;
  }

  const requestedValidationSignature = submissionValidationSignature();
  if (validatedIntakeSignature !== requestedValidationSignature) {
    const runButton = document.getElementById('run-btn');
    const uploadStatus = document.getElementById('upload-status');
    runButton.disabled = true;
    uploadStatus.textContent = 'Validating inputs…';
    await refreshSelectedGenomeChecks();
    renderFileList();
    const refreshedAssignment = taxonAssignmentValidation();
    const refreshedChecker = renderInputChecker();
    const refreshedAssignmentBlocked = normalizeAnalysisScope(stagedAnalysisScope) === 'both'
      && (refreshedAssignment.unresolved.length || refreshedAssignment.issues.length);
    if ((!canUseAdminSurfaces() && refreshedChecker.blocked > 0) || refreshedAssignmentBlocked) {
      renderFileList();
      return;
    }
    validatedIntakeSignature = submissionValidationSignature();
    syncRunButtonPresentation(runButton);
    runButton.disabled = false;
    uploadStatus.textContent = 'Validation passed. Review the inputs, then select Submit run.';
    return;
  }

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
  const runSetupReceipt = collectRunSetupAccessReceipt({ projectName: name });
  if (metadataText) {
    fd.append('files', new File([metadataText], 'ecofun_metadata_normalized.tsv', { type: 'text/tab-separated-values' }));
  }
  fd.append('project_name', name);
  fd.append('analysis_scope', normalizeAnalysisScope(stagedAnalysisScope));
  const taxonAssignments = taxonAssignmentsPayload();
  if (Object.keys(taxonAssignments).length) {
    fd.append('taxon_assignments', JSON.stringify(taxonAssignments));
  }
  fd.append('data_use_ack', boolToFlag(!!dataUseAck?.checked));
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
  fd.append('genome_parallelism', document.getElementById('genome-parallelism').value || '1');
  fd.append('antismash_record_parallelism', document.getElementById('antismash-record-parallelism').value || '1');
  fd.append('antismash_shard_cpus', document.getElementById('antismash-shard-cpus').value || '0');
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
  fd.append('clinker_max_regions', document.getElementById('clinker-max-regions').value || '20');
  fd.append('atlas_stage_limit', document.getElementById('clinker-max-regions').value || '20');
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
  setBrutalInputNotice('submission', '');

  try {
    const resp = await apiFetch('api/jobs', { method: 'POST', body: fd }, { kind: 'submit' });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Upload failed');
    }
    const { job_id, public_run_id, read_token, expires_at, result_url, input_summary } = await resp.json();
    const submittedRunId = String(public_run_id || job_id || '').trim();
    if (submittedRunId) publicResultRunIds.add(submittedRunId);
    if (input_summary) {
      runSetupReceipt.inputSummary = input_summary;
      runSetupReceipt.accessionMetadata = Array.isArray(input_summary.accession_metadata) ? input_summary.accession_metadata : [];
      runSetupReceipt.taxonCounts = normalizeTaxonCounts(input_summary.taxon_counts || input_summary.taxonCounts || input_summary);
    }
    if (read_token) rememberOpenedRun(submittedRunId, read_token, { name, status: 'pending' });
    validatedIntakeSignature = '';
    selectedFiles = [];
    acceptedManualAccessions = [];
    accessionFileSources = [];
    genomeCheckCache = new Map();
    genbankTaxonomyAuthorityCache = new Map();
    stagedTaxonAssignments = new Map();
    stagedTaxonAssignmentSources = new Map();
    taxonAssignmentSidecar = null;
    taxonAssignmentSidecarIssues = [];
    brutalInputNotices.clear();
    if (manualAccessionsInput) manualAccessionsInput.value = '';
    resetBrutalAccessionDrafts();
    renderAcceptedAccessions();
    renderFileList();
    document.getElementById('upload-status').textContent = expires_at ? `Run submitted. Results expire ${new Date(expires_at).toLocaleDateString()}.` : 'Run submitted.';
    renderSubmissionConfirmation({
      projectName: name,
      jobId: submittedRunId,
      readToken: read_token || '',
      resultUrl: result_url || '',
      expiresAt: expires_at || '',
      notifyEmail,
      receipt: runSetupReceipt,
      status: 'queued',
    });
    lockSubmittedIntake();
    await loadJob(submittedRunId, true, {
      publicResult: true,
      readToken: read_token || '',
      source: 'submit',
      analysisScope: runSetupReceipt.analysisScope,
      taxonCounts: input_summary?.taxon_counts || {},
    });
    if (canUseAdminSurfaces()) refreshJobHistory();
  } catch (err) {
    const message = err?.message || 'Upload failed';
    document.getElementById('upload-status').textContent = 'Upload failed: ' + message;
    setBrutalInputNotice('submission', message);
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
    Array.isArray(j.result_files) ? j.result_files.length : Number(j.result_file_count || 0),
    j.id === activeJobId,
    j.id === rerunScopeOpenJobId,
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

function diagnosticRerunDisclosureId(jobId) {
  const safe = String(jobId || '').replace(/[^A-Za-z0-9_-]+/g, '-');
  return `diagnostic-rerun-${safe || 'job'}`;
}

function diagnosticRerunDetails(jobId) {
  return document.getElementById(diagnosticRerunDisclosureId(jobId));
}

function syncDiagnosticRerunDisclosure(event, jobId) {
  const details = event?.currentTarget;
  if (!details) return;
  const item = details.closest('[data-diagnostic-job-item]');
  const button = item?.querySelector('[data-rerun-open]');
  if (details.open) {
    if (button) button.setAttribute('aria-expanded', 'true');
    item?.classList.add('has-open-rerun');
    animateRerunPanelOpen(details);
    return;
  }
  if (rerunScopeOpenJobId === String(jobId || '')) rerunScopeOpenJobId = '';
  if (button) button.setAttribute('aria-expanded', 'false');
  item?.classList.remove('has-open-rerun');
}

async function toggleJobRerunScope(event, jobId) {
  event?.preventDefault?.();
  event?.stopPropagation?.();
  if (!canUseAdminSurfaces()) return;
  const safeJobId = String(jobId || '');
  if (!safeJobId) return;

  if (rerunScopeOpenJobId === safeJobId) {
    rerunScopeOpenJobId = '';
    const openDetails = diagnosticRerunDetails(safeJobId);
    if (openDetails) openDetails.open = false;
    event?.currentTarget?.setAttribute?.('aria-expanded', 'false');
    return;
  }

  const previousDetails = diagnosticRerunDetails(rerunScopeOpenJobId);
  if (previousDetails) previousDetails.open = false;
  rerunScopeOpenJobId = safeJobId;
  openOpsPanel({ tab: 'jobs', focusPanel: false, returnFocus: event?.currentTarget || document.activeElement });
  lastJobHistoryRenderKey = '';
  renderJobHistory([...jobHistoryById.values()]);
  switchOpsTab('jobs', { focus: false });
  const details = diagnosticRerunDetails(safeJobId);
  window.requestAnimationFrame(() => {
    details?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    details?.querySelector('summary')?.focus({ preventScroll: true });
  });
}

async function rerunJobFromHistory(event, jobId) {
  return toggleJobRerunScope(event, jobId);
}

function diagnosticJobDisplayState(job, index) {
  if (!job) return index === 1 ? 'complete' : index === 2 ? 'failed' : 'running';
  const status = String(job.status || '').toLowerCase();
  if (status === 'success') return 'complete';
  if (status === 'failed') return 'failed';
  if (status === 'running') return 'running';
  return status || 'route payload';
}

function diagnosticRouteCardLabel(index) {
  return index === null ? 'jobs[n]' : `jobs[${index}]`;
}

function renderDiagnosticRerunRail(jobId, job, displayLabel) {
  const status = String((job && job.status) || '').toLowerCase();
  const unavailable = status === 'pending' || status === 'running' || !jobCanRerun(job);
  const labels = {
    prep: 'Genome prep',
    annotation: 'Annotation & BGC',
    bigscape: 'BiG-SCAPE',
    summary: 'Summary',
    clinker: 'Clinker',
    figures: 'Figures',
    nplinker: 'NPLinker',
  };
  const checks = STAGES.map(stage => {
    const enabled = !unavailable && jobStageEnabled(job, stage.key) && rerunStageAllowed(stage.key);
    const checked = enabled && rerunDefaultChecked(job, stage.key);
    return `<label class="rerun-check${enabled ? '' : ' is-unavailable'}"><input type="checkbox" data-diagnostic-rerun-stage="${escapeHtml(stage.key)}" ${checked ? 'checked' : ''} ${enabled ? '' : 'disabled'} onchange="updateDiagnosticRerunSubmit(event)" /> <span>${escapeHtml(labels[stage.key] || stage.label)}</span></label>`;
  }).join('') + `<label class="rerun-check rerun-force"><input type="checkbox" data-diagnostic-rerun-force ${unavailable ? 'disabled' : ''} onchange="updateDiagnosticRerunSubmit(event)" /> <span>Force overwrite</span></label>`;
  const statusText = unavailable ? 'Rerun unavailable for this state.' : 'Choose one or more stages.';
  const safeJobId = escapeHtml(escapeJsString(jobId));
  return `
    <details class="rerun-rail rerun-disclosure" id="${escapeHtml(diagnosticRerunDisclosureId(jobId))}" data-rerun-rail data-rerun-job-id="${escapeHtml(jobId)}" open ontoggle="syncDiagnosticRerunDisclosure(event,'${safeJobId}')">
      <summary class="rerun-disclosure-summary">
        <span><b>Rerun stages</b><small>${escapeHtml(displayLabel)}</small></span>
        <code>${escapeHtml(jobId)}</code>
      </summary>
      <div class="rerun-panel-body rerun-disclosure-body">
        <div class="rerun-check-grid">${checks}</div>
        <div class="rerun-actions">
          <button class="rerun-submit" type="button" data-queue-rerun onclick="queueDiagnosticRerun(event,'${safeJobId}')" ${unavailable ? 'disabled' : ''}>Queue selected stages</button>
          <span class="rerun-status" id="diagnostic-rerun-status" data-rerun-status aria-live="polite">${escapeHtml(statusText)}</span>
        </div>
      </div>
    </details>`;
}

function updateDiagnosticRerunSubmit(event = null) {
  const rail = event?.currentTarget?.closest?.('[data-rerun-rail]')
    || diagnosticRerunDetails(rerunScopeOpenJobId)
    || document.querySelector('[data-rerun-rail][open]');
  if (!rail) return;
  const hasSelection = !!rail.querySelector('[data-diagnostic-rerun-stage]:checked:not(:disabled)');
  const submit = rail.querySelector('[data-queue-rerun]');
  if (submit) submit.disabled = !hasSelection;
  const status = rail.querySelector('[data-rerun-status]');
  if (status && hasSelection) status.textContent = '';
}

async function queueDiagnosticRerun(event, jobId) {
  event?.preventDefault?.();
  event?.stopPropagation?.();
  if (!canUseAdminSurfaces()) return;
  const targetJobId = String(jobId || rerunScopeOpenJobId || '');
  const rail = event?.currentTarget?.closest?.('[data-rerun-rail]')
    || diagnosticRerunDetails(targetJobId);
  const statusEl = rail?.querySelector('[data-rerun-status]');
  const selected = new Set([...(rail?.querySelectorAll('[data-diagnostic-rerun-stage]:checked:not(:disabled)') || [])].map(el => el.dataset.diagnosticRerunStage));
  if (!targetJobId || !selected.size) {
    if (statusEl) statusEl.textContent = 'Choose at least one stage.';
    return;
  }
  const payload = rerunPayloadFromStages(selected, !!rail?.querySelector('[data-diagnostic-rerun-force]')?.checked);
  if (!rerunPayloadHasStages(payload)) {
    if (statusEl) statusEl.textContent = 'Choose at least one stage.';
    return;
  }
  if (statusEl) statusEl.textContent = 'Queueing rerun...';
  try {
    await queueJobRerun(targetJobId, payload);
    if (statusEl) statusEl.textContent = 'Rerun queued.';
    rerunScopeOpenJobId = '';
    await loadJob(targetJobId, true, { source: 'rerun' });
    refreshJobHistory();
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message || String(err);
  }
}

function renderJobHistory(jobs) {
  const el = document.getElementById('job-history');
  if (!el) return;
  const list = (Array.isArray(jobs) ? jobs : []).filter(job => job && job.id);
  jobHistoryById = new Map(list.map(job => [String(job.id || ''), job]).filter(([id]) => id));
  const renderKey = jobHistoryRenderKey(list);
  if (renderKey === lastJobHistoryRenderKey) return;
  lastJobHistoryRenderKey = renderKey;
  const summary = document.getElementById('job-history-summary');
  if (summary) summary.textContent = list.length ? `${list.length} submitted job${list.length === 1 ? '' : 's'}` : 'No submitted jobs';
  if (!list.length) {
    el.innerHTML = '<div class="empty-state">No submitted jobs yet.</div>';
    updateDiagnosticRerunSubmit();
    return;
  }
  el.innerHTML = list.map((job) => {
    const jobId = String(job.id || '');
    const jsJobId = escapeJsString(jobId);
    const displayLabel = jobProjectName(job);
    const displayState = diagnosticJobDisplayState(job, 0);
    const selected = jobId && jobId === activeJobId;
    const rerunOpen = jobId && rerunScopeOpenJobId === jobId;
    const statusText = statusLabel(job.status);
    const stageText = jobStageDisplay(job);
    const updatedRaw = job.updated_at || job.updatedAt || job.created_at || job.createdAt || '';
    const updatedDate = updatedRaw ? new Date(updatedRaw) : null;
    const updatedText = updatedDate && !Number.isNaN(updatedDate.getTime())
      ? updatedDate.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
      : 'unknown';
    const rerunCount = Number(job.rerun_count || 0);
    const fileCount = Array.isArray(job.result_files) ? job.result_files.length : Number(job.result_file_count || 0);
    const fileText = `${Number.isFinite(fileCount) ? fileCount : 0} file${fileCount === 1 ? '' : 's'}`;
    const disclosureId = diagnosticRerunDisclosureId(jobId);
    const rerunAttrs = `data-rerun-job-id="${escapeHtml(jobId)}" onclick="toggleJobRerunScope(event,'${escapeHtml(jsJobId)}')" aria-controls="${escapeHtml(disclosureId)}" aria-expanded="${rerunOpen ? 'true' : 'false'}"`;
    return `
      <div class="diagnostic-job-item${rerunOpen ? ' has-open-rerun' : ''}" data-diagnostic-job-item data-job-id="${escapeHtml(jobId)}">
      <article class="diagnostic-job-card${selected ? ' is-selected' : ''}" tabindex="0" data-diagnostic-job data-job-id="${escapeHtml(jobId)}" data-job-label="${escapeHtml(displayLabel)}" data-open-state="${escapeHtml(displayState)}" data-job-hash="#/job/${escapeHtml(encodeURIComponent(jobId))}" onclick="loadJob('${escapeHtml(jsJobId)}', true, { source: 'job-card' })" onkeydown="handleJobCardKeydown(event,'${escapeHtml(jsJobId)}')">
        <div class="diagnostic-job-main">
          <div class="diagnostic-job-top"><strong>${escapeHtml(displayLabel)}</strong><span class="job-status-pill">${escapeHtml(statusText)}</span></div>
          <code class="diagnostic-job-id">${escapeHtml(jobId)}</code>
          <div class="diagnostic-job-line">
            <span>stage <b>${escapeHtml(stageText)}</b></span>
            <span>updated <b>${escapeHtml(updatedText)}</b></span>
            <span>${escapeHtml(fileText)}</span>
            <span>${escapeHtml(String(rerunCount))} rerun${rerunCount === 1 ? '' : 's'}</span>
          </div>
        </div>
        <div class="job-card-actions" aria-label="Job actions">
          <button type="button" data-log-open onclick="openJobLogs(event,'${escapeHtml(jsJobId)}')">Logs</button>
          <button type="button" data-rerun-open ${rerunAttrs}>Rerun</button>
          <button class="job-delete" type="button" aria-label="Delete job ${escapeHtml(jobId)}" onclick="deleteJob(event,'${escapeHtml(jsJobId)}')">X</button>
        </div>
      </article>
      ${rerunOpen ? renderDiagnosticRerunRail(jobId, job || jobHistoryById.get(jobId), displayLabel) : ''}
      </div>`;
  }).join('');
  updateDiagnosticRerunSubmit();
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
    loadJob(jobId, true, { source: 'job-card-keyboard' });
  }
}

async function openJobLogs(event, jobId) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  if (!canUseAdminSurfaces()) return;
  const id = String(jobId || '');
  if (!id) return;
  openOpsPanel({ tab: 'qa', focusPanel: true, returnFocus: event?.currentTarget || document.activeElement });
  renderQaDrawer(jobHistoryById.get(id) || { id, status: 'pending', stage: 'loading', name: id }, activeResultFiles);
  await loadJob(id, true, { source: 'job-logs', deferResultsShell: true });
  openOpsPanel({ tab: 'qa', focusPanel: false, returnFocus: event?.currentTarget || document.activeElement });
}

function markActiveJobCard(jobId) {
  document.querySelectorAll('.job-card, .diagnostic-job-card[data-job-id]').forEach(card => {
    const active = card.dataset.jobId === jobId;
    card.classList.toggle('active-job', active);
    card.classList.toggle('is-selected', active);
  });
}

function moveWorkflowProgressIntoResults(loaded = true) {
  const live = document.querySelector('.weavemap-live');
  const spine = document.getElementById('weavemap');
  const host = document.getElementById('results-workflow-host');
  if (!spine) return;
  const placement = loaded ? 'results' : 'idle';
  const previousPlacement = spine.dataset.progressPlacement || '';
  let moved = false;
  if (loaded && host && spine.parentElement !== host) {
    host.appendChild(spine);
    moved = true;
  }
  if (live && live.parentElement !== spine) spine.appendChild(live);
  spine.dataset.progressPlacement = placement;
  spine.classList.remove('spine-live-detached', 'spine-field');
  spine.classList.toggle('results-workflow-spine', !!loaded);
  spine.classList.toggle('hidden', !loaded);
  const modeChanged = previousPlacement !== placement;
  if (moved || modeChanged) {
    const helix = document.getElementById('weavemap-helix');
    if (helix) delete helix.dataset.rendered;
  }
  if (loaded) renderWeaveHelix(activeJobMeta);
}

function setResultsLoaded(loaded) {
  moveWorkflowProgressIntoResults(loaded);
  const showIdleWorkflowStation = !loaded && document.body.dataset.workflowState === 'idle';
  const showWorkflowStation = loaded || showIdleWorkflowStation;
  if (!loaded) {
    resultDashboardOpen = false;
    activeResultArtifacts = null;
    setResultFocusMode('overview');
    document.body.dataset.resultsDashboard = 'closed';
  }
  document.getElementById('results-empty-state')?.classList.toggle('hidden', loaded || showIdleWorkflowStation);
  document.getElementById('workflow-progress-panel')?.classList.toggle('hidden', !showWorkflowStation);
  document.querySelectorAll('.results-loaded-only').forEach(el => el.classList.toggle('hidden', !loaded));
  if (loaded) updateResultDashboardVisibility(activeJobMeta?.status || '');
  else document.querySelectorAll('.result-dashboard-surface').forEach(el => el.classList.add('hidden'));
  updateArchiveButton();
}

function showEmptyResults() {
  activeStageState = null;
  activeSavedAnalysisContext = null;
  document.body.dataset.workflowState = 'idle';
  document.body.dataset.jobState = 'idle';
  syncClusterweaveGameHost({ lifecycle: 'idle', job: null });
  document.body.dataset.existingRunLoaded = 'false';
  lastSubmittedRun = null;
  activeResultCategory = 'figures';
  activeResultFiles = [];
  activeResultPackageFileCount = 0;
  activeResultArtifacts = null;
  activePublicRunId = '';
  activeResultArtifactByKey = new Map();
  activeResultArtifactById = new Map();
  setResultFocusMode('overview');
  document.body.dataset.resultsDashboard = 'closed';
  document.body.dataset.managementView = 'closed';
  dismissSubmissionConfirmation();
  clearRunSetupAccessPanel();
  resetWeaveActivity();
  resetStages(currentStageControlJob());
  setResultsLoaded(false);
  renderJobRuntime(null);
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
  renderQaDrawer(null, []);
  applyAnalysisCapabilityVisibility();
}

function showResultsShell() {
  document.getElementById('results-card')?.classList.remove('hidden');
  setResultsLoaded(true);
  navigateToSection(null, 'outputs', 'results-card');
}

function lockSubmittedIntake() {
  const card = document.getElementById('upload-card');
  document.body.dataset.workflowState = 'launched';
  document.body.dataset.jobState = 'running';
  syncClusterweaveGameHost({ lifecycle: 'pending', job: null });
  document.body.dataset.managementView = 'closed';
  if (card) card.classList.add('upload-card-locked');
  setCardCollapsed('upload-card', false);
  setRunSetupAccessCollapsed(false);
}

function publicStageTimingEvent(event) {
  const marker = normalizePublicWeaveEvent(event);
  if (!marker) return null;
  const markerMeta = /^canonical workflow stage$/i.test(marker.meta || '');
  const markerTitle = /^(preparing input workspace|running annotation and bgc detection|running big[-\s]?scape family graph|building summary tables|staging synteny panels|rendering summary figures|running optional nplinker follow-up)$/i.test(marker.title || '');
  if (!markerMeta && !markerTitle) return null;
  return marker;
}

function applyStageTimingFromPublicEvents(job) {
  if (!activeStageState || !Array.isArray(job?.public_events)) return;
  if (Number(job?.rerun_count || 0) > 0) return;
  job.public_events.forEach((event) => {
    const marker = publicStageTimingEvent(event);
    if (!marker) return;
    const eventId = `public:${marker.stage}:${marker.time || marker.meta}:${marker.title}`;
    const eventTimeMs = stageTimestampFromClock(marker.time || marker.meta, job, activeStageState.lastEventMs);
    advanceToStage(marker.stage, { eventTimeMs, source: 'event', eventId });
  });
}

function stageSnapshotTimeMs(job) {
  return parseTimestampMs(job?.stage_updated_at || job?.started_at || job?.created_at || job?.updated_at) || Date.now();
}

function shouldApplyJobStageSnapshot(key) {
  if (!activeStageState || !key) return false;
  const current = activeStageState.failed || activeStageState.current || '';
  if (!current || current === key) return true;
  const currentIdx = stageIndex(current);
  const snapshotIdx = stageIndex(key);
  return currentIdx < 0 || snapshotIdx < 0 || snapshotIdx >= currentIdx;
}

function applyJobStageSnapshot(job) {
  if (!activeStageState) initializeStageState(job);
  applyStageTimingFromPublicEvents(job);
  const key = jobCurrentStageKey(job);
  const status = String((job && job.status) || '').toLowerCase();
  if (key && shouldApplyJobStageSnapshot(key)) {
    const snapshotMs = stageSnapshotTimeMs(job);
    const eventId = `snapshot:${job?.id || ''}:${job?.rerun_count || 0}:${status}:${key}:${snapshotMs}`;
    advanceToStage(key, { eventTimeMs: snapshotMs, source: 'snapshot', eventId });
  }
  if (status === 'success' || status === 'failed') finalizeStageState(status);
}

async function deleteJob(event, jobId) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  if (!canUseAdminSurfaces()) return;
  const id = String(jobId || '');
  if (!id) return;
  if (!confirm(`Delete job ${id} and all its data?`)) return;
  const resp = await apiFetch(`api/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' }, { kind: 'admin' });
  if (!resp.ok) {
    alert(`Could not delete job ${id}.`);
    return;
  }
  pendingReadTokens.delete(id);
  jobHistoryById.delete(id);
  lastJobHistoryRenderKey = '';
  if (activeJobId === id) {
    activeJobId = null;
    stopPolling();
    activeStageState = null;
    showEmptyResults();
    renderQaDrawer(null, []);
    syncOpsTabs();
  }
  refreshJobHistory();
  pollSystemStatus();
}

// ── Load / watch a job ─────────────────────────────────────────────────────
async function loadJob(jobId, autoScroll = false, options = {}) {
  if (options.readToken) pendingReadTokens.set(String(jobId), options.readToken);
  const publicResult = options.publicResult === true
    || publicResultRunIds.has(String(jobId))
    || !/^[0-9a-f]{8}$/i.test(String(jobId || ''));
  if (publicResult) publicResultRunIds.add(String(jobId));
  activePublicRunId = publicResult ? String(jobId) : '';
  const deferResultsShell = !!options.deferResultsShell;
  const seq = ++jobLoadSeq;
  hydratePublicResultActivity.lastSignature = '';
  hydratePublicResultActivity.inFlightSignature = '';
  clusterweaveGameEpoch += 1;
  syncClusterweaveGameHost({ lifecycle: 'loading', job: null });
  activeJobId = jobId;
  resetGenomeProgressSnapshot(jobId);
  const loadingContext = options.analysisScope
    ? { scope: options.analysisScope, taxonCounts: options.taxonCounts || {} }
    : jobHistoryById.get(String(jobId || ''));
  setActiveSavedAnalysisContext(loadingContext || { scope: 'fungi', taxonCounts: {} });
  renderRunStack();
  if (rerunScopeOpenJobId && rerunScopeOpenJobId !== String(jobId) && options.source !== 'job-rerun') rerunScopeOpenJobId = '';
  logCursor   = 0;
  logWindowStart = 0;
  logTotal = 0;
  logGeneration = '';
  logHydratedJobId = '';
  stopPolling();
  markActiveJobCard(jobId);
  if (lastSubmittedRun && lastSubmittedRun.jobId !== jobId) dismissSubmissionConfirmation();

  const preferResultsDashboard = shouldPreserveResultsDashboardForJobLoad(jobId, options);
  gsapMotion.lastJobLoadSource = String(options.source || '');
  syncOpsTabs();
  activeJobMeta = null;
  activeStageState = null;
  resultDashboardOpen = preferResultsDashboard;
  activeResultCategory = 'figures';
  activeResultFiles = [];
  activeResultPackageFileCount = 0;
  activeResultArtifacts = null;
  activeResultArtifactByKey = new Map();
  activeResultArtifactById = new Map();
  setResultFocusMode('overview');
  document.body.dataset.resultsDashboard = preferResultsDashboard ? 'open' : 'closed';
  if (preferResultsDashboard) {
    document.body.dataset.managementView = 'closed';
    setResultsPanelCollapsed(true);
  }
  if (!deferResultsShell) {
    showResultsShell();
    if (options.source === 'submit') animateLaunchTransition();
  }
  document.getElementById('rerun-panel').innerHTML = '';
  document.getElementById('log-terminal').innerHTML = '';
  setDrawerText('log-count', '0 lines');
  renderQaDrawer({ id: jobId, status: 'pending', stage: 'queued', name: jobId }, []);
  resetWeaveActivity();
  resetStages();
  if (canUseAdminSurfaces() && currentUIMode === 'guided') setUIMode('lab', { preserveDisclosure: true });

  const job = await pollJobFinal(jobId, autoScroll, seq, JOB_INITIAL_LOAD_TIMEOUT_MS);
  if (!job || seq !== jobLoadSeq || jobId !== activeJobId) {
    if (seq === jobLoadSeq) {
      activeJobId = null;
      activeJobMeta = null;
      activeStageState = null;
      pendingReadTokens.delete(String(jobId));
      showEmptyResults();
      renderQaDrawer(null, []);
    }
    return null;
  }
  if (job.status === 'running' || job.status === 'pending') {
    scheduleJobPoll(jobId, autoScroll, seq, jobPollDelay(job));
  }
  return job;
}

async function pollJobFinal(
  jobId,
  autoScroll = false,
  seq = jobLoadSeq,
  timeoutMs = JOB_POLL_TIMEOUT_MS,
) {
  const abortController = typeof AbortController === 'function' ? new AbortController() : null;
  const timeoutId = abortController ? setTimeout(() => abortController.abort(), timeoutMs) : null;
  let resp;
  try {
    resp = await apiFetch(
      publicResultRunIds.has(String(jobId))
        ? `api/results/${encodeURIComponent(jobId)}`
        : `api/jobs/${encodeURIComponent(jobId)}?compact=1`,
      abortController ? { signal: abortController.signal } : {},
      { kind: 'job', jobId },
    );
  } catch (error) {
    if (seq === jobLoadSeq && jobId === activeJobId) {
      window.ClusterWeaveGame?.setConnectionState?.('reconnecting');
      syncClusterweaveGameHost({ lifecycle: 'pending', job: null });
    }
    return TRANSIENT_JOB_POLL;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
  if ((resp.status === 429 || resp.status >= 500) && seq === jobLoadSeq && jobId === activeJobId) {
    window.ClusterWeaveGame?.setConnectionState?.('reconnecting');
    syncClusterweaveGameHost({ lifecycle: 'pending', job: null });
    return TRANSIENT_JOB_POLL;
  }
  if (!resp.ok || seq !== jobLoadSeq || jobId !== activeJobId) return null;
  window.ClusterWeaveGame?.setConnectionState?.('connected');
  const job = await resp.json();
  if (seq !== jobLoadSeq || jobId !== activeJobId) return null;
  const previousJob = activeJobMeta;
  if (!Array.isArray(job.public_events) && Array.isArray(previousJob?.public_events)) {
    job.public_events = previousJob.public_events;
  }
  if (!Array.isArray(job.genome_progress) && Array.isArray(previousJob?.genome_progress)) {
    job.genome_progress = previousJob.genome_progress;
  }
  activeJobMeta = job;
  const publicRunId = adoptPublicRunIdentity(jobId, job);
  setActiveSavedAnalysisContext(job);
  renderRunStack();
  renderQaDrawer(job, activeResultFiles);
  if (!canUseAdminSurfaces()) renderPublicQaLog(job);
  setWorkflowExperienceState(job);
  rememberOpenedRun(publicRunId, readTokenForJob(publicRunId) || readTokenForJob(jobId), job);
  recordWeaveActivity(job);
  if (!activeStageState || activeStageState.jobId !== jobId) initializeStageState(job);
  applyJobStageSnapshot(job);
  const operationalStatus = String(job.status || '').trim().toLowerCase();
  if (!canUseAdminSurfaces() || operationalStatus === 'running' || operationalStatus === 'pending') {
    void hydratePublicResultActivity(jobId, seq);
  }
  if (canUseAdminSurfaces()) {
    await syncActiveAdminLogs(autoScroll);
    if (seq !== jobLoadSeq || jobId !== activeJobId) return null;
  }
  updateProgressBadge(job.status);
  if (job.status !== 'running' && job.status !== 'pending') stopPolling();
  if (!previousJob || previousJob.status !== job.status || previousJob.stage !== job.stage) {
    await loadResults(jobId, job.status, seq, job);
  }
  if (previousJob && (previousJob.status !== job.status || previousJob.stage !== job.stage)) {
    if (canUseAdminSurfaces()) refreshJobHistory();
  }
  return job;
}

function jobPollDelay(job) {
  if (job === TRANSIENT_JOB_POLL) return JOB_POLL_RETRY_DELAY_MS;
  const logCount = Math.max(0, Number(job?.log_count) || 0);
  return logCount >= JOB_POLL_LONG_LOG_THRESHOLD ? JOB_POLL_LONG_LOG_DELAY_MS : JOB_POLL_BASE_DELAY_MS;
}

function scheduleJobPoll(jobId, autoScroll = false, seq = jobLoadSeq, delay = JOB_POLL_BASE_DELAY_MS) {
  stopPolling();
  pollTimerId = setTimeout(async () => {
    pollTimerId = null;
    if (seq !== jobLoadSeq || jobId !== activeJobId) return;
    let job;
    try {
      job = await pollJobFinal(jobId, autoScroll, seq);
    } catch (error) {
      job = TRANSIENT_JOB_POLL;
      window.ClusterWeaveGame?.setConnectionState?.('reconnecting');
    }
    if (seq !== jobLoadSeq || jobId !== activeJobId || !job) return;
    if (job === TRANSIENT_JOB_POLL || job.status === 'running' || job.status === 'pending') {
      scheduleJobPoll(
        jobId,
        autoScroll,
        seq,
        jobPollDelay(job),
      );
    }
  }, Math.max(250, Number(delay) || JOB_POLL_BASE_DELAY_MS));
}

function stopPolling() {
  if (pollTimerId) {
    clearTimeout(pollTimerId);
    pollTimerId = null;
  }
}

// ── Log rendering ──────────────────────────────────────────────────────────
function publicQaEventLine(event) {
  const marker = normalizePublicWeaveEvent(event);
  if (!marker) return '';
  const stage = String(marker.stage || 'prep').replace(/_/g, ' ').toUpperCase();
  const title = compactActivityChipText(marker.title || marker.status || 'Run update', 72);
  const meta = compactActivityChipText(marker.meta || marker.time || '', 48);
  return `[${stage}] ${title}${meta ? ` - ${meta}` : ''}`;
}

function renderPublicQaLog(job) {
  const term = document.getElementById('log-terminal');
  if (!term || canUseAdminSurfaces()) return;
  const lines = Array.isArray(job?.public_events)
    ? job.public_events.map(publicQaEventLine).filter(Boolean)
    : [];
  if (!lines.length && job) {
    const fallback = job.error_summary || job.error || queueStatusLabel(job) || jobStageDisplay(job);
    if (fallback) lines.push(`[${statusLabel(job.status).toUpperCase()}] ${fallback}`);
  }
  term.innerHTML = lines.map(line => `<div class="log-line public-event${/failed|error|stopped/i.test(line) ? ' err' : ''}">${escapeHtml(line)}</div>`).join('');
  const count = lines.length;
  setDrawerText('log-count', `${count.toLocaleString()} public ${count === 1 ? 'event' : 'events'}`);
}
async function hydratePublicResultActivity(jobId, seq = jobLoadSeq) {
  const runId = publicRunIdForJob(jobId);
  const signature = `${runId}:${Number(activeJobMeta?.log_count || 0)}:${String(activeJobMeta?.status || '')}:${String(activeJobMeta?.stage || '')}`;
  const requestSignature = `${seq}:${signature}`;
  if (!runId
      || hydratePublicResultActivity.lastSignature === signature
      || hydratePublicResultActivity.inFlightSignature === requestSignature) return;
  hydratePublicResultActivity.inFlightSignature = requestSignature;
  try {
    const resp = await apiFetch(
      `api/results/${encodeURIComponent(runId)}/activity`,
      { cache: 'no-store' },
      { kind: 'job', jobId: runId },
    );
    if (!resp.ok) return;
    const payload = await resp.json();
    if (seq !== jobLoadSeq || jobId !== activeJobId || runId !== publicRunIdForJob(jobId)) return;
    hydratePublicResultActivity.lastSignature = signature;
    const publicEvents = Array.isArray(payload.public_events) ? payload.public_events : [];
    const genomeProgress = Array.isArray(payload.genome_progress) ? payload.genome_progress : [];
    activeJobMeta = {
      ...(activeJobMeta || {}),
      public_events: publicEvents,
      genome_progress: genomeProgress,
    };
    renderPublicQaLog(activeJobMeta);
    renderQaDrawer(activeJobMeta, activeResultFiles);
    recordWeaveActivity(activeJobMeta);
    if (!activeStageState || activeStageState.jobId !== jobId) initializeStageState(activeJobMeta);
    applyJobStageSnapshot(activeJobMeta);
  } catch (error) {
  } finally {
    if (hydratePublicResultActivity.inFlightSignature === requestSignature) {
      hydratePublicResultActivity.inFlightSignature = '';
    }
  }
}

function createLogLineElement(text) {
  const div = document.createElement('div');
  div.className = 'log-line';
  if (/error|fatal|failed/i.test(text)) div.classList.add('err');
  else if (/warn/i.test(text)) div.classList.add('warn');
  else if (/=== stage:/i.test(text)) div.classList.add('stage');
  else if (/success|complete|finished/i.test(text)) div.classList.add('ok');
  div.textContent = text;
  return div;
}

function appendLogLine(text) {
  const term = document.getElementById('log-terminal');
  if (term) term.appendChild(createLogLineElement(text));
}

function updateAdminLogControls() {
  const button = document.getElementById('load-earlier-logs');
  const hydrated = canUseAdminSurfaces() && logHydratedJobId === activeJobId;
  if (button) {
    button.hidden = !hydrated || logWindowStart <= 0;
    button.disabled = !!logHydrationInFlight;
  }
  if (!hydrated) return;
  const visible = Math.max(0, logCursor - logWindowStart);
  setDrawerText('log-count', `${Number(logTotal).toLocaleString()} total lines`);
  setDrawerText(
    'qa-log-count-card',
    `Showing ${Number(visible).toLocaleString()} of ${Number(logTotal).toLocaleString()} lines`,
  );
}

async function hydrateQaLogs({ tail = true, before = null, autoScroll = false } = {}) {
  if (!canUseAdminSurfaces() || !activeJobId || activeOpsTab !== 'qa') return;
  if (logHydrationInFlight) return logHydrationInFlight;
  const jobId = String(activeJobId);
  const seq = jobLoadSeq;
  const previousGeneration = logGeneration;
  const query = before === null
    ? `tail=${QA_LOG_PAGE_SIZE}`
    : `before=${Math.max(0, Number(before) || 0)}&limit=${QA_LOG_PAGE_SIZE}`;
  const request = (async () => {
    const resp = await apiFetch(
      `api/jobs/${encodeURIComponent(jobId)}/logs?${query}`,
      {},
      { kind: 'admin' },
    );
    if (!resp.ok || seq !== jobLoadSeq || jobId !== activeJobId) return;
    const page = await resp.json();
    if (seq !== jobLoadSeq || jobId !== activeJobId) return;
    const generation = String(page.generation || '');
    const prepend = before !== null && previousGeneration && generation === previousGeneration;
    const term = document.getElementById('log-terminal');
    if (!term) return;
    const previousHeight = term.scrollHeight;
    const fragment = document.createDocumentFragment();
    (page.lines || []).forEach(line => {
      fragment.appendChild(createLogLineElement(line));
      if (!prepend) updateStageBar(line);
    });
    if (prepend) term.prepend(fragment);
    else {
      term.innerHTML = '';
      term.appendChild(fragment);
    }
    logWindowStart = Math.max(0, Number(page.start) || 0);
    const pageEnd = Math.max(0, Number(page.end) || 0);
    logCursor = prepend ? Math.max(logCursor, pageEnd) : pageEnd;
    logTotal = Math.max(logCursor, Number(page.total) || 0);
    logGeneration = generation;
    logHydratedJobId = jobId;
    if (prepend) term.scrollTop += term.scrollHeight - previousHeight;
    else if (autoScroll) scrollToBottom();
    renderQaDrawer(activeJobMeta, activeResultFiles);
    updateAdminLogControls();
  })();
  logHydrationInFlight = request;
  updateAdminLogControls();
  try {
    await request;
  } finally {
    if (logHydrationInFlight === request) logHydrationInFlight = null;
    updateAdminLogControls();
  }
}

async function loadEarlierLogs() {
  if (logWindowStart <= 0) return;
  await hydrateQaLogs({ tail: false, before: logWindowStart, autoScroll: false });
}

async function syncActiveAdminLogs(autoScroll = false) {
  if (!canUseAdminSurfaces() || activeOpsTab !== 'qa' || !activeJobId) return;
  if (logHydratedJobId !== activeJobId) {
    await hydrateQaLogs({ tail: true, autoScroll: true });
    return;
  }
  const jobId = String(activeJobId);
  const resp = await apiFetch(
    `api/jobs/${encodeURIComponent(jobId)}/logs?since=${encodeURIComponent(logCursor)}`,
    {},
    { kind: 'admin' },
  );
  if (!resp.ok || jobId !== activeJobId) return;
  const page = await resp.json();
  if (logGeneration && page.generation && page.generation !== logGeneration) {
    logHydratedJobId = '';
    logGeneration = '';
    await hydrateQaLogs({ tail: true, autoScroll: true });
    return;
  }
  for (const line of (page.lines || [])) {
    appendLogLine(line);
    updateStageBar(line);
  }
  logCursor = Math.max(0, Number(page.total) || logCursor);
  logTotal = logCursor;
  if (page.generation) logGeneration = page.generation;
  if (autoScroll && (page.lines || []).length) scrollToBottom();
  renderQaDrawer(activeJobMeta, activeResultFiles);
  updateAdminLogControls();
}

function clearLog() {
  const term = document.getElementById('log-terminal');
  if (term) term.innerHTML = '';
  logCursor = 0;
  logWindowStart = 0;
  logTotal = 0;
  logGeneration = '';
  logHydratedJobId = '';
  setDrawerText('log-count', '0 lines');
  updateAdminLogControls();
  renderQaDrawer(activeJobMeta, activeResultFiles);
}

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
function jobHasExplicitStageSettings(job) {
  const settings = jobStageSettings(job);
  return [
    'run_annotation', 'run_bigscape', 'run_summary', 'run_crosswalk',
    'run_clinker', 'run_figures', 'run_nplinker',
  ].some(key => settings[key] !== undefined && settings[key] !== null && settings[key] !== '');
}

function jobStageSettings(job) {
  if (job?.rerun_stage_settings && typeof job.rerun_stage_settings === 'object') {
    return job.rerun_stage_settings;
  }
  if (job?.submission_settings && typeof job.submission_settings === 'object') {
    return job.submission_settings;
  }
  return (job && job.settings) || {};
}

function resultOrEventIndicatesStage(job, key, files = activeResultFiles) {
  if (key === 'prep') return true;
  const eventStages = new Set((Array.isArray(job?.public_events) ? job.public_events : [])
    .map(normalizePublicWeaveEvent)
    .filter(Boolean)
    .map(event => event.stage)
    .filter(Boolean));
  if (eventStages.has(key)) return true;
  const normalizedFiles = (files || []).map(path => normalizedResultPath(path)).filter(Boolean);
  const hasFile = (pattern) => normalizedFiles.some(path => pattern.test(path));
  if (key === 'annotation') return hasFile(/(^|\/)(antismash|funbgcex)(\/|$)/i);
  if (key === 'bigscape') return hasFile(/(^|\/)(bigscape|big-scape)(\/|$)/i);
  if (key === 'summary') return hasFile(/(^|\/)(summary_tables|summaries|atlas|shared_family|crosswalk)(\/|$)/i);
  if (key === 'clinker') return hasFile(/(^|\/)(clinker|synteny)(\/|$)/i);
  if (key === 'figures') return hasFile(/(^|\/)(figures|visuals)(\/|$)/i) || normalizedFiles.some(path => /\.(svg|png|jpe?g|webp)$/i.test(path) && /(^|\/)(figures|plots|summary)(\/|$)/i.test(path));
  if (key === 'nplinker') return hasFile(/(^|\/)nplinker(\/|$)/i);
  return false;
}

function inferredSuccessfulStageSet(job, files = activeResultFiles) {
  const enabled = new Set(['prep']);
  STAGES.forEach((stage) => {
    if (stage.key !== 'prep' && resultOrEventIndicatesStage(job, stage.key, files)) enabled.add(stage.key);
  });
  if (enabled.has('summary')) enabled.add('bigscape');
  if (enabled.has('figures')) enabled.add('summary');
  return enabled;
}

function syncInferredStageState(job = activeJobMeta) {
  if (!activeStageState || !job || activeStageState.jobId !== job.id) return;
  if (jobHasExplicitStageSettings(job)) return;
  if (String(job.status || '').toLowerCase() !== 'success') return;
  const next = inferredSuccessfulStageSet(job, activeResultFiles);
  const same = next.size === activeStageState.enabled.size && Array.from(next).every(key => activeStageState.enabled.has(key));
  if (same) return;
  activeStageState.enabled = next;
  activeStageState.completed = new Set(Array.from(activeStageState.completed).filter(key => next.has(key)));
  next.forEach(key => activeStageState.completed.add(key));
  activeStageState.current = null;
  activeStageState.failed = null;
}

function jobStageEnabled(job, key) {
  const settings = jobStageSettings(job);
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
    startedAtSource: {},
    endedAtSource: {},
    appliedEvents: new Set(),
    lastEventMs: null,
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
  const raw = typeof value === 'string' ? value.trim() : value;
  const normalized = typeof raw === 'string'
    && /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(raw)
    ? `${raw.replace(' ', 'T')}Z`
    : raw;
  const ms = new Date(normalized).getTime();
  return Number.isNaN(ms) ? null : ms;
}

function stageClockSeconds(value) {
  const match = String(value || '').match(/^(\d{2}):(\d{2}):(\d{2})$/);
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  const seconds = Number(match[3]);
  if (hours > 23 || minutes > 59 || seconds > 59) return null;
  return (hours * 3600) + (minutes * 60) + seconds;
}

function stageTimingBaseMs(job = activeJobMeta) {
  return parseTimestampMs(job?.started_at || job?.created_at || job?.updated_at);
}

function stageTimestampFromClock(value, job = activeJobMeta, minMs = null) {
  const clockSeconds = stageClockSeconds(value);
  if (clockSeconds === null) return null;
  const baseMs = stageTimingBaseMs(job);
  if (!baseMs) return null;
  const dayStart = new Date(baseMs);
  dayStart.setHours(0, 0, 0, 0);
  let eventMs = dayStart.getTime() + (clockSeconds * 1000);
  const createdMs = parseTimestampMs(job?.created_at || job?.started_at);
  const lowerBound = Number.isFinite(minMs) ? minMs : createdMs;
  while (createdMs && eventMs < createdMs - 60000) eventMs += 86400000;
  while (Number.isFinite(lowerBound) && eventMs < lowerBound) eventMs += 86400000;
  return eventMs;
}

function stageTimestampFromLogLine(line, job = activeJobMeta) {
  const match = String(line || '').match(/^\[(\d{2}:\d{2}:\d{2})\]/);
  return match ? stageTimestampFromClock(match[1], job, activeStageState?.lastEventMs) : null;
}

function stageTimingSourceRank(source) {
  const ranks = {
    snapshot: 1,
    terminal: 2,
    event: 3,
    log: 3,
  };
  return ranks[source] || 0;
}

function setStageStartTime(key, ms, source = 'snapshot', options = {}) {
  if (!activeStageState || !Number.isFinite(ms)) return false;
  const current = activeStageState.startedAt[key];
  const currentSource = activeStageState.startedAtSource[key] || '';
  const force = !!options.force;
  const sourceRank = stageTimingSourceRank(source);
  const currentRank = stageTimingSourceRank(currentSource);
  const betterSource = sourceRank > currentRank;
  const sameSourceEarlier = sourceRank === currentRank && ms < current;
  if (force || !Number.isFinite(current) || betterSource || sameSourceEarlier) {
    activeStageState.startedAt[key] = ms;
    activeStageState.startedAtSource[key] = source;
    return true;
  }
  return false;
}

function setStageEndTime(key, ms, source = 'snapshot', options = {}) {
  if (!activeStageState || !Number.isFinite(ms)) return false;
  const start = activeStageState.startedAt[key];
  const normalized = Number.isFinite(start) ? Math.max(ms, start) : ms;
  const current = activeStageState.endedAt[key];
  const currentSource = activeStageState.endedAtSource[key] || '';
  const force = !!options.force;
  const betterSource = stageTimingSourceRank(source) > stageTimingSourceRank(currentSource);
  if (force || !Number.isFinite(current) || (betterSource && normalized !== current)) {
    activeStageState.endedAt[key] = normalized;
    activeStageState.endedAtSource[key] = source;
    return true;
  }
  return false;
}

function clearStageTimingFrom(key) {
  if (!activeStageState) return;
  const startIdx = stageIndex(key);
  if (startIdx < 0) return;
  for (let i = startIdx; i < STAGES.length; i++) {
    const stageKey = STAGES[i].key;
    activeStageState.completed.delete(stageKey);
    delete activeStageState.startedAt[stageKey];
    delete activeStageState.endedAt[stageKey];
    delete activeStageState.startedAtSource[stageKey];
    delete activeStageState.endedAtSource[stageKey];
  }
}

function stageTransitionTimeMs(options = {}) {
  if (Number.isFinite(options.eventTimeMs)) return options.eventTimeMs;
  if (Number.isFinite(options.timeMs)) return options.timeMs;
  if (options.line) {
    const lineMs = stageTimestampFromLogLine(options.line, activeJobMeta);
    if (Number.isFinite(lineMs)) return lineMs;
  }
  return Date.now();
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

function jobRuntimeBounds(job = activeJobMeta) {
  const start = parseTimestampMs(job?.started_at || job?.created_at);
  if (start === null) return null;
  const status = String(job?.status || '').trim().toLowerCase();
  const active = status === 'running' || status === 'pending';
  const terminal = parseTimestampMs(
    job?.completed_at || job?.failed_at || job?.finished_at || job?.updated_at,
  );
  const end = active ? Date.now() : (terminal ?? Date.now());
  return { start, end: Math.max(start, end), active };
}

function formatJobRuntimeClock(milliseconds) {
  const total = Math.max(0, Math.floor((Number(milliseconds) || 0) / 1000));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return `(${String(days).padStart(2, '0')}:${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')})`;
}

function renderJobRuntime(job = activeJobMeta) {
  const timer = document.getElementById('results-job-runtime');
  if (!timer) return;
  const bounds = jobRuntimeBounds(job);
  if (!bounds) {
    timer.hidden = true;
    timer.textContent = '';
    timer.removeAttribute('datetime');
    return;
  }
  const elapsedMs = bounds.end - bounds.start;
  const totalSeconds = Math.max(0, Math.floor(elapsedMs / 1000));
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  timer.hidden = false;
  timer.textContent = formatJobRuntimeClock(elapsedMs);
  timer.dateTime = `PT${totalSeconds}S`;
  timer.setAttribute(
    'aria-label',
    `Total job runtime: ${days} days, ${hours} hours, ${minutes} minutes, ${seconds} seconds`,
  );
  timer.title = bounds.active ? 'Total job runtime' : 'Final total job runtime';
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
  const hasStart = Number.isFinite(start);
  const hasEnd = Number.isFinite(end);
  if (visualCls === 'active') return hasStart ? formatDuration(Date.now() - start) : 'Starting';
  if ((visualCls === 'done' || visualCls === 'complete' || visualCls === 'failed') && hasStart && hasEnd) return formatDuration(end - start);
  if (visualCls === 'failed' && hasStart) return formatDuration((hasEnd ? end : Date.now()) - start);
  if (visualCls === 'done' || visualCls === 'complete') return 'Finished';
  if (visualCls === 'failed') return 'Stopped';
  if (hasStart) return 'Waiting';
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
  renderJobRuntime(job);
  const status = String((job && job.status) || '').toLowerCase();
  let state = 'idle';
  if (status === 'success') state = 'complete';
  else if (status === 'failed') state = 'failed';
  else if (status === 'running') state = 'running';
  else if (status === 'pending' || activeJobId) state = 'launched';
  document.body.dataset.workflowState = state;
  document.body.dataset.jobState = state === 'launched' ? 'running' : state;
  syncClusterweaveGameHost({ lifecycle: status === 'pending' ? 'pending' : state, job });
}

const CLUSTERWEAVE_GAME_PHASE_BY_STAGE = Object.freeze({
  prep: 'excavate',
  annotation: 'excavate',
  bigscape: 'classify',
  summary: 'classify',
  clinker: 'compare',
  figures: 'contextualize',
  nplinker: 'contextualize',
});

function clusterweaveGamePhase(job = activeJobMeta) {
  const stage = currentWorkflowStage() || jobCurrentStageKey(job) || 'prep';
  return CLUSTERWEAVE_GAME_PHASE_BY_STAGE[stage] || 'excavate';
}

function syncClusterweaveGameHost(options = {}) {
  const controller = window.ClusterWeaveGame;
  if (!controller?.setHostState) return;
  const hasJob = Object.prototype.hasOwnProperty.call(options, 'job');
  const job = hasJob ? options.job : activeJobMeta;
  let lifecycle = String(options.lifecycle || '').toLowerCase();
  if (!lifecycle) {
    const status = String(job?.status || '').toLowerCase();
    if (status === 'success' || status === 'failed' || status === 'running' || status === 'pending') lifecycle = status;
    else lifecycle = activeJobId ? 'loading' : 'idle';
  }
  if (lifecycle === 'complete') lifecycle = 'success';
  if (lifecycle === 'launched') lifecycle = 'pending';
  controller.setHostState({
    epoch: clusterweaveGameEpoch,
    lifecycle,
    phase: clusterweaveGamePhase(job),
  });
}

function setClusterweaveGameDnaSuspended(suspended) {
  clusterweaveGameDnaSuspended = !!suspended;
  document.body.dataset.clusterweaveGameAnimating = clusterweaveGameDnaSuspended ? 'true' : 'false';
  syncBgcWorkflowDnaSuspension();
}

function bgcWorkflowDnaShouldSuspend() {
  return clusterweaveGameDnaSuspended || bgcWorkflowDnaGenomeLayerSuspended;
}

function syncBgcWorkflowDnaSuspension() {
  if (!bgcWorkflowDna) return;
  if (bgcWorkflowDnaShouldSuspend()) bgcWorkflowDna.suspend?.();
  else bgcWorkflowDna.resume?.();
}

function setBgcWorkflowGenomeLayerSuspended(suspended) {
  bgcWorkflowDnaGenomeLayerSuspended = !!suspended;
  syncBgcWorkflowDnaSuspension();
}

function setBgcWorkflowAggregatePresentationSuspended(suspended) {
  const hidden = !!suspended;
  [
    document.getElementById('bgc-tool-activity-chip'),
    document.querySelector('#bgc-workflow-station > .workflow-tool-status'),
    document.querySelector('#bgc-workflow-station > .workflow-caption'),
    document.getElementById('bgc-dna-progress-region'),
  ].filter(Boolean).forEach((node) => {
    if (hidden) node.setAttribute('aria-hidden', 'true');
    else node.removeAttribute('aria-hidden');
    node.inert = hidden;
  });
  const nativeProgress = document.getElementById('bgc-workflow-native-progress');
  if (nativeProgress) nativeProgress.hidden = hidden;
}

function wireClusterweaveGameAdapter() {
  if (clusterweaveGameAdapterWired) return;
  clusterweaveGameAdapterWired = true;
  window.addEventListener('clusterweave:game-animation', (event) => {
    setClusterweaveGameDnaSuspended(Boolean(event?.detail?.active));
  });
  window.addEventListener('online', () => {
    void fetchSystemStatus({ renderRuntime: false, renderWorker: false });
  });
  window.addEventListener('clusterweave:game-workflow-focus', (event) => {
    const lifecycle = event?.detail?.lifecycle === 'success' ? 'success' : 'failed';
    const handoff = document.getElementById('clusterweave-game-handoff');
    if (handoff) {
      handoff.textContent = lifecycle === 'success'
        ? 'Results ready. Candidate Weave closed and focus moved to Result blocks.'
        : 'Workflow needs attention. Candidate Weave closed and focus moved to the workflow status.';
    }
    const target = lifecycle === 'success'
      ? document.getElementById('results-card')
      : document.getElementById('workflow-progress-panel');
    window.requestAnimationFrame(() => target?.focus?.({ preventScroll: true }));
  });
  syncClusterweaveGameHost();
}

function bgcWorkflowStages(job = activeJobMeta) {
  return workflowStageList(job).filter(stage => stage.key !== 'nplinker' || jobStageEnabled(job || {}, stage.key) || canUseAdminSurfaces());
}

function bgcStageStatus(stage, currentKey, jobStatus) {
  const key = stage.key;
  if (activeStageState && !activeStageState.enabled.has(key)) return 'skipped';
  if (jobStatus === 'success') return 'complete';
  if (activeStageState?.failed === key || (jobStatus === 'failed' && currentKey === key)) return 'error';
  if (activeStageState?.completed.has(key)) return 'complete';
  if (currentKey === key) return 'running';
  return 'pending';
}

function compactActivityChipText(value, maxLength = 96) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  return text.length > maxLength ? `${text.slice(0, Math.max(0, maxLength - 3)).trim()}...` : text;
}

function jobPublicWorkflowEvents(job, currentKey) {
  const jobEvents = Array.isArray(job?.public_events)
    ? job.public_events.map(normalizePublicWeaveEvent).filter(Boolean)
    : [];
  const events = jobEvents.length ? jobEvents : (Array.isArray(weaveActivity.events) ? weaveActivity.events : []);
  if (!currentKey) return events;
  const stageEvents = events.filter(event => event?.stage === currentKey);
  return stageEvents.length ? stageEvents : events;
}

function latestJobPublicWorkflowEvent(job, currentKey) {
  const events = jobPublicWorkflowEvents(job, currentKey);
  return events.length ? events[events.length - 1] : null;
}

function activityOrganismFromMeta(meta) {
  const parts = String(meta || '').split('/').map(part => part.trim()).filter(Boolean);
  return parts.find(part => !/^Genome\s+\d+\s+of\s+\d+$/i.test(part) && !/\bactive$/i.test(part) && !/^\d{1,2}:\d{2}/.test(part)) || '';
}

function activityElapsedFromMeta(meta) {
  const match = String(meta || '').match(/(under 1 min|\d+ min|\d+h(?: \d{2}m)?) active/i);
  return match ? match[1] : '';
}

function activityPartsFromEvent(event) {
  if (!event?.title) return null;
  const heartbeatMatch = event.title.match(/^(.+?)\s+still\s+running$/i);
  if (heartbeatMatch) {
    return {
      kind: 'heartbeat',
      tool: heartbeatMatch[1].trim(),
      organism: activityOrganismFromMeta(event.meta),
      elapsed: activityElapsedFromMeta(event.meta),
      event,
    };
  }
  const progressMatch = event.title.match(/^([^:]+):\s*(.+)$/);
  if (progressMatch) {
    return {
      kind: 'progress',
      tool: progressMatch[1].trim(),
      organism: activityOrganismFromMeta(event.meta),
      message: progressMatch[2].trim(),
      event,
    };
  }
  return null;
}

function activityPartsMatch(a, b) {
  if (!a || !b) return false;
  const toolMatch = !a.tool || !b.tool || a.tool.toLowerCase() === b.tool.toLowerCase();
  const organismMatch = !a.organism || !b.organism || a.organism === b.organism;
  return toolMatch && organismMatch;
}

function latestToolActivityParts(job, currentKey) {
  const parts = jobPublicWorkflowEvents(job, currentKey).map(activityPartsFromEvent).filter(Boolean);
  if (!parts.length) return null;
  let heartbeat = null;
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    if (parts[index].kind === 'heartbeat') {
      heartbeat = parts[index];
      break;
    }
  }
  let progress = null;
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    if (parts[index].kind === 'progress' && (!heartbeat || activityPartsMatch(parts[index], heartbeat))) {
      progress = parts[index];
      break;
    }
  }
  return progress || heartbeat ? { progress, heartbeat } : null;
}

function workflowPayloadHasSkippedStages(payload = null) {
  const steps = payload && Array.isArray(payload.steps) ? payload.steps : null;
  if (steps) return steps.some(step => step.status === 'skipped');
  return !!(activeStageState && workflowStageList(activeJobMeta).some(stage => !activeStageState.enabled.has(stage.key)));
}

function bgcActivityChipPayload(job, state, currentKey, fallbackTool) {
  if (state === 'idle') return { text: 'WAITING', title: 'Waiting for submitted inputs' };
  if (state === 'complete') return workflowPayloadHasSkippedStages()
    ? { text: 'SELECTED COMPLETE', title: 'Selected workflow tools complete; downstream stages skipped' }
    : { text: 'COMPLETE', title: 'All workflow tools complete' };
  if (state === 'failed') return { text: 'NEEDS REVIEW', title: job?.error_summary || job?.error || 'Workflow needs attention' };
  const activity = latestToolActivityParts(job, currentKey);
  if (activity) {
    const { progress, heartbeat } = activity;
    const tool = progress?.tool || heartbeat?.tool || fallbackTool || 'Workflow';
    const organism = progress?.organism || heartbeat?.organism || '';
    const message = progress?.message || 'Running';
    const elapsed = heartbeat?.elapsed || '';
    const pieces = [tool, organism, message, elapsed].filter(Boolean);
    const fullText = pieces.join(' | ');
    return {
      text: compactActivityChipText(fullText),
      title: fullText,
    };
  }
  const event = latestJobPublicWorkflowEvent(job, currentKey);
  if (event?.title) {
    return {
      text: compactActivityChipText(event.title),
      title: [event.title, event.meta].filter(Boolean).join(' - '),
    };
  }
  return {
    text: compactActivityChipText(`${fallbackTool || 'Workflow'} | running`),
    title: fallbackTool || 'Workflow running',
  };
}

function clampUnit(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(1, number));
}

// BEGIN GENOME_PROGRESS_PURE
function safeGenomeProgressText(value, fallback = 'Working', maxLength = 120) {
  let text = String(value ?? '')
    .replace(/[\u0000-\u001f\u007f]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (!text) return fallback;
  const unsafe = [
    /\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:/i,
    /\b(?:basic|bearer)\s+\S+/i,
    /(?:[?&]|\b)(?:access[_-]?token|api[_-]?key|auth[_-]?token|token|secret|password|passwd|credential|signature)\s*=\s*[^\s&]+/i,
    /\b[A-Za-z][A-Za-z0-9_-]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|CREDENTIAL)[A-Za-z0-9_-]*\s*[:=]\s*\S+/,
    /\bfile:\/\//i,
    /(?:^|[\s=:(])[A-Za-z]:[\\/](?:[^\s]+)/,
    /(?:^|[\s=:(])\/(?:[^/\s]+\/)+[^\s)]*/,
  ];
  if (unsafe.some(pattern => pattern.test(text))) return fallback;
  if (/^https?:\/\//i.test(text)) return fallback;
  text = text.replace(/[^A-Za-z0-9 ._:+/%()|'’-]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!text) return fallback;
  return text.length > maxLength ? `${text.slice(0, Math.max(1, maxLength - 3)).trim()}...` : text;
}

function safeGenomeProgressLabel(item, index) {
  const raw = item?.display_label
    ?? item?.displayLabel
    ?? item?.organism_name
    ?? item?.organism
    ?? item?.label
    ?? item?.genome_id
    ?? item?.genome
    ?? `Genome ${index + 1}`;
  const basename = String(raw ?? '').replace(/\\/g, '/').split('/').pop();
  const display = basename.replace(/_/g, ' ').trim();
  return safeGenomeProgressText(display || basename, `Genome ${index + 1}`, 72);
}

function genomeProgressPercent(item) {
  const explicitPercent = item?.percent ?? item?.progress_percent ?? item?.progressPercent;
  const raw = explicitPercent ?? item?.progress ?? 0;
  let number = Number(raw);
  if (!Number.isFinite(number)) number = 0;
  if (explicitPercent === undefined && number > 0 && number <= 1) number *= 100;
  return Math.max(0, Math.min(100, Math.round(number)));
}

function genomeProgressTaxon(value) {
  const taxon = String(value || '').trim().toLowerCase();
  if (taxon === 'fungi' || taxon === 'fungus' || taxon === 'fungal') return 'Fungi';
  if (taxon === 'bacteria' || taxon === 'bacterium' || taxon === 'bacterial') return 'Bacteria';
  return 'Genome';
}

function normalizeGenomeRegionProgress(item) {
  const source = item?.region_progress ?? item?.regionProgress;
  if (!source || typeof source !== 'object' || Array.isArray(source)) return null;
  const total = Math.max(0, Math.round(Number(source.total) || 0));
  if (!total) return null;
  const bounded = value => Math.max(0, Math.min(total, Math.round(Number(value) || 0)));
  const processed = bounded(source.processed ?? source.finished ?? source.complete);
  const failed = Math.min(processed, bounded(source.failed));
  const active = Math.min(total - processed, bounded(source.active));
  return { processed, total, active, failed };
}

function normalizeGenomeProgressItem(item, index) {
  if (!item || typeof item !== 'object') return null;
  const percent = genomeProgressPercent(item);
  const rawStatus = String(item.status ?? item.state ?? item.outcome ?? '').trim().toLowerCase().replace(/\s+/g, '_');
  const message = safeGenomeProgressText(
    item.message ?? item.detail ?? item.status_text ?? item.statusText ?? item.log,
    percent >= 100 ? 'Genome milestone finished' : 'Waiting for the next genome milestone',
  );
  const messageState = /\b(?:dropped|failed|error|unable|insufficient|needs review)\b/i.test(message)
    ? 'warning'
    : /\b(?:complete|completed|finished|not applicable|skipped)\b/i.test(message)
      ? 'complete'
      : '';
  const status = rawStatus || messageState || (percent >= 100 ? 'complete' : percent > 0 ? 'running' : 'waiting');
  const completedWithWarning = status === 'complete_with_warning';
  const warning = !completedWithWarning && (
    GENOME_PROGRESS_WARNING_STATES.has(status) || messageState === 'warning'
  );
  const terminal = item.terminal === true
    || GENOME_PROGRESS_TERMINAL_STATES.has(status)
    || (percent >= 100 && status !== 'running');
  const stage = safeGenomeProgressText(
    item.milestone ?? item.tool ?? item.stage ?? item.phase,
    terminal ? (warning ? 'Needs review' : 'Complete') : 'Queued',
    42,
  );
  const tool = safeGenomeProgressText(item.tool ?? item.milestone ?? item.stage, '', 42);
  const rawAnnotationMethod = String(
    item.annotation_method ?? item.annotationMethod ?? item.effective_prediction_method ?? '',
  ).trim().toLowerCase().replace(/-/g, '_');
  const annotationMethod = ['existing_cds', 'funannotate', 'braker3', 'prodigal'].includes(rawAnnotationMethod)
    ? rawAnnotationMethod
    : '';
  const warningTool = safeGenomeProgressText(item.warning_tool ?? item.warningTool, '', 42);
  const warningMessage = safeGenomeProgressText(
    item.warning_message ?? item.warningMessage,
    '',
    180,
  );
  const activityMessage = safeGenomeProgressText(
    item.activity_message ?? item.activityMessage ?? message,
    message,
    180,
  );
  const regionProgress = normalizeGenomeRegionProgress(item);
  const rawStageStates = item.stage_states ?? item.stageStates;
  const stageStates = {};
  if (rawStageStates && typeof rawStageStates === 'object' && !Array.isArray(rawStageStates)) {
    Object.entries(rawStageStates).forEach(([key, value]) => {
      if (!value || typeof value !== 'object') return;
      const normalizedKey = String(key || '').trim().toLowerCase().replace(/-/g, '_');
      if (!['genome_acquired', 'funannotate', 'antismash', 'funbgcex', 'complete'].includes(normalizedKey)) return;
      const normalizedStatus = String(value.status || 'queued').trim().toLowerCase();
      stageStates[normalizedKey] = {
        status: ['complete', 'running', 'failed', 'queued', 'waiting'].includes(normalizedStatus)
          ? normalizedStatus : 'queued',
        message: safeGenomeProgressText(value.message, '', 180),
      };
    });
  }
  const id = safeGenomeProgressText(item.genome_id ?? item.genome ?? item.id, `genome-${index + 1}`, 96);
  return {
    id,
    label: safeGenomeProgressLabel(item, index),
    taxon: genomeProgressTaxon(item.taxon ?? item.taxon_group ?? item.domain),
    percent,
    status,
    stage,
    tool,
    annotationMethod,
    message,
    activityMessage,
    warningTool,
    warningMessage,
    regionProgress,
    stageStates,
    updatedAt: String(item.updated_at ?? item.updatedAt ?? '').trim(),
    terminal,
    warning,
    completedWithWarning,
    hasWarning: warning || completedWithWarning || !!warningMessage,
  };
}

function resetGenomeProgressSnapshot(jobId = '', rerunCount = 0) {
  genomeProgressSnapshotKey = `${String(jobId || '')}\u001f${Math.max(0, Number(rerunCount) || 0)}`;
  genomeProgressSnapshot = new Map();
}

function genomeProgressAttemptKey(job) {
  const jobId = String(job?.id ?? job?.job_id ?? activeJobId ?? '');
  const rerunCount = Math.max(0, Number(job?.rerun_count ?? job?.rerunCount) || 0);
  return `${jobId}\u001f${rerunCount}`;
}

function genomeProgressExplicitRestart(previous, next) {
  if (!previous?.terminal || next?.percent !== 0) return false;
  const nextTime = parseTimestampMs(next.updatedAt);
  const previousTime = parseTimestampMs(previous.updatedAt);
  if (nextTime !== null && previousTime !== null && nextTime <= previousTime) return false;
  return /\b(?:starting|restarting|rerun)\b/i.test(next.message || '');
}

function genomeProgressSnapshotPrefersPrevious(previous, next) {
  if (!previous || genomeProgressExplicitRestart(previous, next)) return false;
  const previousTime = parseTimestampMs(previous.updatedAt);
  const nextTime = parseTimestampMs(next.updatedAt);
  if (previousTime !== null && nextTime !== null && nextTime < previousTime) return true;
  if (next.percent < previous.percent) return true;
  if (previous.terminal && !next.terminal) return true;
  return previousTime !== null && nextTime === null && next.percent <= previous.percent;
}

function normalizeGenomeProgressItems(job) {
  const source = Array.isArray(job?.genome_progress)
    ? job.genome_progress
    : Array.isArray(job?.genomeProgress)
      ? job.genomeProgress
      : [];
  const keyed = new Map();
  source.forEach((item, index) => {
    const normalized = normalizeGenomeProgressItem(item, index);
    if (!normalized) return;
    const key = String(normalized.id || normalized.label).toLowerCase();
    if (keyed.has(key)) keyed.delete(key);
    keyed.set(key, normalized);
  });
  const attemptKey = genomeProgressAttemptKey(job);
  if (genomeProgressSnapshotKey !== attemptKey) resetGenomeProgressSnapshot(
    job?.id ?? job?.job_id ?? activeJobId ?? '',
    job?.rerun_count ?? job?.rerunCount ?? 0,
  );
  const reconciled = new Map();
  genomeProgressSnapshot.forEach((previous, key) => {
    const next = keyed.get(key);
    reconciled.set(
      key,
      !next || genomeProgressSnapshotPrefersPrevious(previous, next) ? previous : next,
    );
  });
  keyed.forEach((next, key) => {
    if (!reconciled.has(key)) reconciled.set(key, next);
  });
  const items = Array.from(reconciled.values());
  genomeProgressSnapshot = new Map(items.map(item => [String(item.id || item.label).toLowerCase(), item]));
  return items;
}

function genomeProgressStages(item) {
  if (item.taxon === 'Bacteria') return ['Genome acquired', 'antiSMASH', 'Complete'];
  const usesFunannotate = item.annotationMethod === 'funannotate'
    || /\bfunannotate\b/i.test(`${item.stage || ''} ${item.tool || ''}`);
  return usesFunannotate
    ? ['Genome acquired', 'Funannotate', 'antiSMASH', 'FunBGCeX', 'Complete']
    : ['Genome acquired', 'antiSMASH', 'FunBGCeX', 'Complete'];
}

function genomeProgressCurrentStageIndex(item, stages) {
  if (item.terminal && !item.warning) return stages.length - 1;
  const stage = String(item.stage || '').toLowerCase();
  const tool = String(item.tool || '').toLowerCase();
  const combined = `${stage} ${tool}`;
  const acquiredIndex = 0;
  const funannotateIndex = stages.indexOf('Funannotate');
  const antismashIndex = stages.indexOf('antiSMASH');
  const funbgcexIndex = stages.indexOf('FunBGCeX');
  if (item.taxon === 'Bacteria') {
    if (/complete/.test(stage)) return stages.length - 1;
    if (/antismash|prodigal/.test(combined)) return antismashIndex;
    if (item.warning || /download|ncbi/.test(combined)) return acquiredIndex;
    if (GENOME_PROGRESS_ACTIVE_STATES.has(item.status) || item.percent > 8) return antismashIndex;
    return acquiredIndex;
  }
  if (/complete/.test(stage)) return stages.length - 1;
  if (/funbgcex/.test(combined)) return funbgcexIndex;
  if (/antismash/.test(combined)) return antismashIndex;
  if (funannotateIndex >= 0 && /annotat|funannotate|predict/.test(combined)) {
    return funannotateIndex;
  }
  return acquiredIndex;
}

function genomeProgressStageKey(label) {
  return ({
    'Genome acquired': 'genome_acquired',
    Funannotate: 'funannotate',
    antiSMASH: 'antismash',
    FunBGCeX: 'funbgcex',
    Complete: 'complete',
  })[label] || '';
}

function genomeProgressStageFraction(item, key, status) {
  if (status === 'complete') return 1;
  if (!['running', 'failed'].includes(status)) return 0;
  if (key === 'antismash' && item.regionProgress?.total) {
    return Math.max(0, Math.min(1, item.regionProgress.processed / item.regionProgress.total));
  }
  const ranges = {
    genome_acquired: [0, 8],
    funannotate: [10, 25],
    antismash: [35, 70],
    funbgcex: [80, 100],
    complete: [100, 100],
  };
  const [start, end] = ranges[key] || [0, 100];
  if (end <= start) return item.terminal ? 1 : 0;
  return Math.max(0, Math.min(1, (item.percent - start) / (end - start)));
}

function genomeProgressStageModel(item) {
  const stages = genomeProgressStages(item);
  const currentIndex = genomeProgressCurrentStageIndex(item, stages);
  return stages.map((label, index) => {
    const key = genomeProgressStageKey(label);
    const structured = item.stageStates?.[key];
    let status = 'queued';
    if (structured) {
      status = structured.status === 'failed' ? 'failed'
        : structured.status === 'running' ? 'running'
          : structured.status === 'complete' ? 'complete' : 'queued';
    } else {
      const acquiredAndQueued = item.percent > 0 && item.status === 'queued' && currentIndex === 0;
      const complete = item.terminal && !item.warning
        ? index <= currentIndex
        : index < currentIndex || (acquiredAndQueued && index === 0);
      const current = index === currentIndex && (GENOME_PROGRESS_ACTIVE_STATES.has(item.status) || item.warning);
      status = complete ? 'complete' : current ? (item.warning ? 'failed' : 'running') : 'queued';
    }
    const progress = Math.round(genomeProgressStageFraction(item, key, status) * 100);
    return {
      key,
      label,
      status,
      progress,
      stateClass: status === 'complete' ? 'is-complete'
        : status === 'running' ? 'is-active'
          : status === 'failed' ? 'is-warning' : 'is-upcoming',
      stateLabel: status === 'failed' ? 'error'
        : status === 'running' ? 'current'
          : status === 'complete' ? 'complete' : 'queued',
    };
  });
}

function renderGenomeProgressStages(item, model = genomeProgressStageModel(item)) {
  return `<ol class="genome-progress-stages" style="--genome-stage-count: ${model.length}" aria-label="${escapeHtml(`${item.label} workflow stages`)}">${model.map(stage => (
    `<li class="${stage.stateClass}" aria-label="${escapeHtml(`${stage.label}: ${stage.stateLabel}`)}"><span aria-hidden="true"></span><b>${escapeHtml(stage.label)}</b></li>`
  )).join('')}</ol>`;
}

function genomeProgressMeterModel(item, stages = genomeProgressStageModel(item)) {
  const current = stages.find(stage => stage.status === 'running' || stage.status === 'failed');
  if (current) return {
    label: current.label,
    percent: current.progress,
    text: `${current.label} ${current.progress}%`,
  };
  if (item.terminal && !item.warning) return { label: 'Complete', percent: 100, text: 'Complete 100%' };
  return { label: 'Queued', percent: 0, text: 'Queued' };
}

function genomeProgressRibbonText(item, statusMessage, stages) {
  const current = stages.find(stage => stage.status === 'running' || stage.status === 'failed');
  const region = item.regionProgress;
  const pieces = [];
  if (current?.key === 'antismash' && region?.total) {
    pieces.push(`Region (${region.processed}/${region.total})`);
    if (region.active) pieces.push(`${region.active} active`);
  }
  const activity = safeGenomeProgressText(statusMessage, '', 180);
  if (activity && !pieces.some(piece => piece === activity)) pieces.push(activity);
  return pieces.join(' · ') || 'Waiting for the next genome milestone';
}

function renderGenomeProgressMeter(item, statusMessage, stages) {
  const meter = genomeProgressMeterModel(item, stages);
  const ribbonText = genomeProgressRibbonText(item, statusMessage, stages);
  const valueText = `${ribbonText} · overall milestone ${item.percent}%`;
  return `
    <div class="genome-progress-meter-row">
      <div class="genome-progress-track" role="progressbar" aria-label="${escapeHtml(`${item.label} current stage progress`)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${meter.percent}" aria-valuetext="${escapeHtml(valueText)}" style="--genome-stage-count: ${stages.length}">
        ${stages.map(stage => {
          const liveRegionClass = stage.key === 'antismash'
            && stage.status === 'running'
            && item.regionProgress?.active ? ' has-live-region-work' : '';
          return `<span class="genome-progress-segment ${stage.stateClass}${liveRegionClass}" title="${escapeHtml(`${stage.label}: ${stage.progress}%`)}"><span class="genome-progress-segment-fill" style="--genome-stage-progress: ${stage.progress}%"></span></span>`;
        }).join('')}
      </div>
    </div>`;
}

function renderGenomeProgressCard(item) {
  const active = GENOME_PROGRESS_ACTIVE_STATES.has(item.status);
  const stateClass = item.warning ? 'is-warning' : item.terminal ? 'is-complete' : active ? 'is-running' : 'is-waiting';
  const advisoryClass = item.completedWithWarning ? ' has-advisory' : '';
  const stateLabel = item.warning ? 'error'
    : item.completedWithWarning ? 'complete with warning'
      : item.terminal ? 'complete' : active ? 'running' : 'queued';
  const liveMessage = item.activityMessage || item.message;
  const statusMessage = item.warningMessage || (
    item.warning && item.warningTool && !liveMessage.toLowerCase().includes(item.warningTool.toLowerCase())
      ? `${liveMessage} · ${item.warningTool} error` : liveMessage
  );
  const stageModel = genomeProgressStageModel(item);
  const meter = genomeProgressMeterModel(item, stageModel);
  const ribbonText = genomeProgressRibbonText(item, statusMessage, stageModel);
  const aria = `${item.label}, ${item.taxon}, ${meter.text}, ${stateLabel}. ${ribbonText}`;
  return `
    <article class="genome-progress-row ${stateClass}${advisoryClass}" role="listitem" data-genome-progress-id="${escapeHtml(item.id)}" aria-label="${escapeHtml(aria)}">
      <div class="genome-progress-row-head">
        <span class="genome-progress-organism"><strong title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</strong><span class="genome-progress-taxon">${escapeHtml(item.taxon)}</span></span>
      </div>
      ${renderGenomeProgressMeter(item, statusMessage, stageModel)}
      ${renderGenomeProgressStages(item, stageModel)}
      <div class="genome-progress-status"><small title="${escapeHtml(ribbonText)}">${escapeHtml(ribbonText)}</small></div>
    </article>`;
}

function genomeProgressSummaryText(items) {
  const rows = Array.isArray(items) ? items : [];
  const errorCount = rows.filter(item => item.warning).length;
  const advisoryCount = rows.filter(item => item.completedWithWarning).length;
  const completeCount = rows.filter(item => item.terminal && !item.warning).length;
  const activeCount = rows.filter(
    item => !item.terminal && !item.warning && GENOME_PROGRESS_ACTIVE_STATES.has(item.status),
  ).length;
  const queuedCount = Math.max(0, rows.length - completeCount - activeCount - errorCount);
  if (rows.length && completeCount === rows.length) {
    return `All ${rows.length} genome milestone${rows.length === 1 ? '' : 's'} complete${advisoryCount ? ` · warnings: ${advisoryCount}` : ''}`;
  }
  return `${completeCount} complete · ${activeCount} active · ${queuedCount} queued${advisoryCount ? ` · warnings: ${advisoryCount}` : ''}${errorCount ? ` · errors: ${errorCount}` : ''}`;
}

function bgcWorkflowTitle(payload, genomeLayerActive) {
  if (payload?.state === 'idle') return 'Workflow waiting';
  if (payload?.state === 'complete') return 'Workflow complete';
  if (payload?.state === 'failed') return 'Workflow needs review';
  if (genomeLayerActive) return 'Genome annotation / BGC detection';
  const titles = {
    prep: 'Genome preparation',
    bigscape: 'BiG-SCAPE grouping',
    summary: 'BGC family summary',
    clinker: 'Synteny comparison',
    figures: 'Result rendering',
    nplinker: 'NPLinker follow-up',
  };
  return titles[String(payload?.currentStepId || '').toLowerCase()] || 'BGC workflow';
}
// END GENOME_PROGRESS_PURE

function renderGenomeProgressLayer(payload) {
  const station = document.getElementById('bgc-workflow-station');
  const layer = document.getElementById('bgc-genome-progress-layer');
  const grid = document.getElementById('bgc-genome-progress-grid');
  const summary = document.getElementById('bgc-genome-progress-summary');
  if (!station || !layer || !grid) return;
  const items = Array.isArray(payload?.genomes) ? payload.genomes : [];
  const warningCount = items.filter(item => item.warning).length;
  const handoff = !!payload?.genomeProgressHandoff;
  const completed = payload?.state === 'complete';
  station.classList.toggle('has-genome-progress', !!items.length);
  station.classList.toggle('is-genome-progress-handoff', handoff);
  station.classList.toggle('has-terminal-genome-warning', warningCount > 0);
  layer.classList.toggle('is-aggregate-handoff', handoff);
  layer.classList.toggle('has-terminal-warning', warningCount > 0);
  if (!items.length || completed) {
    layer.hidden = true;
    layer.setAttribute('aria-hidden', completed ? 'true' : 'false');
    if (grid.dataset.renderKey) {
      grid.innerHTML = '';
      delete grid.dataset.renderKey;
    }
    if (summary && summary.textContent !== 'Waiting for genome milestones') {
      summary.textContent = 'Waiting for genome milestones';
    }
    return;
  }
  layer.hidden = false;
  layer.setAttribute('aria-hidden', handoff && !warningCount ? 'true' : 'false');
  const renderKey = items.map(item => [
    item.id,
    item.label,
    item.taxon,
    item.percent,
    item.status,
    item.stage,
    item.message,
    item.activityMessage,
    item.terminal ? 1 : 0,
    item.warning ? 1 : 0,
    item.completedWithWarning ? 1 : 0,
    JSON.stringify(item.regionProgress || {}),
    JSON.stringify(item.stageStates || {}),
    item.warningMessage || '',
  ].join('\u001f')).join('\u001e');
  if (grid.dataset.renderKey !== renderKey) {
    grid.innerHTML = items.map(renderGenomeProgressCard).join('');
    grid.dataset.renderKey = renderKey;
  }
  if (summary) {
    const summaryText = genomeProgressSummaryText(items);
    if (summary.textContent !== summaryText) summary.textContent = summaryText;
  }
}

function workflowStageWeight(stage) {
  return WORKFLOW_PROGRESS_WEIGHTS[stage?.key] || 0.1;
}

function parseWorkflowGenomePosition(value) {
  const text = String(value || '');
  const match = text.match(/\bGenome\s+(\d+)\s+of\s+(\d+)\b/i)
    || text.match(/\[(\d+)\/(\d+)\]\s+genome=/i);
  if (!match) return null;
  const current = Number(match[1]);
  const total = Number(match[2]);
  if (!Number.isFinite(current) || !Number.isFinite(total) || total < 1) return null;
  return { current: Math.max(1, Math.min(current, total)), total };
}

function workflowGenomePhaseFromTitle(title) {
  const text = String(title || '');
  const capabilities = activeAnalysisCapabilities();
  if (/Finished\s+FunBGCeX/i.test(text)) return capabilities.funbgcex ? 1 : null;
  if (/Running\s+FunBGCeX/i.test(text)) return capabilities.funbgcex ? 0.82 : null;
  if (/Finished\s+antiSMASH/i.test(text)) return capabilities.funbgcex ? 0.68 : 1;
  if (/antiSMASH:\s*(Writing|Output|Result)/i.test(text)) return 0.62;
  if (/antiSMASH|still\s+running/i.test(text)) return 0.42;
  if (/Preparing\s+genome/i.test(text)) return 0.06;
  if (/Queued\s+\d+\s+genomes?/i.test(text)) return 0;
  return null;
}

function annotationGenomeProgress(job) {
  const events = jobPublicWorkflowEvents(job, 'annotation').filter(event => event?.stage === 'annotation');
  let latestPosition = null;
  let latest = null;
  events.forEach((event) => {
    const position = parseWorkflowGenomePosition(`${event.title || ''} ${event.meta || ''}`);
    if (position) latestPosition = position;
    const phase = workflowGenomePhaseFromTitle(event.title);
    const source = position || (phase !== null ? latestPosition : null);
    if (!source) return;
    const currentPhase = phase === null ? 0.5 : phase;
    const fraction = clampUnit((source.current - 1 + currentPhase) / source.total);
    latest = {
      current: source.current,
      total: source.total,
      fraction,
      label: `Genome ${source.current} of ${source.total}`,
    };
  });
  return latest;
}

function workflowCurrentStageFraction(job, currentKey, status) {
  if (!currentKey) return 0;
  if (currentKey === 'annotation') {
    const genomeProgress = annotationGenomeProgress(job);
    if (genomeProgress) return genomeProgress.fraction;
  }
  if (String(status || '').toLowerCase() === 'pending') return 0;
  return 0.5;
}

function weightedWorkflowProgress(stages, currentKey, status, job, stageProgress = null) {
  if (status === 'success') return 1;
  if (!currentKey) return 0;
  const totalWeight = stages.reduce((sum, stage) => sum + workflowStageWeight(stage), 0) || 1;
  const currentIndex = stages.findIndex(stage => stage.key === currentKey);
  let doneWeight = 0;
  stages.forEach((stage, index) => {
    if (activeStageState?.completed.has(stage.key) || (currentIndex >= 0 && index < currentIndex)) {
      doneWeight += workflowStageWeight(stage);
    }
  });
  if (currentIndex >= 0) {
    const currentStage = stages[currentIndex];
    const currentFraction = stageProgress && currentKey === 'annotation'
      ? stageProgress.fraction
      : workflowCurrentStageFraction(job, currentKey, status);
    doneWeight += workflowStageWeight(currentStage) * currentFraction;
  }
  return clampUnit(doneWeight / totalWeight);
}

function bgcWorkflowPayload(job = activeJobMeta) {
  syncInferredStageState(job);
  const stages = bgcWorkflowStages(job);
  const status = String((job && job.status) || '').toLowerCase();
  const rawCurrentKey = currentWorkflowStage() || jobCurrentStageKey(job);
  const currentKey = status === 'success' ? '' : rawCurrentKey;
  let state = 'idle';
  if (status === 'success') state = 'complete';
  else if (status === 'failed') state = 'failed';
  else if (status === 'running' || status === 'pending' || activeJobId) state = 'running';
  const stageProgress = currentKey === 'annotation' ? annotationGenomeProgress(job) : null;
  const genomes = normalizeGenomeProgressItems(job);
  const genomeProgressAllTerminal = genomes.length > 0 && genomes.every(item => item.terminal);
  const aggregateDownstreamStage = status === 'success'
    || ['bigscape', 'summary', 'clinker', 'figures', 'nplinker'].includes(currentKey);
  const genomeProgressHandoff = genomeProgressAllTerminal && aggregateDownstreamStage;
  const progress = weightedWorkflowProgress(stages, currentKey, status, job, stageProgress);
  const percent = Math.round(progress * 100);
  const currentStage = stages.find(stage => stage.key === currentKey);
  const hasSkippedStages = workflowPayloadHasSkippedStages();
  const tool = currentStage ? (STAGE_DETAILS[currentStage.key]?.name || currentStage.label) : (status === 'success' ? (hasSkippedStages ? 'Selected stages complete' : 'Workflow complete') : 'Input queue');
  const detail = state === 'idle'
    ? 'Waiting for submitted inputs'
    : status === 'failed'
      ? (job?.error_summary || job?.error || 'Workflow needs attention')
      : status === 'success'
        ? (hasSkippedStages ? 'Selected workflow tools complete; downstream stages skipped' : 'All workflow tools complete')
        : currentStage
          ? jobStageDisplay(job)
          : queueStatusLabel(job);
  const activityChip = bgcActivityChipPayload(job, state, currentKey, tool);
  return {
    hasSkippedStages,
    state,
    progress,
    percent,
    tool,
    statusText: detail,
    stationDetailText: state === 'running' ? '' : detail,
    progressLabel: stageProgress?.label || '',
    activityText: activityChip.text,
    activityTitle: activityChip.title,
    motionPaused: state === 'failed',
    genomes,
    genomeProgressAllTerminal,
    genomeProgressHandoff,
    steps: stages.map(stage => ({
      id: stage.key,
      label: STAGE_DETAILS[stage.key]?.name || stage.label,
      status: bgcStageStatus(stage, currentKey, status),
    })),
    currentStepId: currentKey || '',
  };
}

const ALT06_WORKFLOW_STEPS = [
  { id: 'prepare', label: 'Prepare', keys: ['prep'] },
  { id: 'annotate', label: 'Annotate', keys: ['annotation'] },
  { id: 'group', label: 'Group', keys: ['bigscape', 'summary'] },
  { id: 'compare', label: 'Compare', keys: ['clinker'] },
  { id: 'render', label: 'Render', keys: ['figures', 'nplinker'] },
];

function alt06StepStatus(group, sourceSteps, payload) {
  const source = sourceSteps.filter(step => group.keys.includes(step.id));
  if (payload.state === 'idle' || !source.length) return 'waiting';
  if (source.some(step => step.status === 'error' || step.status === 'failed')) return 'failed';
  if (source.some(step => step.status === 'running')) return 'running';
  if (source.every(step => step.status === 'skipped')) return 'skipped';
  if (source.every(step => step.status === 'complete' || step.status === 'done' || step.status === 'skipped')) return 'done';
  return 'waiting';
}

function alt06WorkflowCaption(payload) {
  if (payload.state === 'idle') return 'Submit to activate BGC workflow';
  if (payload.state === 'complete') return payload.hasSkippedStages ? 'Selected workflow stages complete; downstream stages skipped' : 'All workflow stages complete';
  if (payload.state === 'failed') return payload.statusText || 'Compare stage failed validation';
  if (payload.progressLabel) return payload.progressLabel;
  return payload.statusText || 'BGC workflow running';
}

function renderBgcWorkflowStageStrip(payload) {
  const strip = document.getElementById('bgc-stage-strip');
  if (!strip || !payload) return;
  const sourceSteps = Array.isArray(payload.steps) ? payload.steps : [];
  const statuses = ALT06_WORKFLOW_STEPS.map(group => alt06StepStatus(group, sourceSteps, payload));
  const failedIndex = statuses.indexOf('failed');
  const renderKey = statuses.join('|');
  if (strip.dataset.renderKey === renderKey) return;
  strip.innerHTML = ALT06_WORKFLOW_STEPS.map((group, index) => {
    let status = statuses[index];
    if (failedIndex >= 0 && index > failedIndex && status === 'waiting') status = 'blocked';
    const stateClass = status === 'running' ? 'is-active' : status === 'failed' ? 'is-failed' : '';
    return `
    <div class="stage-card bgc-stage-card ${escapeHtml(status)} ${stateClass}" data-bgc-stage="${escapeHtml(group.id)}">
      <span class="num">${index + 1}</span><b>${escapeHtml(group.label)}</b><small>${escapeHtml(status)}</small>
    </div>`;
  }).join('');
  strip.dataset.renderKey = renderKey;
}

function applyBgcWorkflowPayload(payload) {
  if (!payload) return;
  bgcWorkflowPendingPayload = payload;
  const genomeLayerActive = Array.isArray(payload.genomes)
    && payload.genomes.length > 0
    && !payload.genomeProgressHandoff;
  const region = document.getElementById('bgc-dna-progress-region');
  const nativeProgress = document.getElementById('bgc-workflow-native-progress');
  const percent = document.getElementById('bgc-workflow-percent');
  const headMeta = document.getElementById('workflow-head-meta');
  const captionLabel = document.getElementById('workflow-caption-label');
  const captionPercent = document.getElementById('workflow-percent');
  const tool = document.getElementById('bgc-workflow-tool');
  const detail = document.getElementById('bgc-workflow-detail');
  const activityChip = document.getElementById('bgc-tool-activity-chip');
  const title = document.getElementById('workflow-title');
  const stageStrip = document.getElementById('bgc-stage-strip');
  const toolStatus = tool?.closest('.workflow-tool-status');
  const completePresentation = payload.state === 'complete';
  if (region) {
    region.setAttribute('aria-valuenow', String(payload.percent));
    region.setAttribute('aria-valuetext', `${payload.percent}% - ${payload.tool} - ${payload.statusText}`);
  }
  if (nativeProgress) {
    nativeProgress.value = payload.percent;
    nativeProgress.textContent = `${payload.percent}%`;
  }
  if (headMeta) headMeta.textContent = payload.state === 'idle' ? 'Waiting' : payload.state === 'complete' ? 'Complete' : payload.state === 'failed' ? 'Needs review' : 'Running';
  if (title) {
    title.textContent = bgcWorkflowTitle(payload, genomeLayerActive);
    title.hidden = completePresentation;
  }
  if (percent) percent.textContent = `${payload.percent}%`;
  if (captionPercent) captionPercent.textContent = `${payload.percent}%`;
  if (captionLabel) {
    captionLabel.textContent = alt06WorkflowCaption(payload);
    captionLabel.hidden = completePresentation;
  }
  if (tool) tool.textContent = payload.tool;
  if (detail) {
    const stationDetail = payload.stationDetailText || '';
    detail.textContent = stationDetail;
    detail.hidden = !stationDetail;
  }
  if (activityChip) {
    activityChip.textContent = payload.activityText || (payload.state === 'running' ? 'RUNNING' : payload.state.toUpperCase());
    activityChip.dataset.state = payload.state || 'idle';
    activityChip.title = payload.activityTitle || payload.activityText || '';
    activityChip.hidden = completePresentation;
  }
  renderBgcWorkflowStageStrip(payload);
  renderGenomeProgressLayer(payload);
  if (stageStrip) {
    stageStrip.hidden = false;
    stageStrip.removeAttribute('aria-hidden');
  }
  if (toolStatus) {
    toolStatus.hidden = completePresentation;
    toolStatus.setAttribute('aria-hidden', completePresentation ? 'true' : 'false');
  }
  setBgcWorkflowAggregatePresentationSuspended(genomeLayerActive);
  setBgcWorkflowGenomeLayerSuspended(genomeLayerActive);
  if (bgcWorkflowDna) bgcWorkflowDna.setProgress(payload.progress, payload);
  else bootBgcWorkflowDna();
}

function updateBgcWorkflowDnaFromJob(job = activeJobMeta) {
  applyBgcWorkflowPayload(bgcWorkflowPayload(job));
}

function bootBgcWorkflowDna() {
  if (bgcWorkflowDna || bgcWorkflowDnaLoading) return;
  const canvas = document.getElementById('bgc-dna-canvas');
  const region = document.getElementById('bgc-dna-progress-region');
  const fallback = document.getElementById('bgc-dna-fallback');
  if (!canvas || !region) return;
  bgcWorkflowDnaLoading = true;
  import(WORKFLOW_DNA_MODULE_PATH).then(({ createWorkflowDnaProgress }) => {
    bgcWorkflowDna = createWorkflowDnaProgress({
      canvas,
      region,
      autoSpiral: true,
      ariaLabel: 'BGC workflow DNA progress',
    });
    region.classList.add('is-ready');
    if (fallback) fallback.textContent = '';
    syncBgcWorkflowDnaSuspension();
    if (bgcWorkflowPendingPayload) {
      bgcWorkflowDna.setProgress(bgcWorkflowPendingPayload.progress, bgcWorkflowPendingPayload);
    }
  }).catch((error) => {
    if (fallback) fallback.textContent = `3D DNA unavailable: ${error.message}`;
  }).finally(() => {
    bgcWorkflowDnaLoading = false;
  });
}

function updateStageTelemetry() {
  renderJobRuntime(activeJobMeta);
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
  const meta = String(event.meta || '').trim();
  const time = String(event.time || '').trim();
  return {
    stage,
    title,
    meta: meta || time,
    time,
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
  if (weaveActivity.jobId !== job.id) {
    resetWeaveActivity(job);
    mergeWeaveActivityEvents(job.public_events);
    return;
  }
  mergeWeaveActivityEvents(job.public_events);
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

function legacyStageOverviewNodes(job = activeJobMeta) {
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
    ...legacyStageOverviewNodes(job),
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
  const count = document.body.dataset.resultsDashboard === 'open' ? 18 : 24;
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
    renderWeaveHelix(activeJobMeta);
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
  runGsapMotion(`result-focus-${category || resultFocusMode}`, timeline => {
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
  const layer = stageWrap?.querySelector('.legacy-dna-connector-layer');
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
  const triggerCenterX = triggerRect.left + triggerRect.width / 2;
  const triggerCenterY = triggerRect.top + triggerRect.height / 2;
  const startX = triggerCenterX - wrapRect.left;
  const startY = triggerCenterY - wrapRect.top;
  const edgePad = Math.max(16, Math.min(34, Math.min(panelRect.width, panelRect.height) * .18));
  const anchors = [
    {
      distance: Math.abs(triggerCenterX - panelRect.left),
      x: panelRect.left,
      y: clampNumber(triggerCenterY, panelRect.top + edgePad, panelRect.bottom - edgePad),
    },
    {
      distance: Math.abs(triggerCenterX - panelRect.right),
      x: panelRect.right,
      y: clampNumber(triggerCenterY, panelRect.top + edgePad, panelRect.bottom - edgePad),
    },
    {
      distance: Math.abs(triggerCenterY - panelRect.top),
      x: clampNumber(triggerCenterX, panelRect.left + edgePad, panelRect.right - edgePad),
      y: panelRect.top,
    },
    {
      distance: Math.abs(triggerCenterY - panelRect.bottom),
      x: clampNumber(triggerCenterX, panelRect.left + edgePad, panelRect.right - edgePad),
      y: panelRect.bottom,
    },
  ];
  const nearest = anchors.sort((a, b) => a.distance - b.distance)[0];
  const endX = nearest.x - wrapRect.left;
  const endY = nearest.y - wrapRect.top;
  const dx = endX - startX;
  const dy = endY - startY;
  const horizontal = Math.abs(dx) >= Math.abs(dy);
  const c1x = horizontal ? startX + dx * .42 : startX;
  const c1y = horizontal ? startY : startY + dy * .42;
  const c2x = horizontal ? endX - dx * .36 : endX;
  const c2y = horizontal ? endY : endY - dy * .36;
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
  const focusedDrawer = document.body.dataset.resultsDashboard === 'open' && document.body.dataset.resultFocus === 'focused'
    ? document.getElementById('result-dashboard-section')
    : null;
  const rail = focusedDrawer || document.getElementById('results-card');
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
    evidence: 'summary',
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
  if (resultDashboardOpen) return '';
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
  let weaveShell = helix.querySelector('.dna-weave-shell');
  if (!weaveShell) {
    weaveShell = document.createElement('div');
    weaveShell.className = 'dna-weave-shell';
    weaveShell.setAttribute('aria-hidden', 'true');
  }
  Array.from(stageWrap.children).forEach(child => {
    if (!child.classList) return;
    if (child.classList.contains('dna-popover-layer') || child.classList.contains('legacy-dna-connector-layer') || child.classList.contains('dna-result-output-layer')) child.remove();
  });
  helix.replaceChildren(weaveShell);
  weaveShell.innerHTML = `
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
      </svg>`;
  const connectorLayer = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  connectorLayer.classList.add('legacy-dna-connector-layer');
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
  animateDnaOverlayPolish(stageWrap, renderKey);
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

function advanceToStage(key, options = {}) {
  if (!activeStageState || !activeStageState.enabled.has(key)) return;
  const eventId = options.eventId || '';
  if (eventId && activeStageState.appliedEvents.has(eventId)) return;
  const source = options.source || (options.line ? 'log' : 'snapshot');
  const eventMs = stageTransitionTimeMs(options);
  if (eventId) activeStageState.appliedEvents.add(eventId);
  if (Number.isFinite(eventMs)) activeStageState.lastEventMs = Math.max(activeStageState.lastEventMs || eventMs, eventMs);
  const nextIdx = stageIndex(key);
  const currentIdx = stageIndex(activeStageState.current);
  const isRestart = Boolean(
    activeStageState.failed === key ||
    activeStageState.completed.has(key) ||
    (activeStageState.current === key && Number.isFinite(activeStageState.endedAt[key])) ||
    (activeStageState.current && activeStageState.current !== key && currentIdx >= nextIdx)
  );
  if (isRestart) clearStageTimingFrom(key);
  if (activeStageState.current && activeStageState.current !== key) {
    if (currentIdx >= 0 && currentIdx < nextIdx) activeStageState.completed.add(activeStageState.current);
    setStageEndTime(activeStageState.current, eventMs, source);
  }
  for (let i = 0; i < nextIdx; i++) {
    const prior = STAGES[i].key;
    if (!activeStageState.enabled.has(prior)) continue;
    activeStageState.completed.add(prior);
    if (Number.isFinite(activeStageState.startedAt[prior])) setStageEndTime(prior, eventMs, source);
  }
  setStageStartTime(key, eventMs, source, { force: isRestart });
  if (isRestart) delete activeStageState.endedAt[key];
  if (isRestart) delete activeStageState.endedAtSource[key];
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
  const eventTimeMs = stageTimestampFromLogLine(line, activeJobMeta);
  if (key) {
    const eventId = `log:${activeJobId || ''}:${logCursor}:${key}`;
    advanceToStage(key, { eventTimeMs, source: 'log', eventId });
  }
  recordWeaveLogActivity(line, key);
  if (/FATAL:|ERROR:|failed with exit code/i.test(line) && activeStageState && activeStageState.current) {
    activeStageState.failed = activeStageState.current;
    setStageEndTime(activeStageState.current, eventTimeMs || Date.now(), 'log');
    renderStageState();
  }
}

function terminalStageTimeMs(status) {
  const normalized = String(status || '').toLowerCase();
  const finishedAt = normalized === 'success'
    ? activeJobMeta?.completed_at || activeJobMeta?.finished_at || activeJobMeta?.updated_at
    : activeJobMeta?.failed_at || activeJobMeta?.finished_at || activeJobMeta?.updated_at;
  return parseTimestampMs(finishedAt || activeJobMeta?.updated_at || activeJobMeta?.created_at) || Date.now();
}

function finalizeStageState(status) {
  if (!activeStageState) return;
  const normalized = String(status || '').toLowerCase();
  const terminalMs = terminalStageTimeMs(normalized);
  if (normalized === 'success') {
    if (activeStageState.current) setStageEndTime(activeStageState.current, terminalMs, 'terminal');
    for (const key of activeStageState.enabled) activeStageState.completed.add(key);
    activeStageState.current = null;
    activeStageState.failed = null;
  } else if (normalized === 'failed') {
    const failedKey = activeStageState.current || jobCurrentStageKey(activeJobMeta);
    if (failedKey) {
      activeStageState.failed = failedKey;
      activeStageState.current = failedKey;
      setStageEndTime(failedKey, terminalMs, 'terminal');
    }
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
  updateBgcWorkflowDnaFromJob(activeJobMeta);
}


function updateProgressBadge(status) {
  setStatusBadge(document.getElementById('progress-badge'), status, activeJobMeta);
  finalizeStageState(status);
  renderQaDrawer(activeJobMeta, activeResultFiles);
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
    clinker: 'synteny',
    antismash: 'antismash',
    funbgcex: 'funbgcex',
    bigscape: 'bigscape',
    figures: 'figures',
    phylogeny: 'figures',
    synteny: 'synteny',
    other: 'other',
    downloads: 'downloads',
    files: 'downloads',
  };
  return aliases[key] || 'downloads';
}

const RESULT_FOLDER_TABS = [
  { key: 'antismash', label: 'ANTISMASH' },
  { key: 'funbgcex', label: 'FUNBGCEX', capability: 'funbgcex' },
  { key: 'bigscape', label: 'BIG-SCAPE' },
  { key: 'synteny', label: 'CLINKER' },
  { key: 'summaries', label: 'SUMMARY' },
  { key: 'figures', label: 'FIGURES' },
];

function resultFolderTabs(counts = {}) {
  return RESULT_FOLDER_TABS.filter(tab => (
    analysisCapabilityEnabled(tab.capability)
    && (!tab.optionalWhenAvailable || Number((counts || {})[resultCategoryKey(tab.key)] || 0) > 0)
  ));
}

function resultPathExt(path) {
  const name = resultArtifactName(path).toLowerCase();
  return name.includes('.') ? name.split('.').pop() : '';
}

function isHtmlAsset(path) {
  return ['html', 'htm'].includes(resultPathExt(path));
}

function isDataResultsZip(path) {
  const descriptor = resultArtifactDescriptor(path);
  if (descriptor) return descriptor.category === 'downloads' && /_public_results\.zip$/i.test(descriptor.filename);
  const normalized = normalizedResultPath(path);
  return /^downloads\/[^/]+_public_results\.zip$/i.test(normalized) || /\/downloads\/[^/]+_public_results\.zip$/i.test(normalized);
}

function isAntiSmashArtifact(path) {
  return resultArtifactDescriptor(path)?.category === 'antismash'
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

const BIGSCAPE_PUBLIC_DATABASE_NAME = 'clusterweave_public.sqlite';
const BIGSCAPE_VIEWER_DATABASE_NAME = 'clusterweave_viewer.sqlite';
// Automatic Open accepts only the compact web-viewer derivative. The complete
// sanitized public export remains downloadable and is never loaded here.
const BIGSCAPE_BROWSER_DATABASE_MAX_BYTES = 64 * 1024 * 1024;
const SQLITE_FORMAT_HEADER = Object.freeze([83, 81, 76, 105, 116, 101, 32, 102, 111, 114, 109, 97, 116, 32, 51, 0]);

function isBigscapeDatabaseArtifact(path) {
  const descriptor = resultArtifactDescriptor(path);
  if (descriptor) return descriptor.category === 'bigscape' && descriptor.role === 'public-database';
  const normalized = normalizedResultPath(path);
  const parts = normalized.split('/');
  if (parts.some(part => !part || part === '.' || part === '..')) return false;
  return /^data\/results\/[^/]+\/(?:big_scape|bigscape|big-scape)\/(?:public|output_files\/public)\/clusterweave_public\.sqlite$/.test(normalized);
}

function isBigscapeViewerDatabaseArtifact(path) {
  const descriptor = resultArtifactDescriptor(path);
  if (descriptor?.category === 'bigscape' && descriptor.role === 'viewer-database') return true;
  if (String(path || '') === BIGSCAPE_VIEWER_DATABASE_NAME) {
    return activeJobMeta?.bigscape_viewer_available === true;
  }
  const normalized = normalizedResultPath(path);
  const parts = normalized.split('/');
  if (parts.some(part => !part || part === '.' || part === '..')) return false;
  return /^data\/results\/[^/]+\/(?:big_scape|bigscape|big-scape)\/(?:public|output_files\/public)\/clusterweave_viewer\.sqlite$/.test(normalized);
}

function isSummaryArtifact(path) {
  const descriptor = resultArtifactDescriptor(path);
  if (descriptor) return descriptor.category === 'summaries';
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

function summaryReaderArtifactKind(path) {
  const normalized = normalizedResultPath(path);
  if (!isSummaryArtifact(normalized)) return '';
  const name = fileNameFromPath(normalized).toLowerCase();
  if (name === 'all_tools_bgc_comparison.csv') return 'all_bgcs';
  if (/^priority_shortlist\.(md|tsv|csv|txt|html?)$/i.test(name)) return 'target';
  if (/^family_atlas_shortlist\.(md|tsv|csv|txt|html?)$/i.test(name)) return 'atlas';
  return '';
}

function isSummaryReaderArtifact(path) {
  return !!summaryReaderArtifactKind(path);
}

function preferredSummaryViewFile(files, kind) {
  const extensionOrder = kind === 'atlas'
    ? { tsv: 0, csv: 1, md: 2, txt: 3, html: 4, htm: 4 }
    : { md: 0, tsv: 1, csv: 2, txt: 3, html: 4, htm: 4 };
  return (files || [])
    .filter(path => summaryReaderArtifactKind(path) === kind)
    .sort((a, b) => {
      const extA = resultPathExt(a);
      const extB = resultPathExt(b);
      const keyA = (extensionOrder[extA] ?? 9) + ':' + summarySortKey(a);
      const keyB = (extensionOrder[extB] ?? 9) + ':' + summarySortKey(b);
      return keyA.localeCompare(keyB);
    })[0] || '';
}

const CROSS_KINGDOM_EVIDENCE_FILENAMES = Object.freeze([
  'cross_kingdom_evidence_cards.txt',
  'cross_kingdom_evidence.tsv',
  'cross_kingdom_evidence.json',
  'putative_transfer_evidence_cards.txt',
  'putative_transfer_evidence.tsv',
  'putative_transfer_evidence.json',
]);

function crossKingdomEvidenceArtifact(path) {
  const descriptor = resultArtifactDescriptor(path);
  if (descriptor?.category === 'evidence') {
    const descriptorName = String(descriptor.filename || '').toLowerCase();
    return CROSS_KINGDOM_EVIDENCE_FILENAMES.includes(descriptorName)
      ? { path: normalizedResultPath(path), name: descriptorName } : null;
  }
  const normalized = normalizedResultPath(path);
  const match = normalized.match(/^data\/results\/[^/]+\/integrated_evidence\/([^/]+)$/i);
  if (!match) return null;
  const name = String(match[1] || '').toLowerCase();
  if (!CROSS_KINGDOM_EVIDENCE_FILENAMES.includes(name)) return null;
  return { path: normalized, name };
}

function isPackageOnlyResultArtifact(path) {
  const descriptor = resultArtifactDescriptor(path);
  const category = String(descriptor?.category || '').trim().toLowerCase();
  if (['evidence', 'integrated_evidence', 'cross_kingdom', 'putative_transfer'].includes(category)) {
    return true;
  }
  return !!crossKingdomEvidenceArtifact(path);
}

function isSyntenyArtifact(path) {
  if (resultArtifactDescriptor(path)?.category === 'synteny') return true;
  return /(^|\/)(clinker|synteny)(\/|$)|\/panel\.html$|\/panels?\//i.test(normalizedResultPath(path));
}

function isPrimaryResultCategory(path) {
  return isFigureAsset(path)
    || isAntiSmashArtifact(path)
    || isFunbgcexArtifact(path)
    || isBigscapeArtifact(path)
    || isSummaryArtifact(path)
    || isPackageOnlyResultArtifact(path)
    || isSyntenyArtifact(path)
    || isDataResultsZip(path);
}

function resultCategoryMatches(category, path) {
  const key = resultCategoryKey(category);
  if (isPackageOnlyResultArtifact(path)) return false;
  const descriptor = resultArtifactDescriptor(path);
  if (descriptor) {
    const descriptorKey = resultCategoryKey(descriptor.category);
    if (key === 'downloads') return descriptor.downloadable !== false;
    if (key === 'other') return descriptorKey === 'other';
    return descriptorKey === key;
  }
  if (key === 'figures') return isFigureAsset(path) && figureApplicableToAnalysis(path);
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


function readableGenomeArtifactLabel(value, fallback = 'Unknown organism') {
  return readableArtifactLabel(value, fallback).replace(/^bacteria\s+/i, '').trim() || fallback;
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

function syntenyGcfQualifier(value) {
  const match = String(value || '').match(/^gcf_([a-z0-9]+)_c(\d+)_(\d+)_(.+)$/i);
  if (!match) return '';
  return `GCF ${match[1].toUpperCase()} c${match[2]}.${match[3]} ${titleCaseArtifactLabel(match[4], 'family')}`;
}

function syntenyArtifactLabel(path) {
  const descriptor = resultArtifactDescriptor(path);
  if (descriptor) {
    return descriptor.label && !/^panel\.html$/i.test(descriptor.label)
      ? titleCaseArtifactLabel(descriptor.label) : 'clinker synteny HTML panel';
  }
  const parts = resultPathParts(path);
  const idx = parts.findIndex(part => /^(clinker|synteny|clinker_shared_family)$/i.test(part));
  const filename = fileNameFromPath(path);
  const artifact = /^panel\.html$/i.test(filename) ? 'synteny panel.html' : readableArtifactLabel(filename, 'synteny artifact');
  const ignored = /^(panels?|html|assets?|static|scripts?|styles?|css|js|atlas|priority|prioritized?|shared[-_]?family|shared|family|track|tracks)$/i;
  let compound = '';
  let qualifier = '';
  for (let i = Math.max(0, idx + 1); i < parts.length - 1; i += 1) {
    if (!ignored.test(parts[i])) {
      const [compoundPart, qualifierPart = ''] = parts[i].split('__', 2);
      compound = titleCaseArtifactLabel(compoundPart, 'clinker');
      qualifier = syntenyGcfQualifier(qualifierPart);
      break;
    }
  }
  const label = qualifier ? `${compound} · ${qualifier}` : compound;
  if (label && /^panel\.html$/i.test(filename)) return label;
  return label ? `${label} - ${artifact}` : artifact;
}

function activeGenomeArtifactLabel(genomeId, fallback) {
  const source = Array.isArray(activeJobMeta?.genome_progress)
    ? activeJobMeta.genome_progress
    : Array.isArray(activeJobMeta?.genomeProgress)
      ? activeJobMeta.genomeProgress
      : [];
  const target = String(genomeId || '').trim().toLowerCase();
  const match = source.find(item => String(item?.genome_id ?? item?.genome ?? item?.id ?? '').trim().toLowerCase() === target);
  return match ? safeGenomeProgressLabel(match, 0) : fallback;
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
  const descriptor = resultArtifactDescriptor(path);
  if (descriptor?.category === toolKey && descriptor.genome_label) {
    const fallback = readableGenomeArtifactLabel(descriptor.genome_label, fileNameFromPath(path));
    return activeGenomeArtifactLabel(descriptor.genome_label, fallback);
  }
  const parts = resultPathParts(path);
  const matcher = toolKey === 'antismash' ? /^antismash$/i : /^funbgcex$/i;
  const idx = parts.findIndex(part => matcher.test(part));
  const after = idx >= 0 ? parts[idx + 1] : '';
  if (after && !/\.html?$/i.test(after)) {
    const fallback = readableGenomeArtifactLabel(after, fileNameFromPath(path));
    return activeGenomeArtifactLabel(after, fallback);
  }
  const parent = parts.length > 1 ? parts[parts.length - 2] : '';
  if (parent && !matcher.test(parent)) return readableGenomeArtifactLabel(parent, fileNameFromPath(path));
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
    const descriptor = resultArtifactDescriptor(path);
    const groupKey = String(descriptor?.bundle_id || label);
    if (!grouped.has(groupKey)) grouped.set(groupKey, { label, path });
  });
  return Array.from(grouped.values()).sort((a, b) => a.label.localeCompare(b.label));
}

function bigscapeHtmlSortKey(path) {
  const name = fileNameFromPath(path).toLowerCase();
  const priority = name === 'index.html' ? 0 : /visual|network|bigscape|app/.test(name) ? 1 : 2;
  return `${priority}:${normalizedResultPath(path).toLowerCase()}`;
}

function bigscapeExpectedHtmlPathForDatabase(databasePath) {
  const normalized = normalizedResultPath(databasePath);
  const match = normalized.match(/^(data\/results\/[^/]+\/(?:big_scape|bigscape|big-scape)\/(?:output_files\/)?)(?:public\/clusterweave_public\.sqlite)$/);
  return match ? `${match[1]}index.html` : '';
}

function bigscapeExpectedViewerPathForDatabase(databasePath) {
  const normalized = normalizedResultPath(databasePath);
  if (!bigscapeExpectedHtmlPathForDatabase(normalized)) return '';
  return normalized.replace(/\/clusterweave_public\.sqlite$/, '/clusterweave_viewer.sqlite');
}

function chooseBigscapeDatabase(htmlPath, databaseFiles) {
  const htmlDescriptor = resultArtifactDescriptor(htmlPath);
  const pairId = String(htmlDescriptor?.pair_id || htmlDescriptor?.bundle_id || '');
  if (!pairId || !databaseFiles.length) return '';
  return databaseFiles.find(path => {
    const descriptor = resultArtifactDescriptor(path);
    return String(descriptor?.pair_id || descriptor?.bundle_id || '') === pairId;
  }) || '';
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
  const capabilities = activeAnalysisCapabilities();
  const bigscapeHtmlFiles = normalized.filter(isBigscapeHtmlArtifact).sort((a, b) => bigscapeHtmlSortKey(a).localeCompare(bigscapeHtmlSortKey(b)));
  const bigscapeDatabaseFiles = normalized.filter(isBigscapeDatabaseArtifact).sort((a, b) => normalizedResultPath(a).localeCompare(normalizedResultPath(b)));
  const bigscapePairs = bigscapeHtmlFiles.map(html => ({
    html,
    database: chooseBigscapeDatabase(html, bigscapeDatabaseFiles),
  })).filter(pair => pair.database);
  const selectedPair = bigscapePairs[0] || null;
  const bigscapeHtml = selectedPair?.html || bigscapeHtmlFiles[0] || '';
  const bigscapeDatabase = selectedPair?.database || '';
  const bigscapeViewerDatabase = selectedPair && activeJobMeta?.bigscape_viewer_available === true
    ? BIGSCAPE_VIEWER_DATABASE_NAME : '';
  return {
    files: normalized,
    antismash: uniqueToolHtmlArtifacts(normalized, 'antismash'),
    funbgcex: capabilities.funbgcex ? uniqueToolHtmlArtifacts(normalized, 'funbgcex') : [],
    bigscape: {
      html: bigscapeHtml,
      database: bigscapeDatabase,
      viewerDatabase: bigscapeViewerDatabase,
      htmlFiles: bigscapeHtmlFiles,
      databaseFiles: bigscapeDatabaseFiles,
    },
    summaries: normalized.filter(isSummaryReaderArtifact).sort((a, b) => summarySortKey(a).localeCompare(summarySortKey(b))),
    synteny: normalized.filter(isSyntenyArtifact).sort((a, b) => normalizedResultPath(a).localeCompare(normalizedResultPath(b))),
    figures: normalized
      .filter(path => isFigureAsset(path) && figureApplicableToAnalysis(path, capabilities))
      .sort((a, b) => figureSortKey(a).localeCompare(figureSortKey(b))),
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
    bigscape: artifacts.bigscape.html ? 1 : 0,
    summaries: artifacts.summaries.length,
    synteny: artifacts.synteny.length,
    other,
    downloads: normalized.length,
  };
}

function resultCategoryAvailable(category, counts) {
  const key = resultCategoryKey(category);
  return resultCategoryApplicable(key) && Number((counts || {})[key] || 0) > 0;
}

function firstAvailableResultCategory(counts) {
  return resultFolderTabs(counts).map(tab => tab.key)
    .find(key => resultCategoryAvailable(key, counts)) || 'downloads';
}

function defaultFocusedResultCategory(counts) {
  return resultCategoryAvailable('antismash', counts)
    ? 'antismash'
    : firstAvailableResultCategory(counts);
}

function resultFilesForCategory(category, files) {
  const key = resultCategoryKey(category);
  if (!resultCategoryApplicable(key)) return [];
  const normalized = (files || []).map(normalizedResultPath).filter(Boolean);
  if (key === 'downloads') return normalized;
  return normalized.filter(path => resultCategoryMatches(key, path));
}

function resultCategoryLabel(category) {
  const labels = {
    figures: 'FIGURES',
    antismash: 'ANTISMASH',
    funbgcex: 'FUNBGCEX',
    bigscape: 'BIG-SCAPE',
    summaries: 'SUMMARY',
    synteny: 'CLINKER',
    other: 'Other artifacts',
    downloads: 'Files',
  };
  const key = resultCategoryKey(category);
  return labels[key] || labels.downloads;
}

function resultCategoryCopy(category) {
  const capabilities = activeAnalysisCapabilities();
  const copy = {
    figures: 'Zoomable SVG/PNG figures.',
    antismash: 'Per-genome antiSMASH HTML views.',
    funbgcex: 'Per-genome FunBGCeX HTML views.',
    bigscape: 'BiG-SCAPE clustering output; interactive view when a safe database is available.',
    summaries: 'Atlas shortlist and priority tables.',
    synteny: 'clinker panels grouped by family context.',
    other: 'Additional indexed artifacts.',
    downloads: 'All indexed artifacts as download rows.',
  };
  const key = resultCategoryKey(category);
  if (key === 'funbgcex' && capabilities.mixedDomain) {
    return 'Per-genome FunBGCeX HTML views for fungal genomes only; bacterial genomes are not applicable.';
  }
  return copy[key] || copy.downloads;
}

function resultCategoryIcon(category) {
  const icons = { antismash: '06', funbgcex: '07', bigscape: '08', summaries: '09', figures: '10', synteny: 'SYN', other: 'OUT', downloads: 'ZIP' };
  return icons[resultCategoryKey(category)] || 'OUT';
}

function resultItemCountLabel(item) {
  const count = Number((item && item.count) || 0);
  const unit = String((item && item.unit) || 'item');
  return `${count} ${unit}${count === 1 ? '' : 's'}`;
}

function resultOverviewMetricItems(items, counts) {
  const metrics = (items || []).map(item => ({
    key: item.key,
    label: item.label,
    icon: item.icon,
    count: resultItemCountLabel(item),
    copy: item.copy,
  }));
  const totalFiles = Number((counts || {}).downloads || 0);
  if (totalFiles) {
    metrics.push({
      key: 'downloads',
      label: resultCategoryLabel('downloads'),
      icon: resultCategoryIcon('downloads'),
      count: `${totalFiles} file${totalFiles === 1 ? '' : 's'}`,
      copy: 'Full manifest and package downloads.',
    });
  }
  return metrics;
}

function renderResultMetricItem(item) {
  return `
    <div class="result-overview-item" data-output-key="${escapeHtml(item.key)}">
      <span class="result-overview-item-icon" aria-hidden="true">${escapeHtml(item.icon)}</span>
      <span class="result-overview-item-main">
        <span class="result-overview-item-label">${escapeHtml(item.label)}</span>
        <span class="result-overview-item-copy">${escapeHtml(item.copy)}</span>
      </span>
      <span class="result-overview-item-count">${escapeHtml(item.count)}</span>
    </div>`;
}

function resultLollipopItems(artifacts = activeResultArtifacts || buildResultArtifacts(activeResultFiles), counts = null) {
  const items = [];
  if (artifacts.antismash.length) {
    items.push({ key: 'antismash', count: artifacts.antismash.length, unit: 'view', label: resultCategoryLabel('antismash'), copy: resultCategoryCopy('antismash'), icon: resultCategoryIcon('antismash') });
  }
  if (resultCategoryApplicable('funbgcex') && artifacts.funbgcex.length) {
    items.push({ key: 'funbgcex', count: artifacts.funbgcex.length, unit: 'view', label: resultCategoryLabel('funbgcex'), copy: resultCategoryCopy('funbgcex'), icon: resultCategoryIcon('funbgcex') });
  }
  if (artifacts.bigscape.html) {
    items.push({ key: 'bigscape', count: artifacts.bigscape.database ? 2 : 1, unit: 'file', label: resultCategoryLabel('bigscape'), copy: resultCategoryCopy('bigscape'), icon: resultCategoryIcon('bigscape') });
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
  const totalFiles = Number((counts && counts.downloads) || activeResultFiles.length || 0);
  if (totalFiles) {
    items.push({ key: 'downloads', count: totalFiles, unit: 'file', label: resultCategoryLabel('downloads'), copy: 'Full manifest and package downloads.', icon: resultCategoryIcon('downloads') });
  }
  return items;
}

function resultCategoryItems(counts) {
  return resultLollipopItems(activeResultArtifacts || buildResultArtifacts(activeResultFiles), counts).filter(item => resultCategoryAvailable(item.key, counts));
}

function renderResultOverviewPanel(items, counts) {
  const panel = document.getElementById('result-overview-panel');
  if (!panel) return;
  const focusPanel = document.getElementById('result-focus-panel');
  if (!items.length) {
    const fallback = Number((counts || {}).downloads || 0) > 0
      ? 'No tool-specific views were indexed. Use the package download or Files list for the available artifacts.'
      : 'No web-facing result artifacts were indexed for this run.';
    if (focusPanel) focusPanel.dataset.overviewFallback = 'true';
    panel.innerHTML = `<div class="empty-state">${escapeHtml(fallback)}</div>`;
    return;
  }
  if (focusPanel) delete focusPanel.dataset.overviewFallback;
  panel.innerHTML = '';
}

function resultFolderTabUnit(key) {
  const units = {
    antismash: 'view',
    funbgcex: 'view',
    bigscape: 'view',
    synteny: 'panel',
    summaries: 'file',
    figures: 'figure',
    evidence: 'file',
  };
  return units[resultCategoryKey(key)] || 'item';
}

function resultFolderTabCountLabel(key, count) {
  const safeCount = Number(count || 0);
  if (!safeCount) return 'Not available';
  const unit = resultFolderTabUnit(key);
  return `${safeCount} ${unit}${safeCount === 1 ? '' : 's'}`;
}

function resultFolderTabItems(counts) {
  return resultFolderTabs(counts).map(tab => {
    const key = resultCategoryKey(tab.key);
    const count = Number((counts || {})[key] || 0);
    return {
      key,
      label: resultCategoryLabel(key),
      count,
      unit: resultFolderTabUnit(key),
      copy: resultCategoryCopy(key),
      icon: resultCategoryIcon(key),
      available: count > 0,
    };
  });
}

function renderResultFolderTab(item) {
  const selected = resultFocusMode === 'focused' && item.key === activeResultCategory;
  const jsKey = escapeJsString(item.key);
  const disabled = !item.available;
  const classes = `output result-bubble result-lollipop result-folder-tab${selected ? ' active is-selected' : ''}${disabled ? ' is-unavailable' : ''}`;
  const buttonLabel = disabled
    ? `${item.label} output is not available for this run.`
    : `${item.label} output is available.`;
  return `
    <button class="${classes}" type="button" role="tab" data-output-key="${escapeHtml(item.key)}" data-output-node="${escapeHtml(item.icon)}" onclick="focusResultCategory('${escapeHtml(jsKey)}', event)" aria-selected="${selected ? 'true' : 'false'}" aria-controls="result-focus-panel" aria-label="${escapeHtml(buttonLabel)}" title="${escapeHtml(buttonLabel)}"${disabled ? ' disabled aria-disabled="true" tabindex="-1"' : ' tabindex="0"'}>
      <b>${escapeHtml(item.label)}</b>
    </button>`;
}

function updateResultDashboardVisibility(status, fileCount = null) {
  const panel = document.getElementById('result-bubble-panel');
  if (!panel) return;
  const loaded = !!activeJobMeta;
  const files = fileCount === null ? Number(panel.dataset.fileCount || 0) : Number(fileCount || 0);
  const shouldShowReader = loaded && resultDashboardOpen;
  const board = document.getElementById('result-dashboard-section');
  panel.classList.remove('hidden');
  if (board) board.classList.toggle('hidden', !shouldShowReader);
  document.querySelectorAll('.result-dashboard-surface').forEach(el => {
    if (el.id === 'result-dashboard-section') return;
    el.classList.toggle('hidden', !shouldShowReader);
  });
  setStatusBadge(document.getElementById('result-flow-status'), status || panel.dataset.status || '', activeJobMeta);
  updateArchiveButton();
}

function renderResultBubblePanel(files, status) {
  const panel = document.getElementById('result-bubble-panel');
  if (!panel) return;
  const indexedFiles = (files || []).map(normalizedResultPath).filter(Boolean);
  activeResultPackageFileCount = indexedFiles.length;
  activeResultFiles = indexedFiles.filter(path => !isPackageOnlyResultArtifact(path));
  document.body.dataset.resultsAvailable = (activeResultFiles.length || activeResultPackageFileCount) ? 'true' : 'false';
  const artifacts = resultArtifacts(activeResultFiles);
  const counts = resultCategoryCounts(activeResultFiles);
  const folderItems = resultFolderTabItems(counts);
  const availableItems = resultLollipopItems(artifacts, counts)
    .filter(item => resultFolderTabs(counts).some(tab => resultCategoryKey(tab.key) === item.key));
  if (resultFocusMode === 'focused' && !resultCategoryAvailable(activeResultCategory, counts)) {
    setResultFocusMode('overview');
    activeResultCategory = firstAvailableResultCategory(counts);
  }
  panel.dataset.status = String(status || '');
  panel.dataset.fileCount = String(counts.downloads);
  panel.innerHTML = folderItems.map(renderResultFolderTab).join('');
  renderResultOverviewPanel(availableItems, counts);
  updateResultDashboardVisibility(status, counts.downloads);
  rerenderWorkflowSpineForResults();
}

function updateArchiveButton() {
  const btn = document.getElementById('download-package-btn');
  if (!btn) return;
  const inFlight = !!activeArchiveDownload;
  const sameRun = inFlight && activeArchiveDownload.jobId === activeJobId;
  const percent = inFlight && activeArchiveDownload.total > 0
    ? Math.min(100, Math.floor((activeArchiveDownload.received / activeArchiveDownload.total) * 100))
    : 0;
  btn.disabled = !activeJobId || activeResultPackageFileCount < 1 || inFlight;
  btn.textContent = inFlight
    ? (sameRun && percent ? `Downloading ${percent}%` : 'Download in progress')
    : 'Download package';
}

function archiveDownloadDetail(download) {
  const received = Number(download?.received || 0);
  const total = Number(download?.total || 0);
  const runId = String(download?.runId || 'result');
  if (total > 0) return `${runId} · ${fmt_size(received)} of ${fmt_size(total)} received in the background.`;
  if (received > 0) return `${runId} · ${fmt_size(received)} received in the background.`;
  return `${runId} · preparing the full result package in the background.`;
}

function renderArchiveDownloadStatus(status = archiveDownloadStatus) {
  const tray = document.getElementById('archive-download-tray');
  const title = document.getElementById('archive-download-title');
  const percentLabel = document.getElementById('archive-download-percent');
  const detail = document.getElementById('archive-download-detail');
  const progress = document.getElementById('archive-download-progress');
  const fill = document.getElementById('archive-download-progress-fill');
  if (!tray || !title || !percentLabel || !detail || !progress || !fill) return;
  if (!status) {
    tray.hidden = true;
    tray.setAttribute('aria-busy', 'false');
    return;
  }
  const state = String(status.state || 'running');
  const received = Number(status.received || 0);
  const total = Number(status.total || 0);
  const percent = total > 0 ? Math.min(100, Math.floor((received / total) * 100)) : 0;
  tray.hidden = false;
  tray.dataset.state = state;
  tray.setAttribute('aria-busy', state === 'running' ? 'true' : 'false');
  title.textContent = state === 'complete' ? 'PACKAGE READY' : state === 'error' ? 'DOWNLOAD INTERRUPTED' : 'PACKAGE DOWNLOAD';
  percentLabel.textContent = state === 'complete' ? '100%' : state === 'error' ? 'RETRY' : total > 0 ? `${percent}%` : 'WORKING';
  detail.textContent = String(status.message || archiveDownloadDetail(status));
  progress.classList.toggle('is-indeterminate', state === 'running' && total <= 0);
  if (total > 0 || state === 'complete') {
    const value = state === 'complete' ? 100 : percent;
    progress.setAttribute('aria-valuenow', String(value));
    fill.style.width = `${value}%`;
  } else {
    progress.removeAttribute('aria-valuenow');
    fill.style.width = '';
  }
}

function setArchiveDownloadStatus(status, dismissAfterMs = 0) {
  if (archiveDownloadDismissTimer) {
    clearTimeout(archiveDownloadDismissTimer);
    archiveDownloadDismissTimer = null;
  }
  archiveDownloadStatus = status;
  renderArchiveDownloadStatus(status);
  if (status && dismissAfterMs > 0) {
    archiveDownloadDismissTimer = setTimeout(() => {
      archiveDownloadStatus = null;
      archiveDownloadDismissTimer = null;
      renderArchiveDownloadStatus(null);
    }, dismissAfterMs);
  }
}

async function readArchiveResponseBlob(response, requestId) {
  const headerTotal = Number(response.headers.get('content-length') || 0);
  if (!response.body || typeof response.body.getReader !== 'function') {
    const blob = await response.blob();
    if (activeArchiveDownload?.requestId === requestId) {
      activeArchiveDownload.received = blob.size;
      activeArchiveDownload.total = headerTotal || blob.size;
      setArchiveDownloadStatus({ ...activeArchiveDownload, state: 'running' });
    }
    return blob;
  }
  const reader = response.body.getReader();
  const chunks = [];
  let received = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;
    chunks.push(value);
    received += value.byteLength;
    if (activeArchiveDownload?.requestId === requestId) {
      activeArchiveDownload.received = received;
      activeArchiveDownload.total = headerTotal;
      setArchiveDownloadStatus({ ...activeArchiveDownload, state: 'running' });
      updateArchiveButton();
    }
  }
  return new Blob(chunks, { type: response.headers.get('content-type') || 'application/zip' });
}

async function downloadResultArchive(event) {
  event?.preventDefault?.();
  if (!activeJobId || activeArchiveDownload) return false;
  const requestJobId = activeJobId;
  const requestRunId = publicRunIdForJob(requestJobId);
  const requestId = ++resultArchiveRequestSeq;
  activeArchiveDownload = {
    jobId: requestJobId,
    runId: requestRunId,
    requestId,
    received: 0,
    total: 0,
  };
  setArchiveDownloadStatus({ ...activeArchiveDownload, state: 'running' });
  updateArchiveButton();
  try {
    const resp = await apiFetch(
      `api/results/${encodeURIComponent(requestRunId)}/archive`,
      { cache: 'no-store' },
      { kind: 'job', jobId: requestRunId },
    );
    if (!resp.ok) throw new Error('Full package download is not available for this run yet.');
    const blob = await readArchiveResponseBlob(resp, requestId);
    if (resultArchiveObjectUrl) URL.revokeObjectURL(resultArchiveObjectUrl);
    resultArchiveObjectUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = resultArchiveObjectUrl;
    a.download = `${requestRunId}_clusterweave_results.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setArchiveDownloadStatus({
      ...activeArchiveDownload,
      state: 'complete',
      received: blob.size,
      total: blob.size,
      message: `${requestRunId} · package received; the browser download has started.`,
    }, 6000);
  } catch (err) {
    setArchiveDownloadStatus({
      ...(activeArchiveDownload || { runId: requestRunId }),
      state: 'error',
      message: err?.message || 'Package download was interrupted. Select Download package to retry.',
    }, 8000);
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
  animateResultFocusChange(key);
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

function openAlt06ResultFolder(event = null) {
  focusResultCategory(activeResultCategory || 'antismash', event);
}

function clearResultFocus() {
  setResultFocusMode('overview');
  renderResultBubblePanel(activeResultFiles, activeJobMeta?.status || '');
  animateResultFocusChange('overview');
  const firstOutput = document.querySelector('.result-lollipop:not(:disabled)') || document.querySelector('.dna-result-output-trigger');
  (firstOutput || document.getElementById('weavemap'))?.focus({ preventScroll: true });
}

function setResultReaderSurface(surface) {
  const selected = surface === 'viz' ? 'viz' : 'files';
  const viz = document.getElementById('viz-container');
  const files = document.getElementById('files-container');
  if (viz) viz.hidden = selected !== 'viz';
  if (files) files.hidden = selected !== 'files';
}

function renderResultFileSurface(jobId, files) {
  if (resultFocusMode === 'focused') {
    renderFocusedResultCategory(activeResultCategory);
    return;
  }
  setResultReaderSurface('files');
  renderFileTable(jobId, files);
}

function renderFocusedResultCategory(category) {
  const key = resultCategoryKey(category);
  if (!resultCategoryApplicable(key)) {
    setResultFocusMode('overview');
    renderResultBubblePanel(activeResultFiles, activeJobMeta?.status || '');
    return;
  }
  const artifacts = resultArtifacts(activeResultFiles);
  if (key === 'figures') {
    setResultReaderSurface('viz');
    if (activeJobId) renderViz(activeJobId, activeResultFiles);
    return;
  }
  setResultReaderSurface('files');
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
    <div class="artifact-row is-compact result-tool-row">
      <div class="artifact-row-name">${escapeHtml(item.label)}</div>
      <div class="artifact-row-actions">
        ${resultOpenLink(jobId, item.path, 'Open')}
        ${resultDownloadLink(jobId, item.path, 'Download')}
      </div>
    </div>`).join('');
  container.innerHTML = `
    <div class="artifact-reader">
      ${artifactReaderHead(category, `${items.length} ${items.length === 1 ? 'view' : 'views'}`)}
      <div class="artifact-list">${rows}</div>
    </div>`;
  animateResultReaderOpen();
}

function normalizedSyntenyTaxon(value) {
  const taxon = String(value || '').trim().toLowerCase();
  return ['fungi', 'bacteria'].includes(taxon) ? taxon : '';
}

function syntenyArtifactTaxon(path) {
  const descriptorTaxon = normalizedSyntenyTaxon(resultArtifactDescriptor(path)?.taxon_group);
  if (descriptorTaxon) return descriptorTaxon;
  const capabilities = activeAnalysisCapabilities();
  if (capabilities.hasFungi && !capabilities.hasBacteria) return 'fungi';
  if (capabilities.hasBacteria && !capabilities.hasFungi) return 'bacteria';
  return 'other';
}

function syntenyArtifactGenome(path) {
  const descriptor = resultArtifactDescriptor(path);
  const genome = String(descriptor?.genome_label || '').trim();
  if (!genome) return 'Dataset context';
  return activeGenomeArtifactLabel(
    genome,
    readableGenomeArtifactLabel(genome, 'Dataset context'),
  );
}

function syntenyArtifactTrack(path) {
  const track = String(resultArtifactDescriptor(path)?.track || '').trim();
  if (!track) return 'Panel';
  return titleCaseArtifactLabel(track.replace(/_/g, ' '), 'Panel');
}

function syntenyTaxonGroups(items) {
  const groups = new Map();
  (items || []).map(normalizedResultPath).filter(Boolean).forEach(path => {
    const taxon = syntenyArtifactTaxon(path);
    if (!groups.has(taxon)) groups.set(taxon, []);
    groups.get(taxon).push(path);
  });
  return groups;
}

function switchSyntenyTaxon(taxon) {
  const selected = ['fungi', 'bacteria', 'other'].includes(String(taxon || '')) ? String(taxon) : '';
  const groups = syntenyTaxonGroups(resultArtifacts(activeResultFiles).synteny);
  if (!selected || !groups.has(selected)) return;
  activeSyntenyTaxon = selected;
  renderSyntenyReader(activeJobId, resultArtifacts(activeResultFiles).synteny);
}

function renderSyntenyReader(jobId, items) {
  const container = document.getElementById('files-container');
  if (!container) return;
  const syntenyFiles = (items || []).map(normalizedResultPath).filter(Boolean);
  if (!syntenyFiles.length) {
    container.innerHTML = '<div class="empty-state">No synteny panel artifacts were found for this run.</div>';
    return;
  }
  const groups = syntenyTaxonGroups(syntenyFiles);
  const taxonOrder = ['fungi', 'bacteria', 'other'].filter(taxon => groups.has(taxon));
  if (syntenyReaderJobId !== jobId) {
    syntenyReaderJobId = jobId;
    activeSyntenyTaxon = taxonOrder[0] || '';
  }
  if (!groups.has(activeSyntenyTaxon)) activeSyntenyTaxon = taxonOrder[0] || '';
  const labels = { fungi: 'FUNGAL PANELS', bacteria: 'BACTERIAL PANELS', other: 'OTHER PANELS' };
  const tabs = taxonOrder.map(taxon => {
    const active = taxon === activeSyntenyTaxon;
    const count = groups.get(taxon)?.length || 0;
    return `<button class="summary-subtab clinker-subtab" type="button" role="tab" aria-selected="${active ? 'true' : 'false'}" tabindex="${active ? '0' : '-1'}" onclick="switchSyntenyTaxon('${taxon}')">${escapeHtml(labels[taxon])}<span>${count}</span></button>`;
  }).join('');
  const selectedFiles = groups.get(activeSyntenyTaxon) || [];
  const rows = selectedFiles.map(path => `
    <tr>
      <td class="clinker-col-organism">${escapeHtml(syntenyArtifactGenome(path))}</td>
      <td class="clinker-col-panel">${escapeHtml(syntenyArtifactLabel(path))}</td>
      <td>${escapeHtml(syntenyArtifactTrack(path))}</td>
      <td class="clinker-col-actions"><div class="artifact-row-actions">
        ${resultOpenLink(jobId, path, 'Open')}
        ${resultDownloadLink(jobId, path, 'Download')}
      </div></td>
    </tr>`).join('');
  container.innerHTML = `
    <div class="summary-reader clinker-reader" data-clinker-taxon="${escapeHtml(activeSyntenyTaxon)}">
      <div class="summary-reader-head">
        <div class="summary-subtabs" role="tablist" aria-label="clinker panel taxon groups">${tabs}</div>
        <span class="ext-badge">${escapeHtml(`${syntenyFiles.length} ${syntenyFiles.length === 1 ? 'panel' : 'panels'}`)}</span>
      </div>
      <div class="summary-condensed-head clinker-condensed-head">
        <div class="summary-condensed-title">${escapeHtml(labels[activeSyntenyTaxon] || 'CLINKER PANELS')}</div>
        <div class="summary-condensed-meta">${escapeHtml(`${selectedFiles.length} ${selectedFiles.length === 1 ? 'panel' : 'panels'}`)}</div>
      </div>
      <div class="summary-table-wrap clinker-table-wrap">
        <table class="summary-reader-table clinker-table">
          <thead><tr><th>Organism</th><th>Panel</th><th>Set</th><th>Actions</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
  animateResultReaderOpen();
}

function jsonForInlineScript(value) {
  return JSON.stringify(value).replace(/</g, '\\u003c');
}

function bigscapePreviewChannel() {
  if (typeof window.crypto?.randomUUID === 'function') return window.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof window.crypto?.getRandomValues === 'function') window.crypto.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
}

async function validatedBigscapeDatabaseBuffer(response) {
  const declaredSize = Number(response?.headers?.get?.('Content-Length') || 0);
  if (Number.isFinite(declaredSize) && declaredSize > BIGSCAPE_BROWSER_DATABASE_MAX_BYTES) {
    throw new Error('The compact BiG-SCAPE viewer database is too large for automatic browser loading.');
  }
  const buffer = await response.arrayBuffer();
  if (!buffer.byteLength || buffer.byteLength > BIGSCAPE_BROWSER_DATABASE_MAX_BYTES) {
    throw new Error('The compact BiG-SCAPE viewer database is empty or too large for automatic browser loading.');
  }
  const header = new Uint8Array(buffer, 0, Math.min(SQLITE_FORMAT_HEADER.length, buffer.byteLength));
  const validHeader = header.length === SQLITE_FORMAT_HEADER.length
    && SQLITE_FORMAT_HEADER.every((value, index) => header[index] === value);
  if (!validHeader) throw new Error('The paired BiG-SCAPE viewer database is not valid sanitized SQLite.');
  return buffer;
}

function injectBigscapeDatabaseContract(htmlText, dbName, dbPath, channel) {
  const headScript = `<script>window.CLUSTERWEAVE_BIGSCAPE_DATABASE_NAME=${jsonForInlineScript(dbName)};window.CLUSTERWEAVE_BIGSCAPE_DATABASE_PATH=${jsonForInlineScript(dbPath)};window.CLUSTERWEAVE_BIGSCAPE_DATABASE_CHANNEL=${jsonForInlineScript(channel)};<\/script>`;
  const loaderScript = `<script>(function(){
  const name = window.CLUSTERWEAVE_BIGSCAPE_DATABASE_NAME || 'clusterweave_viewer.sqlite';
  const path = window.CLUSTERWEAVE_BIGSCAPE_DATABASE_PATH || name;
  const channel = window.CLUSTERWEAVE_BIGSCAPE_DATABASE_CHANNEL || '';
  let loadPromise = null;
  let bufferPromise = null;

  function setStatus(message) {
    try { if (typeof window.showLoading === 'function') window.showLoading(true, true); } catch (e) {}
    const status = document.getElementById('status');
    if (status) status.textContent = message;
  }

  function fail(err) {
    const message = err && err.message ? err.message : 'ClusterWeave could not load the compact BiG-SCAPE viewer database.';
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

  function receiveBuffer() {
    if (!bufferPromise) {
      bufferPromise = new Promise((resolve, reject) => {
        let timer = null;
        let readyInterval = null;
        let settled = false;
        const maxBytes = ${BIGSCAPE_BROWSER_DATABASE_MAX_BYTES};
        const sqliteHeader = [83, 81, 76, 105, 116, 101, 32, 102, 111, 114, 109, 97, 116, 32, 51, 0];
        function cleanup() {
          window.removeEventListener('message', onMessage);
          if (timer) window.clearTimeout(timer);
          if (readyInterval) window.clearInterval(readyInterval);
          timer = null;
          readyInterval = null;
        }
        function rejectTransfer(message) {
          if (settled) return;
          settled = true;
          cleanup();
          reject(new Error(message));
        }
        function resolveTransfer(buffer) {
          if (settled) return;
          settled = true;
          cleanup();
          resolve(buffer);
        }
        function onMessage(event) {
          if (event.source !== window.parent) return;
          const payload = event && event.data;
          if (!payload || payload.channel !== channel) return;
          if (payload.type === 'clusterweave:bigscape-database-error') {
            rejectTransfer('ClusterWeave could not transfer the compact BiG-SCAPE viewer database.');
            return;
          }
          if (payload.type !== 'clusterweave:bigscape-database') return;
          if (
            Object.prototype.toString.call(payload.buffer) !== '[object ArrayBuffer]'
            || payload.buffer.byteLength <= 0
            || payload.buffer.byteLength > maxBytes
          ) {
            rejectTransfer('The compact BiG-SCAPE viewer database transfer is invalid.');
            return;
          }
          const output = new Uint8Array(payload.buffer);
          const validHeader = sqliteHeader.every((value, index) => output[index] === value);
          if (!validHeader) {
            rejectTransfer('The transferred BiG-SCAPE viewer database is not valid sanitized SQLite.');
            return;
          }
          resolveTransfer(payload.buffer);
        }
        window.addEventListener('message', onMessage);
        function announceReady() {
          try { window.parent.postMessage({ type: 'clusterweave:bigscape-database-ready', channel: channel }, '*'); } catch (e) {}
        }
        announceReady();
        readyInterval = window.setInterval(announceReady, 250);
        timer = window.setTimeout(() => {
          rejectTransfer('Compact BiG-SCAPE viewer database transfer timed out.');
        }, 120000);
      });
    }
    return bufferPromise;
  }

  function emitReady() {
    const detail = { name: name, path: path };
    try { window.dispatchEvent(new CustomEvent('clusterweave:bigscape-database-ready', { detail: detail })); } catch (e) {}
    try { document.dispatchEvent(new CustomEvent('clusterweave:bigscape-database-ready', { detail: detail })); } catch (e) {}
  }

  async function autoloadDatabase() {
    if (loadPromise) return loadPromise;
    loadPromise = (async function(){
      setStatus('Loading BiG-SCAPE database: ' + name);
      const initSqlJs = await waitForFunction('initSqlJs', 24000);
      const dataLoaded = await waitForFunction('dataLoaded', 24000);
      const buffer = await receiveBuffer();
      window.CLUSTERWEAVE_BIGSCAPE_DATABASE_BYTES = buffer.byteLength || 0;
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
  if (!jobId || !isBigscapeHtmlArtifact(htmlPath) || !isBigscapeViewerDatabaseArtifact(databasePath)) {
    window.alert('A compact ClusterWeave BiG-SCAPE viewer database is required for automatic opening.');
    return false;
  }
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
      bigscapeViewerFetch(jobId),
    ]);
    if (!htmlResp.ok) throw new Error('BiG-SCAPE HTML view could not be opened with this result access code.');
    if (!dbResp.ok) throw new Error('The compact BiG-SCAPE viewer database could not be opened with this result access code.');
    const htmlText = await htmlResp.text();
    const databaseBuffer = await validatedBigscapeDatabaseBuffer(dbResp);
    const dbName = fileNameFromPath(databasePath);
    const channel = bigscapePreviewChannel();
    const contractedHtml = injectBigscapeDatabaseContract(htmlText, dbName, databasePath, channel);
    const rewrittenHtml = await rewriteHtmlResultAssets(contractedHtml, jobId, htmlPath, {
      allowBigscapeScripts: true,
    });
    renderSandboxedBigscapePreview(previewWindow, htmlPath, rewrittenHtml, databaseBuffer, channel);
  } catch (err) {
    const message = err && err.message ? err.message : 'BiG-SCAPE result could not be opened.';
    previewWindow.document.body.innerHTML = `<pre style="white-space:pre-wrap;font:14px system-ui,sans-serif;color:#111">${escapeHtml(message)}</pre>`;
  }
  return false;
}

function renderBigscapeReader(jobId, bigscape) {
  const container = document.getElementById('files-container');
  if (!container) return;
  if (!bigscape || !bigscape.html) {
    container.innerHTML = '<div class="empty-state">No BiG-SCAPE web output was indexed for this run.</div>';
    return;
  }
  if (!bigscape.database) {
    container.innerHTML = `
      <div class="artifact-reader">
        ${artifactReaderHead('bigscape', 'clustering complete')}
        <div class="artifact-row result-tool-row">
          <div>
            <div class="artifact-row-name">BiG-SCAPE clustering complete</div>
            <div class="artifact-row-meta">The raw SQLite database is excluded from public results and remains private because it contains sequence data and execution paths. Use the BiG-SCAPE multipanels and network figures; an interactive reader requires the redacted ClusterWeave database.</div>
          </div>
          <div class="artifact-row-actions">
            ${resultDownloadLink(jobId, bigscape.html, 'Download HTML')}
          </div>
        </div>
      </div>`;
    animateResultReaderOpen();
    return;
  }
  if (!bigscape.viewerDatabase) {
    container.innerHTML = `
      <div class="artifact-reader">
        ${artifactReaderHead('bigscape', 'web view')}
        <div class="artifact-row result-tool-row">
          <div>
            <div class="artifact-row-name">BiG-SCAPE web view</div>
            <div class="artifact-row-meta">Automatic Open is unavailable because this run has no independently attested compact viewer database. The complete sanitized database remains available for download.</div>
          </div>
          <div class="artifact-row-actions">
            ${resultDownloadLink(jobId, bigscape.database, 'Download sanitized SQLite')}
          </div>
        </div>
      </div>`;
    animateResultReaderOpen();
    return;
  }
  const jsJobId = escapeJsString(jobId);
  const jsHtml = escapeJsString(bigscape.html);
  const jsDb = escapeJsString(bigscape.viewerDatabase);
  const href = resultHref(jobId, bigscape.html);
  container.innerHTML = `
    <div class="artifact-reader">
      ${artifactReaderHead('bigscape', 'web view')}
      <div class="artifact-row is-compact result-tool-row">
        <div class="artifact-row-name">BiG-SCAPE web view</div>
        <div class="artifact-row-actions">
          <a class="btn btn-primary text-sm" href="${escapeHtml(href)}" target="_blank" onclick="return openBigscapeResult(event,'${escapeHtml(jsJobId)}','${escapeHtml(jsHtml)}','${escapeHtml(jsDb)}')">Open</a>
          ${resultDownloadLink(jobId, bigscape.database, 'Download sanitized SQLite')}
        </div>
      </div>
    </div>`;
  animateResultReaderOpen();
}


function summaryViewDefinitions(summaryFiles) {
  const definitions = [
    { key: 'all_bgcs', label: 'ALL BGCs' },
    { key: 'target', label: 'TARGET' },
    { key: 'atlas', label: 'ATLAS' },
  ];
  return definitions.map(item => ({
    ...item,
    path: preferredSummaryViewFile(summaryFiles, item.key),
  })).filter(item => item.path);
}

function switchSummaryView(view) {
  const summaries = resultArtifacts(activeResultFiles).summaries;
  if (!summaryViewDefinitions(summaries).some(item => item.key === view)) return;
  activeSummaryView = view;
  renderSummaryReader(activeJobId, summaries);
}

function renderSummaryReader(jobId, summaryFiles) {
  const container = document.getElementById('files-container');
  if (!container) return;
  const views = summaryViewDefinitions(summaryFiles);
  if (!views.length) {
    container.innerHTML = '<div class="empty-state">No public Summary table was found for this run.</div>';
    return;
  }
  if (summaryReaderJobId !== jobId) {
    summaryReaderJobId = jobId;
    activeSummaryView = 'all_bgcs';
    allBgcTableState = null;
  }
  if (!views.some(item => item.key === activeSummaryView)) activeSummaryView = views[0].key;
  const selected = views.find(item => item.key === activeSummaryView) || views[0];
  const tabs = views.map(item => {
    const active = item.key === selected.key;
    return `<button class="summary-subtab" type="button" role="tab" aria-selected="${active ? 'true' : 'false'}" tabindex="${active ? '0' : '-1'}" onclick="switchSummaryView('${item.key}')">${escapeHtml(item.label)}</button>`;
  }).join('');
  container.innerHTML = `
    <div class="summary-reader">
      <div class="summary-reader-head">
        <div class="summary-subtabs" role="tablist" aria-label="Summary result views">${tabs}</div>
        ${resultDownloadLink(jobId, selected.path, 'Download table')}
      </div>
      <div class="summary-reader-doc" id="summary-reader-doc" role="tabpanel"><div class="viz-placeholder text-sm">Loading summary document...</div></div>
    </div>`;
  animateResultReaderOpen();
  if (selected.key === 'all_bgcs') loadAllBgcReaderFile(selected.path);
  else loadSummaryReaderFile(selected.path);
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

const ALL_BGC_COLUMNS = Object.freeze([
  { key: 'genome', label: 'Organism' },
  { key: 'taxon_group', label: 'Kingdom' },
  { key: 'detector_relation', label: 'Detector support' },
  { key: 'antismash_bgc_id', label: 'antiSMASH region' },
  { key: 'antismash_bgc_class', label: 'antiSMASH BGC class' },
  { key: 'antismash_knowncluster_similarity_score', label: 'KnownClusterBlast score' },
  { key: 'antismash_knowncluster_accession', label: 'KnownCluster accession' },
  { key: 'antismash_knowncluster_product', label: 'KnownCluster product' },
  { key: 'antismash_clustercompare_similarity_score', label: 'ClusterCompare score' },
  { key: 'antismash_clustercompare_compounds', label: 'ClusterCompare compounds' },
  { key: 'antismash_clustercompare_organism', label: 'ClusterCompare organism' },
  { key: 'funbgcex_core_enzymes', label: 'FunBGCeX core enzymes' },
  { key: 'funbgcex_similar_bgc', label: 'FunBGCeX similar BGC' },
  { key: 'funbgcex_similarity_score', label: 'FunBGCeX similarity score' },
  { key: 'funbgcex_putative_product', label: 'FunBGCeX putative product' },
]);

function allBgcDisplayValue(row, key) {
  if (key === 'genome') {
    const fallback = readableGenomeArtifactLabel(row.genome || '', 'Unknown organism');
    return activeGenomeArtifactLabel(row.genome || '', fallback);
  }
  if (key === 'taxon_group') return titleCaseArtifactLabel(row.taxon_group || '', 'Unresolved');
  if (key === 'detector_relation') return titleCaseArtifactLabel(row.detector_relation || '', 'Single detector');
  if (key === 'antismash_bgc_id') {
    const region = String(row.antismash_bgc_id || '');
    const genome = String(row.genome || '');
    if (String(row.taxon_group || '').toLowerCase() === 'bacteria' && genome) {
      for (const separator of ['_', '.']) {
        const prefix = genome + separator;
        if (region.startsWith(prefix)) return region.slice(prefix.length);
      }
    }
    return region || '—';
  }
  return row[key] || '—';
}

function allBgcFilteredRows() {
  if (!allBgcTableState) return [];
  const query = String(allBgcTableState.query || '').trim().toLowerCase();
  return allBgcTableState.rows.filter(row => {
    if (allBgcTableState.taxon && String(row.taxon_group || '').toLowerCase() !== allBgcTableState.taxon) return false;
    if (allBgcTableState.genome && String(row.genome || '') !== allBgcTableState.genome) return false;
    if (!query) return true;
    return ALL_BGC_COLUMNS.some(column => String(allBgcDisplayValue(row, column.key)).toLowerCase().includes(query));
  }).sort((a, b) => {
    const left = String(allBgcDisplayValue(a, allBgcTableState.sortKey)).toLowerCase();
    const right = String(allBgcDisplayValue(b, allBgcTableState.sortKey)).toLowerCase();
    const order = left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' });
    return allBgcTableState.sortDir === 'desc' ? -order : order;
  });
}

function allBgcGenomeValues(rows, taxon = '') {
  const values = Array.from(new Set(rows
    .filter(row => !taxon || String(row.taxon_group || '').toLowerCase() === taxon)
    .map(row => String(row.genome || '')).filter(Boolean)));
  return values.sort((a, b) => allBgcDisplayValue({ genome: a }, 'genome').localeCompare(
    allBgcDisplayValue({ genome: b }, 'genome'), undefined, { numeric: true, sensitivity: 'base' },
  ));
}

function allBgcTableMarkup(rows) {
  const head = ALL_BGC_COLUMNS.map(column => {
    const selected = allBgcTableState.sortKey === column.key;
    const arrow = selected ? (allBgcTableState.sortDir === 'asc' ? ' ↑' : ' ↓') : '';
    return '<th><button type="button" onclick="sortAllBgcTable(\'' + column.key + '\')" aria-label="Sort by ' + escapeHtml(column.label) + '">' + escapeHtml(column.label + arrow) + '</button></th>';
  }).join('');
  const body = rows.map(row => '<tr>' + ALL_BGC_COLUMNS.map(column => '<td>' + escapeHtml(allBgcDisplayValue(row, column.key)) + '</td>').join('') + '</tr>').join('');
  return rows.length
    ? '<div class="summary-table-wrap all-bgc-table-wrap"><table class="summary-reader-table all-bgc-table"><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>'
    : '<div class="empty-state">No BGC records match the selected filters.</div>';
}

function refreshAllBgcRows() {
  const doc = document.getElementById('summary-reader-doc');
  if (!doc || !allBgcTableState) return;
  const rows = allBgcFilteredRows();
  const meta = doc.querySelector('.summary-condensed-meta');
  const table = doc.querySelector('#all-bgc-table-region');
  if (meta) meta.textContent = rows.length + ' matching BGC records';
  if (table) table.innerHTML = allBgcTableMarkup(rows);
}

function updateAllBgcFilter(key, value) {
  if (!allBgcTableState || !['query', 'taxon', 'genome'].includes(key)) return;
  allBgcTableState[key] = String(value || '');
  if (key === 'query') { refreshAllBgcRows(); return; }
  if (key === 'taxon') {
    const genomes = allBgcGenomeValues(allBgcTableState.rows, allBgcTableState.taxon);
    if (allBgcTableState.genome && !genomes.includes(allBgcTableState.genome)) allBgcTableState.genome = '';
  }
  renderAllBgcTable();
}

function sortAllBgcTable(key) {
  if (!allBgcTableState || !ALL_BGC_COLUMNS.some(column => column.key === key)) return;
  if (allBgcTableState.sortKey === key) {
    allBgcTableState.sortDir = allBgcTableState.sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    allBgcTableState.sortKey = key;
    allBgcTableState.sortDir = 'asc';
  }
  refreshAllBgcRows();
}

function renderAllBgcTable() {
  const doc = document.getElementById('summary-reader-doc');
  if (!doc || !allBgcTableState) return;
  const genomes = allBgcGenomeValues(allBgcTableState.rows, allBgcTableState.taxon);
  const rows = allBgcFilteredRows();
  const taxa = Array.from(new Set(allBgcTableState.rows.map(row => String(row.taxon_group || '').toLowerCase()).filter(Boolean))).sort();
  const taxonOptions = taxa.map(value => '<option value="' + escapeHtml(value) + '"' + (value === allBgcTableState.taxon ? ' selected' : '') + '>' + escapeHtml(titleCaseArtifactLabel(value)) + '</option>').join('');
  const genomeOptions = genomes.map(value => {
    const label = activeGenomeArtifactLabel(value, readableArtifactLabel(value));
    return '<option value="' + escapeHtml(value) + '"' + (value === allBgcTableState.genome ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
  }).join('');
  doc.innerHTML =
    '<div class="summary-condensed-head"><div class="summary-condensed-title">ALL BGCs</div><div class="summary-condensed-meta">' + escapeHtml(rows.length + ' matching BGC records') + '</div></div>' +
    '<div class="all-bgc-controls">' +
      '<label>Search<input type="search" value="' + escapeHtml(allBgcTableState.query) + '" placeholder="Organism, class, region, compound" oninput="updateAllBgcFilter(\'query\',this.value)"></label>' +
      '<label>Kingdom<select onchange="updateAllBgcFilter(\'taxon\',this.value)"><option value="">All</option>' + taxonOptions + '</select></label>' +
      '<label>Organism<select onchange="updateAllBgcFilter(\'genome\',this.value)"><option value="">All</option>' + genomeOptions + '</select></label>' +
    '</div>' +
    '<div id="all-bgc-table-region">' + allBgcTableMarkup(rows) + '</div>';
  animateSummaryReaderDocument();
}

async function loadAllBgcReaderFile(path) {
  if (!activeJobId || !path) return;
  if (allBgcTableState?.path === path) { renderAllBgcTable(); return; }
  const seq = ++summaryReaderSeq;
  const doc = document.getElementById('summary-reader-doc');
  if (doc) doc.innerHTML = '<div class="viz-placeholder text-sm">Loading all BGC records...</div>';
  try {
    const resp = await resultFetch(activeJobId, path);
    if (seq !== summaryReaderSeq) return;
    if (!resp.ok) throw new Error('The all-BGC table could not be opened with this result access code.');
    const text = await resp.text();
    const lines = String(text || '').split(/\r?\n/).filter(line => line.trim());
    if (!lines.length) throw new Error('The all-BGC table is empty.');
    const headers = parseDelimitedLine(lines[0], ',');
    const rows = lines.slice(1).map(line => {
      const cells = parseDelimitedLine(line, ',');
      return Object.fromEntries(headers.map((header, index) => [header, cells[index] || '']));
    });
    allBgcTableState = {
      path,
      rows,
      query: '',
      taxon: '',
      genome: '',
      sortKey: 'genome',
      sortDir: 'asc',
    };
    renderAllBgcTable();
  } catch (err) {
    if (doc) doc.innerHTML = '<div class="empty-state">' + escapeHtml(err.message || 'All BGC records are unavailable.') + '</div>';
  }
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

function summaryMetricValue(text, label) {
  const escaped = String(label || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp('^-\\s*(?:`)?' + escaped + '(?:`)?\\s*:\\s*(?:`([^`]+)`|(.+))$', 'im');
  const match = String(text || '').match(pattern);
  return match ? String(match[1] || match[2] || '').trim() : '';
}

function numericSummaryMetric(value) {
  const match = String(value || '').match(/\d+/);
  return match ? Number(match[0]) : 0;
}

function summaryTitleFromText(path, text) {
  const heading = String(text || '').match(/^#\s+(.+)$/m);
  const title = heading ? heading[1] : summaryArtifactLabel(path).replace(/\s+(MD|TSV|CSV|TXT|HTML?)$/i, '');
  return titleCaseArtifactLabel(title.replace(/[_-]+/g, ' '), 'Dataset-wide family atlas');
}

function summaryTopCount(text) {
  const atlasNow = numericSummaryMetric(summaryMetricValue(text, 'atlas_now'));
  if (atlasNow) return atlasNow;
  const topRows = String(text || '').match(/\bTop\s+`?(\d+)`?\s+rows\b/i);
  if (topRows) return Number(topRows[1]);
  const ranks = String(text || '').match(/^###\s+Atlas rank\s+\d+:/gim);
  return ranks ? ranks.length : 0;
}

function summaryCondensedTitle(path, text, count = 0) {
  const title = summaryTitleFromText(path, text).toUpperCase();
  return count ? `${title}: TOP ${count}` : title;
}

function renderMarkdownBody(text) {
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
    const heading = trimmed.match(/^(#{2,4})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = heading[1].length >= 3 ? 'h4' : 'h3';
      html.push(`<${level}>${escapeHtml(heading[2])}</${level}>`);
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

function condensedMarkdownBodyText(text) {
  const lines = String(text || '').split(/\r?\n/);
  const body = [];
  let sectionStarted = false;
  lines.forEach(line => {
    const trimmed = line.trim();
    if (/^##\s+/.test(trimmed)) sectionStarted = true;
    if (!sectionStarted) return;
    if (/source\s+summary/i.test(trimmed)) return;
    if (/`?data\/(jobs|results)\//i.test(trimmed)) return;
    body.push(line);
  });
  if (body.some(line => line.trim())) return body.join('\n').trim();
  return lines.filter(line => {
    const trimmed = line.trim();
    if (!trimmed) return false;
    if (/^#\s+/.test(trimmed)) return false;
    if (/source\s+summary/i.test(trimmed)) return false;
    if (/`?data\/(jobs|results)\//i.test(trimmed)) return false;
    return true;
  }).join('\n').trim();
}

function renderSummaryHeading(path, text, count) {
  return '<div class="summary-condensed-head"><div class="summary-condensed-title">' + escapeHtml(summaryCondensedTitle(path, text, count)) + '</div></div>';
}

const ATLAS_SUMMARY_COLUMNS = Object.freeze([
  { key: 'atlas_rank', label: 'Rank' },
  { key: 'genome', label: 'Representative organism' },
  { key: 'bigscape_cc', label: 'BiG-SCAPE CC' },
  { key: 'shared_cc_primary_families', label: 'GCF families' },
  { key: 'shared_cc_record_count', label: 'BGCs' },
  { key: 'shared_cc_dataset_genome_count', label: 'Genome count' },
  { key: 'member_genomes', label: 'Genome members' },
  { key: 'antismash_class', label: 'BGC class' },
  { key: 'annotation_hits', label: 'Scored annotation hits' },
  { key: 'note', label: 'Note' },
]);

function atlasMemberGenomes(row) {
  const organisms = String(row.shared_cc_dataset_organisms || '').split(';').map(value => value.trim()).filter(Boolean);
  if (organisms.length) return organisms.join(' · ');
  const genomes = String(row.shared_cc_dataset_genomes || '').split(';').map(value => value.trim()).filter(Boolean);
  return genomes.map(value => activeGenomeArtifactLabel(value, readableArtifactLabel(value))).join(' · ') || '—';
}

function atlasAnnotationHits(row) {
  const hits = [];
  const knownScore = String(row.antismash_knowncluster_similarity_score || '').trim();
  const knownLabel = [row.antismash_knowncluster_product, row.antismash_knowncluster_accession]
    .map(value => String(value || '').trim()).filter(Boolean).join(' · ');
  if (knownLabel || knownScore) hits.push(`KnownClusterBlast: ${knownLabel || 'hit'} · score ${knownScore || 'unavailable'}`);

  const compareScore = String(row.antismash_clustercompare_similarity_score || '').trim();
  const compareLabel = [row.antismash_clustercompare_compounds, row.antismash_clustercompare_organism]
    .map(value => String(value || '').trim()).filter(Boolean).join(' · ');
  if (compareLabel || compareScore) hits.push(`ClusterCompare: ${compareLabel || 'hit'} · score ${compareScore || 'unavailable'}`);

  const funScore = String(row.funbgcex_similarity_score || '').trim();
  const funLabel = [row.funbgcex_similar_bgc, row.funbgcex_putative_product]
    .map(value => String(value || '').trim()).filter(Boolean).join(' · ');
  if (funLabel || funScore) hits.push(`FunBGCeX similar BGC: ${funLabel || 'hit'} · score ${funScore || 'unavailable'}`);
  return hits.join(' | ') || 'No scored annotation hit';
}

function atlasTaxonSection(row) {
  const taxa = String(row.shared_cc_taxon_groups || row.taxon_group || '').toLowerCase()
    .split(';').map(value => value.trim()).filter(Boolean);
  const hasFungi = taxa.includes('fungi');
  const hasBacteria = taxa.includes('bacteria');
  if (hasFungi && hasBacteria) return 'cross';
  if (hasBacteria) return 'bacteria';
  if (hasFungi) return 'fungi';
  return 'unresolved';
}

function atlasSummaryValue(row, key) {
  if (key === 'genome') {
    const fallback = readableGenomeArtifactLabel(row.genome || '', 'Unknown organism');
    return activeGenomeArtifactLabel(row.genome || '', fallback);
  }
  if (key === 'member_genomes') return atlasMemberGenomes(row);
  if (key === 'annotation_hits') return atlasAnnotationHits(row);
  if (key === 'note') {
    const conservative = /product identity is not assigned/i.test(row.safe_claim_text || '')
      ? 'Product identity is not assigned.'
      : 'Putative annotation; confirm experimentally.';
    const followup = String(row.recommended_followup || '').trim().replace(/[.]+$/, '');
    return followup ? `${conservative} Follow-up: ${followup}.` : conservative;
  }
  if (key === 'antismash_class') return String(row[key] || '—').replace(/;/g, ' · ');
  return row[key] || '—';
}

function renderAtlasSummary(headers, bodyRows) {
  const records = bodyRows.map(cells => Object.fromEntries(headers.map((header, index) => [header, cells[index] || ''])));
  const sorted = records.slice().sort(
    (a, b) => (Number(a.atlas_rank) || Number.MAX_SAFE_INTEGER) - (Number(b.atlas_rank) || Number.MAX_SAFE_INTEGER),
  );
  const head = ATLAS_SUMMARY_COLUMNS.map(column => '<th>' + escapeHtml(column.label) + '</th>').join('');
  const sectionDefinitions = [
    { key: 'fungi', label: 'Fungal families' },
    { key: 'bacteria', label: 'Bacterial families' },
    { key: 'cross', label: 'Cross-kingdom families' },
    { key: 'unresolved', label: 'Unresolved-domain families' },
  ];
  const sections = sectionDefinitions.map(section => {
    const sectionRecords = sorted.filter(row => atlasTaxonSection(row) === section.key);
    if (!sectionRecords.length) return '';
    const prioritized = sectionRecords.filter(row => String(row.manual_review_bucket || '').toLowerCase() === 'atlas_now');
    const rows = prioritized.length ? prioritized : sectionRecords.slice(0, 20);
    const body = rows.map(row => '<tr>' + ATLAS_SUMMARY_COLUMNS.map(column => {
      const value = escapeHtml(atlasSummaryValue(row, column.key));
      const content = column.key === 'atlas_rank' ? '<span class="atlas-rank-badge">' + value + '</span>' : value;
      return '<td class="atlas-col-' + column.key + '">' + content + '</td>';
    }).join('') + '</tr>').join('');
    const scopeMeta = prioritized.length
      ? prioritized.length + ' prioritized · ' + sectionRecords.length + ' total'
      : rows.length + ' displayed · ' + sectionRecords.length + ' total';
    return '<section class="atlas-domain-section" data-atlas-domain="' + section.key + '">'
      + '<div class="atlas-domain-head"><h3>' + escapeHtml(section.label) + '</h3><span>' + escapeHtml(scopeMeta) + '</span></div>'
      + '<div class="summary-table-wrap atlas-table-wrap"><table class="summary-reader-table atlas-table"><thead><tr>'
      + head + '</tr></thead><tbody>' + body + '</tbody></table></div></section>';
  }).filter(Boolean).join('');
  const counts = sectionDefinitions.map(section => {
    const count = sorted.filter(row => atlasTaxonSection(row) === section.key).length;
    return count ? section.label.replace(/ families$/, '') + ' ' + count : '';
  }).filter(Boolean).join(' · ');
  return '<div class="summary-condensed-head"><div class="summary-condensed-title">DATASET-WIDE FAMILY ATLAS</div><div class="summary-condensed-meta">'
    + escapeHtml(records.length + ' total families' + (counts ? ' · ' + counts : '')) + '</div></div>'
    + sections;
}

function renderDelimitedSummary(path, text) {
  const delimiter = resultPathExt(path) === 'csv' ? ',' : '\t';
  const lines = String(text || '').split(/\r?\n/).filter(line => line.trim());
  if (!lines.length) return '<div class="empty-state">Summary file is empty.</div>';
  const headers = parseDelimitedLine(lines[0], delimiter);
  const bodyRows = lines.slice(1).map(line => parseDelimitedLine(line, delimiter));
  const kind = summaryReaderArtifactKind(path);
  if (!bodyRows.length) {
    const message = kind === 'target' ? 'No target candidates met the selection criteria.' : 'No atlas candidates met the selection criteria.';
    return renderSummaryHeading(path, '', 0) + '<div class="empty-state">' + escapeHtml(message) + '</div>';
  }
  if (kind === 'atlas') return renderAtlasSummary(headers, bodyRows);
  const indexes = preferredSummaryColumnIndexes(headers);
  const head = indexes.map(idx => '<th>' + escapeHtml(headers[idx] || 'Column ' + (idx + 1)) + '</th>').join('');
  const body = bodyRows.map(row => '<tr>' + indexes.map(idx => '<td>' + escapeHtml(row[idx] || '') + '</td>').join('') + '</tr>').join('');
  return renderSummaryHeading(path, '', bodyRows.length)
    + '<div class="summary-table-wrap"><table class="summary-reader-table"><thead><tr>'
    + head + '</tr></thead><tbody>' + body + '</tbody></table></div>';
}

function renderMarkdownSummary(path, text) {
  const topCount = summaryTopCount(text);
  const bodyText = condensedMarkdownBodyText(text);
  return `
    ${renderSummaryHeading(path, text, topCount)}
    <div class="summary-markdown-body">${renderMarkdownBody(bodyText)}</div>`;
}

function renderTextSummary(path, text) {
  const ext = resultPathExt(path);
  if (ext === 'tsv' || ext === 'csv') return renderDelimitedSummary(path, text);
  if (ext === 'md') return renderMarkdownSummary(path, text);
  const doc = new DOMParser().parseFromString(String(text || ''), ext === 'html' || ext === 'htm' ? 'text/html' : 'text/plain');
  if (ext === 'html' || ext === 'htm') {
    doc.querySelectorAll('script, style, iframe, object, embed').forEach(el => el.remove());
    return renderMarkdownSummary(path, (doc.body && doc.body.textContent) || '');
  }
  return renderMarkdownSummary(path, text);
}

async function loadSummaryReaderFile(path) {
  if (!activeJobId || !path) return;
  const seq = ++summaryReaderSeq;
  const doc = document.getElementById('summary-reader-doc');
  if (doc) doc.innerHTML = '<div class="viz-placeholder text-sm">Loading summary document...</div>';
  try {
    const resp = await resultFetch(activeJobId, path);
    if (seq !== summaryReaderSeq) return;
    if (!resp.ok) throw new Error('Summary document could not be opened with this result access code.');
    const text = await resp.text();
    if (doc) {
      doc.innerHTML = renderTextSummary(path, text);
      animateSummaryReaderDocument();
    }
  } catch (err) {
    if (doc) doc.innerHTML = `<div class="empty-state">${escapeHtml(err.message || 'Summary document unavailable.')}</div>`;
  }
}

function showResultDashboard() {
  if (!activeJobMeta && !activeJobId) return;
  resultDashboardOpen = true;
  document.body.dataset.managementView = 'closed';
  document.body.dataset.resultsDashboard = 'open';
  setResultsPanelCollapsed(true);
  const counts = resultCategoryCounts(activeResultFiles);
  const status = activeJobMeta?.status || 'pending';
  const completed = String(status || '').toLowerCase() === 'success';
  activeResultCategory = defaultFocusedResultCategory(counts);
  setResultFocusMode(completed ? 'focused' : 'overview');
  renderCompletionCallout(status);
  renderResultBubblePanel(activeResultFiles, status);
  if (completed) renderFocusedResultCategory(activeResultCategory);
  updateResultDashboardVisibility(status, counts.downloads);
  rerenderWorkflowSpineForResults();
  const spine = document.getElementById('weavemap');
  if (spine) spine.scrollTop = 0;
  const firstOutput = document.querySelector('.result-lollipop:not(:disabled)') || document.querySelector('.dna-result-output-trigger');
  const board = document.getElementById('result-dashboard-section');
  const focusTarget = firstOutput || spine || board || document.getElementById('results-card');
  focusTarget?.focus({ preventScroll: true });
  const pulseTarget = spine || board || focusTarget;
  pulseTarget?.classList.remove('section-focus');
  void pulseTarget?.offsetWidth;
  pulseTarget?.classList.add('section-focus');
  animateResultDashboardOpen(gsapMotion.lastJobLoadSource || 'open');
}

async function loadResults(jobId, status, seq = jobLoadSeq, job = activeJobMeta) {
  if (seq !== jobLoadSeq || jobId !== activeJobId) return;
  const card = document.getElementById('results-card');
  card.classList.remove('hidden');
  setResultsLoaded(true);
  const runId = publicRunIdForJob(jobId);
  if (!job) {
    const jobResp = await apiFetch(
      `api/results/${encodeURIComponent(runId)}`, {}, { kind: 'job', jobId: runId },
    );
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

  const resp = await apiFetch(
    `api/results/${encodeURIComponent(runId)}/artifacts`, {}, { kind: 'job', jobId: runId },
  );
  if (seq !== jobLoadSeq || jobId !== activeJobId) return;
  if (!resp.ok) return;
  const filePayload = await resp.json();
  const files = installResultArtifactDescriptors(filePayload.artifacts, { replace: true });
  if (activeJobMeta) {
    activeJobMeta.result_index_state = filePayload.result_index_state || '';
    activeJobMeta.bigscape_viewer_available = filePayload.bigscape_viewer_available === true;
  }
  if (seq !== jobLoadSeq || jobId !== activeJobId) return;
  const normalizedFiles = files.map(normalizedResultPath).filter(Boolean);
  renderQaDrawer(activeJobMeta, normalizedFiles);
  const counts = resultCategoryCounts(normalizedFiles);
  const openDashboard = shouldOpenResultDashboardDuringRefresh(normalizedFiles, activeJobMeta);
  resultDashboardOpen = openDashboard;
  document.body.dataset.resultsDashboard = openDashboard ? 'open' : 'closed';
  if (openDashboard) {
    document.body.dataset.managementView = 'closed';
    const completed = String(status || activeJobMeta?.status || '').toLowerCase() === 'success';
    const activeAvailable = resultCategoryAvailable(activeResultCategory, counts);
    if (completed && resultFocusMode !== 'focused') {
      activeResultCategory = defaultFocusedResultCategory(counts);
      setResultFocusMode('focused');
    } else if (!activeAvailable) {
      activeResultCategory = defaultFocusedResultCategory(counts);
      setResultFocusMode(completed ? 'focused' : 'overview');
    } else if (resultFocusMode === 'overview') {
      activeResultCategory = defaultFocusedResultCategory(counts);
    }
  }

  renderResultBubblePanel(normalizedFiles, status);
  if (openDashboard) {
    const dashboardMotionKey = `${jobId}|${normalizedFiles.join('|')}|${resultFocusMode}`;
    if (gsapMotion.lastDashboardMotionKey !== dashboardMotionKey) {
      gsapMotion.lastDashboardMotionKey = dashboardMotionKey;
      animateResultDashboardOpen(gsapMotion.lastJobLoadSource || 'refresh');
    }
  }
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
        <div>${escapeHtml(activeJobMeta?.error_summary || activeJobMeta?.error || 'This job did not finish, but partial outputs and logs remain available.')}</div>
        <div class="mt1 text-sm text-muted">${canUseAdminSurfaces() ? 'Use the QA Console logs and rerun controls to resume selected stages in the same job workspace.' : 'Check any files shown here, or submit a new run after fixing the input.'}</div>
      </div>`;
  }
  renderResultFileSurface(jobId, normalizedFiles);
  if (String(status || '').toLowerCase() !== 'success' && activeResultCategory !== 'figures' && normalizedFiles.length) {
    setResultReaderSurface('files');
  }
}

function rerunDefaultChecked(job, key) {
  if (!job || job.status === 'success') return false;
  if (!rerunStageAllowed(key)) return false;
  if (!activeStageState || !activeStageState.enabled.has(key)) return false;
  return !activeStageState.completed.has(key);
}

function rerunPanelMessage(title, copy, status = '') {
  return `
    <div class="summary-panel rerun-summary rerun-scope-card">
      <div class="summary-head rerun-scope-head">${escapeHtml(title)}</div>
      <div class="rerun-panel-body">
        <div class="help-note">${escapeHtml(copy)}</div>
        <div class="flex-gap">
          <button class="btn btn-primary text-sm" type="button" onclick="rerunActiveJob()">Queue rerun</button>
          <span class="text-muted text-sm" id="rerun-status">${escapeHtml(status)}</span>
        </div>
      </div>
    </div>`;
}

function selectedRerunJob(jobId, job) {
  const requestedId = String(rerunScopeOpenJobId || '');
  if (!requestedId) return { jobId: '', job: null };
  const inlineJobId = String((job && job.id) || jobId || '');
  if (inlineJobId === requestedId && job) return { jobId: requestedId, job };
  if (activeJobId === requestedId && activeJobMeta) return { jobId: requestedId, job: activeJobMeta };
  return { jobId: requestedId, job: jobHistoryById.get(requestedId) || null };
}

function renderRerunPanel(jobId, job) {
  const panel = document.getElementById('rerun-panel');
  if (!panel) return;
  if (!canUseAdminSurfaces()) {
    panel.innerHTML = '';
    return;
  }
  const selection = selectedRerunJob(jobId, job);
  if (!selection.jobId) {
    panel.innerHTML = rerunPanelMessage('Rerun scope', 'Select a submitted job, then use its Rerun button to open job-scoped rerun options.', 'No job selected.');
    return;
  }
  if (!selection.job) {
    panel.innerHTML = rerunPanelMessage('Rerun scope', `Loading selected job ${selection.jobId}.`, 'Waiting for job details.');
    return;
  }
  const status = String(selection.job.status || '').toLowerCase();
  if (status === 'pending' || status === 'running') {
    panel.innerHTML = rerunPanelMessage(
      'Rerun scope',
      `Run ${selection.jobId} is ${statusLabel(selection.job.status).toLowerCase()}. Rerun options unlock after the job finishes or fails.`,
      'Rerun unavailable while active.',
    );
    return;
  }
  if (!jobCanRerun(selection.job)) {
    panel.innerHTML = rerunPanelMessage('Rerun scope', `Run ${selection.jobId} cannot be rerun from its current state.`, 'Rerun unavailable.');
    return;
  }
  const stageRows = STAGES.map(stage => {
    const enabled = jobStageEnabled(selection.job, stage.key) && rerunStageAllowed(stage.key);
    const checked = enabled && rerunDefaultChecked(selection.job, stage.key);
    return `
      <label class="form-group-inline rerun-stage-option ${enabled ? '' : 'disabled'}">
        <input type="checkbox" class="rerun-stage" data-stage="${escapeHtml(stage.key)}" ${checked ? 'checked' : ''} ${enabled ? '' : 'disabled'} />
        <span>${escapeHtml(stage.label)}</span>
      </label>`;
  }).join('');
  panel.innerHTML = `
    <div class="summary-panel rerun-summary rerun-scope-card" data-rerun-job-id="${escapeHtml(selection.jobId)}">
      <div class="summary-head rerun-scope-head">
        <span>Rerun scope</span>
        <code>${escapeHtml(selection.jobId)}</code>
      </div>
      <div class="rerun-panel-body">
        <div class="help-note">Selected stages rerun inside this job workspace and reuse staged inputs/results.</div>
        <div class="rerun-grid">${stageRows}</div>
        <label class="form-group-inline rerun-stage-option"><input type="checkbox" id="rerun-force" /> <span>Force selected stages to overwrite existing outputs</span></label>
        <div class="flex-gap rerun-actions">
          <button class="btn btn-primary text-sm" type="button" onclick="rerunActiveJob()">Queue rerun</button>
          <button class="btn btn-ghost text-sm" type="button" onclick="toggleJobRerunScope(event,'${escapeHtml(escapeJsString(selection.jobId))}')">Close</button>
          <span class="text-muted text-sm" id="rerun-status"></span>
        </div>
      </div>
    </div>`;
  animateRerunPanelReady();
}

async function rerunActiveJob() {
  if (!canUseAdminSurfaces()) return;
  const targetJobId = String(rerunScopeOpenJobId || '');
  const statusEl = document.getElementById('rerun-status');
  if (!targetJobId) {
    if (statusEl) statusEl.textContent = 'Select a submitted job first.';
    return;
  }
  const job = activeJobId === targetJobId && activeJobMeta ? activeJobMeta : jobHistoryById.get(targetJobId);
  const status = String((job && job.status) || '').toLowerCase();
  if (status === 'pending' || status === 'running') {
    if (statusEl) statusEl.textContent = 'Wait until the selected job finishes or fails.';
    return;
  }
  const selected = new Set([...document.querySelectorAll('#rerun-panel .rerun-stage:checked')].map(el => el.dataset.stage));
  if (!selected.size) {
    if (statusEl) statusEl.textContent = 'Choose at least one stage.';
    return;
  }
  const payload = rerunPayloadFromStages(
    selected,
    !!document.getElementById('rerun-force')?.checked,
  );
  if (!rerunPayloadHasStages(payload)) {
    if (statusEl) statusEl.textContent = 'Choose at least one stage.';
    return;
  }
  if (statusEl) statusEl.textContent = 'Queueing rerun...';
  try {
    await queueJobRerun(targetJobId, payload);
    if (statusEl) statusEl.textContent = 'Rerun queued.';
    animateRerunQueued();
    rerunScopeOpenJobId = '';
    document.getElementById('results-card').classList.add('hidden');
    await loadJob(targetJobId, true, { source: 'rerun' });
    refreshJobHistory();
    switchOpsTab('jobs', { focus: false });
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

const APPROVED_PHYLOGENY_ARTIFACT_NAMES = new Set([
  'clusterweave_taxon_tree.svg',
  'clusterweave_taxon_tree.png',
  'clusterweave_taxon_tree.nwk',
  'clusterweave_taxon_tree_leaf_profiles.tsv',
  'clusterweave_gcf_network_edges.tsv',
  'clusterweave_taxon_tree.graphml',
  'clusterweave_tree_manifest.json',
  'clusterweave_tree_methods.json',
  'clusterweave_tree_bundle.zip',
]);

function approvedPhylogenyArtifact(path) {
  const descriptor = resultArtifactDescriptor(path);
  if (descriptor && resultCategoryKey(descriptor.category) === 'figures') {
    const descriptorName = String(descriptor.filename || '').toLowerCase();
    return APPROVED_PHYLOGENY_ARTIFACT_NAMES.has(descriptorName)
      ? { path: normalizedResultPath(path), name: descriptorName } : null;
  }
  const normalized = normalizedResultPath(path);
  const match = normalized.match(/^data\/results\/[^/]+\/figures\/phylogeny\/([^/]+)$/i);
  if (!match) return null;
  const name = String(match[1] || '').toLowerCase();
  if (!APPROVED_PHYLOGENY_ARTIFACT_NAMES.has(name)) return null;
  return { path: normalized, name };
}

function isApprovedPhylogenyArtifact(path) {
  return !!approvedPhylogenyArtifact(path);
}

function isTaxonTreeSvgAsset(path) {
  return approvedPhylogenyArtifact(path)?.name === 'clusterweave_taxon_tree.svg';
}

function isTaxonTreeVisualAsset(path) {
  const name = approvedPhylogenyArtifact(path)?.name || '';
  return name === 'clusterweave_taxon_tree.svg' || name === 'clusterweave_taxon_tree.png';
}

function isTaxonTreeBundleAsset(path) {
  return approvedPhylogenyArtifact(path)?.name === 'clusterweave_tree_bundle.zip';
}

function treeDataBundleForFigure(path, files) {
  if (!isTaxonTreeSvgAsset(path)) return '';
  const sourceDescriptor = resultArtifactDescriptor(path);
  if (sourceDescriptor) {
    return (files || []).find(candidate => {
      const descriptor = resultArtifactDescriptor(candidate);
      return isTaxonTreeBundleAsset(candidate) && descriptor?.bundle_id === sourceDescriptor.bundle_id;
    }) || '';
  }
  const normalized = normalizedResultPath(path);
  const directory = normalized.slice(0, normalized.lastIndexOf('/'));
  const expected = `${directory}/clusterweave_tree_bundle.zip`.toLowerCase();
  return (files || [])
    .map(normalizedResultPath)
    .find(candidate => candidate.toLowerCase() === expected && isTaxonTreeBundleAsset(candidate)) || '';
}

function isFigureAsset(path) {
  const descriptor = resultArtifactDescriptor(path);
  if (descriptor) return resultCategoryKey(descriptor.category) === 'figures'
    && /\.(svg|png|jpe?g|webp)$/i.test(descriptor.filename);
  const normalized = normalizedResultPath(path);
  return /^data\/results\/[^/]+\/figures\/[^/]+\.(svg|png|jpe?g|webp)$/i.test(normalized)
    || isTaxonTreeVisualAsset(normalized);
}

function isSvgFigureAsset(path) {
  const descriptor = resultArtifactDescriptor(path);
  if (descriptor) return resultCategoryKey(descriptor.category) === 'figures' && /\.svg$/i.test(descriptor.filename);
  const normalized = normalizedResultPath(path);
  return /^data\/results\/[^/]+\/figures\/[^/]+\.svg$/i.test(normalized)
    || isTaxonTreeSvgAsset(normalized);
}

function phylogenyArtifactLabel(path) {
  const artifact = approvedPhylogenyArtifact(path);
  if (!artifact) return '';
  const labels = {
    'clusterweave_taxon_tree.svg': 'Taxonomy/BGC/GCF context tree SVG',
    'clusterweave_taxon_tree.png': 'Taxonomy/BGC/GCF context tree PNG',
    'clusterweave_taxon_tree.nwk': 'Taxonomy context topology (Newick)',
    'clusterweave_taxon_tree_leaf_profiles.tsv': 'Taxon tree leaf BGC/GCF profiles',
    'clusterweave_gcf_network_edges.tsv': 'Complete GCF-sharing edge table',
    'clusterweave_taxon_tree.graphml': 'Taxonomy/BGC/GCF context graph',
    'clusterweave_tree_manifest.json': 'Taxon tree artifact manifest',
    'clusterweave_tree_methods.json': 'Taxon tree methods and provenance',
    'clusterweave_tree_bundle.zip': 'Complete taxon tree data bundle',
  };
  return labels[artifact.name] || '';
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
  const descriptor = resultArtifactDescriptor(path);
  if (lower === 'downloads/public_results_manifest.tsv') return 'Public results manifest';
  if (String(descriptor?.filename || '').toLowerCase() === 'clusterweave_evidence_manifest.tsv') return 'Checksummed evidence manifest';
  if (descriptor?.role === 'staged-genome-genbank') return `${descriptor.genome_label || fileStemFromPath(descriptor.filename)} staged genome GenBank`;
  if (/^downloads\/[^/]+_public_results\.zip$/i.test(normalized)) return 'Generated public results package';
  if (isApprovedPhylogenyArtifact(normalized)) return phylogenyArtifactLabel(normalized);
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
  if (/^data\/results\/[^/]+\/figures\/phylogeny$/i.test(normalized)) return true;
  if (/^data\/results\/[^/]+\/integrated_evidence$/i.test(normalized)) return true;
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
  const descriptor = resultArtifactDescriptor(f);
  const name = resultArtifactName(f);
  const label = fileRowLabel(f);
  const detail = descriptor ? resultCategoryLabel(descriptor.category) : normalizedResultPath(f);
  const downloadHref = resultHref(jobId, f, { download: true });
  const jsJobId = escapeJsString(jobId);
  const jsPath = escapeJsString(f);
  return `<tr>
    <td><span class="ext-badge">${escapeHtml(fileTypeLabel(f))}</span></td>
    <td>
      <span class="file-row-main">
        <span class="file-display-name">${escapeHtml(label)}</span>
        <span class="file-path-link">${escapeHtml(detail)}</span>
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
      <thead><tr><th>Type</th><th>File / Result</th><th></th></tr></thead>
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
    'fungi_big_scape_multipanel.svg',
    'fungi_big_scape_multipanel.png',
    'bacteria_big_scape_multipanel.svg',
    'bacteria_big_scape_multipanel.png',
    'bgc_overlap.svg',
    'bgc_overlap.png',
    'clusterweave_taxon_tree.svg',
    'clusterweave_taxon_tree.png',
    // Historical aliases remain discoverable for completed jobs.
    'big_scape_multipanel.svg',
    'big_scape_multipanel.png',
    'bacterial_multipanel.svg',
    'bacterial_multipanel.png',
  ];
  const idx = preferred.indexOf(name);
  const priority = idx === -1 ? preferred.length : idx;
  return `${String(priority).padStart(3, '0')}:${normalizedResultPath(path).toLowerCase()}`;
}

function figureCaption(path) {
  const name = fileNameFromPath(path).toLowerCase();
  if ([
    'fungi_big_scape_multipanel.svg',
    'fungi_big_scape_multipanel.png',
    'big_scape_multipanel.svg',
    'big_scape_multipanel.png',
  ].includes(name)) {
    return 'Fungal BiG-SCAPE multipanel combining stacked BGC/GCF count bars, cluster context, compound labels, and confidence evidence.';
  }
  if (name === 'bgc_overlap.svg' || name === 'bgc_overlap.png') {
    return 'Shared and tool-specific BGC scaffold overlap between antiSMASH and FunBGCeX by genome.';
  }
  if ([
    'bacteria_big_scape_multipanel.svg',
    'bacteria_big_scape_multipanel.png',
    'bacterial_multipanel.svg',
    'bacterial_multipanel.png',
  ].includes(name)) {
    return 'Bacterial BiG-SCAPE multipanel combining stacked antiSMASH BGC/GCF counts, cluster context, compound labels, and confidence evidence.';
  }
  if (isTaxonTreeVisualAsset(path)) {
    return 'Ranked NCBI taxonomy context with BGC-count-scaled composition markers and class-colored GCF-sharing arcs; branch lengths are not inferred.';
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

function preserveInlineSvgAccessibility(svg, path, index) {
  svg.setAttribute('role', 'img');
  const title = Array.from(svg.children).find(child => child.localName?.toLowerCase() === 'title');
  const desc = Array.from(svg.children).find(child => child.localName?.toLowerCase() === 'desc');
  const idSuffix = `${String(index + 1)}-${fileNameFromPath(path).replace(/[^A-Za-z0-9_-]+/g, '-')}`;
  if (title && String(title.textContent || '').trim()) {
    if (!title.id) title.id = `clusterweave-figure-title-${idSuffix}`;
    if (!svg.hasAttribute('aria-label') && !svg.hasAttribute('aria-labelledby')) {
      svg.setAttribute('aria-labelledby', title.id);
    }
  } else if (!svg.hasAttribute('aria-label') && !svg.hasAttribute('aria-labelledby')) {
    svg.setAttribute('aria-label', fileNameFromPath(path));
  }
  if (desc && String(desc.textContent || '').trim()) {
    if (!desc.id) desc.id = `clusterweave-figure-desc-${idSuffix}`;
    if (!svg.hasAttribute('aria-describedby')) svg.setAttribute('aria-describedby', desc.id);
  }
  return svg;
}

async function hydrateSvgFigures(jobId) {
  const stages = Array.from(document.querySelectorAll('.figure-svg-stage'))
    .filter(stage => stage.dataset.resultJob === jobId);
  for (const [index, stage] of stages.entries()) {
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
      const svg = preserveInlineSvgAccessibility(
        sanitizeInlineSvg(document.importNode(parsed, true)),
        path,
        index,
      );
      svg.classList.add('figure-preview', 'figure-svg-preview');
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

const FIGURE_FOLDER_VIEWS = Object.freeze([
  { key: 'fungal_families', label: 'FUNGAL FAMILIES', filename: 'fungi_big_scape_multipanel.svg' },
  { key: 'bacterial_families', label: 'BACTERIAL FAMILIES', filename: 'bacteria_big_scape_multipanel.svg' },
  { key: 'fungal_tool_overlap', label: 'FUNGAL TOOL OVERLAP', filename: 'bgc_overlap.svg' },
  { key: 'tree', label: 'TREE', filename: 'clusterweave_taxon_tree.svg' },
]);

function figureFolderDefinitions(files) {
  return FIGURE_FOLDER_VIEWS.map(folder => ({
    ...folder,
    path: (files || []).find(path => fileNameFromPath(path).toLowerCase() === folder.filename) || '',
  })).filter(folder => folder.path);
}

function switchFigureView(view) {
  const folders = figureFolderDefinitions(activeResultFiles);
  if (!folders.some(folder => folder.key === view)) return;
  activeFigureView = view;
  if (activeJobId) renderViz(activeJobId, activeResultFiles);
}

function renderFigureFolderTabs(folders) {
  if (!folders.length) return '';
  return `<div class="summary-subtabs figure-subtabs" role="tablist" aria-label="Figure result folders">${folders.map(folder => {
    const active = folder.key === activeFigureView;
    return `<button class="summary-subtab" type="button" role="tab" data-figure-view="${escapeHtml(folder.key)}" aria-selected="${active ? 'true' : 'false'}" tabindex="${active ? '0' : '-1'}" onclick="switchFigureView(this.dataset.figureView)">${escapeHtml(folder.label)}</button>`;
  }).join('')}</div>`;
}

function renderViz(jobId, files) {
  const capabilities = activeAnalysisCapabilities();
  let figureFiles = files
    .filter(path => isFigureAsset(path) && figureApplicableToAnalysis(path, capabilities))
    .sort((a, b) => figureSortKey(a).localeCompare(figureSortKey(b)));
  const figureFolders = figureFolderDefinitions(figureFiles);
  if (figureReaderJobId !== jobId) {
    figureReaderJobId = jobId;
    activeFigureView = figureFolders[0]?.key || '';
  }
  if (!figureFolders.some(folder => folder.key === activeFigureView)) {
    activeFigureView = figureFolders[0]?.key || '';
  }
  const selectedFigure = figureFolders.find(folder => folder.key === activeFigureView);
  if (selectedFigure) figureFiles = [selectedFigure.path];
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
  const cards = figureFiles.map((f, index) => {
    const name = fileNameFromPath(f);
    const href = resultHref(jobId, f);
    const downloadHref = resultHref(jobId, f, { download: true });
    const jsJobId = escapeJsString(jobId);
    const jsPath = escapeJsString(f);
    const isSvg = isSvgFigureAsset(f);
    const isTaxonTree = isTaxonTreeVisualAsset(f);
    const treeBundle = treeDataBundleForFigure(f, files);
    const treeDataAction = treeBundle ? resultDownloadLink(jobId, treeBundle, 'Tree data') : '';
    const instructionsId = `figure-preview-instructions-${index}`;
    const accessiblePreviewLabel = `Interactive preview: ${figureCaption(f)}`;
    const imgSrc = resultNeedsAuth(jobId) ? '' : escapeHtml(href);
    const preview = isSvg
      ? `<div class="figure-svg-stage" data-result-path="${escapeHtml(f)}" data-result-job="${escapeHtml(jobId)}"><div class="viz-placeholder text-sm">Loading vector preview...</div></div>`
      : `<img class="figure-preview" src="${imgSrc}" data-result-path="${escapeHtml(f)}" data-result-job="${escapeHtml(jobId)}" alt="${escapeHtml(name)}" draggable="false" />`;
    return `
      <div class="figure-panel${isTaxonTree ? ' is-taxon-tree' : ''}">
        <div class="figure-panel-head">
          <div class="figure-copy">
            <div class="figure-name">${escapeHtml(name)}</div>
            <div class="figure-caption">${escapeHtml(figureCaption(f))}</div>
          </div>
          <div class="figure-actions">
            <span class="ext-badge">${escapeHtml(fileTypeLabel(f))}</span>
            <a class="btn btn-ghost text-sm" href="${escapeHtml(href)}" target="_blank" onclick="return handleResultLinkClick(event,'${escapeHtml(jsJobId)}','${escapeHtml(jsPath)}',false)">Open</a>
            <a class="btn btn-ghost text-sm" href="${escapeHtml(downloadHref)}" download="${escapeHtml(name)}" onclick="return handleResultLinkClick(event,'${escapeHtml(jsJobId)}','${escapeHtml(jsPath)}',true)">Download</a>
            ${treeDataAction}
          </div>
        </div>
        <span class="sr-only" id="${escapeHtml(instructionsId)}">Use plus and minus to zoom, zero or Escape to reset, and drag to pan after zooming. The preview can also be opened or downloaded with the actions above.</span>
        <div class="figure-preview-wrap${isTaxonTree ? ' is-taxon-tree' : ''}"
          data-result-path="${escapeHtml(f)}"
          data-result-job="${escapeHtml(jobId)}"
          role="group"
          tabindex="0"
          aria-label="${escapeHtml(accessiblePreviewLabel)}"
          aria-describedby="${escapeHtml(instructionsId)}"
          aria-keyshortcuts="+ - 0 Escape"
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
  container.innerHTML = `${renderFigureFolderTabs(figureFolders)}<div class="figure-grid">${cards}</div>`;
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
    ? `${visibleCount} downloadable ${visibleCount === 1 ? 'file' : 'files'}`
    : `${visibleCount} shown from ${totalCount} indexed ${totalCount === 1 ? 'file' : 'files'}`;
  return `
    <div class="result-category-summary" id="result-category-summary">
      <div>
        <div class="result-category-title">${escapeHtml(label)}</div>
        <div class="result-category-copy">${escapeHtml(resultCategoryCopy(key))}</div>
      </div>
      <span class="ext-badge result-scope-badge">${escapeHtml(scope)}</span>
    </div>`;
}

function renderFileTable(jobId, files, options = {}) {
  const container = document.getElementById('files-container');
  activeResultFiles = (files || []).map(normalizedResultPath).filter(Boolean)
    .filter(path => !isPackageOnlyResultArtifact(path));
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
  if (visibleFiles.every(path => !!resultArtifactDescriptor(path))) {
    activeFileTree = null;
    activeFileTreeIndex = new Map();
    activeFileTreeJobId = null;
    container.innerHTML = `${summary}<div class="file-tree">${renderFileRows(jobId, visibleFiles)}</div>`;
    return;
  }
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
  renderWorkerDrawer(null, null, { status: 'unknown' });
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

function startPublicImpactPolling() {
  if (publicImpactPollTimer) return;
  publicImpactPollTimer = window.setInterval(() => {
    void fetchSystemStatus({ renderWorker: false });
  }, 15000);
}

async function pollSystemStatus() {
  if (!canUseAdminSurfaces()) return;
  let jobs;
  let system;
  try {
    const [jobsResp, systemPayload] = await Promise.all([
      apiFetch('api/jobs', {}, { kind: 'admin' }),
      fetchSystemStatus({ renderRuntime: false, renderWorker: false }),
    ]);
    if (!jobsResp.ok) return;
    jobs = await jobsResp.json();
    system = systemPayload || {};
  } catch (err) {
    updateWorkerTelemetryBadge('unknown', 'No signal');
    renderWorkerDrawer(null, null, { status: 'unknown' });
    return;
  }

  const worker = system.worker || {};
  const systemState = String(system.state || '').toLowerCase();
  const activeJobIds = Array.isArray(worker.active_jobs) ? worker.active_jobs.filter(Boolean) : [];
  const runningFromJobs = jobs.filter(j => ['running', 'processing'].includes(String(j.status || j.state || j.pipeline_state || '').toLowerCase())).length;
  const pendingFromJobs = jobs.filter(j => String(j.status || j.state || '').toLowerCase() === 'pending').length;
  const workerActiveCount = Number(worker.active_count || 0);
  const aggregateRunningCount = Number(system.running_jobs || 0);
  const aggregateQueuedCount = Number(system.queued_jobs || 0);
  const systemRunningCount = ['running', 'processing'].includes(systemState) ? Math.max(workerActiveCount, activeJobIds.length, aggregateRunningCount, 1) : 0;
  const runningCount = Math.max(runningFromJobs, workerActiveCount, activeJobIds.length, aggregateRunningCount, systemRunningCount);
  const pendingCount = Math.max(pendingFromJobs, aggregateQueuedCount);
  const rawConcurrency = Number(worker.concurrency || system.concurrency || 0);
  const activeCount = Math.max(workerActiveCount, activeJobIds.length, runningCount, aggregateRunningCount);
  const concurrency = rawConcurrency || lastWorkerTelemetry.concurrency || (activeCount > 0 ? Math.max(activeCount, 1) : 0);
  updateRuntimeStatusPanel(system, { runningJobs: runningCount, queuedJobs: pendingCount });
  const drawerStatus = systemState === 'error'
    ? 'error'
    : runningCount > 0
      ? 'processing'
      : pendingCount > 0
        ? 'ready'
        : 'idle';
  lastWorkerTelemetry = { runningCount, pendingCount, activeCount, concurrency, status: drawerStatus };
  renderWorkerDrawer(system, jobs, lastWorkerTelemetry);

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
  if (!term) return;
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
  { key: 'ncbi_cli', label: 'NCBI Datasets CLI' },
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
    ncbi_cli: 'Preparing NCBI Datasets CLI',
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

async function fetchSystemStatus(options = {}) {
  try {
    const resp = await apiFetch('api/system/status', { cache: 'no-store' }, { kind: 'admin' });
    if (!resp.ok) {
      const transient = resp.status === 429 || resp.status >= 500;
      if (transient) window.ClusterWeaveGame?.setConnectionState?.('reconnecting');
      if (!bootstrapComplete) {
        document.body.dataset.clusterweaveGameBootstrapEligible = transient ? 'true' : 'false';
      }
      return null;
    }
    const payload = await resp.json();
    window.ClusterWeaveGame?.setConnectionState?.('connected');
    if (!bootstrapComplete) {
      const bootstrapEligible = isFullSystemStatus(payload) && payload.ready !== true;
      document.body.dataset.clusterweaveGameBootstrapEligible = bootstrapEligible ? 'true' : 'false';
    }
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
    if (options.renderRuntime !== false) updateRuntimeStatusPanel(payload);
    if (options.renderWorker !== false) renderWorkerDrawer(payload);
    return payload;
  } catch (e) {
    window.ClusterWeaveGame?.setConnectionState?.(navigator.onLine === false ? 'browser-offline' : 'reconnecting');
    if (!bootstrapComplete) {
      document.body.dataset.clusterweaveGameBootstrapEligible = 'true';
    }
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
  const initialHashRun = captureInitialResultHash();
  window.addEventListener('hashchange', syncNavFromHash);
  window.addEventListener('resize', () => {
    applyStoredPanelWidths();
    const helix = document.getElementById('weavemap-helix');
    if (helix) delete helix.dataset.rendered;
    renderWeaveHelix(activeJobMeta);
    });
  startStageTicker();
  wireClusterweaveGameAdapter();
  wirePanelResizers();
  wireOpsPanelKeyboard();
  syncOpsTabs();
  initializeRetiredMotionControls();
  wireMotionLifecycleGuards();
  const reducedMotionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  reducedMotionQuery?.addEventListener?.('change', () => {
    const helix = document.getElementById('weavemap-helix');
    if (helix) delete helix.dataset.rendered;
    if (reducedMotionPreferred()) {
      teardownGsapMotion('reduced-motion');
    } else {
      warmGsapMotion();
    }
    renderWeaveHelix(activeJobMeta);
    });
  applyStoredPanelWidths();
  moveWorkflowProgressIntoResults(false);
  updateAccessTokenStatus();
  updateEmailNotificationPanel();
  renderOpenedRuns();
  wireRunStackDismissal();
  resetStagedAnalysisState('fungi');
  renderAcceptedAccessions();
  initializeBrutalInputStation();
  switchEntryTab('new');
  showEmptyResults();
  bootBgcWorkflowDna();
  updateBgcWorkflowDnaFromJob(null);
  wireDocsDisclosure();
  syncNavFromHash();
  setUIMode('guided', { preserveDisclosure: true });
  warmGsapMotion();

  // Wait for worker bootstrap to complete
  await waitForWorkerReady();

  // Now initialize the main UI
  refreshJobHistory();
  setInterval(refreshJobHistory, 5000);
  applyPreset('balanced');

  // Keep the aggregate public impact audit fresh without hydrating job data.
  startPublicImpactPolling();
  // Admin telemetry has its own shorter cadence.
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
    'genome-parallelism',
    'antismash-record-parallelism',
    'antismash-shard-cpus',
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
  const hashRun = initialHashRun || parseResultHash();
  if (hashRun) {
    switchEntryTab('existing');
    const job = await loadJob(hashRun.jobId, true, { readToken: hashRun.token, publicResult: hashRun.publicResult, source: 'result-link', deferResultsShell: true });
    document.body.dataset.existingRunLoaded = job ? 'true' : 'false';
    if (job) navigateToSection(null, 'outputs');
  }
}

// Start the app initialization
initializeApp().catch(err => console.error('Initialization failed:', err));
