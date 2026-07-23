FROM mambaorg/micromamba:2.0.5@sha256:8d0d4cad074afe3ac93b58dce88bd2659153d3fa6de3a6968f501710e8d3c832

ARG MAMBA_DOCKERFILE_ACTIVATE=1

USER root
RUN micromamba install --yes --name base --channel conda-forge --channel bioconda \
      python=3.12.13=hd63d673_0_cpython \
      mafft=7.526=h4bc722e_0 \
      iqtree=2.4.0=h503566f_0 \
      ete4=4.3.0=py312h4c3975b_1 \
      trimal=1.5.0=h9948957_2 \
    && micromamba clean --all --yes

RUN mkdir -p /usr/local/share/clusterweave \
    && micromamba env export --name base --explicit > /usr/local/share/clusterweave/phylogeny-conda-explicit.txt \
    && sha256sum /usr/local/share/clusterweave/phylogeny-conda-explicit.txt > /usr/local/share/clusterweave/phylogeny-conda-explicit.txt.sha256

RUN printf '%s\n' \
      '#!/usr/bin/env sh' \
      'set -eu' \
      'mafft --version 2>&1 | head -n 1' \
      'iqtree2 --version 2>&1 | head -n 1' \
      'trimal --version 2>&1 | sed -n "/trimAl/{p;q;}"' \
      'python -c "import ete4; print(\"ETE 4 \" + getattr(ete4, \"__version__\", \"unknown\"))"' \
      'sed "s#  /usr/local/share/clusterweave/phylogeny-conda-explicit.txt#  conda-explicit-manifest#" /usr/local/share/clusterweave/phylogeny-conda-explicit.txt.sha256' \
      > /usr/local/bin/clusterweave-phylogeny-versions \
    && chmod 0755 /usr/local/bin/clusterweave-phylogeny-versions

COPY software/phylogeny/compare_gene_tree_taxonomy.py /usr/local/bin/clusterweave-compare-gene-tree-taxonomy
RUN chmod 0755 /usr/local/bin/clusterweave-compare-gene-tree-taxonomy

USER $MAMBA_USER
WORKDIR /work
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1

LABEL org.opencontainers.image.title="ClusterWeave optional phylogeny runtime" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.description="Pinned MAFFT 7.526, IQ-TREE 2.4.0, ETE 4.3.0, and trimAl 1.5.0 runtime" \
      org.opencontainers.image.licenses="LicenseRef-Mixed-See-THIRD_PARTY"

ENTRYPOINT ["/usr/local/bin/_entrypoint.sh"]
CMD ["clusterweave-phylogeny-versions"]
