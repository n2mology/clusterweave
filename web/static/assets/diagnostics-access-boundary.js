export function createDiagnosticsAccessBoundary({
  documentImpl,
  windowImpl,
  canUseAdminSurfaces,
  setCardCollapsed,
  hydrateQaLogs,
  shouldTailQaLogs,
  refreshJobHistory,
  pollSystemStatus,
  renderRerunPanel,
  activeJob,
  cssAttributeValue,
  animateOpsPanelToggle,
}) {
  const OPS_TABS = ['jobs', 'worker', 'qa'];
  const OPS_TAB_PANEL_IDS = { jobs: 'jobs-card', worker: 'console-card', qa: 'progress-card' };
  const RERUN_PAYLOAD_STAGE_KEYS = [
    'run_genome_prep', 'run_annotation', 'run_bigscape', 'run_summary',
    'run_clinker', 'run_figures', 'run_nplinker',
  ];
  const STAGE_CAPABILITY_KEYS = {
    prep: 'prepare',
    annotation: 'annotation',
    bigscape: 'bigscape',
    summary: 'summary',
    clinker: 'clinker',
    figures: 'figures',
    nplinker: 'nplinker',
  };
  let activeTab = 'jobs';
  let lastPanelFocus = null;
  let panelKeyboardWired = false;
  let uiMode = 'guided';

  function normalizeAccessMode(mode) {
    return ['public', 'admin', 'local'].includes(mode) ? mode : 'public';
  }

  function setUIMode(mode, options = {}) {
    if (normalizeAccessMode(options.accessMode) === 'public' && mode !== 'guided') mode = 'guided';
    const normalized = ['guided', 'lab', 'advanced'].includes(mode) ? mode : 'guided';
    uiMode = normalized;
    documentImpl.body.dataset.uiMode = normalized;
    documentImpl.querySelectorAll('[data-mode-option]').forEach(button => {
      const active = button.dataset.modeOption === normalized;
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });

    const workflowControls = documentImpl.getElementById('workflow-controls');
    const advancedPanel = documentImpl.getElementById('advanced-panel');
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
    return normalized;
  }

  function setOpsPanelCollapsed(collapsed) {
    const isCollapsed = !!collapsed;
    documentImpl.body.dataset.opsPanel = isCollapsed ? 'collapsed' : 'open';
    const panel = documentImpl.getElementById('ops-side-panel');
    if (panel) panel.setAttribute('aria-hidden', isCollapsed ? 'true' : 'false');
    const toggle = documentImpl.getElementById('ops-panel-toggle');
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

  function activeOpsPanelElement() {
    return documentImpl.getElementById(OPS_TAB_PANEL_IDS[activeTab] || OPS_TAB_PANEL_IDS.jobs);
  }

  function syncOpsTabs() {
    const selectedTab = OPS_TABS.includes(activeTab) ? activeTab : 'jobs';
    activeTab = selectedTab;
    documentImpl.body.dataset.opsTab = selectedTab;
    documentImpl.querySelectorAll('.ops-nav-button[data-ops-tab]').forEach(button => {
      const active = button.dataset.opsTab === selectedTab;
      button.classList.toggle('active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
      button.tabIndex = active ? 0 : -1;
    });
    OPS_TABS.forEach(tab => {
      const panel = documentImpl.getElementById(OPS_TAB_PANEL_IDS[tab]);
      if (!panel) return;
      const active = tab === selectedTab;
      panel.hidden = !active;
      panel.classList.toggle('ops-tab-active', active);
      if (tab === 'qa') panel.classList.toggle('hidden', !active || !canUseAdminSurfaces());
    });
  }

  function switchOpsTab(tab, options = {}) {
    if (!canUseAdminSurfaces()) return;
    activeTab = OPS_TABS.includes(tab) ? tab : 'jobs';
    syncOpsTabs();
    if (activeTab === 'qa') void hydrateQaLogs({ tail: shouldTailQaLogs(), autoScroll: true });
    if (activeTab === 'jobs') refreshJobHistory();
    if (activeTab === 'worker') pollSystemStatus();
    if (activeTab === 'rerun') {
      const { jobId, job } = activeJob();
      renderRerunPanel(jobId, job);
    }
    if (options.focus !== false) {
      const target = options.focusPanel
        ? activeOpsPanelElement()
        : documentImpl.querySelector(`.ops-nav-button[data-ops-tab="${cssAttributeValue(activeTab)}"]`);
      target?.focus?.({ preventScroll: true });
    }
  }

  function handleOpsTabKeydown(event) {
    const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End'];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    const current = OPS_TABS.indexOf(activeTab);
    let next = current >= 0 ? current : 0;
    if (event.key === 'ArrowLeft') next = (next + OPS_TABS.length - 1) % OPS_TABS.length;
    if (event.key === 'ArrowRight') next = (next + 1) % OPS_TABS.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = OPS_TABS.length - 1;
    switchOpsTab(OPS_TABS[next]);
  }

  function openOpsPanel(options = {}) {
    if (!canUseAdminSurfaces()) return;
    lastPanelFocus = options.returnFocus || documentImpl.activeElement || documentImpl.getElementById('ops-panel-toggle');
    setOpsPanelCollapsed(false);
    if (options.tab) activeTab = OPS_TABS.includes(options.tab) ? options.tab : activeTab;
    syncOpsTabs();
    animateOpsPanelToggle(true);
    const focusTarget = options.focusPanel
      ? activeOpsPanelElement()
      : documentImpl.querySelector(`.ops-nav-button[data-ops-tab="${cssAttributeValue(activeTab)}"]`);
    focusTarget?.focus?.({ preventScroll: true });
  }

  function closeOpsPanel(options = {}) {
    setOpsPanelCollapsed(true);
    animateOpsPanelToggle(false);
    if (options.returnFocus !== false) {
      const fallback = documentImpl.getElementById('ops-panel-toggle');
      const target = lastPanelFocus && lastPanelFocus.isConnected ? lastPanelFocus : fallback;
      target?.focus?.({ preventScroll: true });
    }
  }

  function toggleOpsPanel() {
    if (!canUseAdminSurfaces()) return;
    if (documentImpl.body.dataset.opsPanel === 'collapsed') {
      openOpsPanel({ returnFocus: documentImpl.getElementById('ops-panel-toggle') });
    } else {
      closeOpsPanel({ returnFocus: true });
    }
  }

  function ensureOpsPanelToggle() {
    if (!canUseAdminSurfaces() || documentImpl.getElementById('ops-panel-toggle')) return;
    const panel = documentImpl.getElementById('ops-side-panel');
    if (!panel?.parentElement) return;
    if (panel.parentElement !== documentImpl.body) documentImpl.body.appendChild(panel);
    const toggle = documentImpl.createElement('button');
    toggle.className = 'ops-panel-toggle admin-only';
    toggle.id = 'ops-panel-toggle';
    toggle.type = 'button';
    toggle.setAttribute('aria-controls', 'ops-side-panel');
    toggle.innerHTML = '<span class="ops-panel-toggle-icon" data-ops-toggle-icon>▲</span>';
    toggle.addEventListener('click', toggleOpsPanel);
    documentImpl.body.insertBefore(toggle, panel);
    setOpsPanelCollapsed(documentImpl.body.dataset.opsPanel !== 'open');
    syncOpsTabs();
  }

  function removeOpsPanelToggle() {
    documentImpl.getElementById('ops-panel-toggle')?.remove();
    setOpsPanelCollapsed(true);
  }

  function wireOpsPanelKeyboard() {
    if (panelKeyboardWired) return;
    panelKeyboardWired = true;
    documentImpl.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      if (!canUseAdminSurfaces() || documentImpl.body.dataset.opsPanel !== 'open') return;
      event.preventDefault();
      closeOpsPanel({ returnFocus: true });
    });
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
    return RERUN_PAYLOAD_STAGE_KEYS.some(key => !!payload?.[key]);
  }

  function rerunStageAllowed(key, runtimeCapabilities) {
    const stageCaps = runtimeCapabilities?.stages;
    if (!stageCaps) return true;
    const cap = stageCaps[STAGE_CAPABILITY_KEYS[key] || key];
    return !cap || cap.available !== false;
  }

  function scrollElementToBottom(element) {
    if (!element) return;
    element.scrollTop = Math.max(0, element.scrollHeight - element.clientHeight);
  }

  return {
    activeOpsTab: () => activeTab,
    currentUIMode: () => uiMode,
    normalizeAccessMode,
    setUIMode,
    setOpsPanelCollapsed,
    ensureOpsPanelToggle,
    removeOpsPanelToggle,
    activeOpsPanelElement,
    syncOpsTabs,
    switchOpsTab,
    handleOpsTabKeydown,
    openOpsPanel,
    closeOpsPanel,
    toggleOpsPanel,
    wireOpsPanelKeyboard,
    rerunPayloadFromStages,
    rerunPayloadHasStages,
    rerunStageAllowed,
    scrollElementToBottom,
  };
}


export function createDiagnosticsControllerBoundary({
  document,
  window,
  state,
  stages: STAGES,
  capabilities,
}) {
  const {
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
  } = capabilities;

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
    : state.runtimeStatusSnapshot.server;
  const submissions = hasSystem
    ? (system.submissions || (system.submissions_open === true ? 'open' : system.submissions_open === false ? 'paused' : state.runtimeStatusSnapshot.submissions))
    : state.runtimeStatusSnapshot.submissions;
  const jobsProcessed = hasSystem && Object.prototype.hasOwnProperty.call(system, 'jobs_processed')
    ? system.jobs_processed
    : state.runtimeStatusSnapshot.jobsProcessed;
  const runningJobs = Object.prototype.hasOwnProperty.call(counts, 'runningJobs')
    ? counts.runningJobs
    : (hasSystem && Object.prototype.hasOwnProperty.call(system, 'running_jobs') ? system.running_jobs : state.runtimeStatusSnapshot.runningJobs);
  const queuedJobs = Object.prototype.hasOwnProperty.call(counts, 'queuedJobs')
    ? counts.queuedJobs
    : (hasSystem && Object.prototype.hasOwnProperty.call(system, 'queued_jobs') ? system.queued_jobs : state.runtimeStatusSnapshot.queuedJobs);
  const diagnosticsVisible = canUseAdminSurfaces() && (fullStatus || Object.keys(counts).length > 0);

  state.runtimeStatusSnapshot = {
    server: runtimeMetricText(server, 'Checking'),
    submissions: runtimeMetricText(submissions, 'Checking'),
    runningJobs,
    queuedJobs,
    jobsProcessed,
    scope: diagnosticsVisible ? 'diagnostics' : 'public',
  };

  setRuntimePanelValue('public-impact-server', state.runtimeStatusSnapshot.server);
  setRuntimePanelValue('public-impact-running', runtimeMetricText(runningJobs, '0'));
  setRuntimePanelValue('public-impact-queued', runtimeMetricText(queuedJobs, '0'));
  setRuntimePanelValue('public-impact-completed', runtimeMetricText(jobsProcessed, '0'));
  setRuntimePanelValue('runtime-server-status', state.runtimeStatusSnapshot.server);
  setRuntimePanelValue('runtime-submissions-status', state.runtimeStatusSnapshot.submissions);
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

function capabilityStageSummary(capabilities = state.runtimeCapabilities) {
  const stages = capabilities && typeof capabilities === 'object' ? capabilities.stages : null;
  if (!stages || typeof stages !== 'object') return 'Stage policy pending';
  const entries = Object.entries(stages);
  const enabled = entries.filter(([, value]) => capabilityEnabled(value));
  return `${enabled.length}/${entries.length || enabled.length} stages available`;
}

function runtimePolicyLabel(system = null) {
  const runtime = (system && system.runtime) || {};
  const caps = (system && system.capabilities) || state.runtimeCapabilities || {};
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
  const runningCount = hasMeta('runningCount') ? Number(meta.runningCount || 0) : Math.max(listRunning, Number(system?.running_jobs || 0), Number(state.lastWorkerTelemetry.runningCount || 0));
  const pendingCount = hasMeta('pendingCount') ? Number(meta.pendingCount || 0) : Math.max(listPending, Number(system?.queued_jobs || 0), Number(state.lastWorkerTelemetry.pendingCount || 0));
  const worker = (system && system.worker) || {};
  const status = String(meta.status || state.lastWorkerTelemetry.status || state.workerStatus || system?.state || 'unknown').toLowerCase();
  const statusLabels = {
    unknown: 'Monitoring',
    idle: 'Idle',
    ready: 'Ready',
    processing: 'Processing',
    error: 'Error',
    starting: 'Starting',
  };
  const stateLabel = statusLabels[status] || statusLabel(status);
  const concurrency = Number(meta.concurrency || worker.concurrency || system?.concurrency || state.lastWorkerTelemetry.concurrency || 0);
  const activeCount = Number(meta.activeCount || worker.active_count || runningCount || state.lastWorkerTelemetry.activeCount || 0);
  const submissions = state.runtimeStatusSnapshot.submissions || runtimeMetricText(system?.submissions || system?.submissions_open, 'Checking');
  const stageSummary = capabilityStageSummary((system && system.capabilities) || state.runtimeCapabilities);
  summary.textContent = `${stateLabel} · ${runningCount.toLocaleString()} running · ${pendingCount.toLocaleString()} queued`;
  setDrawerText('worker-drawer-state', stateLabel);
  setDrawerText('worker-drawer-detail', status === 'error'
    ? String(system?.detail || 'Worker reported an error.')
    : `Signal ${state.runtimeStatusSnapshot.server || 'checking'}; submissions ${submissions}.`);
  setDrawerText('worker-drawer-queue', `${runningCount} running / ${pendingCount} queued`);
  setDrawerText('worker-drawer-queue-detail', concurrency
    ? `${activeCount} active worker slot${activeCount === 1 ? '' : 's'} of ${concurrency}.`
    : 'Worker concurrency pending.');
  setDrawerText('worker-drawer-policy', runtimePolicyLabel(system));
  setDrawerText('worker-drawer-policy-detail', stageSummary);
}

function renderQaDrawer(job = state.activeJobMeta, files = state.activeResultFiles) {
  const summary = document.getElementById('qa-drawer-summary');
  if (!summary) return;
  const selectedId = String((job && job.id) || state.activeJobId || '');
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
  const rerunJobId = String(state.rerunScopeOpenJobId || '');
  const rerunJob = rerunJobId && (state.jobHistoryById.get(rerunJobId) || (state.activeJobId === rerunJobId ? state.activeJobMeta : null));
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
  setDrawerText('qa-log-count-card', `${Number(state.logCursor || 0).toLocaleString()} lines`);
  setDrawerText('qa-log-detail', selectedId ? `Updated ${updatedText}.` : 'Logs attach after a job is opened.');
  setDrawerText('qa-file-count', pluralizeCount(fileList.length, 'file'));
  setDrawerText('qa-file-detail', fileList.length ? 'Manifest indexed for the selected run.' : 'Result files appear after indexing.');
  setDrawerText('qa-rerun-scope', rerunJobId || 'No job selected');
  setDrawerText('qa-rerun-detail', rerunDetail);
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
  if (state.rerunScopeOpenJobId === String(jobId || '')) state.rerunScopeOpenJobId = '';
  if (button) button.setAttribute('aria-expanded', 'false');
  item?.classList.remove('has-open-rerun');
}

async function toggleJobRerunScope(event, jobId) {
  event?.preventDefault?.();
  event?.stopPropagation?.();
  if (!canUseAdminSurfaces()) return;
  const safeJobId = String(jobId || '');
  if (!safeJobId) return;

  if (state.rerunScopeOpenJobId === safeJobId) {
    state.rerunScopeOpenJobId = '';
    const openDetails = diagnosticRerunDetails(safeJobId);
    if (openDetails) openDetails.open = false;
    event?.currentTarget?.setAttribute?.('aria-expanded', 'false');
    return;
  }

  const previousDetails = diagnosticRerunDetails(state.rerunScopeOpenJobId);
  if (previousDetails) previousDetails.open = false;
  state.rerunScopeOpenJobId = safeJobId;
  openOpsPanel({ tab: 'jobs', focusPanel: false, returnFocus: event?.currentTarget || document.activeElement });
  state.lastJobHistoryRenderKey = '';
  renderJobHistory([...state.jobHistoryById.values()]);
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
    || diagnosticRerunDetails(state.rerunScopeOpenJobId)
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
  const targetJobId = String(jobId || state.rerunScopeOpenJobId || '');
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
    state.rerunScopeOpenJobId = '';
    await loadJob(targetJobId, true, { source: 'rerun' });
    refreshJobHistory();
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message || String(err);
  }
}

function rerunDefaultChecked(job, key) {
  if (!job || job.status === 'success') return false;
  if (!rerunStageAllowed(key)) return false;
  if (!state.activeStageState || !state.activeStageState.enabled.has(key)) return false;
  return !state.activeStageState.completed.has(key);
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
  const requestedId = String(state.rerunScopeOpenJobId || '');
  if (!requestedId) return { jobId: '', job: null };
  const inlineJobId = String((job && job.id) || jobId || '');
  if (inlineJobId === requestedId && job) return { jobId: requestedId, job };
  if (state.activeJobId === requestedId && state.activeJobMeta) return { jobId: requestedId, job: state.activeJobMeta };
  return { jobId: requestedId, job: state.jobHistoryById.get(requestedId) || null };
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
  const targetJobId = String(state.rerunScopeOpenJobId || '');
  const statusEl = document.getElementById('rerun-status');
  if (!targetJobId) {
    if (statusEl) statusEl.textContent = 'Select a submitted job first.';
    return;
  }
  const job = state.activeJobId === targetJobId && state.activeJobMeta ? state.activeJobMeta : state.jobHistoryById.get(targetJobId);
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
    state.rerunScopeOpenJobId = '';
    document.getElementById('results-card').classList.add('hidden');
    await loadJob(targetJobId, true, { source: 'rerun' });
    refreshJobHistory();
    switchOpsTab('jobs', { focus: false });
  } catch (err) {
    if (statusEl) statusEl.textContent = err.message || String(err);
  }
}

function startSystemConsolePolling() {
  if (!canUseAdminSurfaces()) {
    stopSystemConsolePolling();
    return;
  }
  if (state.systemPollTimer) return;
  updateWorkerTelemetryBadge('unknown', 'Monitoring');
  renderWorkerDrawer(null, null, { status: 'unknown' });
  appendSystemLog('[System] ClusterWeave initialization complete. Monitoring worker...');
  state.systemPollTimer = setInterval(() => {
    pollSystemStatus();
  }, 2000);
  // Initial poll
  pollSystemStatus();
}

function stopSystemConsolePolling() {
  if (state.systemPollTimer) {
    clearInterval(state.systemPollTimer);
    state.systemPollTimer = null;
  }
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
  const concurrency = rawConcurrency || state.lastWorkerTelemetry.concurrency || (activeCount > 0 ? Math.max(activeCount, 1) : 0);
  updateRuntimeStatusPanel(system, { runningJobs: runningCount, queuedJobs: pendingCount });
  const drawerStatus = systemState === 'error'
    ? 'error'
    : runningCount > 0
      ? 'processing'
      : pendingCount > 0
        ? 'ready'
        : 'idle';
  state.lastWorkerTelemetry = { runningCount, pendingCount, activeCount, concurrency, status: drawerStatus };
  renderWorkerDrawer(system, jobs, state.lastWorkerTelemetry);

  if (systemState === 'error') {
    const newStatus = 'error';
    updateWorkerTelemetryBadge(newStatus, 'Error');
    if (newStatus !== state.workerStatus) {
      state.workerStatus = newStatus;
      appendSystemLog(`[Worker] ERROR: ${system.detail || 'Worker reported an error'}`);
    }
    return;
  }

  // Determine worker status based on pending jobs
  if (runningCount > 0) {
    const newStatus = 'processing';
    updateWorkerTelemetryBadge(newStatus, 'Processing');
    if (newStatus !== state.workerStatus) {
      state.workerStatus = newStatus;
      appendSystemLog(`[Worker] Processing ${activeCount} job(s); ${pendingCount} queued`);
    }
  } else if (pendingCount > 0 && state.activeJobId === null) {
    const newStatus = 'ready';
    updateWorkerTelemetryBadge(newStatus, 'Ready');
    if (newStatus !== state.workerStatus) {
      state.workerStatus = newStatus;
      appendSystemLog(`[Worker] Ready - ${pendingCount} queued, concurrency ${concurrency}`);
    }
  } else if (pendingCount === 0 && runningCount === 0) {
    const newStatus = 'idle';
    updateWorkerTelemetryBadge(newStatus, 'Idle');
    if (newStatus !== state.workerStatus) {
      state.workerStatus = newStatus;
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

  return {
    runtimeMetricText,
    setRuntimePanelValue,
    updateRuntimeStatusPanel,
    setDrawerText,
    pluralizeCount,
    capabilityEnabled,
    capabilityStageSummary,
    runtimePolicyLabel,
    renderWorkerDrawer,
    renderQaDrawer,
    queueJobRerun,
    diagnosticRerunDisclosureId,
    diagnosticRerunDetails,
    syncDiagnosticRerunDisclosure,
    toggleJobRerunScope,
    rerunJobFromHistory,
    renderDiagnosticRerunRail,
    updateDiagnosticRerunSubmit,
    queueDiagnosticRerun,
    rerunDefaultChecked,
    rerunPanelMessage,
    selectedRerunJob,
    renderRerunPanel,
    rerunActiveJob,
    startSystemConsolePolling,
    stopSystemConsolePolling,
    pollSystemStatus,
    updateWorkerTelemetryBadge,
    appendSystemLog,
  };
}

globalThis.__clusterweaveInstallDiagnosticsAccessBoundary?.(
  createDiagnosticsAccessBoundary,
  createDiagnosticsControllerBoundary,
);
