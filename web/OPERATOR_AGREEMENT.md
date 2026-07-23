# ClusterWeave Hosted Portal Operator Agreement

This agreement is a maintainer and deployment checklist for anyone operating a public or
institution-facing ClusterWeave web portal. It is not legal advice. Operators should ask their
institution, counsel, or technology-transfer office to review the final deployment if the service
will be public, commercial, fee-supported, or used for restricted data.
Project-hosted access is **coming soon**. This agreement describes requirements
for that service and for separately operated institutional services; it is not
an availability announcement.


## Operator Responsibilities

By operating a hosted ClusterWeave portal, the operator agrees to:

- Run ClusterWeave as a portal and workflow wrapper around public/open-access bioinformatics tools,
  not as an official replacement for upstream web services.
- Preserve upstream tool names, source URLs, licenses, and citation guidance in the user-facing UI
  and in any generated reports where practical.
- Avoid implying endorsement, certification, or official reporting by upstream tool maintainers.
- Keep `THIRD_PARTY.md` current when tools, containers, databases, or reference datasets change.
- Keep public submissions bounded by quotas, rate limits, upload limits, retention windows, and
  private result-link access controls.
- Require users to submit only public, releasable, or otherwise authorized data.
- Present ClusterWeave outputs as computational predictions and prioritization context, not
  validated product identities or experimental conclusions.
- Store service secrets in the host secret store or deployment environment, never in source,
  handoff docs, screenshots, browser-visible pages, or support tickets.

## Public Web Runtime Boundary

The hosted web portal must not expose restricted optional annotation runtimes unless the operator
has explicit permission for that deployment model. The current public web runtime disables the
BRAKER/GeneMark path and sends `BRAKER3_ENABLED=0` through the web worker bridge.

For public or shared web deployments:

- Do not expose GeneMark-dependent annotation as a web option.
- Do not pass `BRAKER3_ENABLED=1`, `BRAKER_SIF`, `BRAKER_IMAGE_URI`, `BRAKER_BAM`,
  `BRAKER_PROT_SEQ`, `GENEMARK_PATH`, or `GENEMARK_KEY` through web environment overrides.
- Do not distribute pulled BRAKER/GeneMark containers, SIFs, cached installers, or derived images
  through ClusterWeave without a separate license review.
- Keep restricted optional dependencies disabled even for reviewer/admin web sessions. Local
  command-line users may make their own licensing decisions outside the hosted portal.

Funannotate may be used as a permissively licensed annotation fallback, but operators must not
enable separately licensed optional dependencies such as GeneMark, RepBase, SignalP, or similar
components unless they have rights for the hosted-service context.

## Third-Party Credits

The public UI should state that ClusterWeave depends on public/open-access tools and reference data
made by other teams. Its current credit panels cover the implemented NCBI acquisition/taxonomy path,
fungal and Prodigal-backed bacterial annotation, BGC/GCF and synteny tools, reference datasets, optional
local phylogeny/evidence tools, and rendering dependencies. `THIRD_PARTY.md` records the corresponding
licenses, citations, immutable release pins, and redistribution boundaries; vendored browser-library
license files remain beside their assets under `web/static/vendor/`.

When tools or data sources change, update the UI, `THIRD_PARTY.md`, vendor notices, and this agreement
before launch.

## Metrics And Upstream Stewardship

ClusterWeave should expand access without erasing upstream impact. Operators should:

- Encourage users to cite upstream tools directly.
- Keep versioned provenance for containers and reference data used in each run.
- Consider sharing aggregate, non-identifying usage summaries with upstream maintainers if they
  want evidence of downstream impact.
- Never share user-submitted data, private result links, job IDs, or unpublished results with
  upstream maintainers without user permission.
- Route users to official upstream web services when those services are the better fit, especially
  for small one-off runs or features ClusterWeave does not expose.

## Redistribution Boundary

The source repository can publish ClusterWeave code, docs, build recipes, example accession lists,
and public-safe derived outputs. A binary/container release is a different event. Before shipping
built images, SIFs, database snapshots, or cached reference artifacts, the operator must prepare a
third-party notices bundle with:

- exact source image names, tags, digests, and pull/build dates
- license texts and upstream NOTICE files
- citation guidance
- an SBOM or package manifest for bundled software
- source-code availability notes for copyleft components
- dataset license and attribution records for vendored reference data

## Launch Checklist

Before public-live launch:

- Read `THIRD_PARTY.md`, `docs/DATA_SOURCES.md`, `SECURITY.md`, and `docs/WEB_RUNTIME.md`.
- Confirm the hosted web runtime has no restricted annotation fallback visible or enabled.
- Confirm the reverse proxy enforces upload and rate limits before requests reach the Python app.
- Confirm result links use the final HTTPS origin.
- Confirm public users see third-party credits and citation guidance.
- Confirm the service is invite-only or rate-limited until the operator is comfortable opening
  anonymous submissions.
- Record any upstream-maintainer coordination decision in private operator tracking; do not add private
  contacts, job identifiers, or correspondence to the public source archive.
