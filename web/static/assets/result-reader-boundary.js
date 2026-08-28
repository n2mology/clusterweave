export function createResultReaderBoundary(dependencies) {
const {
  state,
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
} = dependencies;

let activeFileTree = null;
let activeFileTreeIndex = new Map();
let activeFileTreeJobId = null;
let figureZoomState = new Map();
let activeFigurePan = null;
let resultObjectUrls = [];
let resultArchiveObjectUrl = '';
let resultArchiveRequestSeq = 0;
let activeArchiveDownload = null;
let archiveDownloadStatus = null;
let archiveDownloadDismissTimer = null;
let resultHelperObjectUrls = [];
let summaryReaderSeq = 0;
let summaryReaderJobId = '';
let activeSummaryView = 'all_bgcs';
let allBgcTableState = null;
let syntenyReaderJobId = '';
let activeSyntenyTaxon = '';
let figureReaderJobId = '';
let activeFigureView = '';

const TOOL_RESULT_RUNTIME_MAX_ACTIVE = 4;

const TOOL_RESULT_RUNTIME_MAX_QUEUE = 64;

const TOOL_RESULT_RUNTIME_MAX_PER_DOCUMENT = 512;

const TOOL_RESULT_RUNTIME_RESOLVE_TIMEOUT_MS = 15000;

const RESULT_PREVIEW_COPY_MAX_BYTES = 1024 * 1024;

const RESULT_PREVIEW_CLIPBOARD_TIMEOUT_MS = 1500;

const RESULT_PREVIEW_EXTERNAL_URL_MAX_LENGTH = 16384;

const RESULT_PREVIEW_NAVIGATOR_SCRIPT = String.raw`
(function () {
  const scriptEl = document.currentScript || document.querySelector('script[data-clusterweave-result-preview]');
  if (!scriptEl || scriptEl.dataset.ready === '1') return;
  scriptEl.dataset.ready = '1';
  const channel = scriptEl.dataset.channel || '';
  const owner = scriptEl.dataset.owner || '';
  const allowBundleLinks = scriptEl.dataset.bundleLinks === '1';
  const pending = new Map();
  const prepared = new WeakMap();
  const actionPending = new Map();
  const maxPending = 64;
  const maxRequests = 512;
  const resolveTimeoutMs = 15000;
  let requestSequence = 0;
  let actionSequence = 0;

  function announce(message, isError) {
    let status = document.querySelector('[data-clusterweave-result-status]');
    if (!status) {
      status = document.createElement('div');
      status.setAttribute('data-clusterweave-result-status', '');
      status.setAttribute('role', 'status');
      status.setAttribute('aria-live', 'polite');
      status.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;max-width:min(520px,calc(100% - 32px));padding:10px 12px;border:1px solid #57534e;border-radius:6px;background:#fff;color:#292524;font:14px/1.4 system-ui,sans-serif;box-shadow:0 4px 18px rgba(0,0,0,.18)';
      (document.body || document.documentElement).appendChild(status);
    }
    status.style.borderColor = isError ? '#b91c1c' : '#57534e';
    status.textContent = String(message || '');
  }

  function safeExternalReference(value) {
    const raw = String(value || '').trim();
    if (!raw || raw.length > 16384) return '';
    try {
      const url = new URL(raw);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return '';
      return url.href;
    } catch (error) {
      return '';
    }
  }

  function relativeReference(element) {
    const value = String(element && element.getAttribute('href') || '').trim();
    if (!value || value.startsWith('#')) return null;
    const external = safeExternalReference(value);
    if (external) return { value: external, external: true, supported: true };
    if (value.startsWith('/') || value.includes('\\')
        || /^(?:[a-z][a-z0-9+.-]*:)?\/\//i.test(value)
        || /^(?:data|blob|mailto|tel|javascript):/i.test(value)) {
      return { value: value, supported: false };
    }
    const path = value.split(/[?#]/, 1)[0];
    return {
      value: value,
      external: false,
      supported: allowBundleLinks && !!path && value.length <= 2048,
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

  function prepareExternalLink(element, value) {
    const external = safeExternalReference(value);
    if (!external || !channel || !owner) {
      disableLocalLink(element);
      return;
    }
    prepared.delete(element);
    element.removeAttribute('href');
    element.removeAttribute('target');
    element.removeAttribute('rel');
    element.removeAttribute('aria-disabled');
    element.removeAttribute('data-clusterweave-result-pending');
    element.removeAttribute('data-clusterweave-result-request');
    element.setAttribute('data-clusterweave-result-external', external);
    if (!element.hasAttribute('role')) element.setAttribute('role', 'link');
    if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '0');
  }

  function prepareLocalLink(element) {
    if (!element
        || element.hasAttribute('data-clusterweave-result-artifact')
        || element.hasAttribute('data-clusterweave-result-fragment')
        || element.getAttribute('aria-disabled') === 'true') return;
    const storedExternal = element.getAttribute('data-clusterweave-result-external') || '';
    if (storedExternal && !element.hasAttribute('href')) {
      prepareExternalLink(element, storedExternal);
      return;
    }
    const reference = relativeReference(element);
    if (!reference) return;
    if (reference.external) {
      prepareExternalLink(element, reference.value);
      return;
    }
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
      download: element.hasAttribute('download'),
      activate: !!activate,
    }, '*');
  }

  function scan(root) {
    const elements = [];
    if (root && root.matches && root.matches('a[href],area[href],[data-clusterweave-result-external]')) elements.push(root);
    if (root && root.querySelectorAll) elements.push.apply(elements, root.querySelectorAll('a[href],area[href],[data-clusterweave-result-external]'));
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

  function requestAction(action, payload, target) {
    if (!channel || !owner || actionSequence >= maxRequests) {
      announce('This result action is unavailable.', true);
      return;
    }
    const request = 'a' + String(++actionSequence);
    const timer = window.setTimeout(function () {
      if (!actionPending.has(request)) return;
      actionPending.delete(request);
      announce('The result action timed out.', true);
    }, resolveTimeoutMs);
    actionPending.set(request, { target: target || null, timer: timer });
    window.parent.postMessage(Object.assign({
      type: 'clusterweave:result-bundle-action',
      channel: channel,
      owner: owner,
      request: request,
      action: action,
    }, payload || {}), '*');
  }

  function activateResolvedArtifact(element, artifact, fragment, mode, grant) {
    if (mode === 'download') {
      requestAction('download-artifact', {
        artifact: artifact,
        grant: grant || '',
      }, element);
      return;
    }
    navigateArtifact(artifact, fragment);
  }

  window.addEventListener('message', function (event) {
    const payload = event && event.data;
    if (event.source !== window.parent || !payload
        || payload.channel !== channel || payload.owner !== owner) return;
    if (payload.type === 'clusterweave:result-bundle-action-result') {
      const actionRequest = String(payload.request || '');
      const actionEntry = actionPending.get(actionRequest);
      if (!actionEntry) return;
      actionPending.delete(actionRequest);
      window.clearTimeout(actionEntry.timer);
      announce(payload.message || (payload.ok ? 'Result action completed.' : 'Result action failed.'), !payload.ok);
      return;
    }
    if (payload.type !== 'clusterweave:result-bundle-resolved') return;
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
    const mode = String(payload.mode || 'navigate');
    const grant = String(payload.grant || '');
    if (!/^[A-Za-z0-9_-]{16,}$/.test(artifact)
        || !['navigate', 'download'].includes(mode)
        || (mode === 'navigate' && !href)) {
      disableLocalLink(element);
      return;
    }
    if (mode === 'navigate') {
      finishPreparedLink(element);
      element.setAttribute('href', href);
    } else {
      prepared.delete(element);
      element.removeAttribute('href');
      element.removeAttribute('aria-busy');
      element.removeAttribute('data-clusterweave-result-pending');
      if (!element.hasAttribute('role')) element.setAttribute('role', 'link');
      if (!element.hasAttribute('tabindex')) element.setAttribute('tabindex', '0');
    }
    element.setAttribute('data-clusterweave-result-artifact', artifact);
    element.setAttribute('data-clusterweave-result-fragment', fragment);
    element.setAttribute('data-clusterweave-result-mode', mode);
    if (grant) element.setAttribute('data-clusterweave-result-grant', grant);
    if (entry.activate) activateResolvedArtifact(element, artifact, fragment, mode, grant);
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
    const mode = target.getAttribute('data-clusterweave-result-mode') || 'navigate';
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
      if (window.viewer && typeof window.viewer.switchToRegion === 'function') {
        window.viewer.switchToRegion(anchor);
      } else {
        try {
          const destination = document.getElementById(anchor) || document.querySelector('[name="' + CSS.escape(anchor) + '"]');
          if (destination && typeof destination.scrollIntoView === 'function') destination.scrollIntoView({ block: 'start' });
        } catch (error) {}
      }
      return;
    }
    event.preventDefault();
    event.stopImmediatePropagation();
    activateResolvedArtifact(
      target,
      artifact,
      fragment,
      mode,
      target.getAttribute('data-clusterweave-result-grant') || '',
    );
  }

  function copyTarget(event) {
    return event.target && event.target.closest
      ? event.target.closest('.clipboard-copy,[data-clusterweave-copy-source]')
      : null;
  }

  function copyTargetText(target) {
    if (!target) return '';
    if (target.hasAttribute('data-seq')) return String(target.getAttribute('data-seq') || '');
    const selector = String(target.getAttribute('data-clusterweave-copy-source') || '');
    if (!selector) return '';
    try {
      return String(document.querySelector(selector)?.textContent || '');
    } catch (error) {
      return '';
    }
  }

  function activateCopy(event, target) {
    event.preventDefault();
    event.stopImmediatePropagation();
    const text = copyTargetText(target);
    if (!text) {
      announce('Select a gene before copying its sequence.', true);
      return;
    }
    requestAction('copy-text', { text: text }, target);
  }

  function activateExternal(event, target) {
    event.preventDefault();
    event.stopImmediatePropagation();
    const href = safeExternalReference(target.getAttribute('data-clusterweave-result-external') || '');
    if (!href) {
      announce('This external result link is unavailable.', true);
      return;
    }
    requestAction('open-external', { href: href }, target);
  }

  function refreshCopyControls() {
    document.querySelectorAll('[data-clusterweave-copy-source]').forEach(function (control) {
      const ready = !!copyTargetText(control);
      control.setAttribute('aria-disabled', ready ? 'false' : 'true');
      if (!ready) control.setAttribute('title', 'Select a gene before copying its sequence.');
      else if (control.getAttribute('title') === 'Select a gene before copying its sequence.') control.removeAttribute('title');
    });
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
    const copy = copyTarget(event);
    if (copy) {
      activateCopy(event, copy);
      return;
    }
    const target = interactiveTarget(event);
    if (!target) return;
    if (target.hasAttribute('data-clusterweave-result-external')) activateExternal(event, target);
    else activateTarget(event, target);
  }, true);
  document.addEventListener('keydown', function (event) {
    if (!event.isTrusted || event.defaultPrevented) return;
    const copy = copyTarget(event);
    if (copy && event.key === 'Enter') {
      activateCopy(event, copy);
      return;
    }
    const target = interactiveTarget(event);
    if (!target) return;
    if (
      target.hasAttribute('data-clusterweave-bigscape-control')
      && ['Enter', ' '].includes(event.key)
    ) {
      event.preventDefault();
      target.click();
      return;
    }
    if (event.key !== 'Enter') return;
    if (target.hasAttribute('data-clusterweave-result-external')) activateExternal(event, target);
    else if (prepared.has(target) || target.hasAttribute('data-clusterweave-result-artifact')) activateTarget(event, target);
  }, true);
  const observer = new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      if (mutation.type === 'attributes') scan(mutation.target);
      else Array.prototype.forEach.call(mutation.addedNodes || [], scan);
    });
    refreshCopyControls();
  });
  observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ['href'],
  });
  scan(document);
  refreshCopyControls();
})();
`;

// Large antiSMASH runs can legitimately emit a regions.js above 16 MiB. Keep
// individual tool assets bounded while retaining the stricter bundle ceiling.
const TOOL_RESULT_PREVIEW_ASSET_MAX_BYTES = 32 * 1024 * 1024;

const TOOL_RESULT_PREVIEW_TOTAL_ASSET_MAX_BYTES = 64 * 1024 * 1024;

const BIGSCAPE_PREVIEW_ASSET_MAX_BYTES = 16 * 1024 * 1024;

const BIGSCAPE_PREVIEW_TOTAL_ASSET_MAX_BYTES = 64 * 1024 * 1024;

const BIGSCAPE_PORTABLE_ASSET_EXTENSIONS = new Set([
  'css',
  'png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'ico',
  'woff', 'woff2', 'ttf', 'otf', 'eot',
]);

const STATIC_RESULT_PREVIEW_CSP = "default-src 'none'; img-src data: blob:; style-src 'unsafe-inline' data: blob:; font-src data: blob:; media-src data: blob:; connect-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'";

const TOOL_RESULT_PREVIEW_CSP = "default-src 'none'; script-src 'unsafe-inline'; img-src data: blob:; style-src 'unsafe-inline' data: blob:; font-src data: blob:; media-src data: blob:; connect-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'";

const TOOL_RESULT_PREVIEW_SANDBOX = 'allow-scripts allow-downloads';

const CLINKER_RESULT_PREVIEW_CSP = "default-src 'none'; script-src 'unsafe-inline'; img-src data: blob:; style-src 'unsafe-inline' data: blob:; font-src data: blob:; media-src data: blob:; connect-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'";

const CLINKER_PREVIEW_SANDBOX = 'allow-scripts allow-downloads';

const BIGSCAPE_RESULT_PREVIEW_CSP = "default-src 'none'; script-src 'unsafe-inline'; img-src data: blob:; style-src 'unsafe-inline' data: blob:; font-src data: blob:; media-src data: blob:; connect-src 'none'; object-src 'none'; frame-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'";

const BIGSCAPE_PREVIEW_SANDBOX = 'allow-scripts allow-downloads';

const BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM = '(1,eval)("this")';

const BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM_COUNT = 2;

const BIGSCAPE_CONTROL_PLACEHOLDER = "href='##'";

const BIGSCAPE_CONTROL_PLACEHOLDER_COUNT = 13;

const BIGSCAPE_SINGLETON_TREE_SIGNATURE = `    var treeDrawer = new PhylogramTreeDrawer();
    treeDrawer.Init(treeData, { svg_id: 'det_fam_tree', height: ((treeData.num_leaves - 1) * 40), width: 400 });
    treeDrawer.draw_scale_bar = false;
    treeDrawer.CalcCoordinates();
    treeDrawer.Draw();`;

const BIGSCAPE_SINGLETON_TREE_REPLACEMENT = `    if (treeData.num_leaves <= 1) {
      var singletonNodeIterator = new NodeIterator(treeData.root);
      var singletonNode = singletonNodeIterator.Begin();
      while (singletonNode != null) {
        if (singletonNode.IsLeaf()) {
          singletonNode.xy['x'] = 400;
          singletonNode.xy['y'] = 20;
          break;
        }
        singletonNode = singletonNodeIterator.Next();
      }
    } else {
      var treeDrawer = new PhylogramTreeDrawer();
      treeDrawer.Init(treeData, { svg_id: 'det_fam_tree', height: ((treeData.num_leaves - 1) * 40), width: 400 });
      treeDrawer.draw_scale_bar = false;
      treeDrawer.CalcCoordinates();
      treeDrawer.Draw();
    }`;

const RESULT_FOLDER_TABS = [
  { key: 'antismash', label: 'ANTISMASH' },
  { key: 'funbgcex', label: 'FUNBGCEX', capability: 'funbgcex' },
  { key: 'bigscape', label: 'BIG-SCAPE' },
  { key: 'synteny', label: 'CLINKER' },
  { key: 'summaries', label: 'SUMMARY' },
  { key: 'figures', label: 'FIGURES' },
];

const BIGSCAPE_VIEWER_DATABASE_NAME = 'clusterweave_viewer.sqlite';

const BIGSCAPE_BROWSER_DATABASE_MAX_BYTES = 64 * 1024 * 1024;

const SQLITE_FORMAT_HEADER = Object.freeze([83, 81, 76, 105, 116, 101, 32, 102, 111, 114, 109, 97, 116, 32, 51, 0]);

const CROSS_KINGDOM_EVIDENCE_FILENAMES = Object.freeze([
  'cross_kingdom_evidence_cards.txt',
  'cross_kingdom_evidence.tsv',
  'cross_kingdom_evidence.json',
  'putative_transfer_evidence_cards.txt',
  'putative_transfer_evidence.tsv',
  'putative_transfer_evidence.json',
]);

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

const FIGURE_FOLDER_VIEWS = Object.freeze([
  { key: 'fungal_families', label: 'FUNGAL FAMILIES', filename: 'fungi_big_scape_multipanel.svg' },
  { key: 'bacterial_families', label: 'BACTERIAL FAMILIES', filename: 'bacteria_big_scape_multipanel.svg' },
  { key: 'fungal_tool_overlap', label: 'FUNGAL TOOL OVERLAP', filename: 'bgc_overlap.svg' },
  { key: 'tree', label: 'TREE', filename: 'clusterweave_taxon_tree.svg' },
]);

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
  return { byKey: state.activeResultArtifactByKey, byId: state.activeResultArtifactById };
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
    state.activeResultArtifactByKey = new Map();
    state.activeResultArtifactById = new Map();
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
    byKey: new Map(state.activeResultArtifactByKey),
    byId: new Map(state.activeResultArtifactById),
  });
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

function toolResultPreviewChannel() {
  if (typeof window.crypto?.getRandomValues !== 'function') {
    throw new Error('A cryptographically secure result-preview channel is unavailable.');
  }
  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
}

function safeResultPreviewExternalUrl(rawUrl) {
  const value = String(rawUrl || '').trim();
  if (!value || value.length > RESULT_PREVIEW_EXTERNAL_URL_MAX_LENGTH) return '';
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return '';
    return url.href;
  } catch (error) {
    return '';
  }
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
    throw new Error('A result preview asset is missing a safe size or exceeds 32 MiB.');
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
  const assetName = resultArtifactName(assetPath, resultContext);
  const descriptor = resultArtifactDescriptor(assetPath, resultContext);
  if (descriptor?.category === 'funbgcex' && /^BGC[0-9]+\.js$/i.test(assetName)) {
    const xCoordinate = 'const x = event.clientX - rect.left;';
    const yCoordinate = 'const y = event.clientY - rect.top;';
    if (source.split(xCoordinate).length !== 2 || source.split(yCoordinate).length !== 2) {
      throw new Error('The FunBGCeX gene selector does not match the sandbox compatibility profile.');
    }
    return source
      .replace(
        xCoordinate,
        'const x = (event.clientX - rect.left) * canvas.width / rect.width;',
      )
      .replace(
        yCoordinate,
        'const y = (event.clientY - rect.top) * canvas.height / rect.height;',
      );
  }
  if (!/^antismash\.js$/i.test(assetName)) return source;
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
  const assetName = resultArtifactName(assetPath);
  if (/^kinetic-v5\.1\.0\.min\.js$/i.test(assetName)) {
    const occurrences = source.split(BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM).length - 1;
    if (occurrences !== BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM_COUNT) {
      throw new Error('The bundled BiG-SCAPE Kinetic runtime does not match the CSP-safe compatibility profile.');
    }
    return source.replaceAll(BIGSCAPE_KINETIC_GLOBAL_EVAL_SHIM, 'globalThis');
  }
  if (!/^bigscape\.js$/i.test(assetName)) return source;
  const controlOccurrences = source.split(BIGSCAPE_CONTROL_PLACEHOLDER).length - 1;
  const singletonTreeOccurrences = source.split(BIGSCAPE_SINGLETON_TREE_SIGNATURE).length - 1;
  if (
    controlOccurrences !== BIGSCAPE_CONTROL_PLACEHOLDER_COUNT
    || singletonTreeOccurrences !== 1
  ) {
    throw new Error('The bundled BiG-SCAPE controls and family-tree renderer do not match the sandbox compatibility profile.');
  }
  return source
    .replaceAll(
      BIGSCAPE_CONTROL_PLACEHOLDER,
      "data-clusterweave-bigscape-control='' role='button' tabindex='0'",
    )
    .replace(BIGSCAPE_SINGLETON_TREE_SIGNATURE, BIGSCAPE_SINGLETON_TREE_REPLACEMENT);
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
  const deferredScripts = new Set();
  const resultContext = options.resultContext || null;
  await Promise.all(scripts.map(async script => {
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
      return;
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
    if (wasDeferred) deferredScripts.add(script);
  }));
  const deferredTarget = doc.body || doc.documentElement;
  scripts
    .filter(script => deferredScripts.has(script))
    .forEach(script => deferredTarget.appendChild(script));
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
  const interactivePreview = allowClinkerInlineScripts || allowBigscapeScripts || allowToolBundleScripts;
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
    } else if (interactivePreview && value.startsWith('#')) {
      el.setAttribute('href', value);
      el.setAttribute('data-clusterweave-result-fragment', value);
    } else if (interactivePreview && resultUrlShouldStayExternal(value)) {
      const externalUrl = safeResultPreviewExternalUrl(value);
      el.removeAttribute('href');
      el.removeAttribute('target');
      el.removeAttribute('rel');
      if (externalUrl) {
        el.removeAttribute('aria-disabled');
        el.setAttribute('data-clusterweave-result-external', externalUrl);
        if (!el.hasAttribute('role')) el.setAttribute('role', 'link');
        if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
      } else {
        el.setAttribute('aria-disabled', 'true');
        el.setAttribute('title', 'This link is outside the generated result bundle.');
      }
    } else if (!resultUrlShouldStayExternal(value)) {
      if (allowToolBundleScripts) {
        el.removeAttribute('target');
        el.removeAttribute('rel');
      } else {
        el.removeAttribute('href');
        el.setAttribute('aria-disabled', 'true');
        el.setAttribute('title', 'This link is outside the generated result bundle.');
      }
    } else if (interactivePreview && !value.startsWith('#')) {
      el.removeAttribute('href');
      el.setAttribute('aria-disabled', 'true');
    }
  }
  const ownerDescriptor = resultArtifactDescriptor(htmlPath, resultContext);
  if (
    allowToolBundleScripts
    && ownerDescriptor?.category === 'funbgcex'
    && /^BGC[0-9]+\.html?$/i.test(resultArtifactName(htmlPath, resultContext))
  ) {
    const canvas = doc.querySelector('#canvas');
    const sequence = doc.querySelector('#aaseq');
    const copyControl = Array.from(doc.querySelectorAll('[onclick]')).find(element => (
      /^copyToClipboard\s*\(\s*\)\s*;?$/i.test(String(element.getAttribute('onclick') || '').trim())
    ));
    if (!canvas || !sequence || !copyControl) {
      throw new Error('The FunBGCeX gene detail page does not match the sandbox compatibility profile.');
    }
    const instruction = doc.createElement('p');
    instruction.id = 'clusterweave-funbgcex-gene-instruction';
    instruction.setAttribute('data-clusterweave-funbgcex-instruction', '');
    instruction.textContent = 'Select a gene arrow to show its information and enable sequence copying.';
    canvas.parentNode?.insertBefore(instruction, canvas);
    copyControl.removeAttribute('onclick');
    copyControl.setAttribute('data-clusterweave-copy-source', '#aaseq');
    copyControl.setAttribute('aria-describedby', instruction.id);
    copyControl.setAttribute('aria-disabled', 'true');
  }
  if (interactivePreview) {
    const navigator = doc.createElement('script');
    navigator.setAttribute('data-clusterweave-result-preview', '');
    navigator.setAttribute('data-channel', String(options.toolPreviewChannel || ''));
    navigator.setAttribute(
      'data-owner',
      String(options.toolPreviewOwner || resultArtifactId(htmlPath, resultContext)),
    );
    navigator.setAttribute('data-bundle-links', allowToolBundleScripts ? '1' : '0');
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

async function copyResultPreviewText(targetWindow, text) {
  if (typeof targetWindow.navigator?.clipboard?.writeText === 'function') {
    let timeout = null;
    try {
      const copied = await Promise.race([
        targetWindow.navigator.clipboard.writeText(text).then(() => true, () => false),
        new Promise(resolve => {
          timeout = targetWindow.setTimeout(() => resolve(false), RESULT_PREVIEW_CLIPBOARD_TIMEOUT_MS);
        }),
      ]);
      if (copied) return true;
    } catch (error) {
    } finally {
      if (timeout) targetWindow.clearTimeout(timeout);
    }
  }
  const textarea = targetWindow.document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', '');
  textarea.style.cssText = 'position:fixed;left:-10000px;top:0;opacity:0';
  targetWindow.document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  let copied = false;
  try {
    copied = targetWindow.document.execCommand('copy') === true;
  } catch (error) {}
  textarea.remove();
  return copied;
}

function installResultPreviewActionRelay(targetWindow, frame, contextProvider, options = {}) {
  let actionCount = 0;
  const sendResult = (context, request, ok, message) => {
    if (!frame.contentWindow) return;
    const payload = {
      type: 'clusterweave:result-bundle-action-result',
      channel: context.channel,
      owner: context.owner,
      request,
      ok: ok === true,
      message: String(message || ''),
    };
    if (typeof options.postToFrame === 'function') {
      options.postToFrame(frame.id, payload);
    } else {
      frame.contentWindow.postMessage(payload, '*');
    }
  };
  const handleAction = async event => {
    const payload = event?.data;
    const context = contextProvider?.() || {};
    if (
      event.source !== frame.contentWindow
      || !payload
      || payload.type !== 'clusterweave:result-bundle-action'
      || payload.channel !== context.channel
      || payload.owner !== context.owner
    ) return;
    const request = String(payload.request || '');
    const action = String(payload.action || '');
    actionCount += 1;
    if (!/^a[1-9][0-9]{0,8}$/.test(request) || actionCount > TOOL_RESULT_RUNTIME_MAX_PER_DOCUMENT) return;
    const activeGesture = targetWindow.navigator?.userActivation?.isActive === true;
    try {
      if (action === 'copy-text') {
        const text = String(payload.text || '');
        if (!activeGesture || !text || new Blob([text]).size > RESULT_PREVIEW_COPY_MAX_BYTES) {
          throw new Error('Sequence copying was blocked by the result security boundary.');
        }
        if (!await copyResultPreviewText(targetWindow, text)) {
          throw new Error('The browser blocked automatic copying; select the sequence and copy it manually.');
        }
        sendResult(context, request, true, 'Sequence copied to the clipboard.');
        return;
      }
      if (action === 'open-external') {
        const href = safeResultPreviewExternalUrl(payload.href);
        if (!activeGesture || !href) {
          throw new Error('The external result link was blocked by the result security boundary.');
        }
        const opened = targetWindow.open(href, '_blank', 'noopener,noreferrer');
        if (!opened) throw new Error('The browser blocked the external result link.');
        try { opened.opener = null; } catch (error) {}
        sendResult(context, request, true, 'Opened the external result link.');
        return;
      }
      if (action === 'download-artifact' && typeof options.downloadArtifact === 'function') {
        const artifact = String(payload.artifact || '');
        const grant = String(payload.grant || '');
        const granted = typeof options.consumeDownloadGrant === 'function'
          && options.consumeDownloadGrant(grant, artifact) === true;
        if (!activeGesture && !granted) {
          throw new Error('The result download requires a new user action.');
        }
        await options.downloadArtifact(artifact, context);
        sendResult(context, request, true, 'Result file download started.');
        return;
      }
      throw new Error('This result action is not allowed.');
    } catch (error) {
      sendResult(
        context,
        request,
        false,
        error instanceof Error ? error.message : 'The result action failed.',
      );
    }
  };
  targetWindow.addEventListener('message', handleAction);
  return () => targetWindow.removeEventListener('message', handleAction);
}

function renderSandboxedClinkerPreview(targetWindow, relPath, htmlText, channel = '', owner = '') {
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
<script>(function(){
  window.CLUSTERWEAVE_RESULT_ACTION_POST = function(frameId, payload) {
    const selectedFrame = document.getElementById(String(frameId || ''));
    if (selectedFrame && selectedFrame.contentWindow) selectedFrame.contentWindow.postMessage(payload, '*');
  };
  window.addEventListener('pagehide', function() {
    window.CLUSTERWEAVE_RESULT_ACTION_POST = null;
  }, { once: true });
})();<\/script>
</head><body></body></html>`);
  doc.close();
  const frame = doc.createElement('iframe');
  frame.id = 'clusterweave-clinker-preview';
  frame.setAttribute('sandbox', CLINKER_PREVIEW_SANDBOX);
  frame.setAttribute('referrerpolicy', 'no-referrer');
  frame.setAttribute('title', title);
  frame.srcdoc = htmlText;
  doc.body.appendChild(frame);
  const postToFrame = targetWindow.CLUSTERWEAVE_RESULT_ACTION_POST;
  const cleanupActions = channel && owner
    ? installResultPreviewActionRelay(
      targetWindow,
      frame,
      () => ({ channel, owner }),
      { postToFrame },
    )
    : () => {};
  if (channel && owner) targetWindow.addEventListener('pagehide', cleanupActions, { once: true });
  return frame;
}

function renderSandboxedBigscapePreview(targetWindow, relPath, htmlText, databaseBuffer, channel, owner = '') {
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
  window.CLUSTERWEAVE_RESULT_ACTION_POST = function(frameId, payload) {
    const selectedFrame = document.getElementById(String(frameId || ''));
    if (selectedFrame && selectedFrame.contentWindow) selectedFrame.contentWindow.postMessage(payload, '*');
  };
  window.addEventListener('pagehide', function() {
    window.CLUSTERWEAVE_RESULT_ACTION_POST = null;
  }, { once: true });
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
  const postToFrame = targetWindow.CLUSTERWEAVE_RESULT_ACTION_POST;
  const cleanupActions = owner
    ? installResultPreviewActionRelay(
      targetWindow,
      frame,
      () => ({ channel, owner }),
      { postToFrame },
    )
    : () => {};
  if (owner) targetWindow.addEventListener('pagehide', cleanupActions, { once: true });
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
    state.downloadGrants.clear();
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
      downloadGrants: new Map(),
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
      mode: 'navigate',
      grant: '',
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
      const navigable = descriptor?.kind === 'html' || descriptor?.kind === 'image';
      const mode = task.download === true || !navigable ? 'download' : 'navigate';
      const allowedKind = mode === 'navigate' ? navigable : descriptor?.downloadable === true;
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
      const grant = mode === 'download' && task.activationGranted
        ? task.request
        : '';
      if (grant) state.downloadGrants.set(grant, descriptor.id);
      sendResolved(task.source, state, task.request, {
        artifact: descriptor.id,
        href: mode === 'navigate'
          ? `${resultHref(jobId, resolved.key, { resultContext })}${fragment}`
          : '',
        fragment,
        mode,
        grant,
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
      download: event.data.download === true,
      activationGranted: event.data.activate === true
        && targetWindow.navigator?.userActivation?.isActive === true,
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

  const cleanupActions = installResultPreviewActionRelay(
    targetWindow,
    frame,
    () => ({
      channel: String(runtimeState?.channel || ''),
      owner: String(runtimeState?.owner || ''),
    }),
    {
      postToFrame,
      consumeDownloadGrant(grant, artifact) {
        const state = runtimeState;
        if (!state || state.closed || !grant) return false;
        const expectedArtifact = state.downloadGrants.get(grant) || '';
        state.downloadGrants.delete(grant);
        return expectedArtifact === artifact;
      },
      async downloadArtifact(artifact, context) {
        const state = runtimeState;
        if (
          !state
          || state.closed
          || context.channel !== state.channel
          || context.owner !== state.owner
        ) throw new Error('The result download context is no longer active.');
        const descriptor = resultArtifactDescriptor(artifact, resultContext);
        const targetPath = artifactPresentationKey(descriptor);
        const currentDescriptor = resultArtifactDescriptor(currentPath, resultContext);
        if (
          !targetPath
          || descriptor?.downloadable !== true
          || !currentDescriptor?.bundle_id
          || descriptor?.bundle_id !== currentDescriptor.bundle_id
          || descriptor?.category !== currentDescriptor.category
        ) throw new Error('The requested file is outside the signed result bundle.');
        const response = await resultFetch(jobId, targetPath, { resultContext });
        if (!response.ok) throw new Error('The requested result file is unavailable.');
        const blob = await response.blob();
        if (targetWindow.closed) throw new Error('The result preview was closed before the download completed.');
        const url = targetWindow.URL.createObjectURL(blob);
        const link = targetWindow.document.createElement('a');
        link.href = url;
        link.download = resultArtifactName(targetPath, resultContext) || 'clusterweave-result';
        targetWindow.document.body.appendChild(link);
        link.click();
        link.remove();
        targetWindow.setTimeout(() => targetWindow.URL.revokeObjectURL(url), 30000);
      },
    },
  );

  targetWindow.addEventListener('message', resolveRuntimeReference);
  targetWindow.addEventListener('message', navigate);
  targetWindow.addEventListener('pagehide', () => {
    cleanupActions();
    targetWindow.removeEventListener('message', resolveRuntimeReference);
    targetWindow.removeEventListener('message', navigate);
    closeRuntimeState(runtimeState);
    if (frameDocumentUrl) targetWindow.URL.revokeObjectURL(frameDocumentUrl);
  }, { once: true });
  doc.body.appendChild(frame);
  setFrameHtml(htmlText, '', relPath, channel);
  return frame;
}

function stageHtmlResultPreviewWindow(targetWindow, relPath) {
  const title = fileNameFromPath(relPath) || 'Result preview';
  const loadingHtml = `<!doctype html>
<html><head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; img-src data: blob:; style-src 'unsafe-inline' data: blob:; font-src data: blob:; media-src data: blob:; frame-src 'self' blob:; child-src 'self' blob:; connect-src 'none'; object-src 'none'; worker-src 'none'; form-action 'none'; base-uri 'none'">
<meta name="referrer" content="no-referrer">
<title>${escapeHtml(title)}</title>
<style>html,body{height:100%;margin:0;background:#fff;color:#292524;font:14px/1.5 system-ui,sans-serif}body{display:grid;place-items:center}</style>
</head><body>Loading preview...</body></html>`;
  const previewUrl = targetWindow.URL.createObjectURL(new targetWindow.Blob(
    [loadingHtml],
    { type: 'text/html;charset=utf-8' },
  ));
  resultHelperObjectUrls.push(previewUrl);
  return new Promise((resolve, reject) => {
    let settled = false;
    let timeout = null;
    const finish = () => {
      if (settled) return;
      settled = true;
      if (timeout) window.clearTimeout(timeout);
      resolve();
    };
    targetWindow.addEventListener('load', finish, { once: true });
    timeout = window.setTimeout(finish, 2000);
    try {
      targetWindow.location.replace(previewUrl);
    } catch (error) {
      if (timeout) window.clearTimeout(timeout);
      settled = true;
      reject(error);
    }
  });
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
    if (targetWindow.closed) return false;
    await stageHtmlResultPreviewWindow(targetWindow, relPath);
    if (targetWindow.closed) return false;
    if (isExactPublicClinkerPanelHtml(relPath)) {
      const channel = toolResultPreviewChannel();
      const owner = resultArtifactId(relPath, resultContext);
      const rewrittenHtml = await rewriteHtmlResultAssets(htmlText, jobId, relPath, {
        allowClinkerInlineScripts: true,
        toolPreviewChannel: channel,
        toolPreviewOwner: owner,
        resultContext,
      });
      renderSandboxedClinkerPreview(targetWindow, relPath, rewrittenHtml, channel, owner);
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
    const popupWasClosed = targetWindow.closed;
    if (ownsWindow && !popupWasClosed) targetWindow.close();
    if (!popupWasClosed) alert(err.message || String(err));
  }
  return false;
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
    return state.activeJobMeta?.bigscape_viewer_available === true;
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
  const source = Array.isArray(state.activeJobMeta?.genome_progress)
    ? state.activeJobMeta.genome_progress
    : Array.isArray(state.activeJobMeta?.genomeProgress)
      ? state.activeJobMeta.genomeProgress
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

function toolHtmlViewLabel(path) {
  const filename = resultArtifactName(path).toLowerCase();
  if (filename === 'allbgcs.html') return 'All BGCs';
  if (filename === 'results.html') return 'Results';
  if (filename === 'index.html') return 'Index';
  return readableArtifactLabel(resultArtifactName(path), 'HTML view').replace(/\s+HTML?$/i, '');
}

function uniqueToolHtmlArtifacts(files, toolKey) {
  const predicate = toolKey === 'antismash' ? isAntiSmashHtmlArtifact : isFunbgcexHtmlArtifact;
  let items = (files || [])
    .filter(predicate)
    .sort((a, b) => toolHtmlSortKey(a).localeCompare(toolHtmlSortKey(b)))
    .map(path => ({ label: toolGenomeLabel(path, toolKey), path }));
  if (toolKey === 'funbgcex') {
    const canonicalByBundle = new Map();
    items.forEach(item => {
      const descriptor = resultArtifactDescriptor(item.path);
      const bundleKey = String(
        descriptor?.bundle_id
        || descriptor?.pair_id
        || `legacy:${item.label}`,
      );
      const existing = canonicalByBundle.get(bundleKey);
      const filename = resultArtifactName(item.path).toLowerCase();
      const priority = filename === 'results.html' ? 0 : filename === 'allbgcs.html' ? 1 : 2;
      if (!existing || priority < existing.priority) {
        canonicalByBundle.set(bundleKey, { ...item, priority });
      }
    });
    items = Array.from(canonicalByBundle.values()).map(({ priority, ...item }) => item);
  }
  const labelCounts = new Map();
  items.forEach(item => {
    labelCounts.set(item.label, (labelCounts.get(item.label) || 0) + 1);
  });
  return items
    .map(item => ({
      ...item,
      label: labelCounts.get(item.label) > 1
        ? `${item.label} · ${toolHtmlViewLabel(item.path)}`
        : item.label,
    }))
    .sort((a, b) => a.label.localeCompare(b.label));
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
  const bigscapeViewerDatabase = selectedPair && state.activeJobMeta?.bigscape_viewer_available === true
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

function resultArtifacts(files = state.activeResultFiles) {
  state.activeResultArtifacts = buildResultArtifacts(files);
  return state.activeResultArtifacts;
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

function resultLollipopItems(artifacts = state.activeResultArtifacts || buildResultArtifacts(state.activeResultFiles), counts = null) {
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
  const totalFiles = Number((counts && counts.downloads) || state.activeResultFiles.length || 0);
  if (totalFiles) {
    items.push({ key: 'downloads', count: totalFiles, unit: 'file', label: resultCategoryLabel('downloads'), copy: 'Full manifest and package downloads.', icon: resultCategoryIcon('downloads') });
  }
  return items;
}

function resultCategoryItems(counts) {
  return resultLollipopItems(state.activeResultArtifacts || buildResultArtifacts(state.activeResultFiles), counts).filter(item => resultCategoryAvailable(item.key, counts));
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
  const selected = state.resultFocusMode === 'focused' && item.key === state.activeResultCategory;
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
  const loaded = !!state.activeJobMeta;
  const files = fileCount === null ? Number(panel.dataset.fileCount || 0) : Number(fileCount || 0);
  const shouldShowReader = loaded && state.resultDashboardOpen;
  const board = document.getElementById('result-dashboard-section');
  panel.classList.remove('hidden');
  if (board) board.classList.toggle('hidden', !shouldShowReader);
  document.querySelectorAll('.result-dashboard-surface').forEach(el => {
    if (el.id === 'result-dashboard-section') return;
    el.classList.toggle('hidden', !shouldShowReader);
  });
  setStatusBadge(document.getElementById('result-flow-status'), status || panel.dataset.status || '', state.activeJobMeta);
  updateArchiveButton();
}

function renderResultBubblePanel(files, status) {
  const panel = document.getElementById('result-bubble-panel');
  if (!panel) return;
  const indexedFiles = (files || []).map(normalizedResultPath).filter(Boolean);
  state.activeResultPackageFileCount = indexedFiles.length;
  state.activeResultFiles = indexedFiles.filter(path => !isPackageOnlyResultArtifact(path));
  document.body.dataset.resultsAvailable = (state.activeResultFiles.length || state.activeResultPackageFileCount) ? 'true' : 'false';
  const artifacts = resultArtifacts(state.activeResultFiles);
  const counts = resultCategoryCounts(state.activeResultFiles);
  const folderItems = resultFolderTabItems(counts);
  const availableItems = resultLollipopItems(artifacts, counts)
    .filter(item => resultFolderTabs(counts).some(tab => resultCategoryKey(tab.key) === item.key));
  if (state.resultFocusMode === 'focused' && !resultCategoryAvailable(state.activeResultCategory, counts)) {
    setResultFocusMode('overview');
    state.activeResultCategory = firstAvailableResultCategory(counts);
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
  const sameRun = inFlight && activeArchiveDownload.jobId === state.activeJobId;
  const percent = inFlight && activeArchiveDownload.total > 0
    ? Math.min(100, Math.floor((activeArchiveDownload.received / activeArchiveDownload.total) * 100))
    : 0;
  btn.disabled = !state.activeJobId || state.activeResultPackageFileCount < 1 || inFlight;
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
  if (!state.activeJobId || activeArchiveDownload) return false;
  const requestJobId = state.activeJobId;
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

function setResultReaderSurface(surface) {
  const selected = surface === 'viz' ? 'viz' : 'files';
  const viz = document.getElementById('viz-container');
  const files = document.getElementById('files-container');
  if (viz) viz.hidden = selected !== 'viz';
  if (files) files.hidden = selected !== 'files';
}

function renderResultFileSurface(jobId, files) {
  if (state.resultFocusMode === 'focused') {
    renderFocusedResultCategory(state.activeResultCategory);
    return;
  }
  setResultReaderSurface('files');
  renderFileTable(jobId, files);
}

function renderFocusedResultCategory(category) {
  const key = resultCategoryKey(category);
  if (!resultCategoryApplicable(key)) {
    setResultFocusMode('overview');
    renderResultBubblePanel(state.activeResultFiles, state.activeJobMeta?.status || '');
    return;
  }
  const artifacts = resultArtifacts(state.activeResultFiles);
  if (key === 'figures') {
    setResultReaderSurface('viz');
    if (state.activeJobId) renderViz(state.activeJobId, state.activeResultFiles);
    return;
  }
  setResultReaderSurface('files');
  if (!state.activeJobId) return;
  if (key === 'antismash') {
    renderToolHtmlReader(state.activeJobId, 'antismash', artifacts.antismash);
    return;
  }
  if (key === 'funbgcex') {
    renderToolHtmlReader(state.activeJobId, 'funbgcex', artifacts.funbgcex);
    return;
  }
  if (key === 'bigscape') {
    renderBigscapeReader(state.activeJobId, artifacts.bigscape);
    return;
  }
  if (key === 'summaries') {
    renderSummaryReader(state.activeJobId, artifacts.summaries);
    return;
  }
  if (key === 'synteny') {
    renderSyntenyReader(state.activeJobId, artifacts.synteny);
    return;
  }
  renderFileTable(state.activeJobId, state.activeResultFiles, { category: key });
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
  const groups = syntenyTaxonGroups(resultArtifacts(state.activeResultFiles).synteny);
  if (!selected || !groups.has(selected)) return;
  activeSyntenyTaxon = selected;
  renderSyntenyReader(state.activeJobId, resultArtifacts(state.activeResultFiles).synteny);
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
    if (previewWindow.closed) return false;
    await stageHtmlResultPreviewWindow(previewWindow, htmlPath);
    if (previewWindow.closed) return false;
    const dbName = fileNameFromPath(databasePath);
    const channel = bigscapePreviewChannel();
    const owner = resultArtifactId(htmlPath);
    const contractedHtml = injectBigscapeDatabaseContract(htmlText, dbName, databasePath, channel);
    const rewrittenHtml = await rewriteHtmlResultAssets(contractedHtml, jobId, htmlPath, {
      allowBigscapeScripts: true,
      toolPreviewChannel: channel,
      toolPreviewOwner: owner,
    });
    renderSandboxedBigscapePreview(previewWindow, htmlPath, rewrittenHtml, databaseBuffer, channel, owner);
  } catch (err) {
    const message = err && err.message ? err.message : 'BiG-SCAPE result could not be opened.';
    if (!previewWindow.closed) {
      previewWindow.document.body.innerHTML = `<pre style="white-space:pre-wrap;font:14px system-ui,sans-serif;color:#111">${escapeHtml(message)}</pre>`;
    }
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
  const summaries = resultArtifacts(state.activeResultFiles).summaries;
  if (!summaryViewDefinitions(summaries).some(item => item.key === view)) return;
  activeSummaryView = view;
  renderSummaryReader(state.activeJobId, summaries);
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
  if (!state.activeJobId || !path) return;
  if (allBgcTableState?.path === path) { renderAllBgcTable(); return; }
  const seq = ++summaryReaderSeq;
  const doc = document.getElementById('summary-reader-doc');
  if (doc) doc.innerHTML = '<div class="viz-placeholder text-sm">Loading all BGC records...</div>';
  try {
    const resp = await resultFetch(state.activeJobId, path);
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
  if (!state.activeJobId || !path) return;
  const seq = ++summaryReaderSeq;
  const doc = document.getElementById('summary-reader-doc');
  if (doc) doc.innerHTML = '<div class="viz-placeholder text-sm">Loading summary document...</div>';
  try {
    const resp = await resultFetch(state.activeJobId, path);
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

function normalizedResultPath(path) {
  return String(path || '').replace(/\\/g, '/');
}

function fileNameFromPath(path) {
  const parts = normalizedResultPath(path).split('/');
  return parts[parts.length - 1] || normalizedResultPath(path);
}

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
  const category = resultCategoryKey(state.activeResultCategory);
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

function usesScrollableTreeZoom(wrap, preview = null) {
  const figure = preview || wrap?.querySelector('.figure-preview');
  return !!wrap?.classList.contains('is-taxon-tree') && !!figure?.matches('svg');
}

function applySvgFigureZoom(wrap, svg, state) {
  const base = wrap._svgBaseViewBox || readSvgBaseViewBox(svg);
  wrap._svgBaseViewBox = base;
  if (usesScrollableTreeZoom(wrap, svg)) {
    svg.setAttribute('viewBox', `${base.x} ${base.y} ${base.width} ${base.height}`);
    svg.style.width = `${Math.max(1, state.scale || 1) * 100}%`;
    svg.style.maxWidth = state.scale > 1.01 ? 'none' : '100%';
    svg.style.transform = '';
    return;
  }
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
  const preview = wrap.querySelector('.figure-preview');
  const scrollableTree = usesScrollableTreeZoom(wrap, preview);
  if (Math.abs(scale - 1) < 0.01) {
    state.scale = 1;
    state.x = 0;
    state.y = 0;
    applyFigureZoom(wrap);
    if (scrollableTree) {
      wrap.scrollLeft = 0;
      wrap.scrollTop = 0;
    }
    return;
  }
  const previous = state.scale || 1;
  const ratio = scale / previous;
  if (scrollableTree) {
    const anchorX = originX === null ? wrap.clientWidth / 2 : originX;
    const anchorY = originY === null ? wrap.clientHeight / 2 : originY;
    const contentX = wrap.scrollLeft + anchorX;
    const contentY = wrap.scrollTop + anchorY;
    state.scale = scale;
    applyFigureZoom(wrap);
    wrap.scrollLeft = contentX * ratio - anchorX;
    wrap.scrollTop = contentY * ratio - anchorY;
    state.x = wrap.scrollLeft;
    state.y = wrap.scrollTop;
    return;
  }
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
  const scrollableTree = usesScrollableTreeZoom(wrap);
  activeFigurePan = {
    wrap,
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    originX: state.x,
    originY: state.y,
    scrollableTree,
    originScrollLeft: wrap.scrollLeft,
    originScrollTop: wrap.scrollTop,
  };
  wrap.classList.add('is-panning');
  wrap.setPointerCapture?.(event.pointerId);
}

function handleFigurePointerMove(event, wrap) {
  if (!activeFigurePan || activeFigurePan.wrap !== wrap || activeFigurePan.pointerId !== event.pointerId) return;
  const state = figureZoomRecord(wrap);
  if (activeFigurePan.scrollableTree) {
    wrap.scrollLeft = activeFigurePan.originScrollLeft - (event.clientX - activeFigurePan.startX);
    wrap.scrollTop = activeFigurePan.originScrollTop - (event.clientY - activeFigurePan.startY);
    state.x = wrap.scrollLeft;
    state.y = wrap.scrollTop;
    return;
  }
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
  if (usesScrollableTreeZoom(wrap)) {
    wrap.scrollLeft = 0;
    wrap.scrollTop = 0;
  }
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
    if (usesScrollableTreeZoom(wrap)) {
      wrap.scrollLeft = 0;
      wrap.scrollTop = 0;
    }
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

function figureFolderDefinitions(files) {
  return FIGURE_FOLDER_VIEWS.map(folder => ({
    ...folder,
    path: (files || []).find(path => fileNameFromPath(path).toLowerCase() === folder.filename) || '',
  })).filter(folder => folder.path);
}

function switchFigureView(view) {
  const folders = figureFolderDefinitions(state.activeResultFiles);
  if (!folders.some(folder => folder.key === view)) return;
  activeFigureView = view;
  if (state.activeJobId) renderViz(state.activeJobId, state.activeResultFiles);
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
  state.activeResultFiles = (files || []).map(normalizedResultPath).filter(Boolean)
    .filter(path => !isPackageOnlyResultArtifact(path));
  const category = resultCategoryKey(options.category || state.activeResultCategory || 'downloads');
  const visibleFiles = resultFilesForCategory(category, state.activeResultFiles);
  const summary = renderResultCategorySummary(category, visibleFiles.length, state.activeResultFiles.length);
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

return Object.freeze({
  artifactCategoryFromDescriptor,
  safeArtifactFilename,
  artifactPresentationKey,
  resultArtifactMaps,
  installResultArtifactDescriptor,
  installResultArtifactDescriptors,
  resultArtifactDescriptor,
  resultArtifactId,
  resultArtifactName,
  createResultArtifactContext,
  inlineResultMime,
  toolResultPreviewChannel,
  resultUrlShouldStayExternal,
  resultRelativeAssetPath,
  resultArtifactFamilyRoot,
  resultArtifactFamilyAssetPath,
  isToolResultBundleHtml,
  splitResultAssetUrl,
  resultAssetHashSuffix,
  bigscapeHtmlContentRoot,
  bigscapeHtmlContentAssetPath,
  bigscapePortableAssetPathAllowed,
  assertBigscapeAssetDeclaredSize,
  assertBigscapeAssetActualSize,
  assertToolResultAssetSize,
  isExactPublicClinkerPanelHtml,
  injectResultPreviewNavigator,
  resultBlobDataUrl,
  resultAssetObjectUrl,
  stripToolResultCssImports,
  rewriteCssResultUrls,
  isClassicResultScript,
  rewriteToolResultScriptForSandbox,
  rewriteBigscapeScriptForSandbox,
  inlineBigscapeResultScripts,
  inlineToolResultScripts,
  rewriteHtmlResultAssets,
  buildHtmlResultObjectUrl,
  renderSandboxedClinkerPreview,
  renderSandboxedBigscapePreview,
  renderSandboxedToolResultPreview,
  openHtmlResultWithAssets,
  handleResultLinkClick,
  resultCategoryKey,
  resultFolderTabs,
  resultPathExt,
  isHtmlAsset,
  isDataResultsZip,
  isAntiSmashArtifact,
  isAntiSmashHtmlArtifact,
  isFunbgcexArtifact,
  isFunbgcexHtmlArtifact,
  isBigscapeArtifact,
  isBigscapeHtmlArtifact,
  isBigscapeDatabaseArtifact,
  isBigscapeViewerDatabaseArtifact,
  isSummaryArtifact,
  isAtlasShortlistArtifact,
  summaryReaderArtifactKind,
  isSummaryReaderArtifact,
  preferredSummaryViewFile,
  crossKingdomEvidenceArtifact,
  isPackageOnlyResultArtifact,
  isSyntenyArtifact,
  isPrimaryResultCategory,
  resultCategoryMatches,
  resultPathParts,
  toolSegmentIndex,
  readableArtifactLabel,
  readableGenomeArtifactLabel,
  titleCaseArtifactLabel,
  fileStemFromPath,
  summaryArtifactLabel,
  syntenyGcfQualifier,
  syntenyArtifactLabel,
  activeGenomeArtifactLabel,
  artifactMetaLabel,
  toolGenomeLabel,
  toolHtmlSortKey,
  uniqueToolHtmlArtifacts,
  bigscapeHtmlSortKey,
  bigscapeExpectedHtmlPathForDatabase,
  bigscapeExpectedViewerPathForDatabase,
  chooseBigscapeDatabase,
  summarySortKey,
  buildResultArtifacts,
  resultArtifacts,
  resultCategoryCounts,
  resultCategoryAvailable,
  firstAvailableResultCategory,
  defaultFocusedResultCategory,
  resultFilesForCategory,
  resultCategoryLabel,
  resultCategoryCopy,
  resultCategoryIcon,
  resultItemCountLabel,
  resultOverviewMetricItems,
  renderResultMetricItem,
  resultLollipopItems,
  resultCategoryItems,
  renderResultOverviewPanel,
  resultFolderTabUnit,
  resultFolderTabCountLabel,
  resultFolderTabItems,
  renderResultFolderTab,
  updateResultDashboardVisibility,
  renderResultBubblePanel,
  updateArchiveButton,
  archiveDownloadDetail,
  renderArchiveDownloadStatus,
  setArchiveDownloadStatus,
  readArchiveResponseBlob,
  downloadResultArchive,
  setResultReaderSurface,
  renderResultFileSurface,
  renderFocusedResultCategory,
  artifactReaderHead,
  resultOpenLink,
  resultDownloadLink,
  renderToolHtmlReader,
  normalizedSyntenyTaxon,
  syntenyArtifactTaxon,
  syntenyArtifactGenome,
  syntenyArtifactTrack,
  syntenyTaxonGroups,
  switchSyntenyTaxon,
  renderSyntenyReader,
  jsonForInlineScript,
  bigscapePreviewChannel,
  validatedBigscapeDatabaseBuffer,
  injectBigscapeDatabaseContract,
  openBigscapeResult,
  renderBigscapeReader,
  summaryViewDefinitions,
  switchSummaryView,
  renderSummaryReader,
  parseDelimitedLine,
  allBgcDisplayValue,
  allBgcFilteredRows,
  allBgcGenomeValues,
  allBgcTableMarkup,
  refreshAllBgcRows,
  updateAllBgcFilter,
  sortAllBgcTable,
  renderAllBgcTable,
  loadAllBgcReaderFile,
  preferredSummaryColumnIndexes,
  summaryMetricValue,
  numericSummaryMetric,
  summaryTitleFromText,
  summaryTopCount,
  summaryCondensedTitle,
  renderMarkdownBody,
  condensedMarkdownBodyText,
  renderSummaryHeading,
  atlasMemberGenomes,
  atlasAnnotationHits,
  atlasTaxonSection,
  atlasSummaryValue,
  renderAtlasSummary,
  renderDelimitedSummary,
  renderMarkdownSummary,
  renderTextSummary,
  loadSummaryReaderFile,
  normalizedResultPath,
  fileNameFromPath,
  approvedPhylogenyArtifact,
  isApprovedPhylogenyArtifact,
  isTaxonTreeSvgAsset,
  isTaxonTreeVisualAsset,
  isTaxonTreeBundleAsset,
  treeDataBundleForFigure,
  isFigureAsset,
  isSvgFigureAsset,
  phylogenyArtifactLabel,
  fileTypeLabel,
  fileRowLabel,
  makeFileTreeNode,
  buildFileTree,
  defaultFolderOpen,
  folderSortKey,
  renderFileRow,
  renderFileRows,
  renderFileFolder,
  renderFileTreeChildren,
  handleFileFolderToggle,
  figureSortKey,
  figureCaption,
  figureZoomKeyFromWrap,
  figureZoomRecord,
  clampNumber,
  readSvgBaseViewBox,
  applySvgFigureZoom,
  applyFigureZoom,
  setFigureZoom,
  zoomFigureAt,
  handleFigureWheel,
  handleFigurePointerDown,
  handleFigurePointerMove,
  handleFigurePointerEnd,
  zoomFigureControl,
  resetFigureZoomControl,
  handleFigureZoomKeydown,
  initializeFigureZoomCards,
  sanitizeInlineSvg,
  preserveInlineSvgAccessibility,
  hydrateSvgFigures,
  figureFolderDefinitions,
  switchFigureView,
  renderFigureFolderTabs,
  renderViz,
  hydrateAuthenticatedFigures,
  renderResultCategorySummary,
  renderFileTable,
});
}
