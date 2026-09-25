# syntax=docker/dockerfile:1
# Sentinel node on Chainguard's minimal Python image: non-root (65532), no shell
# or package manager at runtime, and fine with a read-only root filesystem
# (the only writable path is the /var/lib/sentinel volume).
#
# The build context is an UNPACKED, SIGNATURE-VERIFIED air-gap bundle, so the
# image carries the same console, NASA fixtures, sentinel wheel and hash-locked
# dependency set as the tarball (docs/supply-chain.md, "Container"):
#
#   deploy/bundle/verify_signature.sh dist/sentinel-<ver>-<arch>.tar.gz
#   tar -xzf dist/sentinel-<ver>-<arch>.tar.gz -C build/
#   docker build -f deploy/containers/Dockerfile -t sentinel:<ver> build/sentinel-<ver>-<arch>
#   docker run --read-only -v sentinel-var:/var/lib/sentinel -p 8000:8000 sentinel:<ver>
#
# Chainguard's free `latest` tags track the newest CPython (3.14 at these
# digests), while the bundle's wheels are cp312. So the dependency wheels for
# 3.14 come from PyPI during the build, verified against the same lock hashes
# (requirements.txt, --require-hashes, binary wheels only). Both bases are pinned
# by digest; resolved from cgr.dev with the pinned crane (deploy/tools.lock) on
# 2026-09-24. Refresh: `crane digest cgr.dev/chainguard/python:latest{,-dev}`.

FROM cgr.dev/chainguard/python:latest-dev@sha256:0b39915a883dc2dbbe6c43be2ef82a37126409818cb66f5919e84cfa3e394ea5 AS build
# Build stage only: root is needed to write /opt/sentinel (the venv's absolute
# path must match the runtime image). The runtime stage runs as 65532.
# hadolint ignore=DL3002
USER 0:0
WORKDIR /bundle
COPY . .
# The context must still be exactly the signed bundle's per-file manifest:
# every listed file matches, and nothing unlisted is present. The same check
# install.sh runs, shipped in the bundle.
RUN bash verify_contents.sh
RUN python -m venv /opt/sentinel/venv \
 && /opt/sentinel/venv/bin/pip install --no-cache-dir --disable-pip-version-check \
      --require-hashes --only-binary=:all: -r requirements.txt \
 && /opt/sentinel/venv/bin/pip install --no-cache-dir --disable-pip-version-check --no-deps wheels/sentinel-*.whl \
 && cp -r web fixtures LICENSE BUNDLE.json /opt/sentinel/ \
 && mkdir -p /var/lib/sentinel

FROM cgr.dev/chainguard/python:latest@sha256:46e5b974e33be50d512688480df92f0e258ea849a562d9e63b701f8b080ea660
ARG VERSION=0.2.0
ARG REVISION=unknown
LABEL org.opencontainers.image.title="sentinel" \
      org.opencontainers.image.description="DDIL-resilient conjunction assessment decision aid" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}" \
      org.opencontainers.image.base.name="cgr.dev/chainguard/python:latest" \
      org.opencontainers.image.base.digest="sha256:46e5b974e33be50d512688480df92f0e258ea849a562d9e63b701f8b080ea660"
COPY --from=build /opt/sentinel /opt/sentinel
COPY --from=build --chown=65532:65532 /var/lib/sentinel /var/lib/sentinel
ENV PATH=/opt/sentinel/venv/bin:/usr/bin:/bin \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SENTINEL_WEB_DIST=/opt/sentinel/web \
    SENTINEL_FIXTURES=/opt/sentinel/fixtures \
    SENTINEL_VAR=/var/lib/sentinel \
    SENTINEL_DB=/var/lib/sentinel/sentinel.db \
    SENTINEL_MARKING="UNCLASSIFIED // EXERCISE" \
    SENTINEL_EXERCISE=1 \
    SENTINEL_LIBRARY=1 \
    SENTINEL_READ_ONLY=0 \
    SENTINEL_LOG_FORMAT=json
USER 65532:65532
WORKDIR /var/lib/sentinel
VOLUME ["/var/lib/sentinel"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
  CMD ["/opt/sentinel/venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"]
ENTRYPOINT ["/opt/sentinel/venv/bin/sentinel", "serve", "--host", "0.0.0.0", "--port", "8000"]
