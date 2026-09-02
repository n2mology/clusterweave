export function createIntakeTaxonBoundary({
  publicGenomeStem,
  canonicalGenomeInputKey,
  normalizeTaxonGroup,
  publicGenomeStemPattern = /^[A-Za-z0-9._-]{1,120}$/,
  maxTaxonAssignments = 500,
}) {
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
      if (parsedRows > maxTaxonAssignments) return;
      const columns = line.split('\t');
      const rawKey = String(columns[inputIndex] || '').trim();
      const inputKey = publicGenomeStem(rawKey);
      const canonicalKey = canonicalGenomeInputKey(rawKey);
      const taxonGroup = normalizeTaxonGroup(columns[taxonIndex]);
      const lineNumber = offset + 2;
      if (!inputKey || !publicGenomeStemPattern.test(inputKey)) {
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
    if (parsedRows > maxTaxonAssignments) {
      issues.push(`taxon_assignments.tsv exceeds ${maxTaxonAssignments} assignment rows.`);
    }
    return { assignments, displayKeys, issues };
  }

  function ecologyMetadataText(enabled, rows) {
    if (!enabled || !rows.length) return '';
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

  return Object.freeze({
    clientLineageHas,
    parseClientGenbankTaxonomy,
    mergeClientGenbankAuthorities,
    clientTaxonAssignmentDecision,
    parseTaxonAssignmentSidecarText,
    ecologyMetadataText,
  });
}

export function createIntakeControllerBoundary({
  state,
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
  publicCanonicalCpus,
}) {
  const {
    clientLineageHas,
    parseClientGenbankTaxonomy,
    mergeClientGenbankAuthorities,
    clientTaxonAssignmentDecision,
    parseTaxonAssignmentSidecarText,
  } = intakeTaxonBoundary;
  const PUBLIC_CANONICAL_CPUS = publicCanonicalCpus;
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
  const TAXON_ASSIGNMENTS_FILENAME = 'taxon_assignments.tsv';
  const MAX_TAXON_ASSIGNMENT_SIDECAR_BYTES = 256 * 1024;
  const MAX_TAXON_ASSIGNMENTS = 500;

  function ncbiAssemblyAccessionHelp() {
    const scope = normalizeAnalysisScope(state.stagedAnalysisScope);
    if (scope === 'bacteria') return 'Use current bacterial NCBI assembly accessions like GCA_000005845.2.';
    if (scope === 'both') return 'Use current fungal or bacterial NCBI assembly accessions; the server resolves authoritative NCBI taxonomy.';
    return NCBI_ASSEMBLY_ACCESSION_HELP;
  }

  function analysisScopeRadioValue() {
    const selected = document.querySelector('input[name="analysis-scope"]:checked');
    return normalizeAnalysisScope(selected?.value, state.stagedAnalysisScope);
  }

  function syncAnalysisScopeControls() {
    const scope = normalizeAnalysisScope(state.stagedAnalysisScope);
    document.querySelectorAll('input[name="analysis-scope"]').forEach((input) => {
      input.checked = input.value === scope;
    });
  }

  function updateAnalysisScopeCopy() {
    const scope = normalizeAnalysisScope(state.stagedAnalysisScope);
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

  function logicalGenomeInputs(files = state.selectedFiles) {
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
    Array.from(state.stagedTaxonAssignments.keys()).forEach((key) => {
      if (currentKeys.has(key) || state.stagedTaxonAssignmentSources.get(key) === 'sidecar') return;
      state.stagedTaxonAssignments.delete(key);
      state.stagedTaxonAssignmentSources.delete(key);
    });
  }

  function stagedTaxonGroupForFileName(name) {
    const scope = normalizeAnalysisScope(state.stagedAnalysisScope);
    if (scope !== 'both') return scope;
    const canonicalKey = canonicalGenomeInputKey(name);
    const logicalInput = logicalGenomeInputs().find(item => item.canonicalKey === canonicalKey);
    const authority = logicalInput ? logicalGenomeAuthority(logicalInput) : null;
    if (authority?.status === 'resolved') return authority.taxonGroup;
    return normalizeTaxonGroup(state.stagedTaxonAssignments.get(canonicalKey));
  }

  function logicalGenomeAuthority(item) {
    const authorities = (item?.files || [])
      .filter(file => PUBLIC_GENBANK_EXTENSIONS.has(ext(file?.name || '')))
      .map(file => clientGenbankAuthorityForFile(file));
    return mergeClientGenbankAuthorities(authorities);
  }

  function logicalGenomeTaxonAssignmentDecision(item) {
    const assigned = normalizeTaxonGroup(state.stagedTaxonAssignments.get(item.canonicalKey));
    return clientTaxonAssignmentDecision(logicalGenomeAuthority(item), assigned, item.inputKey);
  }

  function taxonAssignmentsPayload() {
    if (normalizeAnalysisScope(state.stagedAnalysisScope) !== 'both') return {};
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
    const unresolved = normalizeAnalysisScope(state.stagedAnalysisScope) === 'both'
      ? assignable.filter(decision => !decision.assigned).map(decision => decision.item)
      : [];
    const unknownSidecarKeys = [];
    state.stagedTaxonAssignmentSources.forEach((source, key) => {
      if (source === 'sidecar' && !currentKeys.has(key)) unknownSidecarKeys.push(key);
    });
    const authorityIssues = decisions
      .filter(decision => decision.issue)
      .map(decision => ({ inputKey: decision.item.inputKey, issue: decision.issue }));
    const sidecarIssues = state.taxonAssignmentSidecarIssues.slice();
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
    const visible = normalizeAnalysisScope(state.stagedAnalysisScope) === 'both' && validation.assignable.length > 0;
    panel.hidden = !visible;
    panel.classList.toggle('hidden', !visible);
    if (!visible) {
      list.innerHTML = '';
      status.textContent = '0 unresolved';
      return;
    }
    list.innerHTML = validation.assignable.map((decision, index) => {
      const item = decision.item;
      const assigned = normalizeTaxonGroup(state.stagedTaxonAssignments.get(item.canonicalKey));
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
    const genomeFiles = state.selectedFiles.filter(isGenomeUploadFile);
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
    state.stagedTaxonAssignments.set(key, group);
    state.stagedTaxonAssignmentSources.set(key, 'user');
    await refreshSelectedGenomeChecks();
    renderFileList();
  }

  async function markAllTaxonAssignments(taxonGroup) {
    const group = normalizeTaxonGroup(taxonGroup);
    if (!group) return;
    logicalGenomeInputs().forEach((item) => {
      if (!logicalGenomeTaxonAssignmentDecision(item).requiresAssignment) return;
      state.stagedTaxonAssignments.set(item.canonicalKey, group);
      state.stagedTaxonAssignmentSources.set(item.canonicalKey, 'user');
    });
    await refreshSelectedGenomeChecks();
    renderFileList();
  }


  async function loadTaxonAssignmentSidecar(file) {
    Array.from(state.stagedTaxonAssignmentSources.entries()).forEach(([key, source]) => {
      if (source !== 'sidecar') return;
      state.stagedTaxonAssignments.delete(key);
      state.stagedTaxonAssignmentSources.delete(key);
    });
    state.taxonAssignmentSidecar = {
      name: TAXON_ASSIGNMENTS_FILENAME,
      size: Number(file?.size || 0),
      lastModified: Number(file?.lastModified || 0),
    };
    state.taxonAssignmentSidecarIssues = [];
    if (state.taxonAssignmentSidecar.size > MAX_TAXON_ASSIGNMENT_SIDECAR_BYTES) {
      state.taxonAssignmentSidecarIssues.push('taxon_assignments.tsv exceeds the 256 KB browser limit.');
      return;
    }
    let text = '';
    try {
      text = await file.text();
    } catch (error) {
      state.taxonAssignmentSidecarIssues.push('taxon_assignments.tsv could not be read in this browser.');
      return;
    }
    const parsed = parseTaxonAssignmentSidecarText(text);
    state.taxonAssignmentSidecarIssues = parsed.issues;
    parsed.assignments.forEach((group, key) => {
      state.stagedTaxonAssignments.set(key, group);
      state.stagedTaxonAssignmentSources.set(key, 'sidecar');
    });
  }

  function removeTaxonAssignmentSidecar() {
    state.taxonAssignmentSidecar = null;
    state.taxonAssignmentSidecarIssues = [];
    Array.from(state.stagedTaxonAssignmentSources.entries()).forEach(([key, source]) => {
      if (source !== 'sidecar') return;
      state.stagedTaxonAssignments.delete(key);
      state.stagedTaxonAssignmentSources.delete(key);
    });
    renderFileList();
  }

  async function handleAnalysisScopeChange() {
    state.stagedAnalysisScope = analysisScopeRadioValue();
    syncAnalysisScopeControls();
    updateAnalysisScopeCopy();
    await refreshSelectedGenomeChecks();
    applyAnalysisCapabilityVisibility();
    renderBrutalAccessionRows();
    renderFileList();
  }

  function resetStagedAnalysisState(scope = 'fungi') {
    state.stagedAnalysisScope = normalizeAnalysisScope(scope);
    state.stagedTaxonAssignments = new Map();
    state.stagedTaxonAssignmentSources = new Map();
    state.taxonAssignmentSidecar = null;
    state.taxonAssignmentSidecarIssues = [];
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
  let brutalAccessionDrafts = [];
  let brutalAccessionCommitted = new Set();
  let brutalInputLogMessageSignature = '';
  let brutalInputLogDismissedSignature = '';
  let brutalSyncingAccepted = false;
  let brutalEcoSelections = new Map();
  let brutalEcoContext = null;
  let brutalRowsInitialized = false;
  let accessionPreflightSignatureValue = '';
  let accessionPreflightByAccession = new Map();

  function accessionLimit() {
    const configured = Number(publicQuotaLimits().max_accessions);
    if (Number.isFinite(configured) && configured > 0) return Math.floor(configured);
    return 50;
  }

  function resizedAccessionDrafts(values = []) {
    const source = Array.from(values || []);
    let retainedLength = 0;
    source.forEach((value, index) => {
      if (normalizeAccessionDraft(value)) retainedLength = index + 1;
    });
    const length = Math.max(accessionLimit(), retainedLength);
    return Array.from({ length }, (_, index) => source[index] || '');
  }

  brutalAccessionDrafts = resizedAccessionDrafts();

  function accessionPreflightSignature() {
    return JSON.stringify({
      analysisScope: normalizeAnalysisScope(state.stagedAnalysisScope),
      accessions: manualAccessionLines().map(normalizeAccessionDraft).sort(),
    });
  }

  function accessionPreflightResult(accession) {
    if (accessionPreflightSignatureValue !== accessionPreflightSignature()) return null;
    return accessionPreflightByAccession.get(normalizeAccessionDraft(accession)) || null;
  }

  function blockedAccessionPreflight() {
    return manualAccessionLines().some(accession => accessionPreflightResult(accession)?.accepted === false);
  }

  function accessionPreflightReadyReason(result, sourceName = '') {
    const source = sourceName ? ` from ${sourceName}` : '';
    const organism = String(result?.organism_name || '').trim();
    const taxonGroup = String(result?.taxon_group || '').trim();
    const authority = [organism, taxonGroup].filter(Boolean).join(' / ');
    return `VERIFIED BY NCBI${source}${authority ? ` - ${authority}.` : '.'}`;
  }

  async function validateAcceptedAccessions() {
    const accessions = manualAccessionLines().map(normalizeAccessionDraft);
    const requestedSignature = accessionPreflightSignature();
    if (!accessions.length) {
      accessionPreflightSignatureValue = requestedSignature;
      accessionPreflightByAccession = new Map();
      return;
    }
    const response = await apiFetch('api/inputs/validate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        accessions,
        analysis_scope: normalizeAnalysisScope(state.stagedAnalysisScope),
      }),
    }, { kind: 'submit' });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || 'NCBI accession validation failed');
    if (!Array.isArray(payload.results)) throw new Error('NCBI accession validation returned an invalid response');
    if (requestedSignature !== accessionPreflightSignature()) {
      throw new Error('Inputs changed during validation. Select Validate again.');
    }
    const results = new Map();
    payload.results.forEach((result) => {
      const accession = normalizeAccessionDraft(result?.accession || '');
      if (!accession) return;
      results.set(accession, {
        accession,
        accepted: result?.accepted === true,
        detail: String(result?.detail || ''),
        organism_name: String(result?.organism_name || ''),
        taxon_group: String(result?.taxon_group || ''),
      });
    });
    if (accessions.some(accession => !results.has(accession))) {
      throw new Error('NCBI accession validation did not return every requested accession');
    }
    accessionPreflightSignatureValue = requestedSignature;
    accessionPreflightByAccession = results;
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
    state.selectedFiles.forEach((file) => {
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
    if (!normalizedKey) return false;
    if (message) {
      const nextMessage = String(message);
      if (state.brutalInputNotices.get(normalizedKey) === nextMessage) return false;
      state.brutalInputNotices.set(normalizedKey, nextMessage);
    } else {
      if (!state.brutalInputNotices.has(normalizedKey)) return false;
      state.brutalInputNotices.delete(normalizedKey);
    }
    renderBrutalInputLog();
    return true;
  }

  function updateBrutalRowState(row, index) {
    const input = row.querySelector('.brutal-accession-input');
    const status = row.querySelector('.status-icon');
    const remove = row.querySelector('.accession-remove');
    const accession = normalizeAccessionDraft(input?.value || '');
    const hasInput = !!accession;
    const valid = rowIsAccepted(accession, index);
    const verification = valid ? accessionPreflightResult(accession) : null;
    const verified = valid && verification?.accepted === true;
    const verificationError = valid && verification?.accepted === false;
    const committed = accessionDraftCommitted(index);
    const showInvalid = hasInput && !valid && committed;
    const showError = showInvalid || verificationError;
    row.classList.toggle('has-input', hasInput);
    row.classList.toggle('has-valid-accession', valid);
    row.classList.toggle('has-invalid-accession', showInvalid);
    row.classList.toggle('has-accession-verification-error', verificationError);
    if (input) input.setAttribute('aria-invalid', showError ? 'true' : 'false');
    if (status) {
      status.classList.toggle('waiting', !hasInput || (hasInput && !valid && !committed) || (valid && !verification));
      status.classList.toggle('ok', verified);
      status.classList.toggle('bad', showError);
      const statusLabel = verified
        ? 'Verified accession'
        : verificationError
          ? `Verification failed: ${verification.detail || 'Unsupported accession'}`
          : showInvalid
            ? 'Invalid accession'
            : hasInput
              ? 'Accession validation pending'
              : 'Waiting for accession';
      status.setAttribute('aria-label', statusLabel);
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
      const hasInput = !!normalizeAccessionDraft(brutalAccessionDrafts[index] || '');
      const presented = index < Math.min(accessionLimit(), BRUTAL_ACCESSION_PREVIEW_ROWS) || enabled || hasInput;
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
    state.acceptedManualAccessions = acceptedDraftAccessions().filter(accession => !fileOwned.has(accession));
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
    brutalAccessionDrafts = resizedAccessionDrafts();
    brutalAccessionCommitted = new Set();
    brutalEcoSelections = new Map();
    renderBrutalAccessionRows();
    updateBrutalTargetButton();
  }

  function syncBrutalRowsFromAccepted() {
    const rows = document.getElementById('brutal-accession-rows');
    if (!rows || rows.contains(document.activeElement)) return;
    const accepted = manualAccessionLines();
    const nextDrafts = resizedAccessionDrafts(accepted);
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
    const rowCount = Math.max(limit, brutalAccessionDrafts.length);
    rows.innerHTML = Array.from({ length: rowCount }, (_, index) => {
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
    state.brutalInputNotices.forEach(addMessage);
    document.querySelectorAll('#input-checker-list .input-check-row.blocked').forEach((row) => {
      const label = row.querySelector('.input-check-label')?.textContent?.trim() || 'Input';
      const reason = row.querySelector('.input-check-reason')?.textContent?.trim() || 'Blocked before run.';
      const message = conciseInputNotice(`${label}: ${reason}`);
      if (!draftMessages.has(message) && !label.startsWith('Row ')) addMessage(message);
    });
    const messageSignature = JSON.stringify(messages);
    const html = messages.map(message => `<div class="input-log-note">${escapeHtml(message)}</div>`).join('');
    if (messageSignature !== brutalInputLogMessageSignature) {
      brutalInputLogMessageSignature = messageSignature;
      brutalInputLogDismissedSignature = '';
    }
    if (list.innerHTML !== html) list.innerHTML = html;
    drawer.hidden = messages.length === 0 || brutalInputLogDismissedSignature === messageSignature;
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
      if (!drawer || drawer.hidden) return;
      brutalInputLogDismissedSignature = brutalInputLogMessageSignature;
      drawer.hidden = true;
    });
    const projectNameInput = document.getElementById('project-name');
    projectNameInput?.addEventListener('input', () => {
      renderFileList();
    });
    projectNameInput?.addEventListener('blur', () => {
      const priorValue = projectNameInput.value;
      normalizeProjectNameInput();
      if (projectNameInput.value !== priorValue) renderFileList();
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
    state.acceptedManualAccessions.forEach(add);
    state.accessionFileSources.forEach(source => source.accessions.forEach(add));
    return merged;
  }

  function accessionFileOwnedAccessions() {
    const owned = new Set();
    state.accessionFileSources.forEach((source) => {
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
    state.accessionFileSources.forEach((source) => {
      source.accessions = (Array.isArray(source.accessions) ? source.accessions : [])
        .filter(value => normalizeAccessionDraft(value) !== normalized);
    });
    state.accessionFileSources = state.accessionFileSources.filter(source => source.accessions.length > 0);
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
      max_accessions: Number(state.publicQuota.max_accessions) || 50,
      max_genome_files: Number(state.publicQuota.max_genome_files) || 50,
      max_upload_file_mb: Number(state.publicQuota.max_upload_file_mb) || 500,
      max_cpus_per_job: Number(state.publicQuota.max_cpus_per_job) || PUBLIC_CANONICAL_CPUS,
      max_upload_total_mb: Number(state.publicQuota.max_upload_total_mb) || 1024,
    };
  }

  function formatQuotaMb(value) {
    const mb = Number(value) || 0;
    if (mb >= 1024 && mb % 1024 === 0) return `${mb / 1024} GB`;
    return `${mb} MB`;
  }

  const PUBLIC_WEB_FAQ_URL = 'https://github.com/n2mology/clusterweave#web-portal-faq';

  function publicQuotaSummary(quota = publicQuotaLimits()) {
    const cpuThreads = `${quota.max_cpus_per_job} CPU thread${quota.max_cpus_per_job === 1 ? '' : 's'}`;
    return `${formatQuotaMb(quota.max_upload_file_mb)} per file, ${formatQuotaMb(quota.max_upload_total_mb)} total per run, ${quota.max_genome_files} genome files, or ${quota.max_accessions} NCBI accessions; hosted runs use up to ${cpuThreads}`;
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
    const summary = `${formatQuotaMb(quota.max_upload_file_mb)} per file, ${formatQuotaMb(quota.max_upload_total_mb)} total per run, ${quota.max_genome_files} genome files, or ${quota.max_accessions} NCBI accessions`;
    const note = document.getElementById('upload-limit-note');
    if (note) {
      note.innerHTML = `Limits: ${escapeHtml(summary)}. <a href="${PUBLIC_WEB_FAQ_URL}" target="_blank" rel="noopener">FAQ / local workflow</a>`;
    }
  }

  function applyPublicQuotaLimits() {
    brutalAccessionDrafts = resizedAccessionDrafts(brutalAccessionDrafts);
    renderBrutalAccessionRows();
    updateInputLimitGuidance();
    renderFileList();
  }

  function genomeFileCheckKey(file) {
    const route = stagedTaxonGroupForFileName(file.name) || `unresolved-${normalizeAnalysisScope(state.stagedAnalysisScope)}`;
    return `${file.name}|${file.size}|${file.lastModified || 0}|${route}`;
  }

  function publicGenomeStem(name) {
    return String(name || '').replace(/\.(gbk|gb|gbff|fasta|fa|fna|fsa)$/i, '').trim();
  }





  function genomeFileIdentityKey(file) {
    return `${String(file?.name || '')}|${Number(file?.size || 0)}|${Number(file?.lastModified || 0)}`;
  }

  function clientGenbankAuthorityForFile(file) {
    return state.genbankTaxonomyAuthorityCache.get(genomeFileIdentityKey(file)) || {
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
    state.genbankTaxonomyAuthorityCache.set(genomeFileIdentityKey(file), authority);
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
    if (state.genomeCheckCache.has(key)) {
      const cached = state.genomeCheckCache.get(key);
      rememberClientGenbankAuthority(file, cached);
      return cached;
    }
    const quota = publicQuotaLimits();
    if (file.size > quota.max_upload_file_mb * 1048576) {
      const result = { readiness: 'invalid', reason: publicFileLimitMessage(quota) };
      state.genomeCheckCache.set(key, result);
      rememberClientGenbankAuthority(file, result);
      return result;
    }
    try {
      const preview = await readClientGenomePreview(file);
      const result = preview.partial ? classifyClientGenomePreview(file, preview.text) : classifyClientGenomeText(file, preview.text);
      state.genomeCheckCache.set(key, result);
      rememberClientGenbankAuthority(file, result);
      return result;
    } catch (err) {
      const result = { readiness: 'client_preflight_unconfirmed', reason: browserGenomePrecheckUnavailableReason(file) };
      state.genomeCheckCache.set(key, result);
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
    const requestedCount = existing.size + newAccessions.length;
    if (requestedCount > accessionLimit()) {
      const status = document.getElementById('manual-accessions-status');
      if (status) status.textContent = `This batch would produce ${requestedCount} accepted accessions; this ClusterWeave service accepts at most ${accessionLimit()}. No accessions were added.`;
      return;
    }
    state.acceptedManualAccessions.push(...newAccessions);
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
    state.acceptedManualAccessions = [];
    state.accessionFileSources = [];
    resetBrutalAccessionDrafts();
    clearStaleTargetGenome();
    renderAcceptedAccessions();
    updateManualAccessionsStatus();
    renderFileList();
  }

  function clearAcceptedManualAccessions() {
    state.acceptedManualAccessions = [];
    resetBrutalAccessionDrafts();
    clearStaleTargetGenome();
    renderAcceptedAccessions();
    updateManualAccessionsStatus();
    renderFileList();
  }

  function loadDemoAccessions(event) {
    if (event) event.preventDefault();
    const demoAccessions = ['GCA_000011425.1', 'GCA_030770425.1'];
    state.acceptedManualAccessions = demoAccessions.slice();
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
    const pending = [];
    accessions.forEach((raw) => {
      const accession = normalizeAccessionDraft(raw);
      if (!validBrutalAccession(accession) || existing.has(accession)) return;
      existing.add(accession);
      pending.push(accession);
    });
    if (!pending.length) return pending;
    if (existing.size > limit) return [];
    const nextDrafts = resizedAccessionDrafts(brutalAccessionDrafts);
    for (const accession of pending) {
      const slot = nextDrafts.findIndex((value, index) => index < limit && !normalizeAccessionDraft(value));
      if (slot < 0) return [];
      nextDrafts[slot] = accession;
    }
    brutalAccessionDrafts = nextDrafts;
    state.acceptedManualAccessions = acceptedDraftAccessions();
    if (manualAccessionsInput) manualAccessionsInput.value = '';
    renderBrutalAccessionRows();
    syncEcologyMetadataPanel();
    applyBrutalEcologyToMetadataTable();
    updateBrutalTargetButton();
    updateRunSummary();
    return pending;
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
    const requestedCount = existing.size + newAccessions.length;
    if (requestedCount > accessionLimit()) {
      setBrutalInputNotice(noticeKey, `Accession list ${file.name} would produce ${requestedCount} accepted accessions; this ClusterWeave service accepts at most ${accessionLimit()}. No accessions were imported.`);
      return false;
    }
    const imported = importAccessionsToLoader(newAccessions);
    if (!imported.length) {
      setBrutalInputNotice(noticeKey, `Accession list ${file.name} could not be imported. No accessions were imported.`);
      return false;
    }
    state.accessionFileSources.push({ name: String(file.name || 'accessions.txt'), accessions: imported.slice() });
    const fileOwned = accessionFileOwnedAccessions();
    state.acceptedManualAccessions = state.acceptedManualAccessions.filter(accession => !fileOwned.has(normalizeAccessionDraft(accession)));
    setBrutalInputNotice(noticeKey, '');
    const duplicateCount = parsed.accessions.length - newAccessions.length + parsed.duplicateCount;
    const status = document.getElementById('upload-status');
    if (status) {
      status.textContent = duplicateCount
        ? `${imported.length} accession${imported.length === 1 ? '' : 's'} imported to the accession loader from ${file.name}; ${duplicateCount} duplicate${duplicateCount === 1 ? '' : 's'} skipped.`
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
    limits.textContent = `Limits: ${publicQuotaSummary(quota)}`;
  }

  function accessionPreflightPendingReason(sourceName = '') {
    const source = sourceName ? ` from ${sourceName}` : '';
    const scope = normalizeAnalysisScope(state.stagedAnalysisScope);
    if (scope === 'bacteria') {
      return `FORMAT OK${source} - SELECT VALIDATE FOR AUTHORITATIVE NCBI TAXONOMY AND BACTERIAL ROUTING.`;
    }
    if (scope === 'both') {
      return `FORMAT OK${source} - SELECT VALIDATE TO ROUTE THIS ACCESSION TO FUNGI OR BACTERIA.`;
    }
    return `FORMAT OK${source} - SELECT VALIDATE FOR AUTHORITATIVE NCBI TAXONOMY.`;
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
    const publicGenomeFiles = state.selectedFiles.filter(file => {
      const fileExt = ext(file.name);
      return PUBLIC_FASTA_EXTENSIONS.has(fileExt) || PUBLIC_GENBANK_EXTENSIONS.has(fileExt);
    });
    const totalUploadBytes = state.selectedFiles.reduce((sum, file) => sum + (Number(file.size) || 0), 0);

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

    const addAccessionCheck = (accession, sourceName = '') => {
      const verification = accessionPreflightResult(accession);
      if (verification?.accepted === true) {
        addInputCheckRow(rows, 'ready', 'NCBI accession', accession, accessionPreflightReadyReason(verification, sourceName));
      } else if (verification?.accepted === false) {
        addInputCheckRow(rows, 'blocked', 'NCBI accession', accession, verification.detail || 'NCBI accession verification failed.');
      } else {
        addInputCheckRow(rows, 'warning', 'NCBI accession', accession, accessionPreflightPendingReason(sourceName));
      }
    };
    state.acceptedManualAccessions.forEach(accession => addAccessionCheck(accession));
    state.accessionFileSources.forEach((source) => {
      source.accessions.forEach(accession => addAccessionCheck(accession, source.name));
    });

    const genomeStemKinds = new Map();
    state.selectedFiles.forEach((file) => {
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
    state.selectedFiles.forEach((file) => {
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
      const check = state.genomeCheckCache.get(genomeFileCheckKey(file)) || {
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
    if (state.taxonAssignmentSidecar && !assignmentValidation.issues.length) {
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
      if (!state.selectedFiles.find(x => x.name === f.name)) {
        if (PUBLIC_FASTA_EXTENSIONS.has(fileExt) || PUBLIC_GENBANK_EXTENSIONS.has(fileExt)) await cacheGenomeFileCheck(f);
        state.selectedFiles.push(f);
      }
    }
    await refreshSelectedGenomeChecks();
    renderAcceptedAccessions();
    renderFileList();
  }

  async function removeFile(index) {
    const [removed] = state.selectedFiles.splice(index, 1);
    if (removed) state.genbankTaxonomyAuthorityCache.delete(genomeFileIdentityKey(removed));
    const targetInput = document.getElementById('target-genome');
    const removedTarget = removed && isGenomeUploadName(removed.name)
      ? genomeStemFromName(removed.name)
      : '';
    const sameTargetRemains = removedTarget && state.selectedFiles.some((file) => (
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
    const [removed] = state.accessionFileSources.splice(index, 1);
    if (!removed) return;
    const removedSet = new Set((removed.accessions || []).map(normalizeAccessionDraft));
    const retained = acceptedDraftAccessions().filter(accession => !removedSet.has(accession));
    brutalAccessionDrafts = resizedAccessionDrafts(retained);
    brutalAccessionCommitted = new Set(
      retained.map((value, draftIndex) => normalizeAccessionDraft(value) ? draftIndex : -1).filter(draftIndex => draftIndex >= 0),
    );
    removedSet.forEach(accession => brutalEcoSelections.delete(accession));
    state.acceptedManualAccessions = state.acceptedManualAccessions.filter(accession => !removedSet.has(normalizeAccessionDraft(accession)));
    renderBrutalAccessionRows();
    syncBrutalAcceptedFromDrafts();
  }

  function submissionsPausedForPublic() {
    const submissionState = String(state.runtimeStatusSnapshot.submissions || '').trim().toLowerCase();
    return !canUseAdminSurfaces() && ['paused', 'closed', 'disabled', 'false', '0'].includes(submissionState);
  }

  function uploadedInputRequiresAcknowledgment() {
    return !canUseAdminSurfaces() && (
      state.selectedFiles.length > 0
      || state.accessionFileSources.length > 0
      || !!state.taxonAssignmentSidecar
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
    const files = state.selectedFiles
      .map(file => [String(file.name || ''), Number(file.size || 0), Number(file.lastModified || 0)])
      .sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
    const accessionSources = state.accessionFileSources
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
      analysisScope: normalizeAnalysisScope(state.stagedAnalysisScope),
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
    const submitReady = !!state.validatedIntakeSignature
      && state.validatedIntakeSignature === submissionValidationSignature();
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
    const accessionFileItems = state.accessionFileSources.map((source, idx) => `
      <div class="file-item">
        <span class="file-icon" aria-hidden="true"></span>
        <span class="file-name">${escapeHtml(source.name)}</span>
        <span class="file-size">${source.accessions.length} accession${source.accessions.length === 1 ? '' : 's'}</span>
        <button class="file-remove" onclick="removeAccessionFileSource(${idx})" title="Remove">✕</button>
      </div>`).join('');
    const sidecarItem = state.taxonAssignmentSidecar ? `
      <div class="file-item">
        <span class="file-icon" aria-hidden="true"></span>
        <span class="file-name">${TAXON_ASSIGNMENTS_FILENAME}</span>
        <span class="file-size">${state.taxonAssignmentSidecarIssues.length ? 'Needs review' : `${Object.keys(taxonAssignmentsPayload()).length} assignments`}</span>
        <button class="file-remove" type="button" onclick="removeTaxonAssignmentSidecar()" title="Remove" aria-label="Remove taxon assignments sidecar">✕</button>
      </div>` : '';
    list.innerHTML = state.selectedFiles.map((f, idx) => {
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
    const inputSourceCount = state.selectedFiles.length + (accessionLines.length ? 1 : 0);
    const ackMissing = syncDataUseAcknowledgment();
    const projectMissing = !projectNameValue();
    const queuePaused = inputSourceCount > 0 && submissionsPausedForPublic();
    setBrutalInputNotice('queue-gate', queuePaused ? 'Queue gate: paused before upload.' : '');
    setBrutalInputNotice('data-use', '');
    setBrutalInputNotice('project-name', '');
    setProjectNameRequiredState(projectMissing);
    if (submitShell) submitShell.classList.toggle('is-project-locked', projectMissing);
    const assignmentValidation = taxonAssignmentValidation();
    const assignmentBlocked = normalizeAnalysisScope(state.stagedAnalysisScope) === 'both'
      && (assignmentValidation.unresolved.length > 0 || assignmentValidation.issues.length > 0);
    const assignmentMessage = assignmentValidation.issues[0]
      || (assignmentValidation.unresolved.length
        ? `${assignmentValidation.unresolved.length} logical genome assignment${assignmentValidation.unresolved.length === 1 ? '' : 's'} required in Both mode.`
        : '');
    setBrutalInputNotice('taxon-assignment', '');
    const checkerState = renderInputChecker();
    const checkerBlocked = blockedAccessionPreflight() || (!canUseAdminSurfaces() && checkerState.blocked > 0);
    btn.disabled = inputSourceCount === 0 || draftPending || ackMissing || projectMissing || queuePaused || checkerBlocked || assignmentBlocked;
    const currentValidationSignature = submissionValidationSignature();
    if (state.validatedIntakeSignature && state.validatedIntakeSignature !== currentValidationSignature) {
      state.validatedIntakeSignature = '';
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
    } else {
      stat.textContent = '';
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
    state.selectedFiles.forEach((file) => {
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

  function metadataProfileText() { return intakeTaxonBoundary.ecologyMetadataText(!!document.getElementById('run-ecology')?.checked, currentEcologyMetadataRows()); }

  // ── Start Analysis ─────────────────────────────────────────────────────────
  async function startAnalysis() {
    const name = requireProjectNameForSubmit();
    if (!name) return;
    commitAllBrutalAccessionDrafts({ render: false });
    const manualLines = manualAccessionLines();
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
    if (state.selectedFiles.length === 0 && manualLines.length === 0) return;
    const assignmentValidation = taxonAssignmentValidation();
    if (normalizeAnalysisScope(state.stagedAnalysisScope) === 'both'
        && (assignmentValidation.unresolved.length || assignmentValidation.issues.length)) {
      const message = assignmentValidation.issues[0]
        || `${assignmentValidation.unresolved.length} logical genome assignment${assignmentValidation.unresolved.length === 1 ? '' : 's'} required in Both mode.`;
      document.getElementById('upload-status').textContent = message;
      renderFileList();
      return;
    }
    const checkerState = renderInputChecker();
    if (blockedAccessionPreflight() || (!canUseAdminSurfaces() && checkerState.blocked > 0)) {
      document.getElementById('upload-status').textContent = `${checkerState.blocked} blocked input source${checkerState.blocked === 1 ? '' : 's'} must be fixed before starting.`;
      renderFileList();
      return;
    }

    const requestedValidationSignature = submissionValidationSignature();
    if (state.validatedIntakeSignature !== requestedValidationSignature) {
      const runButton = document.getElementById('run-btn');
      const uploadStatus = document.getElementById('upload-status');
      runButton.disabled = true;
      uploadStatus.textContent = 'Validating inputs…';
      setBrutalInputNotice('validation', '');
      try {
        await Promise.all([
          refreshSelectedGenomeChecks(),
          validateAcceptedAccessions(),
        ]);
      } catch (error) {
        const message = error?.message || 'Input validation failed';
        state.validatedIntakeSignature = '';
        renderBrutalAccessionRows();
        setBrutalInputNotice('validation', message);
        renderFileList();
        uploadStatus.textContent = `Validation failed: ${message}`;
        return;
      }
      renderBrutalAccessionRows();
      renderFileList();
      const refreshedAssignment = taxonAssignmentValidation();
      const refreshedChecker = renderInputChecker();
      const refreshedAssignmentBlocked = normalizeAnalysisScope(state.stagedAnalysisScope) === 'both'
        && (refreshedAssignment.unresolved.length || refreshedAssignment.issues.length);
      if (blockedAccessionPreflight() || (!canUseAdminSurfaces() && refreshedChecker.blocked > 0) || refreshedAssignmentBlocked) {
        state.validatedIntakeSignature = '';
        renderFileList();
        return;
      }
      if (requestedValidationSignature !== submissionValidationSignature()) {
        const message = 'Inputs changed during validation. Select Validate again.';
        state.validatedIntakeSignature = '';
        setBrutalInputNotice('validation', message);
        renderFileList();
        uploadStatus.textContent = message;
        return;
      }
      state.validatedIntakeSignature = requestedValidationSignature;
      setBrutalInputNotice('validation', '');
      renderFileList();
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
    for (const f of state.selectedFiles) fd.append('files', f);
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
    fd.append('analysis_scope', normalizeAnalysisScope(state.stagedAnalysisScope));
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
    const notifyEmail = state.smtpEnabled ? (document.getElementById('notify-email')?.value.trim() || '') : '';
    if (state.smtpEnabled) {
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
      if (submittedRunId) state.publicResultRunIds.add(submittedRunId);
      if (input_summary) {
        runSetupReceipt.inputSummary = input_summary;
        runSetupReceipt.accessionMetadata = Array.isArray(input_summary.accession_metadata) ? input_summary.accession_metadata : [];
        runSetupReceipt.taxonCounts = normalizeTaxonCounts(input_summary.taxon_counts || input_summary.taxonCounts || input_summary);
      }
      if (read_token) {
        rememberOpenedRun(submittedRunId, read_token, {
          name,
          status: 'pending',
          receipt: runSetupReceipt,
        });
      }
      state.validatedIntakeSignature = '';
      state.selectedFiles = [];
      state.acceptedManualAccessions = [];
      state.accessionFileSources = [];
      state.genomeCheckCache = new Map();
      state.genbankTaxonomyAuthorityCache = new Map();
      accessionPreflightSignatureValue = '';
      accessionPreflightByAccession = new Map();
      state.stagedTaxonAssignments = new Map();
      state.stagedTaxonAssignmentSources = new Map();
      state.taxonAssignmentSidecar = null;
      state.taxonAssignmentSidecarIssues = [];
      state.brutalInputNotices.clear();
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

  return Object.freeze({
    ncbiAssemblyAccessionHelp,
    analysisScopeRadioValue,
    syncAnalysisScopeControls,
    updateAnalysisScopeCopy,
    isTaxonAssignmentsSidecarName,
    isGenomeUploadFile,
    canonicalGenomeInputKey,
    logicalGenomeInputs,
    pruneManualTaxonAssignments,
    stagedTaxonGroupForFileName,
    logicalGenomeAuthority,
    logicalGenomeTaxonAssignmentDecision,
    taxonAssignmentsPayload,
    taxonAssignmentValidation,
    renderTaxonAssignmentPanel,
    refreshSelectedGenomeChecks,
    setLogicalGenomeTaxonAssignment,
    markAllTaxonAssignments,
    loadTaxonAssignmentSidecar,
    removeTaxonAssignmentSidecar,
    handleAnalysisScopeChange,
    resetStagedAnalysisState,
    accessionLimit,
    normalizeAccessionDraft,
    normalizeShortToken,
    normalizeProjectNameInput,
    projectNameValue,
    setProjectNameRequiredState,
    requireProjectNameForSubmit,
    validBrutalAccession,
    brutalDraftDuplicate,
    brutalRowVisible,
    updateBrutalTargetButton,
    setBrutalTarget,
    setUploadedGenomeTarget,
    targetGenomeCandidates,
    clearStaleTargetGenome,
    handleUploadedGenomeTargetClick,
    ecologySelectionFor,
    inputEcologyEnabled,
    updateBrutalEcologyToggle,
    updateUploadedGenomeEcoButtons,
    setBrutalEcologyEnabled,
    savedEcoValue,
    rowIsAccepted,
    accessionDraftCommitted,
    brutalAccessionDraftIssues,
    setBrutalInputNotice,
    updateBrutalRowState,
    updateBrutalRowVisibility,
    acceptedDraftAccessions,
    syncBrutalAcceptedFromDrafts,
    resetBrutalAccessionDrafts,
    syncBrutalRowsFromAccepted,
    renderBrutalAccessionRows,
    handleBrutalAccessionInput,
    commitBrutalAccessionRow,
    commitAllBrutalAccessionDrafts,
    removeBrutalAccession,
    handleBrutalAccessionClick,
    handleBrutalAccessionKeydown,
    handleBrutalAccessionFocusout,
    openBrutalEcoPicker,
    openUploadedGenomeEcoPicker,
    openEcoPickerForInput,
    closeBrutalEcoPicker,
    saveBrutalEcoSelection,
    applyBrutalEcologyToMetadataTable,
    conciseInputNotice,
    renderBrutalInputLog,
    initializeBrutalInputStation,
    parseAccessionText,
    parseManualAccessions,
    mergedAcceptedAccessions,
    accessionFileOwnedAccessions,
    detachAccessionFromFileSources,
    manualAccessionLines,
    manualAccessionErrorMessage,
    publicQuotaLimits,
    formatQuotaMb,
    publicQuotaSummary,
    localWorkflowPrompt,
    publicFileLimitMessage,
    publicTotalLimitMessage,
    updateInputLimitGuidance,
    applyPublicQuotaLimits,
    genomeFileCheckKey,
    publicGenomeStem,
    genomeFileIdentityKey,
    clientGenbankAuthorityForFile,
    rememberClientGenbankAuthority,
    clientGenbankAuthorityProblem,
    classifyClientFastaText,
    classifyClientGenbankText,
    publicGenomeUploadKind,
    classifyClientGenomeText,
    classifyClientGenomePreview,
    readClientGenomePreview,
    browserGenomePrecheckUnavailableReason,
    cacheGenomeFileCheck,
    updateManualAccessionsStatus,
    renderAcceptedAccessions,
    normalizeManualAccessions,
    clearManualAccessions,
    clearAcceptedAccessions,
    clearAcceptedManualAccessions,
    loadDemoAccessions,
    importAccessionsToLoader,
    addAccessionFileSource,
    inputCheckLevel,
    inputCheckBadge,
    addInputCheckRow,
    renderInputCheckerRow,
    updateInputCheckerLimits,
    accessionPreflightPendingReason,
    renderInputChecker,
    addFiles,
    removeFile,
    removeAccessionFileSource,
    submissionsPausedForPublic,
    uploadedInputRequiresAcknowledgment,
    syncDataUseAcknowledgment,
    submissionValidationSignature,
    syncRunButtonPresentation,
    renderFileList,
    genomeStemFromName,
    isGenomeUploadName,
    ecologyInputRows,
    collectEcologyRowValues,
    ecologySelectOptions,
    ecologyLabelCellHtml,
    renderEcologyMetadataRows,
    handleEcologyLabelChange,
    ecologyLabelValue,
    currentEcologyMetadataRows,
    updateEcologyLabelStatus,
    syncEcologyMetadataPanel,
    metadataProfileText,
    startAnalysis,
  });
}
