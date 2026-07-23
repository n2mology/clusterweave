# Third-Party Software, Containers, And Data

`ClusterWeave` is BSD-3-Clause for this repository's own source files, including the shell entrypoints,
Python helpers, `software/funbgcex/Dockerfile`, and `software/funbgcex/Singularity.def`. Those files are
workflow glue written for this repo. They do not relicense the third-party software that the workflow
pulls, builds, or bootstraps.

The published source repository currently does not ship pulled containers, SIF files, downloaded
databases, genomes, or full result trees. The current ignore rules exclude `software/**`, `*.sif`,
`*.tar.gz`, `*.hmm`, `data/genomes/**`, and `data/results/**`. That means the public repo is mainly a
launcher and build recipe, not a redistribution bundle for upstream tools.

This file documents what the public repo should disclose, and what additional obligations appear if you
ever redistribute a built image, vendored reference dataset, or pulled SIF. It is a maintainer checklist,
not legal advice.

## Repo-Level Requirements

- Keep the README clear that auto-pulled and auto-built artifacts remain under upstream terms and are not
  covered by the repo BSD-3-Clause license.
- Name the major third-party tools, their upstream homes, their licenses, and where users should cite them.
- Keep runtime acquisition references immutable for archival releases. The release defaults pin
  BRAKER3 v3.0.7.6 by OCI digest and FastTree v2.2.0 by commit plus SHA-256; the
  release profile also disables automatic acquisition of prepopulated artifacts.
- Do not commit or attach pulled containers, SIFs, reference tarballs, or caches unless their
  redistribution terms have been checked for that exact artifact.
- If you publish a binary or container release, include a `THIRD_PARTY_NOTICES/` bundle with:
  exact image digests or source URLs, license texts, NOTICE files where applicable, and a package
  manifest or SBOM for the shipped image.

## Software Referenced By The Current Workflow

### antiSMASH

- Repo reference: `run_annotation_and_detection.sh` pulls `docker://antismash/standalone:8.0.4`.
- Upstream terms: antiSMASH is released under AGPL-3.0-or-later and publishes version-specific citation
  guidance at https://docs.antismash.secondarymetabolites.org/about/ and
  https://github.com/antismash/antismash .
- Requirement for the published repo: list the image source, license, and citation pointer in the README
  and this file. Make clear that the image is pulled from upstream and is not shipped inside this repo.
- If you redistribute the image or a derived SIF: preserve the AGPL notice. If you modify the software or
  redistribute a modified image, make the corresponding source for those modifications available under the
  AGPL as well.

### Prodigal

- Repo reference: bacterial antiSMASH input preparation uses Prodigal gene finding through the pinned
  antiSMASH runtime.
- Upstream terms: Prodigal is GPL-3.0 and publishes source and citation guidance at
  https://github.com/hyattpd/Prodigal .
- Requirement for the published repo: credit Prodigal in the UI and scientific documentation. If a
  binary is redistributed outside the upstream antiSMASH image, preserve its GPL notice and source path.

### FunBGCeX

- Repo reference: `run_annotation_and_detection.sh` can build a repo-local image from
  `software/funbgcex/Singularity.def` or `software/funbgcex/Dockerfile`, and the host fallback installs
  `funbgcex==1.0.1`.
- Upstream terms: FunBGCeX is MIT-licensed upstream and includes citation guidance in its README and Zenodo
  records. See https://github.com/ydmatsd/funbgcex , https://pypi.org/project/funbgcex/ , and
  https://doi.org/10.5281/zenodo.17113445 .
- Requirement for the published repo: identify FunBGCeX as a third-party dependency and identify the local
  Dockerfile and Singularity recipe as ClusterWeave build recipes, not as FunBGCeX source code.
- If you redistribute the built FunBGCeX image: include the MIT license for FunBGCeX plus the notices and
  source pointers for bundled runtime components such as DIAMOND, HMMER, Ubuntu packages, and any other
  software present in the image.

### BRAKER3

- Repo reference: `run_annotation_and_detection.sh` uses
  `docker://teambraker/braker3:v3.0.7.6@sha256:5f8b3c508a9fe1bbc2e9a74dcc013eeed82f91dd5945adca7823514d9c8aecf8`.
- Upstream terms: BRAKER's own source is under the Artistic License 1.0 and its README states that
  publications should cite BRAKER plus the exact tools used in a run. See
  https://github.com/Gaius-Augustus/BRAKER and the upstream license at
  https://raw.githubusercontent.com/Gaius-Augustus/BRAKER/master/LICENSE.TXT .
- Critical separate restriction: BRAKER depends on GeneMark. Georgia Tech's GeneMark download terms for
  academic users are non-exclusive, royalty free, non-transferable, limited to internal research, and
  expressly prohibit transfer, distribution, commercial use, and modification. See
  https://genemark.bme.gatech.edu/license_download.cgi .
- Requirement for the published repo: explicitly state that the BRAKER path is optional and subject to
  separate GeneMark licensing. Do not imply that a pulled BRAKER or GeneMark SIF is covered by the repo
  BSD-3-Clause license.
- If you redistribute the image or a derived SIF: do not mirror it from ClusterWeave without separately
  clearing the rights for included GeneMark components. Preserve the pinned v3.0.7.6 digest, or document
  and revalidate the exact digest selected for a later release.

### funannotate

- Repo reference: `run_annotation_and_detection.sh` pulls `docker://nextgenusfs/funannotate:v1.8.17`.
- Upstream terms: funannotate is BSD-2-Clause and provides citation metadata in its repository and Zenodo
  records. Its README also notes that GeneMark is not included in the Docker image and must be installed
  separately under GeneMark's own terms. See https://github.com/nextgenusfs/funannotate .
- Requirement for the published repo: include the funannotate image reference, license, and citation
  pointer. Note that any later GeneMark-enabled extension of this path inherits the separate GeneMark
  restrictions above.
- If you redistribute the image or a derived SIF: preserve the BSD-2-Clause notice and any bundled
  third-party notices.

### BiG-SCAPE

- Repo reference: `run_bigscape.sh` pulls `docker://ghcr.io/medema-group/big-scape:2.0.0-beta.6`.
- Upstream terms: BiG-SCAPE is AGPL-3.0 and its README provides citation guidance for BiG-SCAPE 2.0 and
  earlier work. See https://github.com/medema-group/BiG-SCAPE and
  https://raw.githubusercontent.com/medema-group/BiG-SCAPE/master/README.md .
- Requirement for the published repo: list the exact image tag currently used and cite the upstream
  project. Prefer a digest-pinned image in any formal release.
- If you redistribute the image or a derived SIF: preserve AGPL notices and make corresponding source
  available for any modifications you distribute.

### clinker

- Repo reference: `run_clinker.sh` pulls
  `docker://quay.io/biocontainers/clinker-py:0.0.32--pyhdfd78af_0`.
- Upstream terms: clinker is MIT-licensed and asks users to cite the Bioinformatics paper in its README.
  See https://github.com/gamcil/clinker and
  https://raw.githubusercontent.com/gamcil/clinker/master/README.md .
- Requirement for the published repo: identify both the underlying tool and the BioContainers image source.
- If you redistribute the image or a derived SIF: preserve the MIT notice and record the upstream image
  provenance so the source package can be reconstructed.

### NPLinker

- Repo reference: `run_nplinker.sh` pulls `docker://python:3.11-slim` and then bootstraps
  `nplinker==2.0.0` into a local virtual environment.
- Upstream terms: NPLinker is Apache-2.0, includes a `NOTICE` file in the upstream repository, and points
  users to its original paper from the README. See https://github.com/NPLinker/nplinker .
- Requirement for the published repo: describe this as an optional environment bootstrap, not a bundled
  redistribution of NPLinker.
- If you redistribute the bootstrapped environment or a container that includes it: include the Apache-2.0
  license and preserve the upstream `NOTICE` file, along with the notices for the base image and installed
  dependencies.

### DIAMOND

- Repo reference: the local FunBGCeX image downloads DIAMOND `v2.1.9` from GitHub releases.
- Upstream terms: DIAMOND is GPL-3.0 and its README includes citation guidance. See
  https://github.com/bbuchfink/diamond and
  https://raw.githubusercontent.com/bbuchfink/diamond/master/LICENSE .
- Requirement for the published repo: disclose that the local FunBGCeX image bundles DIAMOND even though
  the repo itself does not ship the built image.
- If you redistribute the built image or DIAMOND binary: comply with GPL-3.0 obligations for the
  redistributed binary, including preserving license text and a corresponding-source path for the exact
  version you shipped.

### HMMER

- Repo reference: the local FunBGCeX image installs HMMER from Ubuntu packages, and FunBGCeX also lists
  HMMER as a required dependency.
- Upstream terms: the current HMMER upstream `LICENSE` states that HMMER source code is distributed under
  the BSD three-clause license. See https://github.com/EddyRivasLab/hmmer and
  https://raw.githubusercontent.com/EddyRivasLab/hmmer/master/LICENSE .
- Requirement for the published repo: disclose that HMMER is bundled into the locally built FunBGCeX image
  but is not redistributed by the source repo itself.
- If you redistribute the built image: preserve the BSD notice for HMMER and any separate notice required
  by bundled subcomponents such as Easel.

### FastTree

- Repo reference: `run_bigscape.sh` downloads FastTree v2.2.0 from immutable commit
  `29c5e62fbcd93230ee325f9c6a17b81f00e3c72a` at
  `https://raw.githubusercontent.com/morgannprice/fasttree/29c5e62fbcd93230ee325f9c6a17b81f00e3c72a/FastTree` and verifies SHA-256
  `55a9d997813aae2208bd4c2081bfa690e0ecdba2d6c491805d8689415c43e38e`.
- Upstream terms: the current FastTree repository is GPL-3.0 and the official site lists the standard
  citations for FastTree 1 and FastTree 2. See https://github.com/morgannprice/fasttree and
  https://morgannprice.github.io/fasttree/ .
- Requirement for the published repo: disclose the immutable download source, v2.2.0 citation, and
  checksum. Revalidate both commit and checksum before intentionally changing the pinned binary.
- If you redistribute the binary or an image that contains it: preserve GPL-3.0 notice and corresponding
  source access for the exact binary version redistributed.

### Optional Pinned Phylogeny Runtime

- Repo reference: `software/phylogeny/Dockerfile` and `software/phylogeny/Singularity.def` define
  the separately built `clusterweave-phylogeny:1.0.0` runtime. The recipe starts from
  `mambaorg/micromamba:2.0.5` pinned by OCI digest and installs exact conda builds of
  MAFFT `7.526`, IQ-TREE 2 `2.4.0`, ETE 4 `4.3.0`, and trimAl `1.5.0`. The image records
  a checksum of its explicit conda package manifest. The source repository ships recipes only, not the built image,
  SIF, or conda package cache.
- Upstream terms: the MAFFT without-extensions source distribution is BSD-licensed
  (https://mafft.cbrc.jp/alignment/software/); IQ-TREE 2 is GPL-2.0
  (https://github.com/iqtree/iqtree2); ETE 4 is GPL-3.0
  (https://github.com/etetoolkit/ete); trimAl is GPL-3.0
  (https://github.com/inab/trimal); and mamba/micromamba is BSD-3-Clause
  (https://github.com/mamba-org/mamba). Preserve each package's own license metadata because transitive
  conda dependencies may carry additional terms.
- Requirement for the published repo: keep runtime acquisition in the explicit build scripts, never in a
  job. Record the built OCI image ID/repository digest or SIF SHA-256 plus the emitted tool versions and
  explicit conda-manifest checksum in run provenance. Before an archival release, retain the resolved
  package manifest or SBOM alongside the built artifact.
- If you redistribute the built image or SIF: include the GPL license texts and corresponding-source
  pointers for IQ-TREE, ETE, and trimAl; preserve the MAFFT and micromamba BSD notices; include notices for
  all resolved conda/base-image components; and ship the exact package manifest or SBOM used to build it.

### Browser visualization libraries

- Repo reference: the web UI vendors Three.js 0.184.0 and GSAP 3.15.0 under
  `web/static/vendor/`, alongside their upstream license files.
- Requirement for the published repo: keep the pinned versions and bundled license files together, and
  update both when either vendored library changes. These browser assets are source-release inputs, not
  generated runtime caches.

## Reference Data And External Services

### Pfam

- Repo reference: `run_bigscape.sh` downloads `Pfam-A.hmm.gz` from the current Pfam release.
- Upstream terms: Pfam documentation states that Pfam is available under CC0. See
  https://pfam-docs.readthedocs.io/en/latest/pfam.html .
- Requirement for the published repo: cite Pfam scientifically and record the downloaded release version if
  you ever vendor the HMM files. Because CC0 is permissive, redistribution is simpler than for most other
  resources, but provenance still matters.

### MIBiG

- Repo reference: `run_bigscape.sh` downloads `mibig_gbk_<version>.tar.gz` from
  `https://dl.secondarymetabolites.org/mibig`.
- Upstream terms: MIBiG 4.0 is an external reference dataset distributed under CC BY 4.0, with citation
  guidance at https://mibig.secondarymetabolites.org/ and in the MIBiG 4.0 Nucleic Acids Research
  publication, https://doi.org/10.1093/nar/gkae1115.
- Requirement for the published repo: cite MIBiG, record the MIBiG version or snapshot date used in
  provenance, and link users to the official source. If you bundle a MIBiG snapshot in a container or
  release artifact, include the CC BY 4.0 notice, citation, source URL, and snapshot provenance.

### NCBI Genome Downloads

- Repo reference: `prepare_genomes_from_accessions.sh` and related accession workflows.
- Requirement for the published repo: do not commit downloaded genomes. Keep accession lists, provenance,
  and links to official sources instead.

### GNPS, MassIVE, And PODP

- Repo reference: the optional NPLinker workflow can interact with GNPS, MassIVE, and the Paired Omics Data
  Platform.
- Requirement for the published repo: treat these as external services and dataset hosts. Do not bundle
  downloaded project data in this repo unless the project-specific terms permit it.

## Container Release Escalation Points

If this project ever publishes built SIFs, OCI archives, or a Zenodo companion image, the source repo is no
longer enough by itself. At that point you should also ship:

- a machine-readable manifest of each redistributed image, including original source image or build recipe,
  tag, digest, and pull date
- license texts for bundled copyleft and permissive components
- upstream `NOTICE` files where present
- an SBOM or package manifest for distro packages in the image
- a short note that the image is an aggregate distribution containing software under multiple licenses

## Practical Release Policy For This Repo

- Safe to ship in the source repo: ClusterWeave source, docs, original Docker and Singularity recipes,
  accession lists, derived summary tables that do not include protected third-party payloads, and public-safe
  example outputs.
- Do not ship from this repo without a separate review: pulled SIFs, mirrored OCI images, BRAKER or
  GeneMark bundles, vendored reference tarballs, genome sequences, or cached tool databases.
