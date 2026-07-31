const TERMINAL_STATES = new Set(['complete', 'failed', 'warning_terminal', 'skipped']);
const STATE_ALIASES = new Map(Object.entries({
  complete: 'complete',
  completed: 'complete',
  done: 'complete',
  ok: 'complete',
  success: 'complete',
  succeeded: 'complete',
  failed: 'failed',
  failure: 'failed',
  error: 'failed',
  fatal: 'failed',
  skipped: 'skipped',
  skip: 'skipped',
  not_applicable: 'skipped',
  'not-applicable': 'skipped',
  'not applicable': 'skipped',
  warning_terminal: 'warning_terminal',
  complete_with_warning: 'warning_terminal',
  warning: 'warning',
  warn: 'warning',
  rerun: 'rerun',
  retry: 'rerun',
  queued: 'running',
  ready: 'running',
  running: 'running',
  active: 'running',
  processing: 'running',
}));

export function normalizeProgressTreeLine(value) {
  let text = String(value || '').trim();
  while (true) {
    const updated = text
      .replace(/^\[\d{2}:\d{2}:\d{2}\]\s*/, '')
      .replace(/^\[\d{4}-\d{2}-\d{2}[^\]]*\]\s*/, '')
      .replace(/^\[(?:INFO|WARN|WARNING|ERROR|FAIL|FATAL|OK)\]\s*/i, '')
      .trim();
    if (updated === text) return text;
    text = updated;
  }
}

function normalizeTool(value) {
  const raw = String(value || '').trim();
  const key = raw.toLowerCase().replaceAll('_', '').replaceAll('-', '');
  return {
    antismash: 'antiSMASH',
    funbgcex: 'FunBGCeX',
    funannotate: 'funannotate',
    prodigal: 'Prodigal',
    ncbidatasets: 'NCBI Datasets',
  }[key] || raw;
}

function normalizeState(value, fallback = 'running') {
  return STATE_ALIASES.get(String(value || '').trim().toLowerCase()) || fallback;
}

function matchedValues(rule, match) {
  return Object.fromEntries((rule.fields || []).map((field, index) => [field, match[index + 1] || '']));
}

function stateFromPatterns(contract, message, allowComplete) {
  for (const rule of (contract.state_patterns || [])) {
    if (rule.state === 'complete' && !allowComplete) continue;
    if (new RegExp(rule.pattern, 'i').test(message)) {
      return { state: rule.state, permanent: !!rule.permanent };
    }
  }
  return null;
}

export function classifyProgressTreeLine(
  contract,
  line,
  canonicalRawLineIndex,
  currentStage = 'prep',
) {
  const raw = String(line || '').replace(/[\r\n]+$/g, '');
  const message = normalizeProgressTreeLine(raw);
  const base = {
    workflow_stage: currentStage || 'prep',
    genome: '',
    tool: '',
    percentage: null,
    state: 'running',
    display_message: message || 'Running',
    elapsed_activity: null,
    canonical_raw_line_index: Math.max(0, Number(canonicalRawLineIndex) || 0),
    node_level: 'activity',
    kind: 'unknown',
    heartbeat: false,
    permanent: false,
    stage_transition: false,
  };

  for (const rule of (contract.records || [])) {
    const match = message.match(new RegExp(rule.pattern, 'i'));
    if (!match) continue;
    const values = matchedValues(rule, match);
    const event = {
      ...base,
      kind: String(rule.kind || 'structured'),
      workflow_stage: String(rule.workflow_stage || currentStage || 'prep'),
      node_level: String(rule.node_level || 'activity'),
      genome: values.genome || '',
      tool: normalizeTool(rule.tool || values.tool || ''),
      display_message: String(values.display_message || rule.message || message || 'Running'),
      heartbeat: !!rule.heartbeat,
      permanent: !!rule.permanent,
    };
    if (rule.tool_from_field) {
      const rawTool = values[rule.tool_from_field] || '';
      const mapped = (rule.tool_map || {})[rawTool.toLowerCase()] ?? rawTool;
      event.tool = normalizeTool(mapped);
      if (event.tool) event.node_level = 'tool';
    }
    if (/^\d+$/.test(values.percentage || '')) {
      event.percentage = Math.max(0, Math.min(100, Number(values.percentage)));
    }
    if (/^\d+$/.test(values.elapsed_activity || '')) {
      event.elapsed_activity = Math.max(0, Number(values.elapsed_activity));
    }
    event.state = normalizeState(
      rule.state_field ? values[rule.state_field] : rule.state,
      'running',
    );
    const patternState = stateFromPatterns(
      contract,
      `${raw} ${event.display_message}`,
      !!rule.terminal_on_percent,
    );
    if (patternState && patternState.state !== 'complete') {
      event.state = patternState.state;
      event.permanent ||= patternState.permanent;
    }
    if (rule.terminal_on_percent && event.percentage === 100 && event.state === 'running') {
      event.state = 'complete';
      event.permanent = true;
    }
    if (TERMINAL_STATES.has(event.state)) event.permanent = true;
    return event;
  }

  for (const rule of (contract.stage_markers || [])) {
    const match = message.match(new RegExp(rule.pattern, 'i'));
    if (!match) continue;
    const action = String(match[1] || '').toLowerCase();
    const state = String(rule.state || (action === 'skipped' ? 'skipped' : 'running'));
    const displayMessage = {
      complete: 'Complete',
      failed: 'Failed',
      skipped: 'Skipped',
      warning_terminal: 'Complete with warning',
    }[state] || 'Running';
    return {
      ...base,
      kind: 'stage_transition',
      workflow_stage: String(rule.workflow_stage || currentStage || 'prep'),
      node_level: 'stage',
      state,
      display_message: displayMessage,
      permanent: true,
      stage_transition: true,
    };
  }

  for (const rule of (contract.legacy_records || [])) {
    const match = message.match(new RegExp(rule.pattern, 'i'));
    if (!match) continue;
    const values = matchedValues(rule, match);
    return {
      ...base,
      kind: String(rule.kind || 'legacy'),
      workflow_stage: String(rule.workflow_stage || currentStage || 'prep'),
      node_level: String(rule.node_level || 'activity'),
      genome: values.genome || '',
      tool: normalizeTool(rule.tool || values.tool || ''),
      state: normalizeState(rule.state, 'running'),
      display_message: String(rule.message || message || 'Running'),
      permanent: !!rule.permanent,
    };
  }

  const patternState = stateFromPatterns(contract, raw, true);
  if (patternState) {
    base.state = patternState.state;
    base.permanent = patternState.permanent;
  }
  return base;
}

function eventNodeKey(event) {
  const stage = String(event.workflow_stage || 'prep');
  if (event.node_level === 'stage') return `stage:${stage}`;
  if (event.node_level === 'tool') {
    return `tool:${stage}:${event.genome || ''}:${event.tool || ''}`;
  }
  if (event.node_level === 'genome') return `genome:${stage}:${event.genome || ''}`;
  return `activity:${stage}`;
}

function elapsedText(seconds) {
  if (seconds === null || seconds === undefined) return '';
  if (seconds < 60) return `${seconds}s active`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s active`;
  return `${Math.floor(seconds / 3600)}h ${String(Math.floor((seconds % 3600) / 60)).padStart(2, '0')}m active`;
}

export function progressTreeStatus(node) {
  const labelByState = {
    complete: 'Complete',
    failed: 'Failed',
    warning_terminal: 'Complete with warning',
    skipped: 'Skipped',
    warning: 'Warning',
    waiting: 'Waiting',
    running: node.message || 'Running',
  };
  let label = labelByState[node.state] || node.message || 'Running';
  const elapsed = elapsedText(node.elapsed);
  if (elapsed && !label.toLowerCase().includes(elapsed.toLowerCase())) {
    label = `${label} · ${elapsed}`;
  }
  if (node.state === 'complete') return '[##########] 100% - Complete';
  if (node.state === 'skipped') return '[----------]   -- - Skipped';
  if (node.percentage !== null && node.percentage !== undefined) {
    const percent = Math.max(0, Math.min(100, Math.round(Number(node.percentage) || 0)));
    const filled = Math.floor(percent * 10 / 100);
    return `[${'#'.repeat(filled)}${'-'.repeat(10 - filled)}] ${String(percent).padStart(3, ' ')}% - ${label}`;
  }
  if (node.state === 'waiting') return '[----------]   0% - Waiting';
  return `[          ]  --% - ${label}`;
}

export function buildProgressTree(contract, records) {
  const workflow = Array.isArray(contract.workflow) ? contract.workflow : [];
  const workflowByKey = new Map(workflow.map(item => [item.key, item]));
  const nodes = new Map();
  const permanentEvents = [];
  const observedOptionalStages = new Set();
  let currentStage = 'prep';
  let nextOrder = 0;

  function workflowItem(stage) {
    return workflowByKey.get(stage) || {
      key: stage,
      label: String(stage || '').replaceAll('_', ' ').replace(/\b\w/g, value => value.toUpperCase()),
      optional: true,
    };
  }

  function ensureStage(stage) {
    const key = `stage:${stage}`;
    if (!nodes.has(key)) {
      nodes.set(key, {
        key,
        stage,
        level: 'stage',
        label: workflowItem(stage).label || stage,
        state: 'waiting',
        percentage: null,
        message: 'Waiting',
        elapsed: null,
        rawIndex: -1,
        order: nextOrder++,
        parentKey: '',
      });
    }
    if (workflowItem(stage).optional) observedOptionalStages.add(stage);
    return nodes.get(key);
  }

  workflow.filter(item => !item.optional).forEach(item => ensureStage(item.key));

  function labelForEvent(event) {
    if (event.node_level === 'stage') return workflowItem(event.workflow_stage).label;
    if (event.node_level === 'tool') return event.tool || 'Tool';
    if (event.node_level === 'genome') return String(event.genome || 'Genome').replaceAll('_', ' ');
    return 'Activity';
  }

  function parentForEvent(event) {
    const stage = event.workflow_stage || 'prep';
    if (event.node_level === 'tool' && event.genome) {
      const genomeKey = `genome:${stage}:${event.genome}`;
      if (!nodes.has(genomeKey)) {
        nodes.set(genomeKey, {
          key: genomeKey,
          stage,
          level: 'genome',
          label: String(event.genome).replaceAll('_', ' '),
          state: 'running',
          percentage: null,
          message: 'Running',
          elapsed: null,
          rawIndex: -1,
          order: nextOrder++,
          parentKey: `stage:${stage}`,
        });
      }
      return genomeKey;
    }
    return `stage:${stage}`;
  }

  function appendPermanentEvent(event) {
    permanentEvents.push({
      key: `event:${event.canonical_raw_line_index}`,
      stage: event.workflow_stage || 'prep',
      level: 'event',
      label: event.display_message || 'Run update',
      state: event.state || 'running',
      percentage: null,
      message: event.display_message || 'Run update',
      elapsed: event.elapsed_activity,
      rawIndex: event.canonical_raw_line_index,
      order: nextOrder++,
      parentKey: `stage:${event.workflow_stage || 'prep'}`,
    });
  }

  function resetStage(stage) {
    [...nodes.entries()].forEach(([key, node]) => {
      if (node.stage === stage && node.level !== 'stage') nodes.delete(key);
    });
    const stageNode = ensureStage(stage);
    Object.assign(stageNode, {
      state: 'running',
      percentage: null,
      message: 'Running',
      elapsed: null,
    });
  }

  for (const record of records) {
    const event = classifyProgressTreeLine(
      contract,
      record.line,
      record.index,
      currentStage,
    );
    const stage = event.workflow_stage || currentStage || 'prep';
    const stageNode = ensureStage(stage);
    if (event.stage_transition) currentStage = stage;
    if (event.state === 'rerun') {
      resetStage(stage);
      appendPermanentEvent(event);
      continue;
    }
    if (stageNode.state === 'waiting') {
      stageNode.state = 'running';
      stageNode.message = 'Running';
    }
    if (event.permanent && event.node_level === 'activity') {
      appendPermanentEvent(event);
      continue;
    }
    const key = eventNodeKey(event);
    let node = nodes.get(key);
    if (!node) {
      node = {
        key,
        stage,
        level: event.node_level || 'activity',
        label: labelForEvent(event),
        state: 'running',
        percentage: null,
        message: 'Running',
        elapsed: null,
        rawIndex: -1,
        order: nextOrder++,
        parentKey: parentForEvent(event),
      };
      nodes.set(key, node);
    }
    let incomingState = event.state || 'running';
    if (TERMINAL_STATES.has(stageNode.state) && incomingState === 'running') {
      incomingState = stageNode.state;
    }
    if (TERMINAL_STATES.has(node.state) && incomingState === 'running') continue;
    const previousMessage = node.message;
    node.state = incomingState;
    if (event.percentage !== null && event.percentage !== undefined) {
      node.percentage = event.percentage;
    }
    let displayMessage = String(event.display_message || '').trim();
    if (event.heartbeat && !['', 'Waiting', 'Running'].includes(previousMessage)) {
      displayMessage = previousMessage;
    }
    node.message = displayMessage || previousMessage || 'Running';
    if (event.elapsed_activity !== null && event.elapsed_activity !== undefined) {
      node.elapsed = event.elapsed_activity;
    }
    node.rawIndex = event.canonical_raw_line_index;
    if (
      event.kind === 'download'
      && node.level === 'tool'
      && node.parentKey
      && TERMINAL_STATES.has(incomingState)
    ) {
      const parent = nodes.get(node.parentKey);
      if (parent) {
        parent.state = incomingState;
        parent.percentage = node.percentage;
        parent.message = node.message;
        parent.rawIndex = node.rawIndex;
      }
    }
    if (node.level === 'stage' && TERMINAL_STATES.has(incomingState)) {
      stageNode.state = incomingState;
      stageNode.percentage = incomingState === 'complete' ? 100 : null;
      stageNode.message = node.message;
      [...nodes.values()].forEach(child => {
        if (
          child.stage === stage
          && child.level !== 'stage'
          && !TERMINAL_STATES.has(child.state)
        ) {
          child.state = incomingState;
          child.percentage = incomingState === 'complete' ? 100 : null;
          child.message = node.message;
        }
      });
    }
  }

  const rows = [];
  for (const item of workflow) {
    const stage = item.key;
    if (item.optional && !observedOptionalStages.has(stage)) continue;
    const stageKey = `stage:${stage}`;
    const stageNode = nodes.get(stageKey);
    if (!stageNode) continue;
    rows.push({ ...stageNode, depth: 0 });
    const genomes = [...nodes.values()]
      .filter(node => node.stage === stage && node.level === 'genome')
      .sort((left, right) => left.order - right.order);
    for (const genome of genomes) {
      rows.push({ ...genome, depth: 1 });
      [...nodes.values()]
        .filter(node => node.parentKey === genome.key)
        .sort((left, right) => left.order - right.order)
        .forEach(node => rows.push({ ...node, depth: 2 }));
    }
    [...nodes.values()]
      .filter(node => (
        node.stage === stage
        && ['tool', 'activity'].includes(node.level)
        && node.parentKey === stageKey
      ))
      .sort((left, right) => left.order - right.order)
      .forEach(node => rows.push({ ...node, depth: 1 }));
    permanentEvents
      .filter(node => node.stage === stage)
      .sort((left, right) => left.order - right.order)
      .forEach(node => rows.push({ ...node, depth: 1 }));
  }
  return { rows, currentStage };
}

export function createProgressTreeConsole({
  documentImpl,
  contract,
  createRawLineElement,
}) {
  let mode = 'tree';
  let canonicalRecords = [];

  function terminal() {
    return documentImpl.getElementById('log-terminal');
  }

  function syncControls() {
    for (const value of ['tree', 'raw']) {
      const button = documentImpl.querySelector(`[data-qa-log-view="${value}"]`);
      if (!button) continue;
      const selected = mode === value;
      button.setAttribute('aria-pressed', String(selected));
      button.classList.toggle('is-selected', selected);
      button.tabIndex = selected ? 0 : -1;
    }
  }

  function updateTreeRow(element, row) {
    const terminalState = TERMINAL_STATES.has(row.state);
    const glyphs = {
      0: terminalState ? '└─' : '├─',
      1: terminalState ? '│  └─' : '│  ├─',
      2: terminalState ? '│     └─' : '│     ├─',
    };
    const status = progressTreeStatus(row);
    const signature = JSON.stringify([
      row.label,
      status,
      row.state,
      row.depth,
      row.rawIndex,
    ]);
    if (element.dataset.treeSignature === signature) return;
    element.dataset.treeSignature = signature;
    element.dataset.treeState = row.state;
    element.dataset.rawLineIndex = String(row.rawIndex);
    element.className = `progress-tree-row depth-${row.depth} state-${row.state}`;
    element.replaceChildren();
    const glyph = documentImpl.createElement('span');
    glyph.className = 'progress-tree-glyph';
    glyph.setAttribute('aria-hidden', 'true');
    glyph.textContent = glyphs[row.depth] || glyphs[1];
    const label = documentImpl.createElement('span');
    label.className = 'progress-tree-label';
    label.textContent = row.label;
    const meter = documentImpl.createElement('span');
    meter.className = 'progress-tree-meter';
    meter.textContent = status;
    element.append(glyph, label, meter);
    element.setAttribute('aria-label', `${row.label}: ${status}`);
  }

  function renderTree(term) {
    term.setAttribute('aria-live', 'off');
    term.setAttribute('aria-label', 'Selected run progress tree');
    term.dataset.logView = 'tree';
    const model = buildProgressTree(contract, canonicalRecords);
    const existing = new Map(
      [...term.querySelectorAll('[data-tree-key]')]
        .map(element => [element.dataset.treeKey, element]),
    );
    const fragment = documentImpl.createDocumentFragment();
    for (const row of model.rows) {
      const element = existing.get(row.key) || documentImpl.createElement('div');
      element.dataset.treeKey = row.key;
      updateTreeRow(element, row);
      fragment.appendChild(element);
      existing.delete(row.key);
    }
    term.replaceChildren(fragment);
  }

  function renderRaw(term) {
    term.setAttribute('aria-live', 'polite');
    term.setAttribute('aria-label', 'Selected run raw log');
    term.dataset.logView = 'raw';
    const fragment = documentImpl.createDocumentFragment();
    canonicalRecords.forEach(record => fragment.appendChild(createRawLineElement(record.line)));
    term.replaceChildren(fragment);
  }

  function render({ preserveScroll = false, autoScroll = false } = {}) {
    const term = terminal();
    if (!term) return;
    const previousHeight = term.scrollHeight;
    const previousTop = term.scrollTop;
    if (mode === 'raw') renderRaw(term);
    else renderTree(term);
    if (preserveScroll) {
      term.scrollTop = previousTop + (term.scrollHeight - previousHeight);
    } else if (autoScroll) {
      term.scrollTop = term.scrollHeight;
    }
    syncControls();
  }

  function merge(lines, start, replace) {
    const records = (Array.isArray(lines) ? lines : []).map((line, offset) => ({
      index: Math.max(0, Number(start) || 0) + offset,
      line: String(line),
    }));
    if (replace) {
      canonicalRecords = records;
      return;
    }
    const byIndex = new Map(canonicalRecords.map(record => [record.index, record]));
    records.forEach(record => byIndex.set(record.index, record));
    canonicalRecords = [...byIndex.values()].sort((left, right) => left.index - right.index);
  }

  return Object.freeze({
    reset() {
      canonicalRecords = [];
      mode = 'tree';
      render();
    },
    hydrate({ lines, start, prepend = false, autoScroll = false }) {
      merge(lines, start, !prepend);
      render({ preserveScroll: prepend, autoScroll });
    },
    append({ lines, start, autoScroll = false }) {
      merge(lines, start, false);
      render({ autoScroll });
    },
    setMode(value) {
      const next = value === 'raw' ? 'raw' : 'tree';
      if (next === mode) return;
      mode = next;
      render({ preserveScroll: true });
    },
    handleModeKeydown(event) {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'ArrowLeft' || event.key === 'Home' ? 'tree' : 'raw';
      mode = next;
      render({ preserveScroll: true });
      documentImpl.querySelector(`[data-qa-log-view="${next}"]`)?.focus();
    },
    mode() {
      return mode;
    },
    canonicalRecords() {
      return canonicalRecords.map(record => ({ ...record }));
    },
  });
}
