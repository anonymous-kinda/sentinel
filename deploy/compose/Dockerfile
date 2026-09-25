# syntax=docker/dockerfile:1
# Sentinel node for the Compose stack (deploy/compose/compose.yaml), built
# from this checkout with nothing but Docker:
#
#   docker compose -f deploy/compose/compose.yaml build      (or: make compose-up)
#
# Why not deploy/containers/Dockerfile: that is the release image, and its
# build context is an unpacked, signature-verified air-gap bundle. Making one
# needs Node, uv and a download of every wheel on the host (make bundle), so
# it cannot be the one command a reviewer runs. This file builds the same
# image from source instead, and tests/test_compose_image.py holds the two
# together:
#   - the same Chainguard bases at the same digests;
#   - the dependency set exported from uv.lock exactly as the bundle does, and
#     installed exactly as the release does (--require-hashes, binary only);
#   - a runtime stage identical line for line (non-root 65532, no shell,
#     fine with a read-only root filesystem).
# It adds one thing: an empty /var/lib/sentinel/trust owned by 65532, so the
# stack's trust volume mounted there is writable by the enrolment containers.
# The reference data is the release image's: NASA CARA and the OMM
# element-set snapshot a hub serves (fixtures/omm), copied here from the
# checkout where the release image takes them from the bundle.
#
# The wheel is built against the setuptools the pinned build image ships
# (--no-build-isolation), so nothing unpinned is fetched to build it.

FROM node:22.23.3-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS console
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM cgr.dev/chainguard/python:latest-dev@sha256:0b39915a883dc2dbbe6c43be2ef82a37126409818cb66f5919e84cfa3e394ea5 AS build
# Build stage only: root writes /opt/sentinel (the venv's absolute path must
# match the runtime image). The runtime stage runs as 65532.
# hadolint ignore=DL3002
USER 0:0
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY sentinel/ sentinel/
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt -o requirements.txt \
 && pip wheel --no-cache-dir --disable-pip-version-check --no-deps --no-build-isolation --wheel-dir wheels . \
 && python -m venv /opt/sentinel/venv \
 && /opt/sentinel/venv/bin/pip install --no-cache-dir --disable-pip-version-check \
      --require-hashes --only-binary=:all: -r requirements.txt \
 && /opt/sentinel/venv/bin/pip install --no-cache-dir --disable-pip-version-check --no-deps wheels/sentinel-*.whl \
 && mkdir -p /var/lib/sentinel/trust
COPY fixtures/cara /opt/sentinel/fixtures/cara
COPY fixtures/cara_cases.json /opt/sentinel/fixtures/
COPY fixtures/omm /opt/sentinel/fixtures/omm
COPY LICENSE /opt/sentinel/
COPY --from=console /web/dist /opt/sentinel/web

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
