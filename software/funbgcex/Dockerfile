FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TMPDIR=/var/tmp \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH=/opt/venv/bin:/usr/local/bin:$PATH

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      bash \
      build-essential \
      ca-certificates \
      curl \
      hmmer \
      python3 \
      python3-pip \
      python3-venv \
      unzip \
      wget && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /var/tmp/diamond && \
    cd /var/tmp/diamond && \
    curl -L -o diamond.tar.gz "https://github.com/bbuchfink/diamond/releases/download/v2.1.9/diamond-linux64.tar.gz" && \
    tar -xzf diamond.tar.gz && \
    install -m 0755 diamond /usr/local/bin/diamond && \
    cd / && \
    rm -rf /var/tmp/diamond

RUN python3 -m venv /opt/venv && \
    /opt/venv/bin/python -m pip install --upgrade pip setuptools wheel && \
    /opt/venv/bin/python -m pip install --no-cache-dir funbgcex==1.0.1

RUN printf '%s\n' \
  '#!/usr/bin/env bash' \
  'set -euo pipefail' \
  'export TMPDIR=/var/tmp' \
  'INDIR="$1"' \
  'OUTDIR="${2:-./funbgcex_out}"' \
  'WORKERS="${3:-2}"' \
  'exec funbgcex "${INDIR}" "${OUTDIR}" --workers "${WORKERS}"' \
  > /usr/local/bin/run_funbgcex && \
  chmod +x /usr/local/bin/run_funbgcex

WORKDIR /work
