# Rendered by prepare.py with the immutable base from sources.lock.json.
FROM @BASE_IMAGE@ AS builder
COPY micromamba /usr/local/bin/micromamba
COPY conda /build/conda
COPY locks /build/locks
ENV MAMBA_ROOT_PREFIX=/build/mamba MAMBA_NO_BANNER=1 SOURCE_DATE_EPOCH=315532800
RUN set -eu; for group in repeat2 native-tools hmmer2 build-tools; do \
      micromamba create --offline --yes --prefix /opt/plantismash/$group --file /build/locks/$group.txt; \
    done
COPY python /build/python
COPY install.py sources.lock.json modifications.json scientific-files.json hmm-index-layout.json /build/
COPY modifications /build/modifications
COPY resources /build/resources
COPY resources.lock.json install_resources.py plantismash_prereqs.py plantismash-profile.json /build/
RUN /opt/plantismash/repeat2/bin/python /build/install.py && /opt/plantismash/repeat2/bin/python /build/install_resources.py

FROM @BASE_IMAGE@
COPY --from=builder /opt/plantismash/repeat2 /opt/plantismash/repeat2
COPY --from=builder /opt/plantismash/native-tools /opt/plantismash/native-tools
COPY --from=builder /opt/plantismash/hmmer2 /opt/plantismash/hmmer2
COPY --from=builder /usr/local/bin/plantismash /usr/local/bin/plantismash
COPY --from=builder /opt/plantismash/provenance /opt/plantismash/provenance
ENV PATH=/opt/plantismash/repeat2/bin:/opt/plantismash/native-tools/bin:/opt/plantismash/hmmer2/bin:/usr/bin:/bin \
    PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
ENTRYPOINT ["/usr/local/bin/plantismash"]
