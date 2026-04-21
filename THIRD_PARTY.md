# Third-Party Software And Services

`ClusterWeave` orchestrates third-party bioinformatics tools and public data services. Before public release, confirm license compatibility and redistribution rules for any cached assets or bundled reference files.

Core tools referenced by the current workflow:

- antiSMASH
- FunBGCeX
- BRAKER3
- funannotate
- BiG-SCAPE
- clinker
- NPLinker
- FastTree
- Singularity / Apptainer

Reference resources and services referenced by the current workflow:

- MiBIG
- Pfam
- NCBI genome downloads
- GNPS / MassIVE
- Paired Omics Data Platform

Release checklist:

- Pin exact tool versions or container digests
- Record download URLs plus checksums where practical
- Avoid committing third-party caches unless redistribution is explicitly allowed
- Document which modules require network access and which are offline-safe
