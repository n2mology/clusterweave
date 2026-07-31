export function createApiResultBoundary({
  currentHref,
  configuredApiBase,
  fetchImpl,
  HeadersImpl,
  adminToken,
  submitToken,
  readTokenForJob,
  accessMode,
  canUseAdminSurfaces,
  publicRunIdForJob,
  resultArtifactId,
  installResultArtifactDescriptor,
  resultArtifactDescriptor,
  resultUrlShouldStayExternal,
  resultAssetHashSuffix,
}) {
  function defaultApiBaseUrl() {
    const url = new URL(currentHref());
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
    const configuredBase = configuredApiBase();
    const base = configuredBase
      ? new URL(configuredBase, currentHref()).toString()
      : defaultApiBaseUrl();
    return new URL(cleanPath, base).toString();
  }

  function privateResultLink(jobId, token, serverUrl = '') {
    if (serverUrl && /#\/?results\//i.test(serverUrl)) return serverUrl;
    return `${defaultApiBaseUrl()}#/results/${encodeURIComponent(jobId)}${token ? `/${encodeURIComponent(token)}` : ''}`;
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
    if (admin) headers.Authorization = `Bearer ${admin}`;
    return headers;
  }

  function mergeAuthHeaders(options = {}, auth = {}) {
    const headers = new HeadersImpl(options.headers || {});
    const tokenHeaders = authHeadersFor(auth.kind || 'none', auth.jobId || null);
    Object.entries(tokenHeaders).forEach(([key, value]) => {
      if (value && !headers.has(key)) headers.set(key, value);
    });
    return { ...options, headers };
  }

  function apiFetch(path, options = {}, auth = {}) {
    return fetchImpl(apiUrl(path), mergeAuthHeaders(options, auth));
  }

  function resultNeedsAuth(jobId) {
    return !!adminToken()
      || (accessMode() === 'public' && !!readTokenForJob(publicRunIdForJob(jobId)));
  }

  function canOpenRichHtmlArtifacts(jobId) {
    return canUseAdminSurfaces() || !!readTokenForJob(publicRunIdForJob(jobId));
  }

  function resultHref(jobId, artifactKey, options = {}) {
    const resultContext = options.resultContext || null;
    const runId = resultContext?.runId || publicRunIdForJob(jobId);
    const artifactId = resultArtifactId(artifactKey, resultContext);
    const base = apiUrl(`api/results/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(artifactId || 'unavailable')}`);
    return options.download ? `${base}/download` : base;
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

  return Object.freeze({
    defaultApiBaseUrl,
    apiUrl,
    privateResultLink,
    authHeadersFor,
    mergeAuthHeaders,
    apiFetch,
    resultNeedsAuth,
    canOpenRichHtmlArtifacts,
    resultHref,
    resultFetch,
    resolveResultArtifact,
    bigscapeViewerFetch,
  });
}
