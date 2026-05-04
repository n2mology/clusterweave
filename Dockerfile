# ─────────────────────────────────────────────────────────────────────────────
# ClusterWeave Docker image
#
# Base: antismash/standalone (includes antiSMASH + all heavy bioinformatics deps)
# Adds: BiG-SCAPE v2, clinker, FastAPI web server, ClusterWeave Python helpers
#
# Build:
#   docker build -t clusterweave-web .
#
# Run (quick test, databases downloaded on first startup):
#   docker run -p 8080:8080 -v cw_databases:/databases -v cw_data:/data clusterweave-web
#
# Or use docker-compose (recommended):
#   docker compose up
# ─────────────────────────────────────────────────────────────────────────────
FROM antismash/standalone:8.0.4

# Switch to root to install extra packages
USER root

# ── System packages ────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gzip \
        hmmer \
    && rm -rf /var/lib/apt/lists/*

# ── Copy ClusterWeave repository ───────────────────────────────────────────
COPY . /clusterweave

# ── Copy web application ───────────────────────────────────────────────────
WORKDIR /app
COPY web/ /app/

RUN chmod +x /app/entrypoint.sh

# ── Data directories (overridable via volumes) ─────────────────────────────
RUN mkdir -p /data/uploads /data/jobs /databases/antismash /databases/pfam

# ── Metadata ───────────────────────────────────────────────────────────────
EXPOSE 8080

ENV DATA_DIR=/data
ENV ANTISMASH_DB_DIR=/databases/antismash
ENV PFAM_DIR=/databases/pfam
ENV PORT=8080

ENTRYPOINT ["/app/entrypoint.sh"]
