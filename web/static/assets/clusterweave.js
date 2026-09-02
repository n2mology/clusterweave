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

let jobHistoryInFlight = false;
let lastJobHistoryRenderKey = '';
let jobHistoryById = new Map();
let rerunScopeOpenJobId = '';
let accessMode = 'public'; // public, admin, local
let authChecked = false;

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

let validatedIntakeSignature = '';

let resultAccessCollapsed = false;
let runStackOpen = false;
let runStackDismissalWired = false;
const MANUAL_ACCESSIONS_FILENAME = 'manual_accessions.txt';
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
let bgcWorkflowDna = null;
let bgcWorkflowDnaLoading = false;
let bgcWorkflowPendingPayload = null;
let clusterweaveGameEpoch = 0;
let clusterweaveGameDnaSuspended = false;
let bgcWorkflowDnaGenomeLayerSuspended = false;
let clusterweaveGameAdapterWired = false;
let clusterweaveGameAssetsPromise = null;
let clusterweaveGamePendingHost = null;
let clusterweaveGameDemandWired = false;
let clusterweaveGameConnectionState = navigator.onLine === false ? 'browser-offline' : 'connected';

const GSAP_BROWSER_PATH = 'vendor/gsap-3.15.0/gsap.min.js';
const WORKFLOW_DNA_MODULE_PATH = new URL('assets/workflow-dna-progress.js?v=20260713-fanout-ui1', window.location.href).toString();
const API_RESULT_MODULE_PATH = new URL('assets/api-result-boundary.js?v=20260725-r12a1', window.location.href).toString();
const RESULT_READER_MODULE_PATH = new URL('assets/result-reader-boundary.js?v=20260827-bigscape-family1', window.location.href).toString();
const INTAKE_TAXON_MODULE_PATH = new URL('assets/intake-taxon-boundary.js?v=20260902-input-station1', window.location.href).toString();
const JOB_LIFECYCLE_MODULE_PATH = new URL('assets/job-lifecycle-boundary.js?v=20260727-r12g1', window.location.href).toString();
const PROGRESS_TREE_MODULE_PATH = new URL('assets/progress-tree.js?v=20260730-stage-tree2', window.location.href).toString();
const PROGRESS_TREE_CONTRACT_PATH = new URL('assets/progress-tree-contract.json?v=20260730-stage-tree2', window.location.href).toString();
const DIAGNOSTICS_ACCESS_MODULE_PATH = new URL('assets/diagnostics-access-boundary.js?v=20260727-r12h1', window.location.href).toString();
const MOTION_MODULE_PATH = new URL('assets/motion-boundary.js?v=20260727-r12h1', window.location.href).toString();
const CLUSTERWEAVE_GAME_ASSET_SELECTOR = 'meta[name="clusterweave-game-asset"]';
let apiResultBoundary = null;
let resultReaderBoundary = null;
let intakeTaxonBoundary = null;
let intakeControllerBoundary = null;
let jobLifecycleBoundary = null;
let jobLifecycleControllerBoundary = null;
let diagnosticsAccessBoundary = null;
let diagnosticsControllerBoundary = null;
let motionBoundary = null;
const progressTreeConsolePromise = Promise.all([
  import(PROGRESS_TREE_MODULE_PATH),
  fetch(PROGRESS_TREE_CONTRACT_PATH, { cache: 'no-store' }).then(response => {
    if (!response.ok) throw new Error('Progress-tree contract is unavailable');
    return response.json();
  }),
]).then(([module, contract]) => module.createProgressTreeConsole({
  documentImpl: document,
  contract,
  createRawLineElement: text => createLogLineElement(text),
}));
const resultReaderState = {
  get activeJobId() { return activeJobId; },
  set activeJobId(value) { activeJobId = value; },
  get activeJobMeta() { return activeJobMeta; },
  set activeJobMeta(value) { activeJobMeta = value; },
  get activeResultArtifactById() { return activeResultArtifactById; },
  set activeResultArtifactById(value) { activeResultArtifactById = value; },
  get activeResultArtifactByKey() { return activeResultArtifactByKey; },
  set activeResultArtifactByKey(value) { activeResultArtifactByKey = value; },
  get activeResultArtifacts() { return activeResultArtifacts; },
  set activeResultArtifacts(value) { activeResultArtifacts = value; },
  get activeResultCategory() { return activeResultCategory; },
  set activeResultCategory(value) { activeResultCategory = value; },
  get activeResultFiles() { return activeResultFiles; },
  set activeResultFiles(value) { activeResultFiles = value; },
  get activeResultPackageFileCount() { return activeResultPackageFileCount; },
  set activeResultPackageFileCount(value) { activeResultPackageFileCount = value; },
  get resultDashboardOpen() { return resultDashboardOpen; },
  set resultDashboardOpen(value) { resultDashboardOpen = value; },
  get resultFocusMode() { return resultFocusMode; },
  set resultFocusMode(value) { resultFocusMode = value; },
};
const intakeControllerState = {
  get selectedFiles() { return selectedFiles; },
  set selectedFiles(value) { selectedFiles = value; },
  get acceptedManualAccessions() { return acceptedManualAccessions; },
  set acceptedManualAccessions(value) { acceptedManualAccessions = value; },
  get accessionFileSources() { return accessionFileSources; },
  set accessionFileSources(value) { accessionFileSources = value; },
  get accessionFileSourceSerial() { return accessionFileSourceSerial; },
  set accessionFileSourceSerial(value) { accessionFileSourceSerial = value; },
  get genomeCheckCache() { return genomeCheckCache; },
  set genomeCheckCache(value) { genomeCheckCache = value; },
  get genbankTaxonomyAuthorityCache() { return genbankTaxonomyAuthorityCache; },
  set genbankTaxonomyAuthorityCache(value) { genbankTaxonomyAuthorityCache = value; },
  get brutalInputNotices() { return brutalInputNotices; },
  set brutalInputNotices(value) { brutalInputNotices = value; },
  get stagedAnalysisScope() { return stagedAnalysisScope; },
  set stagedAnalysisScope(value) { stagedAnalysisScope = value; },
  get stagedTaxonAssignments() { return stagedTaxonAssignments; },
  set stagedTaxonAssignments(value) { stagedTaxonAssignments = value; },
  get stagedTaxonAssignmentSources() { return stagedTaxonAssignmentSources; },
  set stagedTaxonAssignmentSources(value) { stagedTaxonAssignmentSources = value; },
  get taxonAssignmentSidecar() { return taxonAssignmentSidecar; },
  set taxonAssignmentSidecar(value) { taxonAssignmentSidecar = value; },
  get taxonAssignmentSidecarIssues() { return taxonAssignmentSidecarIssues; },
  set taxonAssignmentSidecarIssues(value) { taxonAssignmentSidecarIssues = value; },
  get validatedIntakeSignature() { return validatedIntakeSignature; },
  set validatedIntakeSignature(value) { validatedIntakeSignature = value; },
  get publicQuota() { return publicQuota; },
  set publicQuota(value) { publicQuota = value; },
  get runtimeStatusSnapshot() { return runtimeStatusSnapshot; },
  get smtpEnabled() { return smtpEnabled; },
  get publicResultRunIds() { return publicResultRunIds; },
};
const jobLifecycleControllerState = {
  get activeJobId() { return activeJobId; },
  set activeJobId(value) { activeJobId = value; },
  get activeJobMeta() { return activeJobMeta; },
  set activeJobMeta(value) { activeJobMeta = value; },
  get activePublicRunId() { return activePublicRunId; },
  set activePublicRunId(value) { activePublicRunId = value; },
  get activeResultArtifactById() { return activeResultArtifactById; },
  set activeResultArtifactById(value) { activeResultArtifactById = value; },
  get activeResultArtifactByKey() { return activeResultArtifactByKey; },
  set activeResultArtifactByKey(value) { activeResultArtifactByKey = value; },
  get activeResultArtifacts() { return activeResultArtifacts; },
  set activeResultArtifacts(value) { activeResultArtifacts = value; },
  get activeResultCategory() { return activeResultCategory; },
  set activeResultCategory(value) { activeResultCategory = value; },
  get activeResultFiles() { return activeResultFiles; },
  set activeResultFiles(value) { activeResultFiles = value; },
  get activeResultPackageFileCount() { return activeResultPackageFileCount; },
  set activeResultPackageFileCount(value) { activeResultPackageFileCount = value; },
  get activeStageState() { return activeStageState; },
  set activeStageState(value) { activeStageState = value; },
  get bgcWorkflowDna() { return bgcWorkflowDna; },
  set bgcWorkflowDna(value) { bgcWorkflowDna = value; },
  get bgcWorkflowDnaLoading() { return bgcWorkflowDnaLoading; },
  set bgcWorkflowDnaLoading(value) { bgcWorkflowDnaLoading = value; },
  get bgcWorkflowPendingPayload() { return bgcWorkflowPendingPayload; },
  set bgcWorkflowPendingPayload(value) { bgcWorkflowPendingPayload = value; },
  get clusterweaveGameEpoch() { return clusterweaveGameEpoch; },
  set clusterweaveGameEpoch(value) { clusterweaveGameEpoch = value; },
  get gsapMotion() { return gsapMotion; },
  set gsapMotion(value) { gsapMotion = value; },
  get jobHistoryById() { return jobHistoryById; },
  set jobHistoryById(value) { jobHistoryById = value; },
  get jobHistoryInFlight() { return jobHistoryInFlight; },
  set jobHistoryInFlight(value) { jobHistoryInFlight = value; },
  get jobLoadSeq() { return jobLoadSeq; },
  set jobLoadSeq(value) { jobLoadSeq = value; },
  get lastJobHistoryRenderKey() { return lastJobHistoryRenderKey; },
  set lastJobHistoryRenderKey(value) { lastJobHistoryRenderKey = value; },
  get lastSubmittedRun() { return lastSubmittedRun; },
  set lastSubmittedRun(value) { lastSubmittedRun = value; },
  get logCursor() { return logCursor; },
  set logCursor(value) { logCursor = value; },
  get logGeneration() { return logGeneration; },
  set logGeneration(value) { logGeneration = value; },
  get logHydratedJobId() { return logHydratedJobId; },
  set logHydratedJobId(value) { logHydratedJobId = value; },
  get logHydrationInFlight() { return logHydrationInFlight; },
  set logHydrationInFlight(value) { logHydrationInFlight = value; },
  get logTotal() { return logTotal; },
  set logTotal(value) { logTotal = value; },
  get logWindowStart() { return logWindowStart; },
  set logWindowStart(value) { logWindowStart = value; },
  get pendingReadTokens() { return pendingReadTokens; },
  set pendingReadTokens(value) { pendingReadTokens = value; },
  get pollTimerId() { return pollTimerId; },
  set pollTimerId(value) { pollTimerId = value; },
  get publicResultRunIds() { return publicResultRunIds; },
  set publicResultRunIds(value) { publicResultRunIds = value; },
  get rerunScopeOpenJobId() { return rerunScopeOpenJobId; },
  set rerunScopeOpenJobId(value) { rerunScopeOpenJobId = value; },
  get resultDashboardOpen() { return resultDashboardOpen; },
  set resultDashboardOpen(value) { resultDashboardOpen = value; },
  get runStackDismissalWired() { return runStackDismissalWired; },
  set runStackDismissalWired(value) { runStackDismissalWired = value; },
  get runStackOpen() { return runStackOpen; },
  set runStackOpen(value) { runStackOpen = value; },
  get stageTickerId() { return stageTickerId; },
  set stageTickerId(value) { stageTickerId = value; },
  get weaveActivity() { return weaveActivity; },
  set weaveActivity(value) { weaveActivity = value; },
};
const diagnosticsControllerState = {
  get runtimeStatusSnapshot() { return runtimeStatusSnapshot; },
  set runtimeStatusSnapshot(value) { runtimeStatusSnapshot = value; },
  get runtimeCapabilities() { return runtimeCapabilities; },
  set runtimeCapabilities(value) { runtimeCapabilities = value; },
  get lastWorkerTelemetry() { return lastWorkerTelemetry; },
  set lastWorkerTelemetry(value) { lastWorkerTelemetry = value; },
  get workerStatus() { return workerStatus; },
  set workerStatus(value) { workerStatus = value; },
  get activeJobMeta() { return activeJobMeta; },
  set activeJobMeta(value) { activeJobMeta = value; },
  get activeResultFiles() { return activeResultFiles; },
  set activeResultFiles(value) { activeResultFiles = value; },
  get activeJobId() { return activeJobId; },
  set activeJobId(value) { activeJobId = value; },
  get rerunScopeOpenJobId() { return rerunScopeOpenJobId; },
  set rerunScopeOpenJobId(value) { rerunScopeOpenJobId = value; },
  get jobHistoryById() { return jobHistoryById; },
  set jobHistoryById(value) { jobHistoryById = value; },
  get logCursor() { return logCursor; },
  set logCursor(value) { logCursor = value; },
  get activeStageState() { return activeStageState; },
  set activeStageState(value) { activeStageState = value; },
  get lastJobHistoryRenderKey() { return lastJobHistoryRenderKey; },
  set lastJobHistoryRenderKey(value) { lastJobHistoryRenderKey = value; },
  get systemPollTimer() { return systemPollTimer; },
  set systemPollTimer(value) { systemPollTimer = value; },
};
const motionBoundaryState = {
  get activeJobMeta() { return activeJobMeta; },
  get resultFocusMode() { return resultFocusMode; },
};
const jobLifecycleBoundaryInstalled = new Promise((resolve, reject) => {
  window.__clusterweaveInstallJobLifecycleBoundary = (createJobLifecycleBoundary, createJobLifecycleControllerBoundary) => {
    jobLifecycleBoundary = createJobLifecycleBoundary({
      escapeHtml,
      getActiveJobId: () => activeJobId,
      getCurrentJobSequence: () => jobLoadSeq,
      documentImpl: document,
      stages: STAGES,
      transientJobPoll: TRANSIENT_JOB_POLL,
      pollBaseDelayMs: JOB_POLL_BASE_DELAY_MS,
      pollRetryDelayMs: JOB_POLL_RETRY_DELAY_MS,
      pollLongLogDelayMs: JOB_POLL_LONG_LOG_DELAY_MS,
      pollLongLogThreshold: JOB_POLL_LONG_LOG_THRESHOLD,
    });
    jobLifecycleControllerBoundary = createJobLifecycleControllerBoundary({
      state: jobLifecycleControllerState,
      lifecyclePolicy: jobLifecycleBoundary,
      capabilities: {
        activeAnalysisCapabilities,
        adoptPublicRunIdentity,
        animateLaunchTransition,
        apiFetch,
        canUseAdminSurfaces,
        diagnosticRerunDisclosureId,
        dismissSubmissionConfirmation,
        envToBool,
        escapeHtml,
        escapeJsString,
        loadOpenedRuns,
        loadResults,
        navigateToSection,
        normalizedResultPath,
        openOpsPanel,
        pollSystemStatus,
        publicRunIdForJob,
        readTokenForJob,
        rememberClusterweaveGameConnectionState,
        rememberOpenedRun,
        renderDiagnosticRerunRail,
        renderOpenedRuns,
        renderQaDrawer,
        renderWeaveHelix,
        rerunStageAllowed,
        resetToIdleWorkbench,
        scrollElementToBottom,
        setActiveSavedAnalysisContext,
        setBgcWorkflowAggregatePresentationSuspended,
        setBgcWorkflowGenomeLayerSuspended,
        setDrawerText,
        setResultFocusMode,
        setResultsPanelCollapsed,
        setUIMode,
        shouldPreserveResultsDashboardForJobLoad,
        showEmptyResults,
        showResultsShell,
        syncBgcWorkflowDnaSuspension,
        syncClusterweaveGameHost,
        syncOpsTabs,
        toggleJobRerunScope,
        updateDiagnosticRerunSubmit,
        activeOpsTab: () => diagnosticsAccessBoundary.activeOpsTab(),
        currentUIMode: () => diagnosticsAccessBoundary.currentUIMode(),
      },
      qaLogPageSize: QA_LOG_PAGE_SIZE,
      stages: STAGES,
      stageRuntimeHints: STAGE_RUNTIME_HINTS,
      workflowProgressWeights: WORKFLOW_PROGRESS_WEIGHTS,
      stageDetails: STAGE_DETAILS,
      pollBaseDelayMs: JOB_POLL_BASE_DELAY_MS,
      pollTimeoutMs: JOB_POLL_TIMEOUT_MS,
      initialLoadTimeoutMs: JOB_INITIAL_LOAD_TIMEOUT_MS,
      transientJobPoll: TRANSIENT_JOB_POLL,
      workflowDnaModulePath: WORKFLOW_DNA_MODULE_PATH,
      progressTreeConsolePromise,
    });
    delete window.__clusterweaveInstallJobLifecycleBoundary;
    resolve();
  };
  const script = document.createElement('script');
  script.type = 'module';
  script.src = JOB_LIFECYCLE_MODULE_PATH;
  script.addEventListener('error', reject, { once: true });
  document.head.appendChild(script);
});
const diagnosticsAccessBoundaryInstalled = new Promise((resolve, reject) => {
  window.__clusterweaveInstallDiagnosticsAccessBoundary = (createBoundary, createControllerBoundary) => {
    diagnosticsAccessBoundary = createBoundary({
      documentImpl: document,
      windowImpl: window,
      canUseAdminSurfaces,
      setCardCollapsed,
      hydrateQaLogs,
      shouldTailQaLogs: () => logHydratedJobId !== activeJobId,
      refreshJobHistory,
      pollSystemStatus,
      renderRerunPanel,
      activeJob: () => ({ jobId: activeJobId, job: activeJobMeta }),
      cssAttributeValue,
      animateOpsPanelToggle,
    });
    diagnosticsControllerBoundary = createControllerBoundary({
      document,
      window,
      state: diagnosticsControllerState,
      stages: STAGES,
      capabilities: {
        animateRerunPanelOpen,
        animateRerunPanelReady,
        animateRerunQueued,
        apiFetch,
        canUseAdminSurfaces,
        escapeHtml,
        escapeJsString,
        fetchSystemStatus,
        isFullSystemStatus,
        jobCanRerun,
        jobProjectName,
        jobStageDisplay,
        jobStageEnabled,
        loadJob,
        normalizedResultPath,
        openOpsPanel,
        refreshJobHistory,
        renderJobHistory,
        rerunPayloadFromStages,
        rerunPayloadHasStages,
        rerunStageAllowed,
        rerunStageKeysForJob,
        statusLabel,
        switchOpsTab,
        updateRuntimeStatusChip,
      },
    });
    delete window.__clusterweaveInstallDiagnosticsAccessBoundary;
    resolve();
  };
  const script = document.createElement('script');
  script.type = 'module';
  script.src = DIAGNOSTICS_ACCESS_MODULE_PATH;
  script.addEventListener('error', reject, { once: true });
  document.head.appendChild(script);
});
const motionBoundaryInstalled = new Promise((resolve, reject) => {
  window.__clusterweaveInstallMotionBoundary = createBoundary => {
    motionBoundary = createBoundary({
      document,
      window,
      state: motionBoundaryState,
      gsapMotion,
      retiredMotionStorageKeys: RETIRED_MOTION_STORAGE_KEYS,
      gsapBrowserPath: GSAP_BROWSER_PATH,
      renderWeaveHelix,
    });
    delete window.__clusterweaveInstallMotionBoundary;
    resolve();
  };
  const script = document.createElement('script');
  script.type = 'module';
  script.src = MOTION_MODULE_PATH;
  script.addEventListener('error', reject, { once: true });
  document.head.appendChild(script);
});
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



// ── Helpers ────────────────────────────────────────────────────────────────
function setCardCollapsed(id, collapsed) {
  const body = document.getElementById(id + '-body');
  const hdr = document.querySelector('#' + id + ' .card-header');
  if (body) body.classList.toggle('hidden', collapsed);
  if (hdr) hdr.classList.toggle('collapsed', collapsed);
}

function setOpsPanelCollapsed(collapsed) { return diagnosticsAccessBoundary.setOpsPanelCollapsed(collapsed); }
function ensureOpsPanelToggle() { return diagnosticsAccessBoundary.ensureOpsPanelToggle(); }
function removeOpsPanelToggle() { return diagnosticsAccessBoundary.removeOpsPanelToggle(); }
function activeOpsPanelElement() { return diagnosticsAccessBoundary.activeOpsPanelElement(); }
function syncOpsTabs() { return diagnosticsAccessBoundary.syncOpsTabs(); }
function switchOpsTab(tab, options = {}) { return diagnosticsAccessBoundary.switchOpsTab(tab, options); }
function handleOpsTabKeydown(event) { return diagnosticsAccessBoundary.handleOpsTabKeydown(event); }
function openOpsPanel(options = {}) { return diagnosticsAccessBoundary.openOpsPanel(options); }
function closeOpsPanel(options = {}) { return diagnosticsAccessBoundary.closeOpsPanel(options); }
function toggleOpsPanel() { return diagnosticsAccessBoundary.toggleOpsPanel(); }
function wireOpsPanelKeyboard() { return diagnosticsAccessBoundary.wireOpsPanelKeyboard(); }

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
}

function setUIMode(mode, options = {}) { return diagnosticsAccessBoundary.setUIMode(mode, { ...options, accessMode }); }

function setAccessMode(mode) {
  const hadAdminSurfaces = canUseAdminSurfaces();
  accessMode = diagnosticsAccessBoundary.normalizeAccessMode(mode);
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
  if (publicWorkflowLocked()) return publicQuotaLimits().max_cpus_per_job;
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
  const canonicalCpus = effectiveCpuCount();
  const cpus = document.getElementById('cpus');
  if (cpus) cpus.value = String(canonicalCpus);
  const annoCpus = document.getElementById('anno-cpus');
  if (annoCpus) annoCpus.value = String(canonicalCpus);
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
        switchToolCreditTab('support');
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
    if (diagnosticsAccessBoundary.currentUIMode() === 'guided') setUIMode('lab', { preserveDisclosure: true });
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

function runtimeMetricText(value, fallback = 'Not available') { return diagnosticsControllerBoundary.runtimeMetricText(...arguments); }
function setRuntimePanelValue(id, value) { return diagnosticsControllerBoundary.setRuntimePanelValue(...arguments); }
function updateRuntimeStatusPanel(system = null, counts = {}) { return diagnosticsControllerBoundary.updateRuntimeStatusPanel(...arguments); }
function setDrawerText(id, value) { return diagnosticsControllerBoundary.setDrawerText(...arguments); }
function pluralizeCount(count, noun) { return diagnosticsControllerBoundary.pluralizeCount(...arguments); }
function capabilityEnabled(value) { return diagnosticsControllerBoundary.capabilityEnabled(...arguments); }
function capabilityStageSummary(capabilities = runtimeCapabilities) { return diagnosticsControllerBoundary.capabilityStageSummary(...arguments); }
function runtimePolicyLabel(system = null) { return diagnosticsControllerBoundary.runtimePolicyLabel(...arguments); }
function renderWorkerDrawer(system = null, jobs = null, meta = {}) { return diagnosticsControllerBoundary.renderWorkerDrawer(...arguments); }
function renderQaDrawer(job = activeJobMeta, files = activeResultFiles) { return diagnosticsControllerBoundary.renderQaDrawer(...arguments); }

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


function shortRunId(jobId) { return jobLifecycleControllerBoundary.shortRunId(...arguments); }

function runStackProjectName(run) { return jobLifecycleControllerBoundary.runStackProjectName(...arguments); }

function runStackStatus(run) { return jobLifecycleControllerBoundary.runStackStatus(...arguments); }

function setRunStackOpen(open) { return jobLifecycleControllerBoundary.setRunStackOpen(...arguments); }

function toggleRunStack() { return jobLifecycleControllerBoundary.toggleRunStack(...arguments); }

function renderRunStack(runs = loadOpenedRuns()) { return jobLifecycleControllerBoundary.renderRunStack(...arguments); }

async function loadRunStackJob(jobId) { return jobLifecycleControllerBoundary.loadRunStackJob(...arguments); }

function addRunFromStack() { return jobLifecycleControllerBoundary.addRunFromStack(...arguments); }

function wireRunStackDismissal() { return jobLifecycleControllerBoundary.wireRunStackDismissal(...arguments); }

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
  const names = ['support', 'web', 'local'];
  const selected = names.includes(name) ? name : 'support';
  document.querySelectorAll('.tool-credit-tab').forEach(tab => {
    const active = tab.dataset.toolCreditTab === selected;
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
  const selected = tabs[next]?.dataset.toolCreditTab || 'support';
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

  let fragmentMatch = raw.match(/#\/?(job|results)\/([^/\s#?]+)\/([^/\s#?]+)/i);
  if (!fragmentMatch) {
    let text = raw;
    try {
      const url = new URL(raw, window.location.href);
      text = url.hash || url.pathname || raw;
    } catch (e) {}
    fragmentMatch = text.match(/#\/?(job|results)\/([^/\s#?]+)\/([^/\s#?]+)/i);
  }
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

function defaultApiBaseUrl() { return apiResultBoundary.defaultApiBaseUrl(); }

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

function artifactCategoryFromDescriptor(descriptor) { return resultReaderBoundary.artifactCategoryFromDescriptor(descriptor); }

function safeArtifactFilename(value, fallback = 'artifact') { return resultReaderBoundary.safeArtifactFilename(value, fallback); }

function artifactPresentationKey(descriptor) { return resultReaderBoundary.artifactPresentationKey(descriptor); }

function resultArtifactMaps(resultContext = null) { return resultReaderBoundary.resultArtifactMaps(resultContext); }

function installResultArtifactDescriptor(rawDescriptor, resultContext = null) { return resultReaderBoundary.installResultArtifactDescriptor(rawDescriptor, resultContext); }

function installResultArtifactDescriptors(rawDescriptors, options = {}) { return resultReaderBoundary.installResultArtifactDescriptors(rawDescriptors, options); }

function resultArtifactDescriptor(value, resultContext = null) { return resultReaderBoundary.resultArtifactDescriptor(value, resultContext); }

function resultArtifactId(value, resultContext = null) { return resultReaderBoundary.resultArtifactId(value, resultContext); }

function resultArtifactName(value, resultContext = null) { return resultReaderBoundary.resultArtifactName(value, resultContext); }

function createResultArtifactContext(jobId) { return resultReaderBoundary.createResultArtifactContext(jobId); }

function apiUrl(path) { return apiResultBoundary.apiUrl(path); }

function resultHref(jobId, artifactKey, options = {}) { return apiResultBoundary.resultHref(jobId, artifactKey, options); }

function privateResultLink(jobId, token, serverUrl = '') { return apiResultBoundary.privateResultLink(jobId, token, serverUrl); }

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
  const openedRuns = loadOpenedRuns();
  const existingRun = openedRuns.find(r => String(r.id) === id);
  const incomingReceipt = meta.receipt || runSetupReceiptFromJob(meta);
  const receipt = runSetupStoredReceiptSnapshot(
    preferredRunSetupReceipt(incomingReceipt, existingRun?.receipt),
  );
  const runs = openedRuns.filter(r => String(r.id) !== id);
  runs.unshift({
    id,
    token,
    name: meta.name || meta.project_name || meta.projectName || jobId,
    status: meta.status || '',
    updatedAt: new Date().toISOString(),
    ...(receipt ? { receipt } : {}),
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
    const openedRuns = loadOpenedRuns();
    const rememberedRun = openedRuns.find(
      run => [requested, publicId].includes(String(run.id || '')),
    );
    const receipt = runSetupStoredReceiptSnapshot(rememberedRun?.receipt);
    const runs = openedRuns
      .filter(run => ![requested, publicId].includes(String(run.id || '')));
    runs.unshift({
      id: publicId,
      token,
      name: job?.name || job?.project_name || job?.projectName || publicId,
      status: job?.status || '',
      updatedAt: new Date().toISOString(),
      ...(receipt ? { receipt } : {}),
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


function legacyCopyTextToClipboard(text) {
  if (typeof document.execCommand !== 'function') return false;
  const helper = document.createElement('textarea');
  const previousFocus = document.activeElement;
  let copyEventHandled = false;
  const writeClipboardData = event => {
    if (!event.clipboardData) return;
    event.clipboardData.setData('text/plain', text);
    event.preventDefault();
    copyEventHandled = true;
  };
  helper.value = text;
  helper.readOnly = true;
  helper.style.position = 'fixed';
  helper.style.left = '0';
  helper.style.top = '0';
  helper.style.width = '2px';
  helper.style.height = '2px';
  helper.style.opacity = '0.01';
  helper.style.pointerEvents = 'none';
  document.addEventListener('copy', writeClipboardData);
  document.body.appendChild(helper);
  try {
    helper.focus({ preventScroll: true });
    helper.select();
    helper.setSelectionRange(0, helper.value.length);
    const commandAccepted = document.execCommand('copy') === true;
    return commandAccepted || copyEventHandled;
  } catch (error) {
    return false;
  } finally {
    document.removeEventListener('copy', writeClipboardData);
    helper.remove();
    try { previousFocus?.focus?.({ preventScroll: true }); }
    catch (error) {}
  }
}

async function copyTextToClipboard(text, successMessage) {
  const status = document.getElementById('submission-confirmation-status');
  if (!text) {
    if (status) status.textContent = 'Nothing to copy yet.';
    return false;
  }
  try {
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        copied = true;
      }
    } catch (error) {
      copied = false;
    }
    if (!copied) copied = legacyCopyTextToClipboard(text);
    if (!copied) throw new Error('Clipboard copy was rejected.');
    if (status) status.textContent = successMessage || 'Copied.';
    return true;
  } catch (err) {
    if (status) status.textContent = 'Copy failed; select the field and copy manually.';
    return false;
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

function runSetupReceiptHasSpecificInputs(receipt) {
  return receiptAcceptedInputItems(receipt || {}).some(item => !item.summary);
}

function runSetupStoredReceiptSnapshot(receipt) {
  if (!receipt || typeof receipt !== 'object') return null;
  const cleanText = (value, maxLength = 256) => String(value || '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, maxLength);
  const acceptedInputs = receiptAcceptedInputItems(receipt)
    .filter(item => !item.summary)
    .slice(0, 100)
    .map(item => ({
      label: cleanText(item.label),
      kind: cleanText(item.kind, 64),
      source: cleanText(item.source),
      isTarget: item.isTarget === true,
      organismName: cleanText(item.organismName),
      taxa: cleanText(item.taxa),
      taxonGroup: normalizeTaxonGroup(item.taxonGroup),
      taxId: cleanText(item.taxId, 32),
      orderName: cleanText(item.orderName),
      familyName: cleanText(item.familyName),
      className: cleanText(item.className),
      orderFamily: cleanText(item.orderFamily),
    }))
    .filter(item => item.label);
  if (!acceptedInputs.length) return null;
  return {
    projectName: cleanText(receipt.projectName || receipt.project_name, 200),
    acceptedInputs,
    targetGenome: cleanText(receipt.targetGenome || receipt.target_genome),
    analysisScope: normalizeAnalysisScope(receipt.analysisScope || receipt.analysis_scope),
    taxonCounts: normalizeTaxonCounts(receipt.taxonCounts || receipt.taxon_counts || {}),
  };
}

function rememberedRunSetupReceipt(jobId, publicRunId) {
  const expected = new Set(
    [jobId, publicRunId].map(value => String(value || '').trim()).filter(Boolean),
  );
  const run = loadOpenedRuns().find(item => expected.has(String(item.id || '').trim()));
  return runSetupStoredReceiptSnapshot(run?.receipt);
}

function runSetupReceiptMatchesJob(record, jobId, publicRunId) {
  if (!record) return false;
  const expected = new Set(
    [jobId, publicRunId].map(value => String(value || '').trim()).filter(Boolean),
  );
  return [record.jobId, record.publicRunId]
    .map(value => String(value || '').trim())
    .some(value => value && expected.has(value));
}

function preferredRunSetupReceipt(incomingReceipt, existingReceipt) {
  if (!incomingReceipt) return existingReceipt;
  if (
    existingReceipt
    && runSetupReceiptHasSpecificInputs(existingReceipt)
    && !runSetupReceiptHasSpecificInputs(incomingReceipt)
  ) {
    return existingReceipt;
  }
  return incomingReceipt;
}

function runSetupJobHref(jobId) {
  const id = String(jobId || '').trim();
  return id ? `${defaultApiBaseUrl()}#/results/${encodeURIComponent(id)}` : '';
}

function configureRunSetupResultLink(link, jobId, readToken = '', resultUrl = '') {
  if (!link) return;
  const id = String(jobId || '').trim();
  if (!id) {
    link.textContent = 'Pending';
    link.removeAttribute('href');
    link.removeAttribute('data-job-id');
    link.removeAttribute('data-private-link');
    link.removeAttribute('aria-label');
    return;
  }
  const runId = publicRunIdForJob(id);
  const token = String(readToken || '').trim();
  if (!token) {
    link.textContent = 'Not saved in this tab';
    link.removeAttribute('href');
    link.dataset.jobId = runId;
    link.dataset.privateLink = '';
    link.setAttribute('aria-label', `Private result access is unavailable for run ${runId}`);
    return;
  }
  const href = privateResultLink(runId, token, resultUrl);
  link.textContent = href;
  link.href = href;
  link.dataset.jobId = runId;
  link.dataset.privateLink = href;
  link.setAttribute('aria-label', `Open results for run ${runId}`);
}

async function copyRunSetupCredentials() {
  const link = document.getElementById('run-setup-result-link');
  const accessCode = document.getElementById('run-setup-access-code')?.textContent?.trim() || '';
  const runId = document.getElementById('run-setup-public-id')?.textContent?.trim() || '';
  const privateLink = String(
    link?.dataset.privateLink || link?.getAttribute('href') || '',
  ).trim();
  const button = document.getElementById('copy-run-setup-credentials');
  if (!privateLink || !accessCode || !runId || button?.disabled) return;
  const credentials = `PRIVATE LINK: ${privateLink}\nACCESS CODE: ${accessCode}\nRUN ID: ${runId}`;
  const copied = await copyTextToClipboard(credentials, 'Job credentials copied.');
  if (copied && button) {
    button.textContent = 'COPIED';
    button.classList.add('is-copied');
  }
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
  const runId = String(
    payload.publicRunId || payload.public_run_id || payload.runId || payload.run_id
    || publicRunIdForJob(jobId) || jobId,
  ).trim();
  const existingReceipt = runSetupReceiptMatchesJob(submittedRunReceipt, jobId, runId)
    ? submittedRunReceipt.receipt
    : null;
  const receipt = preferredRunSetupReceipt(payload.receipt, existingReceipt)
    || collectRunSetupAccessReceipt({ projectName: payload.projectName });
  submittedRunReceipt = {
    jobId,
    publicRunId: runId,
    receipt,
    jobState: payload.jobState || payload.status || 'queued',
  };
  const inputList = document.getElementById('run-setup-input-list');
  const inputCount = document.getElementById('run-setup-input-count');
  const project = document.getElementById('run-setup-project');
  const analysisScope = document.getElementById('run-setup-analysis-scope');
  const target = document.getElementById('run-setup-target');
  const link = document.getElementById('run-setup-result-link');
  const accessCode = document.getElementById('run-setup-access-code');
  const publicId = document.getElementById('run-setup-public-id');
  const copyButton = document.getElementById('copy-run-setup-credentials');
  const previousPrivateLink = String(link?.dataset.privateLink || '').trim();
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
  const readToken = String(
    payload.readToken || payload.read_token || payload.token
    || readTokenForJob(jobId) || readTokenForJob(runId) || '',
  ).trim();
  const resultUrl = payload.resultUrl || payload.result_url || '';
  configureRunSetupResultLink(link, runId, readToken, resultUrl);
  if (accessCode) accessCode.textContent = readToken || 'Not saved in this tab';
  if (publicId) publicId.textContent = runId;
  const keepCopied = Boolean(
    copyButton?.classList.contains('is-copied')
    && previousPrivateLink
    && previousPrivateLink === String(link?.dataset.privateLink || '').trim()
  );
  if (copyButton) {
    copyButton.disabled = !readToken;
    if (!keepCopied) copyButton.textContent = 'COPY';
    if (!keepCopied) copyButton.classList.remove('is-copied');
  }
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
  const publicRunId = publicRunIdForJob(jobId);
  if (!jobId || !runSetupReceiptMatchesJob(submittedRunReceipt, jobId, publicRunId)) return false;
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
  const publicRunId = publicRunIdForJob(jobId);
  const token = readTokenForJob(publicRunId) || readTokenForJob(jobId);
  const link = token ? privateResultLink(publicRunId, token, job.result_url || '') : '';
  const project = runSetupProjectNameFromJob(job);
  const rememberedReceipt = rememberedRunSetupReceipt(jobId, publicRunId);
  const incomingReceipt = runSetupReceiptFromJob(job);
  const receipt = runSetupReceiptMatchesJob(submittedRunReceipt, jobId, publicRunId)
    ? submittedRunReceipt.receipt
    : preferredRunSetupReceipt(incomingReceipt, rememberedReceipt);
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
    publicRunId,
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

function authHeadersFor(kind, jobId = null) { return apiResultBoundary.authHeadersFor(kind, jobId); }

function mergeAuthHeaders(options = {}, auth = {}) { return apiResultBoundary.mergeAuthHeaders(options, auth); }

function apiFetch(path, options = {}, auth = {}) { return apiResultBoundary.apiFetch(path, options, auth); }

function resultNeedsAuth(jobId) { return apiResultBoundary.resultNeedsAuth(jobId); }

function canOpenRichHtmlArtifacts(jobId = activeJobId) { return apiResultBoundary.canOpenRichHtmlArtifacts(jobId); }

function inlineResultMime(relPath, fallback = '') { return resultReaderBoundary.inlineResultMime(relPath, fallback); }

function toolResultPreviewChannel() { return resultReaderBoundary.toolResultPreviewChannel(); }

function resultUrlShouldStayExternal(rawUrl) { return resultReaderBoundary.resultUrlShouldStayExternal(rawUrl); }

function resultRelativeAssetPath(ownerPath, rawUrl) { return resultReaderBoundary.resultRelativeAssetPath(ownerPath, rawUrl); }

function resultArtifactFamilyRoot(path) { return resultReaderBoundary.resultArtifactFamilyRoot(path); }

function resultArtifactFamilyAssetPath(ownerPath, rawUrl) { return resultReaderBoundary.resultArtifactFamilyAssetPath(ownerPath, rawUrl); }

function isToolResultBundleHtml(path, resultContext = null) { return resultReaderBoundary.isToolResultBundleHtml(path, resultContext); }

function splitResultAssetUrl(rawUrl) { return resultReaderBoundary.splitResultAssetUrl(rawUrl); }

function resultAssetHashSuffix(rawUrl) { return resultReaderBoundary.resultAssetHashSuffix(rawUrl); }

function bigscapeHtmlContentRoot(ownerPath) { return resultReaderBoundary.bigscapeHtmlContentRoot(ownerPath); }

function bigscapeHtmlContentAssetPath(ownerPath, rawUrl) { return resultReaderBoundary.bigscapeHtmlContentAssetPath(ownerPath, rawUrl); }

function bigscapePortableAssetPathAllowed(path) { return resultReaderBoundary.bigscapePortableAssetPathAllowed(path); }

function assertBigscapeAssetDeclaredSize(response, budget = null) { return resultReaderBoundary.assertBigscapeAssetDeclaredSize(response, budget); }

function assertBigscapeAssetActualSize(size, budget = null) { return resultReaderBoundary.assertBigscapeAssetActualSize(size, budget); }

function assertToolResultAssetSize(response, actualSize, budget) { return resultReaderBoundary.assertToolResultAssetSize(response, actualSize, budget); }

function isExactPublicClinkerPanelHtml(path) { return resultReaderBoundary.isExactPublicClinkerPanelHtml(path); }

function injectResultPreviewNavigator(doc, jobId, htmlPath) { return resultReaderBoundary.injectResultPreviewNavigator(doc, jobId, htmlPath); }

function resultBlobDataUrl(blob) { return resultReaderBoundary.resultBlobDataUrl(blob); }

async function resultAssetObjectUrl(jobId, ownerPath, rawUrl, cache, options = {}) { return resultReaderBoundary.resultAssetObjectUrl(jobId, ownerPath, rawUrl, cache, options); }

function stripToolResultCssImports(cssText) { return resultReaderBoundary.stripToolResultCssImports(cssText); }

async function rewriteCssResultUrls(cssText, jobId, ownerPath, cache, options = {}) { return resultReaderBoundary.rewriteCssResultUrls(cssText, jobId, ownerPath, cache, options); }

function isClassicResultScript(script) { return resultReaderBoundary.isClassicResultScript(script); }

function rewriteToolResultScriptForSandbox(assetPath, sourceText, resultContext = null) { return resultReaderBoundary.rewriteToolResultScriptForSandbox(assetPath, sourceText, resultContext); }

function rewriteBigscapeScriptForSandbox(assetPath, sourceText) { return resultReaderBoundary.rewriteBigscapeScriptForSandbox(assetPath, sourceText); }

async function inlineBigscapeResultScripts(doc, jobId, htmlPath, options = {}) { return resultReaderBoundary.inlineBigscapeResultScripts(doc, jobId, htmlPath, options); }

async function inlineToolResultScripts(doc, jobId, htmlPath, options = {}) { return resultReaderBoundary.inlineToolResultScripts(doc, jobId, htmlPath, options); }

async function rewriteHtmlResultAssets(htmlText, jobId, htmlPath, options = {}) { return resultReaderBoundary.rewriteHtmlResultAssets(htmlText, jobId, htmlPath, options); }

async function buildHtmlResultObjectUrl(jobId, htmlPath, htmlText, options = {}) { return resultReaderBoundary.buildHtmlResultObjectUrl(jobId, htmlPath, htmlText, options); }

function renderSandboxedClinkerPreview(targetWindow, relPath, htmlText) { return resultReaderBoundary.renderSandboxedClinkerPreview(targetWindow, relPath, htmlText); }

function renderSandboxedBigscapePreview(targetWindow, relPath, htmlText, databaseBuffer, channel) { return resultReaderBoundary.renderSandboxedBigscapePreview(targetWindow, relPath, htmlText, databaseBuffer, channel); }

function renderSandboxedToolResultPreview(targetWindow, jobId, relPath, htmlText, channel, resultContext) { return resultReaderBoundary.renderSandboxedToolResultPreview(targetWindow, jobId, relPath, htmlText, channel, resultContext); }

async function openHtmlResultWithAssets(event, jobId, relPath, previewWindow = null) { return resultReaderBoundary.openHtmlResultWithAssets(event, jobId, relPath, previewWindow); }

function resultFetch(jobId, artifactKey, options = {}) { return apiResultBoundary.resultFetch(jobId, artifactKey, options); }

function resolveResultArtifact(jobId, ownerKey, reference, options = {}) { return apiResultBoundary.resolveResultArtifact(jobId, ownerKey, reference, options); }

function bigscapeViewerFetch(jobId, options = {}) { return apiResultBoundary.bigscapeViewerFetch(jobId, options); }

async function handleResultLinkClick(event, jobId, relPath, download = false) { return resultReaderBoundary.handleResultLinkClick(event, jobId, relPath, download); }

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

const ANALYSIS_SCOPES = new Set(['fungi', 'both', 'bacteria']);
const TAXON_GROUPS = new Set(['fungi', 'bacteria']);

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

// ── Intake controller compatibility ───────────────────────────────────────
function ncbiAssemblyAccessionHelp() { return intakeControllerBoundary.ncbiAssemblyAccessionHelp(...arguments); }
function analysisScopeRadioValue() { return intakeControllerBoundary.analysisScopeRadioValue(...arguments); }
function syncAnalysisScopeControls() { return intakeControllerBoundary.syncAnalysisScopeControls(...arguments); }
function updateAnalysisScopeCopy() { return intakeControllerBoundary.updateAnalysisScopeCopy(...arguments); }
function isTaxonAssignmentsSidecarName(name) { return intakeControllerBoundary.isTaxonAssignmentsSidecarName(...arguments); }
function isGenomeUploadFile(file) { return intakeControllerBoundary.isGenomeUploadFile(...arguments); }
function canonicalGenomeInputKey(value) { return intakeControllerBoundary.canonicalGenomeInputKey(...arguments); }
function logicalGenomeInputs(files = selectedFiles) { return intakeControllerBoundary.logicalGenomeInputs(...arguments); }
function pruneManualTaxonAssignments() { return intakeControllerBoundary.pruneManualTaxonAssignments(...arguments); }
function stagedTaxonGroupForFileName(name) { return intakeControllerBoundary.stagedTaxonGroupForFileName(...arguments); }
function logicalGenomeAuthority(item) { return intakeControllerBoundary.logicalGenomeAuthority(...arguments); }
function logicalGenomeTaxonAssignmentDecision(item) { return intakeControllerBoundary.logicalGenomeTaxonAssignmentDecision(...arguments); }
function taxonAssignmentsPayload() { return intakeControllerBoundary.taxonAssignmentsPayload(...arguments); }
function taxonAssignmentValidation() { return intakeControllerBoundary.taxonAssignmentValidation(...arguments); }
function renderTaxonAssignmentPanel() { return intakeControllerBoundary.renderTaxonAssignmentPanel(...arguments); }
async function refreshSelectedGenomeChecks() { return intakeControllerBoundary.refreshSelectedGenomeChecks(...arguments); }
async function setLogicalGenomeTaxonAssignment(canonicalKey, taxonGroup) { return intakeControllerBoundary.setLogicalGenomeTaxonAssignment(...arguments); }
async function markAllTaxonAssignments(taxonGroup) { return intakeControllerBoundary.markAllTaxonAssignments(...arguments); }
function parseTaxonAssignmentSidecarText(text) { return intakeTaxonBoundary.parseTaxonAssignmentSidecarText(...arguments); }
async function loadTaxonAssignmentSidecar(file) { return intakeControllerBoundary.loadTaxonAssignmentSidecar(...arguments); }
function removeTaxonAssignmentSidecar() { return intakeControllerBoundary.removeTaxonAssignmentSidecar(...arguments); }
async function handleAnalysisScopeChange() { return intakeControllerBoundary.handleAnalysisScopeChange(...arguments); }
function resetStagedAnalysisState(scope = 'fungi') { return intakeControllerBoundary.resetStagedAnalysisState(...arguments); }
function accessionLimit() { return intakeControllerBoundary.accessionLimit(...arguments); }
function normalizeAccessionDraft(value) { return intakeControllerBoundary.normalizeAccessionDraft(...arguments); }
function normalizeShortToken(value, maxLength = 20) { return intakeControllerBoundary.normalizeShortToken(...arguments); }
function normalizeProjectNameInput() { return intakeControllerBoundary.normalizeProjectNameInput(...arguments); }
function projectNameValue() { return intakeControllerBoundary.projectNameValue(...arguments); }
function setProjectNameRequiredState(missing) { return intakeControllerBoundary.setProjectNameRequiredState(...arguments); }
function requireProjectNameForSubmit() { return intakeControllerBoundary.requireProjectNameForSubmit(...arguments); }
function validBrutalAccession(value) { return intakeControllerBoundary.validBrutalAccession(...arguments); }
function brutalDraftDuplicate(index, value) { return intakeControllerBoundary.brutalDraftDuplicate(...arguments); }
function brutalRowVisible(index) { return intakeControllerBoundary.brutalRowVisible(...arguments); }
function updateBrutalTargetButton() { return intakeControllerBoundary.updateBrutalTargetButton(...arguments); }
function setBrutalTarget(value) { return intakeControllerBoundary.setBrutalTarget(...arguments); }
function setUploadedGenomeTarget(value) { return intakeControllerBoundary.setUploadedGenomeTarget(...arguments); }
function targetGenomeCandidates() { return intakeControllerBoundary.targetGenomeCandidates(...arguments); }
function clearStaleTargetGenome() { return intakeControllerBoundary.clearStaleTargetGenome(...arguments); }
function handleUploadedGenomeTargetClick(event) { return intakeControllerBoundary.handleUploadedGenomeTargetClick(...arguments); }
function ecologySelectionFor(key) { return intakeControllerBoundary.ecologySelectionFor(...arguments); }
function inputEcologyEnabled() { return intakeControllerBoundary.inputEcologyEnabled(...arguments); }
function updateBrutalEcologyToggle() { return intakeControllerBoundary.updateBrutalEcologyToggle(...arguments); }
function updateUploadedGenomeEcoButtons() { return intakeControllerBoundary.updateUploadedGenomeEcoButtons(...arguments); }
function setBrutalEcologyEnabled(enabled) { return intakeControllerBoundary.setBrutalEcologyEnabled(...arguments); }
function savedEcoValue(accession, field) { return intakeControllerBoundary.savedEcoValue(...arguments); }
function rowIsAccepted(accession, index) { return intakeControllerBoundary.rowIsAccepted(...arguments); }
function accessionDraftCommitted(index) { return intakeControllerBoundary.accessionDraftCommitted(...arguments); }
function brutalAccessionDraftIssues({ committedOnly = true } = {}) { return intakeControllerBoundary.brutalAccessionDraftIssues(...arguments); }
function setBrutalInputNotice(key, message) { return intakeControllerBoundary.setBrutalInputNotice(...arguments); }
function updateBrutalRowState(row, index) { return intakeControllerBoundary.updateBrutalRowState(...arguments); }
function updateBrutalRowVisibility() { return intakeControllerBoundary.updateBrutalRowVisibility(...arguments); }
function acceptedDraftAccessions() { return intakeControllerBoundary.acceptedDraftAccessions(...arguments); }
function syncBrutalAcceptedFromDrafts() { return intakeControllerBoundary.syncBrutalAcceptedFromDrafts(...arguments); }
function resetBrutalAccessionDrafts() { return intakeControllerBoundary.resetBrutalAccessionDrafts(...arguments); }
function syncBrutalRowsFromAccepted() { return intakeControllerBoundary.syncBrutalRowsFromAccepted(...arguments); }
function renderBrutalAccessionRows() { return intakeControllerBoundary.renderBrutalAccessionRows(...arguments); }
function handleBrutalAccessionInput(event) { return intakeControllerBoundary.handleBrutalAccessionInput(...arguments); }
function commitBrutalAccessionRow(row) { return intakeControllerBoundary.commitBrutalAccessionRow(...arguments); }
function commitAllBrutalAccessionDrafts({ render = true } = {}) { return intakeControllerBoundary.commitAllBrutalAccessionDrafts(...arguments); }
function removeBrutalAccession(index) { return intakeControllerBoundary.removeBrutalAccession(...arguments); }
function handleBrutalAccessionClick(event) { return intakeControllerBoundary.handleBrutalAccessionClick(...arguments); }
function handleBrutalAccessionKeydown(event) { return intakeControllerBoundary.handleBrutalAccessionKeydown(...arguments); }
function handleBrutalAccessionFocusout(event) { return intakeControllerBoundary.handleBrutalAccessionFocusout(...arguments); }
function openBrutalEcoPicker(button) { return intakeControllerBoundary.openBrutalEcoPicker(...arguments); }
function openUploadedGenomeEcoPicker(button) { return intakeControllerBoundary.openUploadedGenomeEcoPicker(...arguments); }
function openEcoPickerForInput(button, accession, field) { return intakeControllerBoundary.openEcoPickerForInput(...arguments); }
function closeBrutalEcoPicker(returnFocus = false) { return intakeControllerBoundary.closeBrutalEcoPicker(...arguments); }
function saveBrutalEcoSelection(rawValue) { return intakeControllerBoundary.saveBrutalEcoSelection(...arguments); }
function applyBrutalEcologyToMetadataTable() { return intakeControllerBoundary.applyBrutalEcologyToMetadataTable(...arguments); }
function conciseInputNotice(message) { return intakeControllerBoundary.conciseInputNotice(...arguments); }
function renderBrutalInputLog() { return intakeControllerBoundary.renderBrutalInputLog(...arguments); }
function initializeBrutalInputStation() { return intakeControllerBoundary.initializeBrutalInputStation(...arguments); }
function parseAccessionText(raw) { return intakeControllerBoundary.parseAccessionText(...arguments); }
function parseManualAccessions() { return intakeControllerBoundary.parseManualAccessions(...arguments); }
function mergedAcceptedAccessions() { return intakeControllerBoundary.mergedAcceptedAccessions(...arguments); }
function accessionFileOwnedAccessions() { return intakeControllerBoundary.accessionFileOwnedAccessions(...arguments); }
function detachAccessionFromFileSources(accession) { return intakeControllerBoundary.detachAccessionFromFileSources(...arguments); }
function manualAccessionLines() { return intakeControllerBoundary.manualAccessionLines(...arguments); }
function manualAccessionErrorMessage(parsed) { return intakeControllerBoundary.manualAccessionErrorMessage(...arguments); }
function publicQuotaLimits() { return intakeControllerBoundary.publicQuotaLimits(...arguments); }
function formatQuotaMb(value) { return intakeControllerBoundary.formatQuotaMb(...arguments); }
function publicQuotaSummary(quota = publicQuotaLimits()) { return intakeControllerBoundary.publicQuotaSummary(...arguments); }
function localWorkflowPrompt() { return intakeControllerBoundary.localWorkflowPrompt(...arguments); }
function publicFileLimitMessage(quota = publicQuotaLimits()) { return intakeControllerBoundary.publicFileLimitMessage(...arguments); }
function publicTotalLimitMessage(quota = publicQuotaLimits()) { return intakeControllerBoundary.publicTotalLimitMessage(...arguments); }
function updateInputLimitGuidance() { return intakeControllerBoundary.updateInputLimitGuidance(...arguments); }
function genomeFileCheckKey(file) { return intakeControllerBoundary.genomeFileCheckKey(...arguments); }
function publicGenomeStem(name) { return intakeControllerBoundary.publicGenomeStem(...arguments); }
function clientLineageHas(lineage, name) { return intakeTaxonBoundary.clientLineageHas(...arguments); }
function parseClientGenbankTaxonomy(text) { return intakeTaxonBoundary.parseClientGenbankTaxonomy(...arguments); }
function mergeClientGenbankAuthorities(authorities) { return intakeTaxonBoundary.mergeClientGenbankAuthorities(...arguments); }
function clientTaxonAssignmentDecision(authority, assignedGroup = '', inputKey = 'genome') { return intakeTaxonBoundary.clientTaxonAssignmentDecision(...arguments); }
function genomeFileIdentityKey(file) { return intakeControllerBoundary.genomeFileIdentityKey(...arguments); }
function clientGenbankAuthorityForFile(file) { return intakeControllerBoundary.clientGenbankAuthorityForFile(...arguments); }
function rememberClientGenbankAuthority(file, result) { return intakeControllerBoundary.rememberClientGenbankAuthority(...arguments); }
function clientGenbankAuthorityProblem(authority, declaredGroup) { return intakeControllerBoundary.clientGenbankAuthorityProblem(...arguments); }
function classifyClientFastaText(name, text, taxonGroup = stagedTaxonGroupForFileName(name)) { return intakeControllerBoundary.classifyClientFastaText(...arguments); }
function classifyClientGenbankText(name, text, taxonGroup = stagedTaxonGroupForFileName(name)) { return intakeControllerBoundary.classifyClientGenbankText(...arguments); }
function publicGenomeUploadKind(fileExt) { return intakeControllerBoundary.publicGenomeUploadKind(...arguments); }
function classifyClientGenomeText(file, text) { return intakeControllerBoundary.classifyClientGenomeText(...arguments); }
function classifyClientGenomePreview(file, text) { return intakeControllerBoundary.classifyClientGenomePreview(...arguments); }
async function readClientGenomePreview(file) { return intakeControllerBoundary.readClientGenomePreview(...arguments); }
function browserGenomePrecheckUnavailableReason(file) { return intakeControllerBoundary.browserGenomePrecheckUnavailableReason(...arguments); }
async function cacheGenomeFileCheck(file) { return intakeControllerBoundary.cacheGenomeFileCheck(...arguments); }
function updateManualAccessionsStatus() { return intakeControllerBoundary.updateManualAccessionsStatus(...arguments); }
function renderAcceptedAccessions() { return intakeControllerBoundary.renderAcceptedAccessions(...arguments); }
function normalizeManualAccessions() { return intakeControllerBoundary.normalizeManualAccessions(...arguments); }
function clearManualAccessions() { return intakeControllerBoundary.clearManualAccessions(...arguments); }
function clearAcceptedAccessions() { return intakeControllerBoundary.clearAcceptedAccessions(...arguments); }
function clearAcceptedManualAccessions() { return intakeControllerBoundary.clearAcceptedManualAccessions(...arguments); }
function loadDemoAccessions(event) { return intakeControllerBoundary.loadDemoAccessions(...arguments); }
function importAccessionsToLoader(accessions) { return intakeControllerBoundary.importAccessionsToLoader(...arguments); }
async function addAccessionFileSource(file) { return intakeControllerBoundary.addAccessionFileSource(...arguments); }
function inputCheckLevel(readiness) { return intakeControllerBoundary.inputCheckLevel(...arguments); }
function inputCheckBadge(level) { return intakeControllerBoundary.inputCheckBadge(...arguments); }
function addInputCheckRow(rows, level, type, label, reason) { return intakeControllerBoundary.addInputCheckRow(...arguments); }
function renderInputCheckerRow(row) { return intakeControllerBoundary.renderInputCheckerRow(...arguments); }
function updateInputCheckerLimits(quota) { return intakeControllerBoundary.updateInputCheckerLimits(...arguments); }
function accessionPreflightPendingReason(sourceName = '') { return intakeControllerBoundary.accessionPreflightPendingReason(...arguments); }
function renderInputChecker() { return intakeControllerBoundary.renderInputChecker(...arguments); }
async function addFiles(files) { return intakeControllerBoundary.addFiles(...arguments); }
async function removeFile(index) { return intakeControllerBoundary.removeFile(...arguments); }
function removeAccessionFileSource(index) { return intakeControllerBoundary.removeAccessionFileSource(...arguments); }
function submissionsPausedForPublic() { return intakeControllerBoundary.submissionsPausedForPublic(...arguments); }
function uploadedInputRequiresAcknowledgment() { return intakeControllerBoundary.uploadedInputRequiresAcknowledgment(...arguments); }
function syncDataUseAcknowledgment() { return intakeControllerBoundary.syncDataUseAcknowledgment(...arguments); }
function submissionValidationSignature() { return intakeControllerBoundary.submissionValidationSignature(...arguments); }
function syncRunButtonPresentation(button = document.getElementById('run-btn')) { return intakeControllerBoundary.syncRunButtonPresentation(...arguments); }
function renderFileList() { return intakeControllerBoundary.renderFileList(...arguments); }
function genomeStemFromName(name) { return intakeControllerBoundary.genomeStemFromName(...arguments); }
function isGenomeUploadName(name) { return intakeControllerBoundary.isGenomeUploadName(...arguments); }
function ecologyInputRows() { return intakeControllerBoundary.ecologyInputRows(...arguments); }
function collectEcologyRowValues() { return intakeControllerBoundary.collectEcologyRowValues(...arguments); }
function ecologySelectOptions(selected) { return intakeControllerBoundary.ecologySelectOptions(...arguments); }
function ecologyLabelCellHtml(key, field, saved = {}) { return intakeControllerBoundary.ecologyLabelCellHtml(...arguments); }
function renderEcologyMetadataRows(inputRows, savedValues) { return intakeControllerBoundary.renderEcologyMetadataRows(...arguments); }
function handleEcologyLabelChange(el) { return intakeControllerBoundary.handleEcologyLabelChange(...arguments); }
function ecologyLabelValue(row, field) { return intakeControllerBoundary.ecologyLabelValue(...arguments); }
function currentEcologyMetadataRows() { return intakeControllerBoundary.currentEcologyMetadataRows(...arguments); }
function updateEcologyLabelStatus() { return intakeControllerBoundary.updateEcologyLabelStatus(...arguments); }
function syncEcologyMetadataPanel() { return intakeControllerBoundary.syncEcologyMetadataPanel(...arguments); }
function metadataProfileText() { return intakeControllerBoundary.metadataProfileText(...arguments); }
async function startAnalysis() { return intakeControllerBoundary.startAnalysis(...arguments); }

// ── Job history ────────────────────────────────────────────────────────────
async function refreshJobHistory() { return jobLifecycleControllerBoundary.refreshJobHistory(...arguments); }

function jobHistoryRenderKey(jobs) { return jobLifecycleControllerBoundary.jobHistoryRenderKey(...arguments); }

function jobStageSignature(job) { return jobLifecycleControllerBoundary.jobStageSignature(...arguments); }

function jobProjectName(job) { return jobLifecycleControllerBoundary.jobProjectName(...arguments); }

function jobStageDisplay(job) { return jobLifecycleControllerBoundary.jobStageDisplay(...arguments); }

function jobCurrentStageKey(job) { return jobLifecycleControllerBoundary.jobCurrentStageKey(...arguments); }

function jobStagePipState(job, key) { return jobLifecycleControllerBoundary.jobStagePipState(...arguments); }

function renderJobStagePips(job) { return jobLifecycleControllerBoundary.renderJobStagePips(...arguments); }

function statusLabel(status) { return jobLifecycleControllerBoundary.statusLabel(...arguments); }

function jobCanRerun(job) { return jobLifecycleControllerBoundary.jobCanRerun(...arguments); }

function rerunStageKeysForJob(job) { return jobLifecycleControllerBoundary.rerunStageKeysForJob(...arguments); }

function rerunPayloadFromStages(stageKeys, force = false) { return diagnosticsAccessBoundary.rerunPayloadFromStages(stageKeys, force); }
function rerunPayloadHasStages(payload) { return diagnosticsAccessBoundary.rerunPayloadHasStages(payload); }

async function queueJobRerun(jobId, payload) { return diagnosticsControllerBoundary.queueJobRerun(...arguments); }
function diagnosticRerunDisclosureId(jobId) { return diagnosticsControllerBoundary.diagnosticRerunDisclosureId(...arguments); }
function diagnosticRerunDetails(jobId) { return diagnosticsControllerBoundary.diagnosticRerunDetails(...arguments); }
function syncDiagnosticRerunDisclosure(event, jobId) { return diagnosticsControllerBoundary.syncDiagnosticRerunDisclosure(...arguments); }
async function toggleJobRerunScope(event, jobId) { return diagnosticsControllerBoundary.toggleJobRerunScope(...arguments); }
async function rerunJobFromHistory(event, jobId) { return diagnosticsControllerBoundary.rerunJobFromHistory(...arguments); }

function diagnosticJobDisplayState(job, index) { return jobLifecycleControllerBoundary.diagnosticJobDisplayState(...arguments); }

function diagnosticRouteCardLabel(index) { return jobLifecycleControllerBoundary.diagnosticRouteCardLabel(...arguments); }

function renderDiagnosticRerunRail(jobId, job, displayLabel) { return diagnosticsControllerBoundary.renderDiagnosticRerunRail(...arguments); }
function updateDiagnosticRerunSubmit(event = null) { return diagnosticsControllerBoundary.updateDiagnosticRerunSubmit(...arguments); }
async function queueDiagnosticRerun(event, jobId) { return diagnosticsControllerBoundary.queueDiagnosticRerun(...arguments); }

function renderJobHistory(jobs) { return jobLifecycleControllerBoundary.renderJobHistory(...arguments); }

function statusBadge(status) { return jobLifecycleControllerBoundary.statusBadge(...arguments); }

function handleJobCardKeydown(event, jobId) { return jobLifecycleControllerBoundary.handleJobCardKeydown(...arguments); }

async function openJobLogs(event, jobId) { return jobLifecycleControllerBoundary.openJobLogs(...arguments); }

function markActiveJobCard(jobId) { return jobLifecycleControllerBoundary.markActiveJobCard(...arguments); }

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

function publicStageTimingEvent(event) { return jobLifecycleControllerBoundary.publicStageTimingEvent(...arguments); }

function applyStageTimingFromPublicEvents(job) { return jobLifecycleControllerBoundary.applyStageTimingFromPublicEvents(...arguments); }

function stageSnapshotTimeMs(job) { return jobLifecycleControllerBoundary.stageSnapshotTimeMs(...arguments); }

function shouldApplyJobStageSnapshot(key) { return jobLifecycleControllerBoundary.shouldApplyJobStageSnapshot(...arguments); }

function applyJobStageSnapshot(job) { return jobLifecycleControllerBoundary.applyJobStageSnapshot(...arguments); }

async function deleteJob(event, jobId) { return jobLifecycleControllerBoundary.deleteJob(...arguments); }

// ── Load / watch a job ─────────────────────────────────────────────────────
function currentJobSelection(jobId, seq) { return jobLifecycleBoundary.isCurrentJobSelection(jobId, seq); }

async function loadJob(jobId, autoScroll = false, options = {}) { return jobLifecycleControllerBoundary.loadJob(...arguments); }

async function pollJobFinal( jobId, autoScroll = false, seq = jobLoadSeq, timeoutMs = JOB_POLL_TIMEOUT_MS, ) { return jobLifecycleControllerBoundary.pollJobFinal(...arguments); }

function jobPollDelay(job) { return jobLifecycleBoundary.jobPollDelay(job); }

function scheduleJobPoll(jobId, autoScroll = false, seq = jobLoadSeq, delay = JOB_POLL_BASE_DELAY_MS) { return jobLifecycleControllerBoundary.scheduleJobPoll(...arguments); }

function stopPolling() { return jobLifecycleControllerBoundary.stopPolling(...arguments); }

// ── Log rendering ──────────────────────────────────────────────────────────
function publicQaEventLine(event) { return jobLifecycleBoundary.publicQaEventLine(event); }

function renderPublicQaLog(job) { return jobLifecycleControllerBoundary.renderPublicQaLog(...arguments); }
async function hydratePublicResultActivity(jobId, seq = jobLoadSeq) { return jobLifecycleControllerBoundary.hydratePublicResultActivity(...arguments); }

function createLogLineElement(text) { return jobLifecycleBoundary.createLogLineElement(text); }

function appendLogLine(text) { return jobLifecycleControllerBoundary.appendLogLine(...arguments); }

function updateAdminLogControls() { return jobLifecycleControllerBoundary.updateAdminLogControls(...arguments); }

async function hydrateQaLogs({ tail = true, before = null, autoScroll = false } = {}) { return jobLifecycleControllerBoundary.hydrateQaLogs(...arguments); }

async function loadEarlierLogs() { return jobLifecycleControllerBoundary.loadEarlierLogs(...arguments); }

async function syncActiveAdminLogs(autoScroll = false) { return jobLifecycleControllerBoundary.syncActiveAdminLogs(...arguments); }

function clearLog() { return jobLifecycleControllerBoundary.clearLog(...arguments); }

function setQaLogView(value) { return jobLifecycleControllerBoundary.setQaLogView(value); }
function handleQaLogViewKeydown(event) { return jobLifecycleControllerBoundary.handleQaLogViewKeydown(event); }

function scrollElementToBottom(el) { return diagnosticsAccessBoundary.scrollElementToBottom(el); }
function scrollToBottom() { return jobLifecycleControllerBoundary.scrollToBottom(...arguments); }

// ── Stage bar ──────────────────────────────────────────────────────────────
function jobHasExplicitStageSettings(job) { return jobLifecycleControllerBoundary.jobHasExplicitStageSettings(...arguments); }

function jobStageSettings(job) { return jobLifecycleControllerBoundary.jobStageSettings(...arguments); }

function resultOrEventIndicatesStage(job, key, files = activeResultFiles) { return jobLifecycleControllerBoundary.resultOrEventIndicatesStage(...arguments); }

function inferredSuccessfulStageSet(job, files = activeResultFiles) { return jobLifecycleControllerBoundary.inferredSuccessfulStageSet(...arguments); }

function syncInferredStageState(job = activeJobMeta) { return jobLifecycleControllerBoundary.syncInferredStageState(...arguments); }

function jobStageEnabled(job, key) { return jobLifecycleControllerBoundary.jobStageEnabled(...arguments); }

function rerunStageAllowed(key) { return diagnosticsAccessBoundary.rerunStageAllowed(key, runtimeCapabilities); }

function initializeStageState(job) { return jobLifecycleControllerBoundary.initializeStageState(...arguments); }

function resetStages(job = null) { return jobLifecycleControllerBoundary.resetStages(...arguments); }

function stageIndex(key) { return jobLifecycleControllerBoundary.stageIndex(...arguments); }

function resetWeaveActivity(job = null) { return jobLifecycleControllerBoundary.resetWeaveActivity(...arguments); }

function workflowStageList(job = activeJobMeta) { return jobLifecycleControllerBoundary.workflowStageList(...arguments); }

function finalEnabledStageKey(job = activeJobMeta) { return jobLifecycleControllerBoundary.finalEnabledStageKey(...arguments); }

function stageVisualState(key) { return jobLifecycleControllerBoundary.stageVisualState(...arguments); }

function formatWorkflowTime(value) { return jobLifecycleControllerBoundary.formatWorkflowTime(...arguments); }

function formatDuration(ms) { return jobLifecycleControllerBoundary.formatDuration(...arguments); }

function parseTimestampMs(value) { return jobLifecycleBoundary.parseTimestampMs(...arguments); }

function stageClockSeconds(value) { return jobLifecycleControllerBoundary.stageClockSeconds(...arguments); }

function stageTimingBaseMs(job = activeJobMeta) { return jobLifecycleControllerBoundary.stageTimingBaseMs(...arguments); }

function stageTimestampFromClock(value, job = activeJobMeta, minMs = null) { return jobLifecycleControllerBoundary.stageTimestampFromClock(...arguments); }

function stageTimestampFromLogLine(line, job = activeJobMeta) { return jobLifecycleControllerBoundary.stageTimestampFromLogLine(...arguments); }

function stageTimingSourceRank(source) { return jobLifecycleControllerBoundary.stageTimingSourceRank(...arguments); }

function setStageStartTime(key, ms, source = 'snapshot', options = {}) { return jobLifecycleControllerBoundary.setStageStartTime(...arguments); }

function setStageEndTime(key, ms, source = 'snapshot', options = {}) { return jobLifecycleControllerBoundary.setStageEndTime(...arguments); }

function clearStageTimingFrom(key) { return jobLifecycleControllerBoundary.clearStageTimingFrom(...arguments); }

function stageTransitionTimeMs(options = {}) { return jobLifecycleControllerBoundary.stageTransitionTimeMs(...arguments); }

function jobElapsedText(job = activeJobMeta) { return jobLifecycleControllerBoundary.jobElapsedText(...arguments); }

function jobRuntimeBounds(job = activeJobMeta) { return jobLifecycleBoundary.jobRuntimeBounds(job); }

function formatJobRuntimeClock(milliseconds) { return jobLifecycleBoundary.formatJobRuntimeClock(milliseconds); }

function renderJobRuntime(job = activeJobMeta) { return jobLifecycleControllerBoundary.renderJobRuntime(...arguments); }

function stageRuntimeHint(key) { return jobLifecycleControllerBoundary.stageRuntimeHint(...arguments); }

function stageEstimateText(key) { return jobLifecycleControllerBoundary.stageEstimateText(...arguments); }

function compactRuntimeHint(key) { return jobLifecycleControllerBoundary.compactRuntimeHint(...arguments); }

function dnaStageMetaText(key, visual) { return jobLifecycleControllerBoundary.dnaStageMetaText(...arguments); }

function stageElapsedText(key, visualCls) { return jobLifecycleControllerBoundary.stageElapsedText(...arguments); }

function currentWorkflowStage() { return jobLifecycleControllerBoundary.currentWorkflowStage(...arguments); }

function setWorkflowExperienceState(job = activeJobMeta) { return jobLifecycleControllerBoundary.setWorkflowExperienceState(...arguments); }

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

function clusterweaveGameAssetManifest() {
  const nodes = Array.from(document.querySelectorAll(CLUSTERWEAVE_GAME_ASSET_SELECTOR));
  const entries = nodes.map(node => {
    const kind = String(node.dataset.kind || '');
    const url = new URL(String(node.content || ''), window.location.href);
    if (url.origin !== window.location.origin) throw new Error('Pixel Runner assets must be same-origin');
    if (!url.searchParams.get('v')) throw new Error('Pixel Runner assets must be cache-busted');
    return { kind, url: url.toString() };
  });
  const styles = entries.filter(entry => entry.kind === 'style');
  const scripts = entries.filter(entry => entry.kind === 'script');
  if (entries.length !== 4 || styles.length !== 1 || scripts.length !== 3) {
    throw new Error('Pixel Runner asset manifest must declare one style and three ordered scripts');
  }
  return { style: styles[0].url, scripts: scripts.map(entry => entry.url) };
}

function loadClusterweaveGameStyle(url) {
  return new Promise((resolve, reject) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = url;
    link.dataset.clusterweaveGameAsset = 'style';
    link.addEventListener('load', resolve, { once: true });
    link.addEventListener('error', () => reject(new Error('Pixel Runner stylesheet failed to load')), { once: true });
    document.head.appendChild(link);
  });
}

function loadClusterweaveGameScript(url) {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = url;
    script.async = false;
    script.dataset.clusterweaveGameAsset = 'script';
    script.addEventListener('load', resolve, { once: true });
    script.addEventListener('error', () => reject(new Error('Pixel Runner script failed to load')), { once: true });
    document.head.appendChild(script);
  });
}

function showClusterweaveGameLoadFailure() {
  const launcher = document.getElementById('clusterweave-game-launcher');
  if (!launcher) return;
  launcher.removeAttribute('hidden');
  launcher.classList.remove('hidden');
  launcher.removeAttribute('inert');
  launcher.setAttribute('aria-hidden', 'false');
  const title = launcher.querySelector('strong');
  const copy = launcher.querySelector('p');
  if (title) title.textContent = 'Game unavailable';
  if (copy) copy.textContent = 'The workflow is unaffected. Reload after the optional game assets are available.';
  launcher.querySelector('.clusterweave-game-launcher-actions')?.setAttribute('hidden', '');
}

async function loadClusterweaveGameAssets() {
  if (window.ClusterWeaveGame?.setHostState) return window.ClusterWeaveGame;
  if (clusterweaveGameAssetsPromise) return clusterweaveGameAssetsPromise;
  clusterweaveGameAssetsPromise = (async () => {
    const manifest = clusterweaveGameAssetManifest();
    await loadClusterweaveGameStyle(manifest.style);
    for (const script of manifest.scripts) await loadClusterweaveGameScript(script);
    const controller = window.ClusterWeaveGame;
    if (!controller?.setHostState) throw new Error('Pixel Runner controller did not initialize');
    controller.setConnectionState?.(clusterweaveGameConnectionState);
    syncClusterweaveGameHost(clusterweaveGamePendingHost || {});
    return controller;
  })().catch(error => {
    showClusterweaveGameLoadFailure();
    throw error;
  });
  return clusterweaveGameAssetsPromise;
}

function requestClusterweaveGameAssets() {
  void loadClusterweaveGameAssets().catch(error => {
    console.error('Pixel Runner assets failed to load:', error);
  });
}

function clusterweaveGameEligible(lifecycle = '') {
  return lifecycle === 'pending'
    || lifecycle === 'running'
    || clusterweaveGameConnectionState !== 'connected'
    || document.body.dataset.clusterweaveGameBootstrapEligible === 'true';
}

function rememberClusterweaveGameConnectionState(connection) {
  if (!['connected', 'reconnecting', 'browser-offline'].includes(connection)) return;
  clusterweaveGameConnectionState = connection;
  if (connection !== 'connected') requestClusterweaveGameAssets();
}

function setClusterweaveGameBootstrapEligible(eligible) {
  const isEligible = eligible === true;
  document.body.dataset.clusterweaveGameBootstrapEligible = isEligible ? 'true' : 'false';
  if (isEligible) requestClusterweaveGameAssets();
}

function wireClusterweaveGameDemand() {
  if (clusterweaveGameDemandWired) return;
  clusterweaveGameDemandWired = true;
  ['clusterweave-game-start', 'clusterweave-game-bootstrap-open'].forEach(id => {
    const button = document.getElementById(id);
    button?.addEventListener('click', event => {
      if (window.ClusterWeaveGame?.open) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      void loadClusterweaveGameAssets().then(controller => controller.open({
        returnFocus: button,
        fromBootstrap: id === 'clusterweave-game-bootstrap-open',
      })).catch(error => console.error('Pixel Runner could not start:', error));
    }, true);
  });
}

function syncClusterweaveGameHost(options = {}) {
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
  clusterweaveGamePendingHost = { lifecycle, job };
  const controller = window.ClusterWeaveGame;
  if (!controller?.setHostState) {
    if (clusterweaveGameEligible(lifecycle)) requestClusterweaveGameAssets();
    return;
  }
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
  wireClusterweaveGameDemand();
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

function bgcWorkflowStages(job = activeJobMeta) { return jobLifecycleControllerBoundary.bgcWorkflowStages(...arguments); }

function bgcStageStatus(stage, currentKey, jobStatus) { return jobLifecycleControllerBoundary.bgcStageStatus(...arguments); }

function compactActivityChipText(value, maxLength = 96) { return jobLifecycleBoundary.compactActivityChipText(...arguments); }

function jobPublicWorkflowEvents(job, currentKey) { return jobLifecycleControllerBoundary.jobPublicWorkflowEvents(...arguments); }

function latestJobPublicWorkflowEvent(job, currentKey) { return jobLifecycleControllerBoundary.latestJobPublicWorkflowEvent(...arguments); }

function activityOrganismFromMeta(meta) { return jobLifecycleControllerBoundary.activityOrganismFromMeta(...arguments); }

function activityElapsedFromMeta(meta) { return jobLifecycleControllerBoundary.activityElapsedFromMeta(...arguments); }

function activityPartsFromEvent(event) { return jobLifecycleControllerBoundary.activityPartsFromEvent(...arguments); }

function activityPartsMatch(a, b) { return jobLifecycleControllerBoundary.activityPartsMatch(...arguments); }

function latestToolActivityParts(job, currentKey) { return jobLifecycleControllerBoundary.latestToolActivityParts(...arguments); }

function workflowPayloadHasSkippedStages(payload = null) { return jobLifecycleControllerBoundary.workflowPayloadHasSkippedStages(...arguments); }

function bgcActivityChipPayload(job, state, currentKey, fallbackTool) { return jobLifecycleControllerBoundary.bgcActivityChipPayload(...arguments); }

function clampUnit(value) { return jobLifecycleControllerBoundary.clampUnit(...arguments); }



function safeGenomeProgressText(value, fallback = 'Working', maxLength = 120) { return jobLifecycleBoundary.safeGenomeProgressText(value, fallback, maxLength); }
function safeGenomeProgressLabel(item, index) { return jobLifecycleBoundary.safeGenomeProgressLabel(item, index); }
function genomeProgressPercent(item) { return jobLifecycleBoundary.genomeProgressPercent(item); }
function genomeProgressTaxon(value) { return jobLifecycleBoundary.genomeProgressTaxon(value); }
function normalizeGenomeRegionProgress(item) { return jobLifecycleBoundary.normalizeGenomeRegionProgress(item); }
function normalizeGenomeProgressItem(item, index) { return jobLifecycleBoundary.normalizeGenomeProgressItem(item, index); }
function resetGenomeProgressSnapshot(jobId = '', rerunCount = 0) { return jobLifecycleBoundary.resetGenomeProgressSnapshot(jobId, rerunCount); }
function genomeProgressAttemptKey(job) { return jobLifecycleBoundary.genomeProgressAttemptKey(job); }
function genomeProgressExplicitRestart(previous, next) { return jobLifecycleBoundary.genomeProgressExplicitRestart(previous, next); }
function genomeProgressSnapshotPrefersPrevious(previous, next) { return jobLifecycleBoundary.genomeProgressSnapshotPrefersPrevious(previous, next); }
function normalizeGenomeProgressItems(job) { return jobLifecycleBoundary.normalizeGenomeProgressItems(job); }
function genomeProgressStages(item) { return jobLifecycleBoundary.genomeProgressStages(item); }
function genomeProgressCurrentStageIndex(item, stages) { return jobLifecycleBoundary.genomeProgressCurrentStageIndex(item, stages); }
function genomeProgressStageKey(label) { return jobLifecycleBoundary.genomeProgressStageKey(label); }
function genomeProgressStageFraction(item, key, status) { return jobLifecycleBoundary.genomeProgressStageFraction(item, key, status); }
function genomeProgressStageModel(item) { return jobLifecycleBoundary.genomeProgressStageModel(item); }
function renderGenomeProgressStages(item, model = genomeProgressStageModel(item)) { return jobLifecycleBoundary.renderGenomeProgressStages(item, model); }
function genomeProgressMeterModel(item, stages = genomeProgressStageModel(item)) { return jobLifecycleBoundary.genomeProgressMeterModel(item, stages); }
function genomeProgressRibbonText(item, statusMessage, stages) { return jobLifecycleBoundary.genomeProgressRibbonText(item, statusMessage, stages); }
function renderGenomeProgressMeter(item, statusMessage, stages) { return jobLifecycleBoundary.renderGenomeProgressMeter(item, statusMessage, stages); }
function renderGenomeProgressCard(item) { return jobLifecycleBoundary.renderGenomeProgressCard(item); }
function genomeProgressSummaryText(items) { return jobLifecycleBoundary.genomeProgressSummaryText(items); }
function bgcWorkflowTitle(payload, genomeLayerActive) { return jobLifecycleBoundary.bgcWorkflowTitle(payload, genomeLayerActive); }

function renderGenomeProgressLayer(payload) { return jobLifecycleControllerBoundary.renderGenomeProgressLayer(...arguments); }

function workflowStageWeight(stage) { return jobLifecycleControllerBoundary.workflowStageWeight(...arguments); }

function parseWorkflowGenomePosition(value) { return jobLifecycleControllerBoundary.parseWorkflowGenomePosition(...arguments); }

function workflowGenomePhaseFromTitle(title) { return jobLifecycleControllerBoundary.workflowGenomePhaseFromTitle(...arguments); }

function annotationGenomeProgress(job) { return jobLifecycleControllerBoundary.annotationGenomeProgress(...arguments); }

function workflowCurrentStageFraction(job, currentKey, status) { return jobLifecycleControllerBoundary.workflowCurrentStageFraction(...arguments); }

function weightedWorkflowProgress(stages, currentKey, status, job, stageProgress = null) { return jobLifecycleControllerBoundary.weightedWorkflowProgress(...arguments); }

function bgcWorkflowPayload(job = activeJobMeta) { return jobLifecycleControllerBoundary.bgcWorkflowPayload(...arguments); }



function alt06StepStatus(group, sourceSteps, payload) { return jobLifecycleControllerBoundary.alt06StepStatus(...arguments); }

function alt06WorkflowCaption(payload) { return jobLifecycleControllerBoundary.alt06WorkflowCaption(...arguments); }

function renderBgcWorkflowStageStrip(payload) { return jobLifecycleControllerBoundary.renderBgcWorkflowStageStrip(...arguments); }

function applyBgcWorkflowPayload(payload) { return jobLifecycleControllerBoundary.applyBgcWorkflowPayload(...arguments); }

function updateBgcWorkflowDnaFromJob(job = activeJobMeta) { return jobLifecycleControllerBoundary.updateBgcWorkflowDnaFromJob(...arguments); }

function bootBgcWorkflowDna() { return jobLifecycleControllerBoundary.bootBgcWorkflowDna(...arguments); }

function updateStageTelemetry() { return jobLifecycleControllerBoundary.updateStageTelemetry(...arguments); }

function refreshDnaTimingNodes() { return jobLifecycleControllerBoundary.refreshDnaTimingNodes(...arguments); }

function startStageTicker() { return jobLifecycleControllerBoundary.startStageTicker(...arguments); }

function normalizePublicWeaveEvent(event) { return jobLifecycleBoundary.normalizePublicWeaveEvent(...arguments); }

function mergeWeaveActivityEvents(events) { return jobLifecycleControllerBoundary.mergeWeaveActivityEvents(...arguments); }

function recordWeaveActivity(job) { return jobLifecycleControllerBoundary.recordWeaveActivity(...arguments); }

function latestWeaveEventByStage() { return jobLifecycleControllerBoundary.latestWeaveEventByStage(...arguments); }

function stageTimelineLabel(visual) { return jobLifecycleControllerBoundary.stageTimelineLabel(...arguments); }

function stageTimelineDetailKey(visual) { return jobLifecycleControllerBoundary.stageTimelineDetailKey(...arguments); }

function eventSummaryText(event) { return jobLifecycleControllerBoundary.eventSummaryText(...arguments); }

function stageTimelineMeta(stage, visual, event) { return jobLifecycleControllerBoundary.stageTimelineMeta(...arguments); }

function legacyStageOverviewNodes(job = activeJobMeta) { return jobLifecycleControllerBoundary.legacyStageOverviewNodes(...arguments); }

function publicStageNodes(stage, visual, job) { return jobLifecycleControllerBoundary.publicStageNodes(...arguments); }

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

function reducedMotionPreferred() { return motionBoundary.reducedMotionPreferred(...arguments); }
function clearRetiredMotionSettings() { return motionBoundary.clearRetiredMotionSettings(...arguments); }
function richMotionDisabled() { return motionBoundary.richMotionDisabled(...arguments); }
function initializeRetiredMotionControls() { return motionBoundary.initializeRetiredMotionControls(...arguments); }
function wireMotionLifecycleGuards() { return motionBoundary.wireMotionLifecycleGuards(...arguments); }
function richDomMotionEnabled() { return motionBoundary.richDomMotionEnabled(...arguments); }
function markGsapMotionFallback(reason) { return motionBoundary.markGsapMotionFallback(...arguments); }
function gsapMotionReady() { return motionBoundary.gsapMotionReady(...arguments); }
function loadGsapMotion() { return motionBoundary.loadGsapMotion(...arguments); }
function warmGsapMotion() { return motionBoundary.warmGsapMotion(...arguments); }
function killGsapTimeline(key) { return motionBoundary.killGsapTimeline(...arguments); }
function clearDocsMotionVars(docs = document.getElementById('docs')) { return motionBoundary.clearDocsMotionVars(...arguments); }
function teardownGsapMotion(reason = '') { return motionBoundary.teardownGsapMotion(...arguments); }
function motionTargets(targets, root = document) { return motionBoundary.motionTargets(...arguments); }
function runGsapMotion(key, build) { return motionBoundary.runGsapMotion(...arguments); }
function animateEntryTabTransition(selectedName) { return motionBoundary.animateEntryTabTransition(...arguments); }
function animateLaunchTransition() { return motionBoundary.animateLaunchTransition(...arguments); }
function animateExistingResultUnlock() { return motionBoundary.animateExistingResultUnlock(...arguments); }
function animateResultDashboardOpen(source = '') { return motionBoundary.animateResultDashboardOpen(...arguments); }
function animateResultFocusChange(category = '') { return motionBoundary.animateResultFocusChange(...arguments); }
function animateResultReaderOpen() { return motionBoundary.animateResultReaderOpen(...arguments); }
function animateSummaryReaderDocument() { return motionBoundary.animateSummaryReaderDocument(...arguments); }
function animateRerunPanelReady() { return motionBoundary.animateRerunPanelReady(...arguments); }
function animateRerunPanelOpen(details) { return motionBoundary.animateRerunPanelOpen(...arguments); }
function wireRerunPanelMotion(details) { return motionBoundary.wireRerunPanelMotion(...arguments); }
function animateRerunQueued() { return motionBoundary.animateRerunQueued(...arguments); }
function animateOpsPanelToggle(expanded) { return motionBoundary.animateOpsPanelToggle(...arguments); }
function animateDiagnosticsReveal() { return motionBoundary.animateDiagnosticsReveal(...arguments); }
function setDocsMotionVars(docs, values) { return motionBoundary.setDocsMotionVars(...arguments); }
function animateDocsDisclosureOpen() { return motionBoundary.animateDocsDisclosureOpen(...arguments); }
function animateDocsDisclosureClose(docs, done) { return motionBoundary.animateDocsDisclosureClose(...arguments); }
function animateDnaOverlayPolish(stageWrap, renderKey) { return motionBoundary.animateDnaOverlayPolish(...arguments); }

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

function stageFromLine(line) { return jobLifecycleControllerBoundary.stageFromLine(...arguments); }

function advanceToStage(key, options = {}) { return jobLifecycleControllerBoundary.advanceToStage(...arguments); }

function sanitizeWeaveLogTitle(line) { return jobLifecycleControllerBoundary.sanitizeWeaveLogTitle(...arguments); }

function recordWeaveLogActivity(line, stageKey = '') { return jobLifecycleControllerBoundary.recordWeaveLogActivity(...arguments); }

function updateStageBar(line) { return jobLifecycleControllerBoundary.updateStageBar(...arguments); }

function terminalStageTimeMs(status) { return jobLifecycleControllerBoundary.terminalStageTimeMs(...arguments); }

function finalizeStageState(status) { return jobLifecycleControllerBoundary.finalizeStageState(...arguments); }

function renderStageState() { return jobLifecycleControllerBoundary.renderStageState(...arguments); }


function updateProgressBadge(status) { return jobLifecycleControllerBoundary.updateProgressBadge(...arguments); }

// ── Results ────────────────────────────────────────────────────────────────
function queueStatusForJob(job = activeJobMeta) { return jobLifecycleControllerBoundary.queueStatusForJob(...arguments); }

function queueStatusLabel(job = activeJobMeta) { return jobLifecycleControllerBoundary.queueStatusLabel(...arguments); }

function queueStatusDetail(job = activeJobMeta) { return jobLifecycleControllerBoundary.queueStatusDetail(...arguments); }

function statusBadgeModel(status, job = activeJobMeta) { return jobLifecycleControllerBoundary.statusBadgeModel(...arguments); }

function setStatusBadge(el, status, job = activeJobMeta) { return jobLifecycleControllerBoundary.setStatusBadge(...arguments); }

function pendingQueueNote(job = activeJobMeta) { return jobLifecycleControllerBoundary.pendingQueueNote(...arguments); }

function renderCompletionCallout(status) { return jobLifecycleControllerBoundary.renderCompletionCallout(...arguments); }

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

function resultCategoryKey(category) { return resultReaderBoundary.resultCategoryKey(category); }

function resultFolderTabs(counts = {}) { return resultReaderBoundary.resultFolderTabs(counts); }

function resultPathExt(path) { return resultReaderBoundary.resultPathExt(path); }

function isHtmlAsset(path) { return resultReaderBoundary.isHtmlAsset(path); }

function isDataResultsZip(path) { return resultReaderBoundary.isDataResultsZip(path); }

function isAntiSmashArtifact(path) { return resultReaderBoundary.isAntiSmashArtifact(path); }

function isAntiSmashHtmlArtifact(path) { return resultReaderBoundary.isAntiSmashHtmlArtifact(path); }

function isFunbgcexArtifact(path) { return resultReaderBoundary.isFunbgcexArtifact(path); }

function isFunbgcexHtmlArtifact(path) { return resultReaderBoundary.isFunbgcexHtmlArtifact(path); }

function isBigscapeArtifact(path) { return resultReaderBoundary.isBigscapeArtifact(path); }

function isBigscapeHtmlArtifact(path) { return resultReaderBoundary.isBigscapeHtmlArtifact(path); }

const BIGSCAPE_PUBLIC_DATABASE_NAME = 'clusterweave_public.sqlite';

// Automatic Open accepts only the compact web-viewer derivative. The complete
// sanitized public export remains downloadable and is never loaded here.

function isBigscapeDatabaseArtifact(path) { return resultReaderBoundary.isBigscapeDatabaseArtifact(path); }

function isBigscapeViewerDatabaseArtifact(path) { return resultReaderBoundary.isBigscapeViewerDatabaseArtifact(path); }

function isSummaryArtifact(path) { return resultReaderBoundary.isSummaryArtifact(path); }

function isAtlasShortlistArtifact(path) { return resultReaderBoundary.isAtlasShortlistArtifact(path); }

function summaryReaderArtifactKind(path) { return resultReaderBoundary.summaryReaderArtifactKind(path); }

function isSummaryReaderArtifact(path) { return resultReaderBoundary.isSummaryReaderArtifact(path); }

function preferredSummaryViewFile(files, kind) { return resultReaderBoundary.preferredSummaryViewFile(files, kind); }

function crossKingdomEvidenceArtifact(path) { return resultReaderBoundary.crossKingdomEvidenceArtifact(path); }

function isPackageOnlyResultArtifact(path) { return resultReaderBoundary.isPackageOnlyResultArtifact(path); }

function isSyntenyArtifact(path) { return resultReaderBoundary.isSyntenyArtifact(path); }

function isPrimaryResultCategory(path) { return resultReaderBoundary.isPrimaryResultCategory(path); }

function resultCategoryMatches(category, path) { return resultReaderBoundary.resultCategoryMatches(category, path); }

function resultPathParts(path) { return resultReaderBoundary.resultPathParts(path); }

function toolSegmentIndex(path, matcher) { return resultReaderBoundary.toolSegmentIndex(path, matcher); }

function readableArtifactLabel(value, fallback = 'artifact') { return resultReaderBoundary.readableArtifactLabel(value, fallback); }


function readableGenomeArtifactLabel(value, fallback = 'Unknown organism') { return resultReaderBoundary.readableGenomeArtifactLabel(value, fallback); }
function titleCaseArtifactLabel(value, fallback = 'artifact') { return resultReaderBoundary.titleCaseArtifactLabel(value, fallback); }

function fileStemFromPath(path) { return resultReaderBoundary.fileStemFromPath(path); }

function summaryArtifactLabel(path) { return resultReaderBoundary.summaryArtifactLabel(path); }

function syntenyGcfQualifier(value) { return resultReaderBoundary.syntenyGcfQualifier(value); }

function syntenyArtifactLabel(path) { return resultReaderBoundary.syntenyArtifactLabel(path); }

function activeGenomeArtifactLabel(genomeId, fallback) { return resultReaderBoundary.activeGenomeArtifactLabel(genomeId, fallback); }

function artifactMetaLabel(path, category = '') { return resultReaderBoundary.artifactMetaLabel(path, category); }

function toolGenomeLabel(path, toolKey) { return resultReaderBoundary.toolGenomeLabel(path, toolKey); }

function toolHtmlSortKey(path) { return resultReaderBoundary.toolHtmlSortKey(path); }

function uniqueToolHtmlArtifacts(files, toolKey) { return resultReaderBoundary.uniqueToolHtmlArtifacts(files, toolKey); }

function bigscapeHtmlSortKey(path) { return resultReaderBoundary.bigscapeHtmlSortKey(path); }

function bigscapeExpectedHtmlPathForDatabase(databasePath) { return resultReaderBoundary.bigscapeExpectedHtmlPathForDatabase(databasePath); }

function bigscapeExpectedViewerPathForDatabase(databasePath) { return resultReaderBoundary.bigscapeExpectedViewerPathForDatabase(databasePath); }

function chooseBigscapeDatabase(htmlPath, databaseFiles) { return resultReaderBoundary.chooseBigscapeDatabase(htmlPath, databaseFiles); }

function summarySortKey(path) { return resultReaderBoundary.summarySortKey(path); }

function buildResultArtifacts(files) { return resultReaderBoundary.buildResultArtifacts(files); }

function resultArtifacts(files = activeResultFiles) { return resultReaderBoundary.resultArtifacts(files); }

function resultCategoryCounts(files) { return resultReaderBoundary.resultCategoryCounts(files); }

function resultCategoryAvailable(category, counts) { return resultReaderBoundary.resultCategoryAvailable(category, counts); }

function firstAvailableResultCategory(counts) { return resultReaderBoundary.firstAvailableResultCategory(counts); }

function defaultFocusedResultCategory(counts) { return resultReaderBoundary.defaultFocusedResultCategory(counts); }

function resultFilesForCategory(category, files) { return resultReaderBoundary.resultFilesForCategory(category, files); }

function resultCategoryLabel(category) { return resultReaderBoundary.resultCategoryLabel(category); }

function resultCategoryCopy(category) { return resultReaderBoundary.resultCategoryCopy(category); }

function resultCategoryIcon(category) { return resultReaderBoundary.resultCategoryIcon(category); }

function resultItemCountLabel(item) { return resultReaderBoundary.resultItemCountLabel(item); }

function resultOverviewMetricItems(items, counts) { return resultReaderBoundary.resultOverviewMetricItems(items, counts); }

function renderResultMetricItem(item) { return resultReaderBoundary.renderResultMetricItem(item); }

function resultLollipopItems(artifacts = activeResultArtifacts || buildResultArtifacts(activeResultFiles), counts = null) { return resultReaderBoundary.resultLollipopItems(artifacts, counts); }

function resultCategoryItems(counts) { return resultReaderBoundary.resultCategoryItems(counts); }

function renderResultOverviewPanel(items, counts) { return resultReaderBoundary.renderResultOverviewPanel(items, counts); }

function resultFolderTabUnit(key) { return resultReaderBoundary.resultFolderTabUnit(key); }

function resultFolderTabCountLabel(key, count) { return resultReaderBoundary.resultFolderTabCountLabel(key, count); }

function resultFolderTabItems(counts) { return resultReaderBoundary.resultFolderTabItems(counts); }

function renderResultFolderTab(item) { return resultReaderBoundary.renderResultFolderTab(item); }

function updateResultDashboardVisibility(status, fileCount = null) { return resultReaderBoundary.updateResultDashboardVisibility(status, fileCount); }

function renderResultBubblePanel(files, status) { return resultReaderBoundary.renderResultBubblePanel(files, status); }

function updateArchiveButton() { return resultReaderBoundary.updateArchiveButton(); }

function archiveDownloadDetail(download) { return resultReaderBoundary.archiveDownloadDetail(download); }

function renderArchiveDownloadStatus(status = archiveDownloadStatus) { return resultReaderBoundary.renderArchiveDownloadStatus(status); }

function setArchiveDownloadStatus(status, dismissAfterMs = 0) { return resultReaderBoundary.setArchiveDownloadStatus(status, dismissAfterMs); }

async function readArchiveResponseBlob(response, requestId) { return resultReaderBoundary.readArchiveResponseBlob(response, requestId); }

async function downloadResultArchive(event) { return resultReaderBoundary.downloadResultArchive(event); }


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

function setResultReaderSurface(surface) { return resultReaderBoundary.setResultReaderSurface(surface); }

function renderResultFileSurface(jobId, files) { return resultReaderBoundary.renderResultFileSurface(jobId, files); }

function renderFocusedResultCategory(category) { return resultReaderBoundary.renderFocusedResultCategory(category); }

function artifactReaderHead(category, countLabel) { return resultReaderBoundary.artifactReaderHead(category, countLabel); }

function resultOpenLink(jobId, path, label = 'Open') { return resultReaderBoundary.resultOpenLink(jobId, path, label); }

function resultDownloadLink(jobId, path, label = 'Download') { return resultReaderBoundary.resultDownloadLink(jobId, path, label); }

function renderToolHtmlReader(jobId, toolKey, items) { return resultReaderBoundary.renderToolHtmlReader(jobId, toolKey, items); }

function normalizedSyntenyTaxon(value) { return resultReaderBoundary.normalizedSyntenyTaxon(value); }

function syntenyArtifactTaxon(path) { return resultReaderBoundary.syntenyArtifactTaxon(path); }

function syntenyArtifactGenome(path) { return resultReaderBoundary.syntenyArtifactGenome(path); }

function syntenyArtifactTrack(path) { return resultReaderBoundary.syntenyArtifactTrack(path); }

function syntenyTaxonGroups(items) { return resultReaderBoundary.syntenyTaxonGroups(items); }

function switchSyntenyTaxon(taxon) { return resultReaderBoundary.switchSyntenyTaxon(taxon); }

function renderSyntenyReader(jobId, items) { return resultReaderBoundary.renderSyntenyReader(jobId, items); }

function jsonForInlineScript(value) { return resultReaderBoundary.jsonForInlineScript(value); }

function bigscapePreviewChannel() { return resultReaderBoundary.bigscapePreviewChannel(); }

async function validatedBigscapeDatabaseBuffer(response) { return resultReaderBoundary.validatedBigscapeDatabaseBuffer(response); }

function injectBigscapeDatabaseContract(htmlText, dbName, dbPath, channel) { return resultReaderBoundary.injectBigscapeDatabaseContract(htmlText, dbName, dbPath, channel); }

async function openBigscapeResult(event, jobId, htmlPath, databasePath) { return resultReaderBoundary.openBigscapeResult(event, jobId, htmlPath, databasePath); }

function renderBigscapeReader(jobId, bigscape) { return resultReaderBoundary.renderBigscapeReader(jobId, bigscape); }


function summaryViewDefinitions(summaryFiles) { return resultReaderBoundary.summaryViewDefinitions(summaryFiles); }

function switchSummaryView(view) { return resultReaderBoundary.switchSummaryView(view); }

function renderSummaryReader(jobId, summaryFiles) { return resultReaderBoundary.renderSummaryReader(jobId, summaryFiles); }
function parseDelimitedLine(line, delimiter) { return resultReaderBoundary.parseDelimitedLine(line, delimiter); }

function allBgcDisplayValue(row, key) { return resultReaderBoundary.allBgcDisplayValue(row, key); }

function allBgcFilteredRows() { return resultReaderBoundary.allBgcFilteredRows(); }

function allBgcGenomeValues(rows, taxon = '') { return resultReaderBoundary.allBgcGenomeValues(rows, taxon); }

function allBgcTableMarkup(rows) { return resultReaderBoundary.allBgcTableMarkup(rows); }

function refreshAllBgcRows() { return resultReaderBoundary.refreshAllBgcRows(); }

function updateAllBgcFilter(key, value) { return resultReaderBoundary.updateAllBgcFilter(key, value); }

function sortAllBgcTable(key) { return resultReaderBoundary.sortAllBgcTable(key); }

function renderAllBgcTable() { return resultReaderBoundary.renderAllBgcTable(); }

async function loadAllBgcReaderFile(path) { return resultReaderBoundary.loadAllBgcReaderFile(path); }

function preferredSummaryColumnIndexes(headers) { return resultReaderBoundary.preferredSummaryColumnIndexes(headers); }

function summaryMetricValue(text, label) { return resultReaderBoundary.summaryMetricValue(text, label); }

function numericSummaryMetric(value) { return resultReaderBoundary.numericSummaryMetric(value); }

function summaryTitleFromText(path, text) { return resultReaderBoundary.summaryTitleFromText(path, text); }

function summaryTopCount(text) { return resultReaderBoundary.summaryTopCount(text); }

function summaryCondensedTitle(path, text, count = 0) { return resultReaderBoundary.summaryCondensedTitle(path, text, count); }

function renderMarkdownBody(text) { return resultReaderBoundary.renderMarkdownBody(text); }

function condensedMarkdownBodyText(text) { return resultReaderBoundary.condensedMarkdownBodyText(text); }

function renderSummaryHeading(path, text, count) { return resultReaderBoundary.renderSummaryHeading(path, text, count); }

function atlasMemberGenomes(row) { return resultReaderBoundary.atlasMemberGenomes(row); }

function atlasAnnotationHits(row) { return resultReaderBoundary.atlasAnnotationHits(row); }

function atlasTaxonSection(row) { return resultReaderBoundary.atlasTaxonSection(row); }

function atlasSummaryValue(row, key) { return resultReaderBoundary.atlasSummaryValue(row, key); }

function renderAtlasSummary(headers, bodyRows) { return resultReaderBoundary.renderAtlasSummary(headers, bodyRows); }

function renderDelimitedSummary(path, text) { return resultReaderBoundary.renderDelimitedSummary(path, text); }

function renderMarkdownSummary(path, text) { return resultReaderBoundary.renderMarkdownSummary(path, text); }

function renderTextSummary(path, text) { return resultReaderBoundary.renderTextSummary(path, text); }

async function loadSummaryReaderFile(path) { return resultReaderBoundary.loadSummaryReaderFile(path); }

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
  if (!currentJobSelection(jobId, seq)) return;
  const card = document.getElementById('results-card');
  card.classList.remove('hidden');
  setResultsLoaded(true);
  const runId = publicRunIdForJob(jobId);
  if (!job) {
    const jobResp = await apiFetch(
      `api/results/${encodeURIComponent(runId)}`, {}, { kind: 'job', jobId: runId },
    );
    if (!currentJobSelection(jobId, seq)) return;
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
  if (!currentJobSelection(jobId, seq)) return;
  if (!resp.ok) return;
  const filePayload = await resp.json();
  const files = installResultArtifactDescriptors(filePayload.artifacts, { replace: true });
  if (activeJobMeta) {
    activeJobMeta.result_index_state = filePayload.result_index_state || '';
    activeJobMeta.bigscape_viewer_available = filePayload.bigscape_viewer_available === true;
  }
  if (!currentJobSelection(jobId, seq)) return;
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

function rerunDefaultChecked(job, key) { return diagnosticsControllerBoundary.rerunDefaultChecked(...arguments); }
function rerunPanelMessage(title, copy, status = '') { return diagnosticsControllerBoundary.rerunPanelMessage(...arguments); }
function selectedRerunJob(jobId, job) { return diagnosticsControllerBoundary.selectedRerunJob(...arguments); }
function renderRerunPanel(jobId, job) { return diagnosticsControllerBoundary.renderRerunPanel(...arguments); }
async function rerunActiveJob() { return diagnosticsControllerBoundary.rerunActiveJob(...arguments); }

function normalizedResultPath(path) { return resultReaderBoundary.normalizedResultPath(path); }

function fileNameFromPath(path) { return resultReaderBoundary.fileNameFromPath(path); }

function approvedPhylogenyArtifact(path) { return resultReaderBoundary.approvedPhylogenyArtifact(path); }

function isApprovedPhylogenyArtifact(path) { return resultReaderBoundary.isApprovedPhylogenyArtifact(path); }

function isTaxonTreeSvgAsset(path) { return resultReaderBoundary.isTaxonTreeSvgAsset(path); }

function isTaxonTreeVisualAsset(path) { return resultReaderBoundary.isTaxonTreeVisualAsset(path); }

function isTaxonTreeBundleAsset(path) { return resultReaderBoundary.isTaxonTreeBundleAsset(path); }

function treeDataBundleForFigure(path, files) { return resultReaderBoundary.treeDataBundleForFigure(path, files); }

function isFigureAsset(path) { return resultReaderBoundary.isFigureAsset(path); }

function isSvgFigureAsset(path) { return resultReaderBoundary.isSvgFigureAsset(path); }

function phylogenyArtifactLabel(path) { return resultReaderBoundary.phylogenyArtifactLabel(path); }

function fileTypeLabel(path) { return resultReaderBoundary.fileTypeLabel(path); }

function fileRowLabel(path) { return resultReaderBoundary.fileRowLabel(path); }

function makeFileTreeNode(name, path) { return resultReaderBoundary.makeFileTreeNode(name, path); }

function buildFileTree(files) { return resultReaderBoundary.buildFileTree(files); }

function defaultFolderOpen(path, depth) { return resultReaderBoundary.defaultFolderOpen(path, depth); }

function folderSortKey(node) { return resultReaderBoundary.folderSortKey(node); }

function renderFileRow(jobId, f) { return resultReaderBoundary.renderFileRow(jobId, f); }

function renderFileRows(jobId, files) { return resultReaderBoundary.renderFileRows(jobId, files); }

function renderFileFolder(jobId, node, depth = 0) { return resultReaderBoundary.renderFileFolder(jobId, node, depth); }

function renderFileTreeChildren(jobId, node, depth = 0) { return resultReaderBoundary.renderFileTreeChildren(jobId, node, depth); }

function handleFileFolderToggle(detailsEl) { return resultReaderBoundary.handleFileFolderToggle(detailsEl); }

function figureSortKey(path) { return resultReaderBoundary.figureSortKey(path); }

function figureCaption(path) { return resultReaderBoundary.figureCaption(path); }

function figureZoomKeyFromWrap(wrap) { return resultReaderBoundary.figureZoomKeyFromWrap(wrap); }

function figureZoomRecord(wrap) { return resultReaderBoundary.figureZoomRecord(wrap); }

function clampNumber(value, min, max) { return resultReaderBoundary.clampNumber(value, min, max); }

function readSvgBaseViewBox(svg) { return resultReaderBoundary.readSvgBaseViewBox(svg); }

function applySvgFigureZoom(wrap, svg, state) { return resultReaderBoundary.applySvgFigureZoom(wrap, svg, state); }

function applyFigureZoom(wrap) { return resultReaderBoundary.applyFigureZoom(wrap); }

function setFigureZoom(wrap, nextScale, originX, originY) { return resultReaderBoundary.setFigureZoom(wrap, nextScale, originX, originY); }

function zoomFigureAt(wrap, factor, originX = null, originY = null) { return resultReaderBoundary.zoomFigureAt(wrap, factor, originX, originY); }

function handleFigureWheel(event, wrap) { return resultReaderBoundary.handleFigureWheel(event, wrap); }

function handleFigurePointerDown(event, wrap) { return resultReaderBoundary.handleFigurePointerDown(event, wrap); }

function handleFigurePointerMove(event, wrap) { return resultReaderBoundary.handleFigurePointerMove(event, wrap); }

function handleFigurePointerEnd(event, wrap) { return resultReaderBoundary.handleFigurePointerEnd(event, wrap); }

function zoomFigureControl(event, button, factor) { return resultReaderBoundary.zoomFigureControl(event, button, factor); }

function resetFigureZoomControl(event, button) { return resultReaderBoundary.resetFigureZoomControl(event, button); }

function handleFigureZoomKeydown(event, wrap) { return resultReaderBoundary.handleFigureZoomKeydown(event, wrap); }

function initializeFigureZoomCards() { return resultReaderBoundary.initializeFigureZoomCards(); }

function sanitizeInlineSvg(svg) { return resultReaderBoundary.sanitizeInlineSvg(svg); }

function preserveInlineSvgAccessibility(svg, path, index) { return resultReaderBoundary.preserveInlineSvgAccessibility(svg, path, index); }

async function hydrateSvgFigures(jobId) { return resultReaderBoundary.hydrateSvgFigures(jobId); }

function figureFolderDefinitions(files) { return resultReaderBoundary.figureFolderDefinitions(files); }

function switchFigureView(view) { return resultReaderBoundary.switchFigureView(view); }

function renderFigureFolderTabs(folders) { return resultReaderBoundary.renderFigureFolderTabs(folders); }

function renderViz(jobId, files) { return resultReaderBoundary.renderViz(jobId, files); }

async function hydrateAuthenticatedFigures(jobId) { return resultReaderBoundary.hydrateAuthenticatedFigures(jobId); }

function renderResultCategorySummary(category, visibleCount, totalCount) { return resultReaderBoundary.renderResultCategorySummary(category, visibleCount, totalCount); }

function renderFileTable(jobId, files, options = {}) { return resultReaderBoundary.renderFileTable(jobId, files, options); }

// ── System Console (Worker Status) ──────────────────────────────────────────
function startSystemConsolePolling() { return diagnosticsControllerBoundary.startSystemConsolePolling(...arguments); }
function stopSystemConsolePolling() { return diagnosticsControllerBoundary.stopSystemConsolePolling(...arguments); }

function startPublicImpactPolling() {
  if (publicImpactPollTimer) return;
  publicImpactPollTimer = window.setInterval(() => {
    void fetchSystemStatus({ renderWorker: false });
  }, 15000);
}

async function pollSystemStatus() { return diagnosticsControllerBoundary.pollSystemStatus(...arguments); }
function updateWorkerTelemetryBadge(status, label) { return diagnosticsControllerBoundary.updateWorkerTelemetryBadge(...arguments); }
function appendSystemLog(text) { return diagnosticsControllerBoundary.appendSystemLog(...arguments); }

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
      if (transient) {
        rememberClusterweaveGameConnectionState('reconnecting');
        window.ClusterWeaveGame?.setConnectionState?.('reconnecting');
      }
      if (!bootstrapComplete) {
        setClusterweaveGameBootstrapEligible(transient);
      }
      return null;
    }
    const payload = await resp.json();
    rememberClusterweaveGameConnectionState('connected');
    window.ClusterWeaveGame?.setConnectionState?.('connected');
    if (!bootstrapComplete) {
      const bootstrapEligible = isFullSystemStatus(payload) && payload.ready !== true;
      setClusterweaveGameBootstrapEligible(bootstrapEligible);
    }
    authChecked = true;
    smtpEnabled = !!payload.smtp_enabled;
    if (payload.public_quota && typeof payload.public_quota === 'object') {
      publicQuota = { ...publicQuota, ...payload.public_quota };
      intakeControllerBoundary?.applyPublicQuotaLimits();
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
    const connection = navigator.onLine === false ? 'browser-offline' : 'reconnecting';
    rememberClusterweaveGameConnectionState(connection);
    window.ClusterWeaveGame?.setConnectionState?.(connection);
    if (!bootstrapComplete) {
      setClusterweaveGameBootstrapEligible(true);
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
async function bootApiResultBoundary() {
  const { createApiResultBoundary } = await import(API_RESULT_MODULE_PATH);
  apiResultBoundary = createApiResultBoundary({
    currentHref: () => window.location.href,
    configuredApiBase: () => window.CLUSTERWEAVE_API_BASE || '',
    fetchImpl: (...args) => window.fetch(...args),
    HeadersImpl: window.Headers,
    adminToken,
    submitToken,
    readTokenForJob,
    accessMode: () => accessMode,
    canUseAdminSurfaces,
    publicRunIdForJob,
    resultArtifactId,
    installResultArtifactDescriptor,
    resultArtifactDescriptor,
    resultUrlShouldStayExternal,
    resultAssetHashSuffix,
  });
}

async function bootResultReaderBoundary() {
  const { createResultReaderBoundary } = await import(RESULT_READER_MODULE_PATH);
  resultReaderBoundary = createResultReaderBoundary({
    state: resultReaderState,
    activeAnalysisCapabilities,
    analysisCapabilityEnabled,
    animateResultReaderOpen,
    animateSummaryReaderDocument,
    apiFetch,
    bigscapeViewerFetch,
    canOpenRichHtmlArtifacts,
    canUseAdminSurfaces,
    escapeHtml,
    escapeJsString,
    figureApplicableToAnalysis,
    fmt_size,
    publicRunIdForJob,
    rerenderWorkflowSpineForResults,
    resolveResultArtifact,
    resultCategoryApplicable,
    resultFetch,
    resultHref,
    resultNeedsAuth,
    safeGenomeProgressLabel,
    setResultFocusMode,
    setStatusBadge,
  });
}

async function bootIntakeTaxonBoundary() {
  const { createIntakeTaxonBoundary, createIntakeControllerBoundary } = await import(INTAKE_TAXON_MODULE_PATH);
  intakeTaxonBoundary = createIntakeTaxonBoundary({
    publicGenomeStem,
    canonicalGenomeInputKey,
    normalizeTaxonGroup,
  });
  intakeControllerBoundary = createIntakeControllerBoundary({
    state: intakeControllerState,
    intakeTaxonBoundary,
    ext,
    escapeHtml,
    escapeJsString,
    fmt_size,
    boolToFlag,
    normalizeAnalysisScope,
    analysisScopeLabel,
    normalizeTaxonGroup,
    normalizeTaxonCounts,
    applyAnalysisCapabilityVisibility,
    canUseAdminSurfaces,
    publicWorkflowLocked,
    effectiveCpuCount,
    effectiveAnnotationStrategy,
    effectiveCheckboxValue,
    collectRunSetupAccessReceipt,
    rememberOpenedRun,
    renderSubmissionConfirmation,
    lockSubmittedIntake,
    loadJob,
    refreshJobHistory,
    apiFetch,
    updateRunSummary,
    navigateToSection,
    publicCanonicalCpus: PUBLIC_CANONICAL_CPUS,
  });
}

async function bootJobLifecycleBoundary() {
  await jobLifecycleBoundaryInstalled;
}

async function bootDiagnosticsAccessBoundary() {
  await diagnosticsAccessBoundaryInstalled;
}

async function bootMotionBoundary() {
  await motionBoundaryInstalled;
}

async function initializeApp() {
  const apiResultBoundaryReady = bootApiResultBoundary();
  const resultReaderBoundaryReady = bootResultReaderBoundary();
  const intakeTaxonBoundaryReady = bootIntakeTaxonBoundary();
  const jobLifecycleBoundaryReady = bootJobLifecycleBoundary();
  const diagnosticsAccessBoundaryReady = bootDiagnosticsAccessBoundary();
  const motionBoundaryReady = bootMotionBoundary();
  const initialHashRun = captureInitialResultHash();
  window.addEventListener('hashchange', syncNavFromHash);
  window.addEventListener('resize', () => {
    applyStoredPanelWidths();
    const helix = document.getElementById('weavemap-helix');
    if (helix) delete helix.dataset.rendered;
    renderWeaveHelix(activeJobMeta);
    });
  await Promise.all([jobLifecycleBoundaryReady, motionBoundaryReady]);
  startStageTicker();
  wireClusterweaveGameAdapter();
  wirePanelResizers();
  await diagnosticsAccessBoundaryReady;
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
  await intakeTaxonBoundaryReady;
  resetStagedAnalysisState('fungi');
  renderAcceptedAccessions();
  initializeBrutalInputStation();
  switchEntryTab('new');
  await Promise.all([jobLifecycleBoundaryReady, resultReaderBoundaryReady]);
  showEmptyResults();
  bootBgcWorkflowDna();
  updateBgcWorkflowDnaFromJob(null);
  wireDocsDisclosure();
  syncNavFromHash();
  setUIMode('guided', { preserveDisclosure: true });
  warmGsapMotion();
  await apiResultBoundaryReady;

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
