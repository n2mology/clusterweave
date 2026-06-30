ARG FUNANNOTATE_BASE_IMAGE=nextgenusfs/funannotate:v1.8.17
FROM ${FUNANNOTATE_BASE_IMAGE}

ARG FUNANNOTATE_DB=/opt/databases
ARG FUNANNOTATE_BUSCO_DBS="ascomycota basidiomycota microsporidia dikarya fungi"

ENV FUNANNOTATE_DB=${FUNANNOTATE_DB}

COPY install_busco_db.py /opt/clusterweave-install-busco-db.py
COPY busco_cache/ /opt/clusterweave-busco-cache/

RUN set -eu; \
    mkdir -p "${FUNANNOTATE_DB}"; \
    install_from_cache() { \
      db="$1"; \
      for tarball in "/opt/clusterweave-busco-cache/${db}.tar.gz" "/opt/clusterweave-busco-cache/${db}_odb9.tar.gz"; do \
        [ -s "${tarball}" ] || continue; \
        root="$(tar -tzf "${tarball}" | awk -F/ 'NR==1 {print $1; exit}')"; \
        [ -n "${root}" ] || return 1; \
        rm -rf "${FUNANNOTATE_DB:?}/${db}" "${FUNANNOTATE_DB}/${root}"; \
        tar -zxf "${tarball}" -C "${FUNANNOTATE_DB}"; \
        if [ "${root}" != "${db}" ]; then mv "${FUNANNOTATE_DB}/${root}" "${FUNANNOTATE_DB}/${db}"; fi; \
        return 0; \
      done; \
      return 1; \
    }; \
    for db in ${FUNANNOTATE_BUSCO_DBS}; do \
      if install_from_cache "${db}"; then \
        echo "Installed ${db} BUSCO DB from local cache"; \
      else \
        attempt=1; \
        until /venv/bin/python /opt/clusterweave-install-busco-db.py \
          --database "${FUNANNOTATE_DB}" \
          --cache-dir /opt/clusterweave-busco-cache \
          --db "${db}"; do \
          if [ "${attempt}" -ge 3 ]; then exit 1; fi; \
          attempt=$((attempt + 1)); \
          sleep 5; \
        done; \
      fi; \
    done; \
    for db in ${FUNANNOTATE_BUSCO_DBS}; do \
      test -d "${FUNANNOTATE_DB}/${db}/hmms"; \
      find "${FUNANNOTATE_DB}/${db}/hmms" -type f -print -quit | grep -q .; \
    done

WORKDIR /work
