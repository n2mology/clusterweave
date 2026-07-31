export function createJobLifecycleBoundary({
  escapeHtml,
  getActiveJobId,
  getCurrentJobSequence,
  documentImpl,
  stages,
  transientJobPoll,
  pollBaseDelayMs,
  pollRetryDelayMs,
  pollLongLogDelayMs,
  pollLongLogThreshold,
}) {
  const GENOME_PROGRESS_TERMINAL_STATES = new Set([
    'complete', 'completed', 'done', 'success', 'succeeded',
    'complete_with_warning',
    'warning', 'dropped', 'failed', 'error', 'skipped',
    'not_applicable', 'not_applicable_taxon', 'not-applicable', 'not applicable',
  ]);
  const GENOME_PROGRESS_WARNING_STATES = new Set([
    'complete_with_warning', 'warning', 'dropped', 'failed', 'error',
  ]);
  const GENOME_PROGRESS_ACTIVE_STATES = new Set(['running', 'active', 'processing']);
  let genomeProgressSnapshotKey = '';
  let genomeProgressSnapshot = new Map();


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

  function compactActivityChipText(value, maxLength = 96) {
    const text = String(value || '').replace(/\s+/g, ' ').trim();
    if (!text) return '';
    return text.length > maxLength ? `${text.slice(0, Math.max(0, maxLength - 3)).trim()}...` : text;
  }

  function normalizePublicWeaveEvent(event) {
    if (!event || typeof event !== 'object') return null;
    const stage = stages.some(item => item.key === event.stage) ? event.stage : 'prep';
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

  function isCurrentJobSelection(jobId, sequence) {
    return sequence === getCurrentJobSequence() && jobId === getActiveJobId();
  }

  function jobDetailPath(jobId, publicResult) {
    const encoded = encodeURIComponent(jobId);
    return publicResult ? `api/results/${encoded}` : `api/jobs/${encoded}?compact=1`;
  }

  function publicActivityPath(runId) {
    return `api/results/${encodeURIComponent(runId)}/activity`;
  }

  function adminLogsPath(jobId, query) {
    return `api/jobs/${encodeURIComponent(jobId)}/logs?${query}`;
  }

  function jobPollDelay(job) {
    if (job === transientJobPoll) return pollRetryDelayMs;
    const logCount = Math.max(0, Number(job?.log_count) || 0);
    return logCount >= pollLongLogThreshold ? pollLongLogDelayMs : pollBaseDelayMs;
  }

  function publicQaEventLine(event) {
    const marker = normalizePublicWeaveEvent(event);
    if (!marker) return '';
    const stage = String(marker.stage || 'prep').replace(/_/g, ' ').toUpperCase();
    const title = compactActivityChipText(marker.title || marker.status || 'Run update', 72);
    const meta = compactActivityChipText(marker.meta || marker.time || '', 48);
    return `[${stage}] ${title}${meta ? ` - ${meta}` : ''}`;
  }

  function createLogLineElement(text) {
    const div = documentImpl.createElement('div');
    div.className = 'log-line';
    if (/error|fatal|failed/i.test(text)) div.classList.add('err');
    else if (/warn/i.test(text)) div.classList.add('warn');
    else if (/=== stage:/i.test(text)) div.classList.add('stage');
    else if (/success|complete|finished/i.test(text)) div.classList.add('ok');
    div.textContent = text;
    return div;
  }

  function jobRuntimeBounds(job) {
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
    const jobId = String(job?.id ?? job?.job_id ?? getActiveJobId() ?? '');
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
      job?.id ?? job?.job_id ?? getActiveJobId() ?? '',
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

  return Object.freeze({
    isCurrentJobSelection,
    parseTimestampMs,
    compactActivityChipText,
    normalizePublicWeaveEvent,
    jobDetailPath,
    publicActivityPath,
    adminLogsPath,
    jobPollDelay,
    publicQaEventLine,
    createLogLineElement,
    jobRuntimeBounds,
    formatJobRuntimeClock,
    safeGenomeProgressText, safeGenomeProgressLabel, genomeProgressPercent, genomeProgressTaxon, normalizeGenomeRegionProgress, normalizeGenomeProgressItem, resetGenomeProgressSnapshot, genomeProgressAttemptKey, genomeProgressExplicitRestart, genomeProgressSnapshotPrefersPrevious, normalizeGenomeProgressItems, genomeProgressStages, genomeProgressCurrentStageIndex, genomeProgressStageKey, genomeProgressStageFraction, genomeProgressStageModel, renderGenomeProgressStages, genomeProgressMeterModel, genomeProgressRibbonText, renderGenomeProgressMeter, renderGenomeProgressCard, genomeProgressSummaryText, bgcWorkflowTitle,
  });
}

export function createJobLifecycleControllerBoundary({
  state,
  lifecyclePolicy,
  capabilities,
  qaLogPageSize,
  stages,
  stageRuntimeHints,
  workflowProgressWeights,
  stageDetails,
  pollBaseDelayMs,
  pollTimeoutMs,
  initialLoadTimeoutMs,
  transientJobPoll,
  workflowDnaModulePath,
  progressTreeConsolePromise,
}) {
  const {
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
    activeOpsTab,
    currentUIMode,
  } = capabilities;
  const QA_LOG_PAGE_SIZE = qaLogPageSize;
  const STAGES = stages;
  const STAGE_RUNTIME_HINTS = stageRuntimeHints;
  const WORKFLOW_PROGRESS_WEIGHTS = workflowProgressWeights;
  const STAGE_DETAILS = stageDetails;
  const JOB_POLL_BASE_DELAY_MS = pollBaseDelayMs;
  const JOB_POLL_TIMEOUT_MS = pollTimeoutMs;
  const JOB_INITIAL_LOAD_TIMEOUT_MS = initialLoadTimeoutMs;
  const TRANSIENT_JOB_POLL = transientJobPoll;
  const WORKFLOW_DNA_MODULE_PATH = workflowDnaModulePath;
  const PROGRESS_TREE_CONSOLE = progressTreeConsolePromise;
  const currentJobSelection = lifecyclePolicy.isCurrentJobSelection;
  const {
    jobPollDelay,
    publicQaEventLine,
    createLogLineElement,
    jobRuntimeBounds,
    formatJobRuntimeClock,
    safeGenomeProgressText,
    safeGenomeProgressLabel,
    genomeProgressPercent,
    genomeProgressTaxon,
    normalizeGenomeRegionProgress,
    normalizeGenomeProgressItem,
    resetGenomeProgressSnapshot,
    genomeProgressAttemptKey,
    genomeProgressExplicitRestart,
    genomeProgressSnapshotPrefersPrevious,
    normalizeGenomeProgressItems,
    genomeProgressStages,
    genomeProgressCurrentStageIndex,
    genomeProgressStageKey,
    genomeProgressStageFraction,
    genomeProgressStageModel,
    renderGenomeProgressStages,
    genomeProgressMeterModel,
    genomeProgressRibbonText,
    renderGenomeProgressMeter,
    renderGenomeProgressCard,
    genomeProgressSummaryText,
    bgcWorkflowTitle,
    compactActivityChipText,
    normalizePublicWeaveEvent,
    parseTimestampMs,
  } = lifecyclePolicy;
  const jobLifecycleBoundary = lifecyclePolicy;

const ALT06_WORKFLOW_STEPS = [
  { id: 'prepare', label: 'Prepare', keys: ['prep'] },
  { id: 'annotate', label: 'Annotate', keys: ['annotation'] },
  { id: 'group', label: 'Group', keys: ['bigscape', 'summary'] },
  { id: 'compare', label: 'Compare', keys: ['clinker'] },
  { id: 'render', label: 'Render', keys: ['figures', 'nplinker'] },
];

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
  if (id && state.activeJobId === id && state.activeJobMeta?.status) return state.activeJobMeta.status;
  return run?.status || '';
}

function setRunStackOpen(open) {
  const shell = document.getElementById('run-stack-shell');
  const menu = document.getElementById('run-stack-menu');
  const toggle = document.getElementById('run-stack-toggle');
  if (!shell || !menu || !toggle) return;
  const hasRuns = loadOpenedRuns().length > 0;
  state.runStackOpen = !!open && hasRuns;
  shell.dataset.runStackOpen = state.runStackOpen ? 'true' : 'false';
  menu.hidden = !state.runStackOpen;
  toggle.setAttribute('aria-expanded', state.runStackOpen ? 'true' : 'false');
  toggle.setAttribute('aria-label', state.runStackOpen ? 'Close run stack' : 'Open run stack');
}

function toggleRunStack() {
  setRunStackOpen(!state.runStackOpen);
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
    const active = id && id === state.activeJobId;
    const label = runStackProjectName(run);
    const status = statusLabel(runStackStatus(run));
    return `
      <button class="run-stack-run${active ? ' active' : ''}" type="button" role="menuitem" data-run-stack-job="${escapeHtml(id)}" onclick="loadRunStackJob('${escapeHtml(jsId)}')">
        <b>${escapeHtml(label)}</b>
        <span>${escapeHtml(shortRunId(id))} | ${escapeHtml(status)}</span>
      </button>`;
  }).join('');
  if (state.runStackOpen) setRunStackOpen(true);
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
  if (state.runStackDismissalWired) return;
  state.runStackDismissalWired = true;
  document.addEventListener('click', event => {
    if (!state.runStackOpen) return;
    const shell = document.getElementById('run-stack-shell');
    if (shell?.contains(event.target)) return;
    setRunStackOpen(false);
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !state.runStackOpen) return;
    event.preventDefault();
    setRunStackOpen(false);
    document.getElementById('run-stack-toggle')?.focus?.({ preventScroll: true });
  });
}

async function refreshJobHistory() {
  if (!canUseAdminSurfaces()) {
    renderOpenedRuns();
    return;
  }
  if (state.jobHistoryInFlight) return;
  state.jobHistoryInFlight = true;
  try {
    const resp = await apiFetch('api/jobs', {}, { kind: 'admin' });
    if (!resp.ok) return;
    const jobs = await resp.json();
    renderJobHistory(jobs);
  } catch (err) {
    console.warn('Job history refresh failed', err);
  } finally {
    state.jobHistoryInFlight = false;
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
    j.id === state.activeJobId,
    j.id === state.rerunScopeOpenJobId,
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

function renderJobHistory(jobs) {
  const el = document.getElementById('job-history');
  if (!el) return;
  const list = (Array.isArray(jobs) ? jobs : []).filter(job => job && job.id);
  state.jobHistoryById = new Map(list.map(job => [String(job.id || ''), job]).filter(([id]) => id));
  const renderKey = jobHistoryRenderKey(list);
  if (renderKey === state.lastJobHistoryRenderKey) return;
  state.lastJobHistoryRenderKey = renderKey;
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
    const selected = jobId && jobId === state.activeJobId;
    const rerunOpen = jobId && state.rerunScopeOpenJobId === jobId;
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
      ${rerunOpen ? renderDiagnosticRerunRail(jobId, job || state.jobHistoryById.get(jobId), displayLabel) : ''}
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
  renderQaDrawer(state.jobHistoryById.get(id) || { id, status: 'pending', stage: 'loading', name: id }, state.activeResultFiles);
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

function publicStageTimingEvent(event) {
  const marker = normalizePublicWeaveEvent(event);
  if (!marker) return null;
  const markerMeta = /^canonical workflow stage$/i.test(marker.meta || '');
  const markerTitle = /^(preparing input workspace|running annotation and bgc detection|running big[-\s]?scape family graph|building summary tables|staging synteny panels|rendering summary figures|running optional nplinker follow-up)$/i.test(marker.title || '');
  if (!markerMeta && !markerTitle) return null;
  return marker;
}

function applyStageTimingFromPublicEvents(job) {
  if (!state.activeStageState || !Array.isArray(job?.public_events)) return;
  if (Number(job?.rerun_count || 0) > 0) return;
  job.public_events.forEach((event) => {
    const marker = publicStageTimingEvent(event);
    if (!marker) return;
    const eventId = `public:${marker.stage}:${marker.time || marker.meta}:${marker.title}`;
    const eventTimeMs = stageTimestampFromClock(marker.time || marker.meta, job, state.activeStageState.lastEventMs);
    advanceToStage(marker.stage, { eventTimeMs, source: 'event', eventId });
  });
}

function stageSnapshotTimeMs(job) {
  return parseTimestampMs(job?.stage_updated_at || job?.started_at || job?.created_at || job?.updated_at) || Date.now();
}

function shouldApplyJobStageSnapshot(key) {
  if (!state.activeStageState || !key) return false;
  const current = state.activeStageState.failed || state.activeStageState.current || '';
  if (!current || current === key) return true;
  const currentIdx = stageIndex(current);
  const snapshotIdx = stageIndex(key);
  return currentIdx < 0 || snapshotIdx < 0 || snapshotIdx >= currentIdx;
}

function applyJobStageSnapshot(job) {
  if (!state.activeStageState) initializeStageState(job);
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
  state.pendingReadTokens.delete(id);
  state.jobHistoryById.delete(id);
  state.lastJobHistoryRenderKey = '';
  if (state.activeJobId === id) {
    state.activeJobId = null;
    stopPolling();
    state.activeStageState = null;
    showEmptyResults();
    renderQaDrawer(null, []);
    syncOpsTabs();
  }
  refreshJobHistory();
  pollSystemStatus();
}

async function loadJob(jobId, autoScroll = false, options = {}) {
  if (options.readToken) state.pendingReadTokens.set(String(jobId), options.readToken);
  const publicResult = options.publicResult === true
    || state.publicResultRunIds.has(String(jobId))
    || !/^[0-9a-f]{8}$/i.test(String(jobId || ''));
  if (publicResult) state.publicResultRunIds.add(String(jobId));
  state.activePublicRunId = publicResult ? String(jobId) : '';
  const deferResultsShell = !!options.deferResultsShell;
  const seq = ++state.jobLoadSeq;
  hydratePublicResultActivity.lastSignature = '';
  hydratePublicResultActivity.inFlightSignature = '';
  state.clusterweaveGameEpoch += 1;
  syncClusterweaveGameHost({ lifecycle: 'loading', job: null });
  state.activeJobId = jobId;
  resetGenomeProgressSnapshot(jobId);
  const loadingContext = options.analysisScope
    ? { scope: options.analysisScope, taxonCounts: options.taxonCounts || {} }
    : state.jobHistoryById.get(String(jobId || ''));
  setActiveSavedAnalysisContext(loadingContext || { scope: 'fungi', taxonCounts: {} });
  renderRunStack();
  if (state.rerunScopeOpenJobId && state.rerunScopeOpenJobId !== String(jobId) && options.source !== 'job-rerun') state.rerunScopeOpenJobId = '';
  state.logCursor   = 0;
  state.logWindowStart = 0;
  state.logTotal = 0;
  state.logGeneration = '';
  state.logHydratedJobId = '';
  stopPolling();
  markActiveJobCard(jobId);
  if (state.lastSubmittedRun && state.lastSubmittedRun.jobId !== jobId) dismissSubmissionConfirmation();

  const preferResultsDashboard = shouldPreserveResultsDashboardForJobLoad(jobId, options);
  state.gsapMotion.lastJobLoadSource = String(options.source || '');
  syncOpsTabs();
  state.activeJobMeta = null;
  state.activeStageState = null;
  state.resultDashboardOpen = preferResultsDashboard;
  state.activeResultCategory = 'figures';
  state.activeResultFiles = [];
  state.activeResultPackageFileCount = 0;
  state.activeResultArtifacts = null;
  state.activeResultArtifactByKey = new Map();
  state.activeResultArtifactById = new Map();
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
  try {
    (await PROGRESS_TREE_CONSOLE).reset();
  } catch (error) {
    document.getElementById('log-terminal').replaceChildren();
  }
  setDrawerText('log-count', '0 lines');
  renderQaDrawer({ id: jobId, status: 'pending', stage: 'queued', name: jobId }, []);
  resetWeaveActivity();
  resetStages();
  if (canUseAdminSurfaces() && currentUIMode() === 'guided') setUIMode('lab', { preserveDisclosure: true });

  const job = await pollJobFinal(jobId, autoScroll, seq, JOB_INITIAL_LOAD_TIMEOUT_MS);
  if (!job || !currentJobSelection(jobId, seq)) {
    if (seq === state.jobLoadSeq) {
      state.activeJobId = null;
      state.activeJobMeta = null;
      state.activeStageState = null;
      state.pendingReadTokens.delete(String(jobId));
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
  seq = state.jobLoadSeq,
  timeoutMs = JOB_POLL_TIMEOUT_MS,
) {
  const abortController = typeof AbortController === 'function' ? new AbortController() : null;
  const timeoutId = abortController ? setTimeout(() => abortController.abort(), timeoutMs) : null;
  let resp;
  try {
    resp = await apiFetch(
      jobLifecycleBoundary.jobDetailPath(jobId, state.publicResultRunIds.has(String(jobId))),
      abortController ? { signal: abortController.signal } : {},
      { kind: 'job', jobId },
    );
  } catch (error) {
    if (currentJobSelection(jobId, seq)) {
      rememberClusterweaveGameConnectionState('reconnecting');
      window.ClusterWeaveGame?.setConnectionState?.('reconnecting');
      syncClusterweaveGameHost({ lifecycle: 'pending', job: null });
    }
    return TRANSIENT_JOB_POLL;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
  if ((resp.status === 429 || resp.status >= 500) && currentJobSelection(jobId, seq)) {
    rememberClusterweaveGameConnectionState('reconnecting');
    window.ClusterWeaveGame?.setConnectionState?.('reconnecting');
    syncClusterweaveGameHost({ lifecycle: 'pending', job: null });
    return TRANSIENT_JOB_POLL;
  }
  if (!resp.ok || !currentJobSelection(jobId, seq)) return null;
  rememberClusterweaveGameConnectionState('connected');
  window.ClusterWeaveGame?.setConnectionState?.('connected');
  const job = await resp.json();
  if (!currentJobSelection(jobId, seq)) return null;
  const previousJob = state.activeJobMeta;
  if (!Array.isArray(job.public_events) && Array.isArray(previousJob?.public_events)) {
    job.public_events = previousJob.public_events;
  }
  if (!Array.isArray(job.genome_progress) && Array.isArray(previousJob?.genome_progress)) {
    job.genome_progress = previousJob.genome_progress;
  }
  state.activeJobMeta = job;
  const publicRunId = adoptPublicRunIdentity(jobId, job);
  setActiveSavedAnalysisContext(job);
  renderRunStack();
  renderQaDrawer(job, state.activeResultFiles);
  if (!canUseAdminSurfaces()) renderPublicQaLog(job);
  setWorkflowExperienceState(job);
  rememberOpenedRun(publicRunId, readTokenForJob(publicRunId) || readTokenForJob(jobId), job);
  recordWeaveActivity(job);
  if (!state.activeStageState || state.activeStageState.jobId !== jobId) initializeStageState(job);
  applyJobStageSnapshot(job);
  const operationalStatus = String(job.status || '').trim().toLowerCase();
  if (!canUseAdminSurfaces() || operationalStatus === 'running' || operationalStatus === 'pending') {
    void hydratePublicResultActivity(jobId, seq);
  }
  if (canUseAdminSurfaces()) {
    await syncActiveAdminLogs(autoScroll);
    if (!currentJobSelection(jobId, seq)) return null;
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

function scheduleJobPoll(jobId, autoScroll = false, seq = state.jobLoadSeq, delay = JOB_POLL_BASE_DELAY_MS) {
  stopPolling();
  state.pollTimerId = setTimeout(async () => {
    state.pollTimerId = null;
    if (!currentJobSelection(jobId, seq)) return;
    let job;
    try {
      job = await pollJobFinal(jobId, autoScroll, seq);
    } catch (error) {
      job = TRANSIENT_JOB_POLL;
      rememberClusterweaveGameConnectionState('reconnecting');
      window.ClusterWeaveGame?.setConnectionState?.('reconnecting');
    }
    if (!currentJobSelection(jobId, seq) || !job) return;
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
  if (state.pollTimerId) {
    clearTimeout(state.pollTimerId);
    state.pollTimerId = null;
  }
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

async function hydratePublicResultActivity(jobId, seq = state.jobLoadSeq) {
  const runId = publicRunIdForJob(jobId);
  const signature = `${runId}:${Number(state.activeJobMeta?.log_count || 0)}:${String(state.activeJobMeta?.status || '')}:${String(state.activeJobMeta?.stage || '')}`;
  const requestSignature = `${seq}:${signature}`;
  if (!runId
      || hydratePublicResultActivity.lastSignature === signature
      || hydratePublicResultActivity.inFlightSignature === requestSignature) return;
  hydratePublicResultActivity.inFlightSignature = requestSignature;
  try {
    const resp = await apiFetch(
      jobLifecycleBoundary.publicActivityPath(runId),
      { cache: 'no-store' },
      { kind: 'job', jobId: runId },
    );
    if (!resp.ok) return;
    const payload = await resp.json();
    if (!currentJobSelection(jobId, seq) || runId !== publicRunIdForJob(jobId)) return;
    hydratePublicResultActivity.lastSignature = signature;
    const publicEvents = Array.isArray(payload.public_events) ? payload.public_events : [];
    const genomeProgress = Array.isArray(payload.genome_progress) ? payload.genome_progress : [];
    state.activeJobMeta = {
      ...(state.activeJobMeta || {}),
      public_events: publicEvents,
      genome_progress: genomeProgress,
    };
    renderPublicQaLog(state.activeJobMeta);
    renderQaDrawer(state.activeJobMeta, state.activeResultFiles);
    recordWeaveActivity(state.activeJobMeta);
    if (!state.activeStageState || state.activeStageState.jobId !== jobId) initializeStageState(state.activeJobMeta);
    applyJobStageSnapshot(state.activeJobMeta);
  } catch (error) {
  } finally {
    if (hydratePublicResultActivity.inFlightSignature === requestSignature) {
      hydratePublicResultActivity.inFlightSignature = '';
    }
  }
}

function appendLogLine(text, rawIndex = state.logCursor) {
  void PROGRESS_TREE_CONSOLE
    .then(consoleView => consoleView.append({ lines: [text], start: rawIndex }))
    .catch(() => {
      const term = document.getElementById('log-terminal');
      if (term) term.appendChild(createLogLineElement(text));
    });
}

async function presentAdminLogLines({
  lines,
  start,
  prepend = false,
  append = false,
  autoScroll = false,
} = {}) {
  const materialized = Array.isArray(lines) ? lines : [];
  try {
    const consoleView = await PROGRESS_TREE_CONSOLE;
    if (append) {
      consoleView.append({ lines: materialized, start, autoScroll });
    } else {
      consoleView.hydrate({ lines: materialized, start, prepend, autoScroll });
    }
    return;
  } catch (error) {
  }
  const term = document.getElementById('log-terminal');
  if (!term) return;
  const previousHeight = term.scrollHeight;
  const previousTop = term.scrollTop;
  const fragment = document.createDocumentFragment();
  materialized.forEach(line => fragment.appendChild(createLogLineElement(line)));
  if (prepend) term.prepend(fragment);
  else if (append) term.appendChild(fragment);
  else term.replaceChildren(fragment);
  if (prepend) term.scrollTop = previousTop + (term.scrollHeight - previousHeight);
  else if (autoScroll) scrollToBottom();
}

function updateAdminLogControls() {
  const button = document.getElementById('load-earlier-logs');
  const hydrated = canUseAdminSurfaces() && state.logHydratedJobId === state.activeJobId;
  if (button) {
    button.hidden = !hydrated || state.logWindowStart <= 0;
    button.disabled = !!state.logHydrationInFlight;
  }
  if (!hydrated) return;
  const visible = Math.max(0, state.logCursor - state.logWindowStart);
  setDrawerText('log-count', `${Number(state.logTotal).toLocaleString()} total lines`);
  setDrawerText(
    'qa-log-count-card',
    `Showing ${Number(visible).toLocaleString()} of ${Number(state.logTotal).toLocaleString()} lines`,
  );
}

async function hydrateQaLogs({ tail = true, before = null, autoScroll = false } = {}) {
  if (!canUseAdminSurfaces() || !state.activeJobId || activeOpsTab() !== 'qa') return;
  if (state.logHydrationInFlight) return state.logHydrationInFlight;
  const jobId = String(state.activeJobId);
  const seq = state.jobLoadSeq;
  const previousGeneration = state.logGeneration;
  const query = before === null
    ? `tail=${QA_LOG_PAGE_SIZE}`
    : `before=${Math.max(0, Number(before) || 0)}&limit=${QA_LOG_PAGE_SIZE}`;
  const request = (async () => {
    const resp = await apiFetch(
      jobLifecycleBoundary.adminLogsPath(jobId, query),
      {},
      { kind: 'admin' },
    );
    if (!resp.ok || !currentJobSelection(jobId, seq)) return;
    const page = await resp.json();
    if (!currentJobSelection(jobId, seq)) return;
    const generation = String(page.generation || '');
    const prepend = before !== null && previousGeneration && generation === previousGeneration;
    if (!prepend) (page.lines || []).forEach(line => updateStageBar(line));
    await presentAdminLogLines({
      lines: page.lines || [],
      start: Math.max(0, Number(page.start) || 0),
      prepend,
      autoScroll,
    });
    state.logWindowStart = Math.max(0, Number(page.start) || 0);
    const pageEnd = Math.max(0, Number(page.end) || 0);
    state.logCursor = prepend ? Math.max(state.logCursor, pageEnd) : pageEnd;
    state.logTotal = Math.max(state.logCursor, Number(page.total) || 0);
    state.logGeneration = generation;
    state.logHydratedJobId = jobId;
    renderQaDrawer(state.activeJobMeta, state.activeResultFiles);
    updateAdminLogControls();
  })();
  state.logHydrationInFlight = request;
  updateAdminLogControls();
  try {
    await request;
  } finally {
    if (state.logHydrationInFlight === request) state.logHydrationInFlight = null;
    updateAdminLogControls();
  }
}

async function loadEarlierLogs() {
  if (state.logWindowStart <= 0) return;
  await hydrateQaLogs({ tail: false, before: state.logWindowStart, autoScroll: false });
}

async function syncActiveAdminLogs(autoScroll = false) {
  if (!canUseAdminSurfaces() || activeOpsTab() !== 'qa' || !state.activeJobId) return;
  if (state.logHydratedJobId !== state.activeJobId) {
    await hydrateQaLogs({ tail: true, autoScroll: true });
    return;
  }
  const jobId = String(state.activeJobId);
  const resp = await apiFetch(
    jobLifecycleBoundary.adminLogsPath(jobId, `since=${encodeURIComponent(state.logCursor)}`),
    {},
    { kind: 'admin' },
  );
  if (!resp.ok || jobId !== state.activeJobId) return;
  const page = await resp.json();
  if (state.logGeneration && page.generation && page.generation !== state.logGeneration) {
    state.logHydratedJobId = '';
    state.logGeneration = '';
    await hydrateQaLogs({ tail: true, autoScroll: true });
    return;
  }
  const appendStart = state.logCursor;
  for (const line of (page.lines || [])) {
    updateStageBar(line);
  }
  await presentAdminLogLines({
    lines: page.lines || [],
    start: appendStart,
    append: true,
    autoScroll,
  });
  state.logCursor = Math.max(0, Number(page.total) || state.logCursor);
  state.logTotal = state.logCursor;
  if (page.generation) state.logGeneration = page.generation;
  renderQaDrawer(state.activeJobMeta, state.activeResultFiles);
  updateAdminLogControls();
}

function clearLog() {
  void PROGRESS_TREE_CONSOLE
    .then(consoleView => consoleView.reset())
    .catch(() => {
      document.getElementById('log-terminal')?.replaceChildren();
    });
  state.logCursor = 0;
  state.logWindowStart = 0;
  state.logTotal = 0;
  state.logGeneration = '';
  state.logHydratedJobId = '';
  setDrawerText('log-count', '0 lines');
  updateAdminLogControls();
  renderQaDrawer(state.activeJobMeta, state.activeResultFiles);
}

function setQaLogView(value) {
  void PROGRESS_TREE_CONSOLE
    .then(consoleView => consoleView.setMode(value))
    .catch(() => {});
}

function handleQaLogViewKeydown(event) {
  void PROGRESS_TREE_CONSOLE
    .then(consoleView => consoleView.handleModeKeydown(event))
    .catch(() => {});
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

function resultOrEventIndicatesStage(job, key, files = state.activeResultFiles) {
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

function inferredSuccessfulStageSet(job, files = state.activeResultFiles) {
  const enabled = new Set(['prep']);
  STAGES.forEach((stage) => {
    if (stage.key !== 'prep' && resultOrEventIndicatesStage(job, stage.key, files)) enabled.add(stage.key);
  });
  if (enabled.has('summary')) enabled.add('bigscape');
  if (enabled.has('figures')) enabled.add('summary');
  return enabled;
}

function syncInferredStageState(job = state.activeJobMeta) {
  if (!state.activeStageState || !job || state.activeStageState.jobId !== job.id) return;
  if (jobHasExplicitStageSettings(job)) return;
  if (String(job.status || '').toLowerCase() !== 'success') return;
  const next = inferredSuccessfulStageSet(job, state.activeResultFiles);
  const same = next.size === state.activeStageState.enabled.size && Array.from(next).every(key => state.activeStageState.enabled.has(key));
  if (same) return;
  state.activeStageState.enabled = next;
  state.activeStageState.completed = new Set(Array.from(state.activeStageState.completed).filter(key => next.has(key)));
  next.forEach(key => state.activeStageState.completed.add(key));
  state.activeStageState.current = null;
  state.activeStageState.failed = null;
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

function initializeStageState(job) {
  const enabled = new Set(STAGES.filter(s => jobStageEnabled(job, s.key)).map(s => s.key));
  state.activeStageState = {
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
  initializeStageState(job || state.activeJobMeta || {});
}

function stageIndex(key) {
  return STAGES.findIndex(s => s.key === key);
}

function resetWeaveActivity(job = null) {
  state.weaveActivity = {
    jobId: job && job.id ? job.id : null,
    lastLogCount: job ? Number(job.log_count || 0) : null,
    lastStatus: job ? String(job.status || '') : null,
    events: [],
  };
  const helix = document.getElementById('weavemap-helix');
  if (helix) delete helix.dataset.rendered;
}

function workflowStageList(job = state.activeJobMeta) {
  return STAGES.filter(stage => {
    if (stage.key === 'nplinker' && !canUseAdminSurfaces() && !jobStageEnabled(job || {}, stage.key)) return false;
    return true;
  });
}

function finalEnabledStageKey(job = state.activeJobMeta) {
  const stages = workflowStageList(job).filter(stage => state.activeStageState
    ? state.activeStageState.enabled.has(stage.key)
    : jobStageEnabled(job || {}, stage.key));
  return stages.length ? stages[stages.length - 1].key : null;
}

function stageVisualState(key) {
  if (!state.activeStageState || !state.activeStageState.enabled.has(key)) return { cls: 'disabled', label: 'Skipped' };
  if (state.activeStageState.failed === key) return { cls: 'failed', label: 'Failed' };
  if (state.activeStageState.completed.has(key)) {
    const status = String((state.activeJobMeta && state.activeJobMeta.status) || '').toLowerCase();
    return status === 'success' && finalEnabledStageKey(state.activeJobMeta) === key
      ? { cls: 'complete', label: 'Complete' }
      : { cls: 'done', label: 'Past' };
  }
  if (state.activeStageState.current === key) return { cls: 'active', label: 'Current' };
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

function stageClockSeconds(value) {
  const match = String(value || '').match(/^(\d{2}):(\d{2}):(\d{2})$/);
  if (!match) return null;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  const seconds = Number(match[3]);
  if (hours > 23 || minutes > 59 || seconds > 59) return null;
  return (hours * 3600) + (minutes * 60) + seconds;
}

function stageTimingBaseMs(job = state.activeJobMeta) {
  return parseTimestampMs(job?.started_at || job?.created_at || job?.updated_at);
}

function stageTimestampFromClock(value, job = state.activeJobMeta, minMs = null) {
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

function stageTimestampFromLogLine(line, job = state.activeJobMeta) {
  const match = String(line || '').match(/^\[(\d{2}:\d{2}:\d{2})\]/);
  return match ? stageTimestampFromClock(match[1], job, state.activeStageState?.lastEventMs) : null;
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
  if (!state.activeStageState || !Number.isFinite(ms)) return false;
  const current = state.activeStageState.startedAt[key];
  const currentSource = state.activeStageState.startedAtSource[key] || '';
  const force = !!options.force;
  const sourceRank = stageTimingSourceRank(source);
  const currentRank = stageTimingSourceRank(currentSource);
  const betterSource = sourceRank > currentRank;
  const sameSourceEarlier = sourceRank === currentRank && ms < current;
  if (force || !Number.isFinite(current) || betterSource || sameSourceEarlier) {
    state.activeStageState.startedAt[key] = ms;
    state.activeStageState.startedAtSource[key] = source;
    return true;
  }
  return false;
}

function setStageEndTime(key, ms, source = 'snapshot', options = {}) {
  if (!state.activeStageState || !Number.isFinite(ms)) return false;
  const start = state.activeStageState.startedAt[key];
  const normalized = Number.isFinite(start) ? Math.max(ms, start) : ms;
  const current = state.activeStageState.endedAt[key];
  const currentSource = state.activeStageState.endedAtSource[key] || '';
  const force = !!options.force;
  const betterSource = stageTimingSourceRank(source) > stageTimingSourceRank(currentSource);
  if (force || !Number.isFinite(current) || (betterSource && normalized !== current)) {
    state.activeStageState.endedAt[key] = normalized;
    state.activeStageState.endedAtSource[key] = source;
    return true;
  }
  return false;
}

function clearStageTimingFrom(key) {
  if (!state.activeStageState) return;
  const startIdx = stageIndex(key);
  if (startIdx < 0) return;
  for (let i = startIdx; i < STAGES.length; i++) {
    const stageKey = STAGES[i].key;
    state.activeStageState.completed.delete(stageKey);
    delete state.activeStageState.startedAt[stageKey];
    delete state.activeStageState.endedAt[stageKey];
    delete state.activeStageState.startedAtSource[stageKey];
    delete state.activeStageState.endedAtSource[stageKey];
  }
}

function stageTransitionTimeMs(options = {}) {
  if (Number.isFinite(options.eventTimeMs)) return options.eventTimeMs;
  if (Number.isFinite(options.timeMs)) return options.timeMs;
  if (options.line) {
    const lineMs = stageTimestampFromLogLine(options.line, state.activeJobMeta);
    if (Number.isFinite(lineMs)) return lineMs;
  }
  return Date.now();
}

function jobElapsedText(job = state.activeJobMeta) {
  if (!job) return 'Not started';
  const start = parseTimestampMs(job.started_at || job.created_at);
  if (!start) return 'Not started';
  const status = String(job.status || '').toLowerCase();
  const end = (status === 'running' || status === 'pending')
    ? Date.now()
    : (parseTimestampMs(job.completed_at || job.finished_at || job.failed_at || job.updated_at) || Date.now());
  return formatDuration(end - start);
}

function renderJobRuntime(job = state.activeJobMeta) {
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
  if (!state.activeStageState || !state.activeStageState.enabled.has(key)) return 'Skipped';
  const start = state.activeStageState.startedAt && state.activeStageState.startedAt[key];
  const end = state.activeStageState.endedAt && state.activeStageState.endedAt[key];
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
  if (!state.activeStageState) return null;
  if (state.activeStageState.failed) return state.activeStageState.failed;
  if (state.activeStageState.current) return state.activeStageState.current;
  if (state.activeJobMeta && String(state.activeJobMeta.status || '').toLowerCase() === 'success') return finalEnabledStageKey(state.activeJobMeta) || 'figures';
  return null;
}

function setWorkflowExperienceState(job = state.activeJobMeta) {
  renderJobRuntime(job);
  const status = String((job && job.status) || '').toLowerCase();
  let state = 'idle';
  if (status === 'success') state = 'complete';
  else if (status === 'failed') state = 'failed';
  else if (status === 'running') state = 'running';
  else if (status === 'pending' || state.activeJobId) state = 'launched';
  document.body.dataset.workflowState = state;
  document.body.dataset.jobState = state === 'launched' ? 'running' : state;
  syncClusterweaveGameHost({ lifecycle: status === 'pending' ? 'pending' : state, job });
}

function bgcWorkflowStages(job = state.activeJobMeta) {
  return workflowStageList(job).filter(stage => stage.key !== 'nplinker' || jobStageEnabled(job || {}, stage.key) || canUseAdminSurfaces());
}

function bgcStageStatus(stage, currentKey, jobStatus) {
  const key = stage.key;
  if (state.activeStageState && !state.activeStageState.enabled.has(key)) return 'skipped';
  if (jobStatus === 'success') return 'complete';
  if (state.activeStageState?.failed === key || (jobStatus === 'failed' && currentKey === key)) return 'error';
  if (state.activeStageState?.completed.has(key)) return 'complete';
  if (currentKey === key) return 'running';
  return 'pending';
}

function jobPublicWorkflowEvents(job, currentKey) {
  const jobEvents = Array.isArray(job?.public_events)
    ? job.public_events.map(normalizePublicWeaveEvent).filter(Boolean)
    : [];
  const events = jobEvents.length ? jobEvents : (Array.isArray(state.weaveActivity.events) ? state.weaveActivity.events : []);
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
  return !!(state.activeStageState && workflowStageList(state.activeJobMeta).some(stage => !state.activeStageState.enabled.has(stage.key)));
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
    if (state.activeStageState?.completed.has(stage.key) || (currentIndex >= 0 && index < currentIndex)) {
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

function bgcWorkflowPayload(job = state.activeJobMeta) {
  syncInferredStageState(job);
  const stages = bgcWorkflowStages(job);
  const status = String((job && job.status) || '').toLowerCase();
  const rawCurrentKey = currentWorkflowStage() || jobCurrentStageKey(job);
  const currentKey = status === 'success' ? '' : rawCurrentKey;
  let state = 'idle';
  if (status === 'success') state = 'complete';
  else if (status === 'failed') state = 'failed';
  else if (status === 'running' || status === 'pending' || state.activeJobId) state = 'running';
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
  state.bgcWorkflowPendingPayload = payload;
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
  if (state.bgcWorkflowDna) state.bgcWorkflowDna.setProgress(payload.progress, payload);
  else bootBgcWorkflowDna();
}

function updateBgcWorkflowDnaFromJob(job = state.activeJobMeta) {
  applyBgcWorkflowPayload(bgcWorkflowPayload(job));
}

function bootBgcWorkflowDna() {
  if (state.bgcWorkflowDna || state.bgcWorkflowDnaLoading) return;
  const canvas = document.getElementById('bgc-dna-canvas');
  const region = document.getElementById('bgc-dna-progress-region');
  const fallback = document.getElementById('bgc-dna-fallback');
  if (!canvas || !region) return;
  state.bgcWorkflowDnaLoading = true;
  import(WORKFLOW_DNA_MODULE_PATH).then(({ createWorkflowDnaProgress }) => {
    state.bgcWorkflowDna = createWorkflowDnaProgress({
      canvas,
      region,
      autoSpiral: true,
      ariaLabel: 'BGC workflow DNA progress',
    });
    region.classList.add('is-ready');
    if (fallback) fallback.textContent = '';
    syncBgcWorkflowDnaSuspension();
    if (state.bgcWorkflowPendingPayload) {
      state.bgcWorkflowDna.setProgress(state.bgcWorkflowPendingPayload.progress, state.bgcWorkflowPendingPayload);
    }
  }).catch((error) => {
    if (fallback) fallback.textContent = `3D DNA unavailable: ${error.message}`;
  }).finally(() => {
    state.bgcWorkflowDnaLoading = false;
  });
}

function updateStageTelemetry() {
  renderJobRuntime(state.activeJobMeta);
  if (!state.activeStageState) return;
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
  const queued = String((state.activeJobMeta && state.activeJobMeta.status) || '').toLowerCase() === 'pending';
  const stageEl = document.getElementById('workflow-current-stage');
  const elapsedEl = document.getElementById('workflow-current-elapsed');
  const estimateEl = document.getElementById('workflow-current-estimate');
  if (stageEl) stageEl.textContent = currentStage ? (STAGE_DETAILS[currentStage.key]?.name || currentStage.label) : (queued ? queueStatusLabel(state.activeJobMeta) : 'Waiting for run');
  if (elapsedEl) elapsedEl.textContent = currentKey && visual ? stageElapsedText(currentKey, visual.cls) : 'Not started';
  if (estimateEl) estimateEl.textContent = currentKey ? stageEstimateText(currentKey) : (queued ? queueStatusDetail(state.activeJobMeta) : 'Run dependent');
  refreshDnaTimingNodes();
}

function refreshDnaTimingNodes() {
  if (!state.activeStageState) return;
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
  if (state.stageTickerId) return;
  state.stageTickerId = setInterval(updateStageTelemetry, 1000);
}

function mergeWeaveActivityEvents(events) {
  const incoming = Array.isArray(events)
    ? events.map(normalizePublicWeaveEvent).filter(Boolean)
    : [];
  if (!incoming.length) return 0;
  const keyed = new Map();
  [...state.weaveActivity.events, ...incoming].forEach(event => {
    keyed.set(`${event.stage}|${event.title}|${event.meta}`, event);
  });
  state.weaveActivity.events = Array.from(keyed.values()).slice(-24);
  return incoming.length;
}

function recordWeaveActivity(job) {
  if (!job || !job.id) return;
  const currentCount = Number(job.log_count || 0);
  const status = String(job.status || '');
  if (state.weaveActivity.jobId !== job.id) {
    resetWeaveActivity(job);
    mergeWeaveActivityEvents(job.public_events);
    return;
  }
  mergeWeaveActivityEvents(job.public_events);
  state.weaveActivity.lastLogCount = currentCount;
  state.weaveActivity.lastStatus = status;
  if (state.weaveActivity.events.length > 18) state.weaveActivity.events = state.weaveActivity.events.slice(-18);
}

function latestWeaveEventByStage() {
  const latest = new Map();
  (state.weaveActivity.events || []).forEach(event => {
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

function legacyStageOverviewNodes(job = state.activeJobMeta) {
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
  if (!state.activeStageState || !state.activeStageState.enabled.has(key)) return;
  const eventId = options.eventId || '';
  if (eventId && state.activeStageState.appliedEvents.has(eventId)) return;
  const source = options.source || (options.line ? 'log' : 'snapshot');
  const eventMs = stageTransitionTimeMs(options);
  if (eventId) state.activeStageState.appliedEvents.add(eventId);
  if (Number.isFinite(eventMs)) state.activeStageState.lastEventMs = Math.max(state.activeStageState.lastEventMs || eventMs, eventMs);
  const nextIdx = stageIndex(key);
  const currentIdx = stageIndex(state.activeStageState.current);
  const isRestart = Boolean(
    state.activeStageState.failed === key ||
    state.activeStageState.completed.has(key) ||
    (state.activeStageState.current === key && Number.isFinite(state.activeStageState.endedAt[key])) ||
    (state.activeStageState.current && state.activeStageState.current !== key && currentIdx >= nextIdx)
  );
  if (isRestart) clearStageTimingFrom(key);
  if (state.activeStageState.current && state.activeStageState.current !== key) {
    if (currentIdx >= 0 && currentIdx < nextIdx) state.activeStageState.completed.add(state.activeStageState.current);
    setStageEndTime(state.activeStageState.current, eventMs, source);
  }
  for (let i = 0; i < nextIdx; i++) {
    const prior = STAGES[i].key;
    if (!state.activeStageState.enabled.has(prior)) continue;
    state.activeStageState.completed.add(prior);
    if (Number.isFinite(state.activeStageState.startedAt[prior])) setStageEndTime(prior, eventMs, source);
  }
  setStageStartTime(key, eventMs, source, { force: isRestart });
  if (isRestart) delete state.activeStageState.endedAt[key];
  if (isRestart) delete state.activeStageState.endedAtSource[key];
  state.activeStageState.current = key;
  state.activeStageState.failed = null;
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
  if (!state.activeJobMeta || !state.weaveActivity || !state.weaveActivity.jobId) return;
  const title = sanitizeWeaveLogTitle(line);
  if (!title || /^New version of client/i.test(title)) return;
  if (!/antiSMASH|genome|Stage|flags|process|staged|complete|queued|running|prepared|input/i.test(title)) return;
  const stage = stageKey || state.activeStageState?.current || jobCurrentStageKey(state.activeJobMeta) || 'prep';
  const timeMatch = String(line || '').match(/^\[(\d{2}:\d{2}:\d{2})\]/);
  const meta = timeMatch ? timeMatch[1] : formatWorkflowTime(state.activeJobMeta.updated_at || state.activeJobMeta.created_at);
  const key = `${stage}|${title}|${meta}`;
  if (state.weaveActivity.events.some(event => `${event.stage}|${event.title}|${event.meta}` === key)) return;
  state.weaveActivity.events.push({ stage, title, meta });
  if (state.weaveActivity.events.length > 18) state.weaveActivity.events = state.weaveActivity.events.slice(-18);
}

function updateStageBar(line) {
  const key = stageFromLine(line);
  const eventTimeMs = stageTimestampFromLogLine(line, state.activeJobMeta);
  if (key) {
    const eventId = `log:${state.activeJobId || ''}:${state.logCursor}:${key}`;
    advanceToStage(key, { eventTimeMs, source: 'log', eventId });
  }
  recordWeaveLogActivity(line, key);
  if (/FATAL:|ERROR:|failed with exit code/i.test(line) && state.activeStageState && state.activeStageState.current) {
    state.activeStageState.failed = state.activeStageState.current;
    setStageEndTime(state.activeStageState.current, eventTimeMs || Date.now(), 'log');
    renderStageState();
  }
}

function terminalStageTimeMs(status) {
  const normalized = String(status || '').toLowerCase();
  const finishedAt = normalized === 'success'
    ? state.activeJobMeta?.completed_at || state.activeJobMeta?.finished_at || state.activeJobMeta?.updated_at
    : state.activeJobMeta?.failed_at || state.activeJobMeta?.finished_at || state.activeJobMeta?.updated_at;
  return parseTimestampMs(finishedAt || state.activeJobMeta?.updated_at || state.activeJobMeta?.created_at) || Date.now();
}

function finalizeStageState(status) {
  if (!state.activeStageState) return;
  const normalized = String(status || '').toLowerCase();
  const terminalMs = terminalStageTimeMs(normalized);
  if (normalized === 'success') {
    if (state.activeStageState.current) setStageEndTime(state.activeStageState.current, terminalMs, 'terminal');
    for (const key of state.activeStageState.enabled) state.activeStageState.completed.add(key);
    state.activeStageState.current = null;
    state.activeStageState.failed = null;
  } else if (normalized === 'failed') {
    const failedKey = state.activeStageState.current || jobCurrentStageKey(state.activeJobMeta);
    if (failedKey) {
      state.activeStageState.failed = failedKey;
      state.activeStageState.current = failedKey;
      setStageEndTime(failedKey, terminalMs, 'terminal');
    }
  }
  renderStageState();
}

function renderStageState() {
  if (!state.activeStageState) return;
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
  renderWeaveHelix(state.activeJobMeta);
  updateStageTelemetry();
  updateBgcWorkflowDnaFromJob(state.activeJobMeta);
}

function updateProgressBadge(status) {
  setStatusBadge(document.getElementById('progress-badge'), status, state.activeJobMeta);
  finalizeStageState(status);
  renderQaDrawer(state.activeJobMeta, state.activeResultFiles);
}

function queueStatusForJob(job = state.activeJobMeta) {
  const queue = job && job.queue_status;
  return queue && typeof queue === 'object' ? queue : null;
}

function queueStatusLabel(job = state.activeJobMeta) {
  const queue = queueStatusForJob(job);
  if (!queue) return 'Queued';
  if (queue.state === 'running') return 'Running';
  if (queue.state === 'claiming') return 'Claiming worker slot';
  const position = Number(queue.position || 0);
  return position > 0 ? `Queued #${position}` : 'Queued';
}

function queueStatusDetail(job = state.activeJobMeta) {
  const queue = queueStatusForJob(job);
  if (!queue) return 'Waiting for a worker slot.';
  return String(queue.detail || 'Waiting for a worker slot.');
}

function statusBadgeModel(status, job = state.activeJobMeta) {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'success') return ['badge-success', 'Complete'];
  if (normalized === 'failed') return ['badge-failed', 'Failed'];
  if (normalized === 'running') return ['badge-running', 'Running'];
  if (normalized === 'pending') return ['badge-pending', queueStatusLabel(job)];
  return ['badge-pending', status || 'Pending'];
}

function setStatusBadge(el, status, job = state.activeJobMeta) {
  if (!el) return;
  const [cls, label] = statusBadgeModel(status, job);
  el.className = 'badge ' + cls;
  el.innerHTML = `<span class="badge-dot"></span> ${escapeHtml(label)}`;
}

function pendingQueueNote(job = state.activeJobMeta) {
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

  return Object.freeze({
    shortRunId,
    runStackProjectName,
    runStackStatus,
    setRunStackOpen,
    toggleRunStack,
    renderRunStack,
    loadRunStackJob,
    addRunFromStack,
    wireRunStackDismissal,
    refreshJobHistory,
    jobHistoryRenderKey,
    jobStageSignature,
    jobProjectName,
    jobStageDisplay,
    jobCurrentStageKey,
    jobStagePipState,
    renderJobStagePips,
    statusLabel,
    jobCanRerun,
    rerunStageKeysForJob,
    diagnosticJobDisplayState,
    diagnosticRouteCardLabel,
    renderJobHistory,
    statusBadge,
    handleJobCardKeydown,
    openJobLogs,
    markActiveJobCard,
    publicStageTimingEvent,
    applyStageTimingFromPublicEvents,
    stageSnapshotTimeMs,
    shouldApplyJobStageSnapshot,
    applyJobStageSnapshot,
    deleteJob,
    loadJob,
    pollJobFinal,
    scheduleJobPoll,
    stopPolling,
    renderPublicQaLog,
    hydratePublicResultActivity,
    appendLogLine,
    updateAdminLogControls,
    hydrateQaLogs,
    loadEarlierLogs,
    syncActiveAdminLogs,
    clearLog,
    setQaLogView,
    handleQaLogViewKeydown,
    scrollToBottom,
    jobHasExplicitStageSettings,
    jobStageSettings,
    resultOrEventIndicatesStage,
    inferredSuccessfulStageSet,
    syncInferredStageState,
    jobStageEnabled,
    initializeStageState,
    resetStages,
    stageIndex,
    resetWeaveActivity,
    workflowStageList,
    finalEnabledStageKey,
    stageVisualState,
    formatWorkflowTime,
    formatDuration,
    stageClockSeconds,
    stageTimingBaseMs,
    stageTimestampFromClock,
    stageTimestampFromLogLine,
    stageTimingSourceRank,
    setStageStartTime,
    setStageEndTime,
    clearStageTimingFrom,
    stageTransitionTimeMs,
    jobElapsedText,
    renderJobRuntime,
    stageRuntimeHint,
    stageEstimateText,
    compactRuntimeHint,
    dnaStageMetaText,
    stageElapsedText,
    currentWorkflowStage,
    setWorkflowExperienceState,
    bgcWorkflowStages,
    bgcStageStatus,
    jobPublicWorkflowEvents,
    latestJobPublicWorkflowEvent,
    activityOrganismFromMeta,
    activityElapsedFromMeta,
    activityPartsFromEvent,
    activityPartsMatch,
    latestToolActivityParts,
    workflowPayloadHasSkippedStages,
    bgcActivityChipPayload,
    clampUnit,
    renderGenomeProgressLayer,
    workflowStageWeight,
    parseWorkflowGenomePosition,
    workflowGenomePhaseFromTitle,
    annotationGenomeProgress,
    workflowCurrentStageFraction,
    weightedWorkflowProgress,
    bgcWorkflowPayload,
    alt06StepStatus,
    alt06WorkflowCaption,
    renderBgcWorkflowStageStrip,
    applyBgcWorkflowPayload,
    updateBgcWorkflowDnaFromJob,
    bootBgcWorkflowDna,
    updateStageTelemetry,
    refreshDnaTimingNodes,
    startStageTicker,
    mergeWeaveActivityEvents,
    recordWeaveActivity,
    latestWeaveEventByStage,
    stageTimelineLabel,
    stageTimelineDetailKey,
    eventSummaryText,
    stageTimelineMeta,
    legacyStageOverviewNodes,
    publicStageNodes,
    stageFromLine,
    advanceToStage,
    sanitizeWeaveLogTitle,
    recordWeaveLogActivity,
    updateStageBar,
    terminalStageTimeMs,
    finalizeStageState,
    renderStageState,
    updateProgressBadge,
    queueStatusForJob,
    queueStatusLabel,
    queueStatusDetail,
    statusBadgeModel,
    setStatusBadge,
    pendingQueueNote,
    renderCompletionCallout,
  });
}

globalThis.__clusterweaveInstallJobLifecycleBoundary?.(
  createJobLifecycleBoundary,
  createJobLifecycleControllerBoundary,
);
