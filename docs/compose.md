# Hub and edge in Docker Compose

One command starts a hub and an edge in containers. Each node has its own `nats-server` and console, and the edge's leafnode link to the hub runs through Toxiproxy, which can shape or cut it. This is the topology of the process harness (`harness/cluster.py`, `make demo-local`, `make ddil`), in containers. The only prerequisite is Docker with Compose v2: the sentinel image builds from this checkout.

```
[edge] -- nats(edge) --leaf--> toxiproxy --> nats(hub) -- [hub]
 :8001                                                    :8000
```

CI runs the whole stack on every push and pull request (`.github/workflows/ci.yml`, job `compose-smoke`).

## Before you start: Docker inside WSL

With Docker Desktop on Windows, the `docker` command works inside a WSL distro only once WSL integration is turned on for that distro. Until then, `docker version` in WSL prints "The command 'docker' could not be found in this WSL 2 distro".

1. Open Docker Desktop, then **Settings → Resources → WSL Integration**.
2. Leave **Enable integration with my default WSL distro** on, and switch on your distro (for example Ubuntu) in the list below it.
3. Select **Apply & restart**.
4. In a new WSL shell, check that both commands answer:

```bash
docker version
docker compose version    # Compose v2 (the `docker compose` plugin, not docker-compose v1)
```

On Linux, install Docker Engine and its Compose plugin. On macOS, use Docker Desktop.

## Run the demo

```bash
make compose-up                    # build, start, and return once both nodes are healthy
#   hub   http://127.0.0.1:8000    cloud / operations center
#   edge  http://127.0.0.1:8001    forward node: LINK chip in the top bar
make compose-link PRESET=DENIED    # cut the link; the edge measures DENIED within about 15 s
make compose-link PRESET=LIMITED   # about 8 kbit/s, 600 ms each way
make compose-link PRESET=CONNECTED
make compose-smoke                 # the checks below, on the running stack
make compose-down                  # stop, and delete the volumes (keys, databases, trust file)
```

Without `make`, run `docker compose -f deploy/compose/compose.yaml up --build --wait` to start the stack and `docker compose -f deploy/compose/compose.yaml down --volumes` to remove it. The first build takes a few minutes, because it installs the console's npm packages and the locked Python wheels.

The demo sequence is the one in `harness/demo.py`:

1. CONNECTED: both consoles agree, and every edge event is VERIFIED.
2. DENIED: the edge keeps working. Triage an event and record a decision there, then set a different triage status on the same event at the hub.
3. LIMITED: the Sync tab shows summaries first, then the most urgent record. The two triage edits arrive as a CONFLICT on both sides.
4. CONNECTED: everything converges.

**Why `make compose-link` instead of the LINK chip's buttons.** The edge accepts link presets only from its own loopback address. That guard belongs to the application (`POST /api/demo/link` in `sentinel/api/app.py`). A request from your browser reaches the container through the Docker bridge, so the guard refuses it with HTTP 403, as designed. The chip still shows the link state the edge *measured* and the preset that was applied.

`make compose-link` sends the same request from where an operator on the edge host would send it: inside the edge container's network namespace, through `docker compose exec` (`harness/compose_link.py`). Forwarding browser traffic so it appears to come from loopback was rejected: it would make the application's guard meaningless.

## What runs

| Service | Image | Role |
|---|---|---|
| `hub-nats` | `nats:2.15.0-scratch`, by digest | The hub's bus, plus the leaf listener. Owns the hub's network namespace and publishes the hub console on `127.0.0.1:8000`. |
| `hub` | `sentinel-compose:local`, built here | Hub node (`SENTINEL_ROLE=hub`). Runs the exercise scenario. |
| `toxiproxy` | `ghcr.io/shopify/toxiproxy:2.12.0`, by digest | The link emulator. It is the only container on both networks. |
| `edge-nats` | `nats:2.15.0-scratch`, by digest | The edge's bus, plus one leaf remote that dials Toxiproxy. Publishes the edge console on `127.0.0.1:8001`. |
| `edge` | `sentinel-compose:local` | Edge node (`SENTINEL_ROLE=edge`), with link emulation controls on. |
| `hub-identity`, `edge-identity` | `sentinel-compose:local` | One-shot enrolment: each creates its node's signing key and adds the public key to the shared trust file, then exits. |

- **Each node is a pod.** `sentinel` joins its `nats-server`'s network namespace (`network_mode: service:...`). The rendered NATS configs listen on `127.0.0.1` for clients and monitoring, exactly as on a host. A node's bus is reachable by that node only.
- **One path between the nodes.** The hub pair sits on network `hub-side` and the edge pair on `edge-side`. The edge's leaf remote dials `toxiproxy:17422`, and Toxiproxy forwards to `hub-nats:7422`. No other container is on both networks, so there is no route around the emulator, whatever NATS advertises. The hub's config also sets `no_advertise: true`.
- **Configs from the harness's own code.** `scripts/compose_config.py` renders the files in `deploy/compose/nats/` and `deploy/compose/toxiproxy.json` from `deploy/nats/*.tmpl`, through the functions `harness/cluster.py` uses. `tests/test_compose_config.py` proves two things: the committed files match the script's output, and they differ from the harness's rendering only in listen, monitor and URL addresses. The leaf permissions (`deny_exports` of `unit.>`, `passes.>` and `node.>`) and the four DDIL fixes are therefore the ones every DDIL scenario runs. After editing a template, run `make compose-config`.
- **State and trust.** Each node's keys, database and unit file live in its own named volume (`hub-var`, `edge-var`), mounted at `/var/lib/sentinel`. The edge's volume is never mounted into any hub-side container, because the unit's position rests there (ADR-010). The `trust` volume holds public keys only. The two enrolment containers write it, and the nodes mount it read-only. Without it, the hub would refuse the edge's signed operator data and the two would never converge.
- **Hardening.** Every container runs as `65532:65532` with a read-only root filesystem, `cap_drop: [ALL]` and `no-new-privileges`. Sentinel containers get a private tmpfs at `/tmp`. The enrolment containers have no network at all.

### Images and pins

| Image | Pinned digest (multi-arch index) | Check |
|---|---|---|
| `docker.io/library/nats:2.15.0-scratch` | `sha256:c0d27f3054601a99055aa5ec897b0a55bf1869ae50f454e659acfbbea11d2ab7` | `/nats-server` is byte-identical to the binary in the `deploy/tools.lock` tarball, on x86_64 and aarch64 |
| `ghcr.io/shopify/toxiproxy:2.12.0` | `sha256:9378ed52a28bc50edc1350f936f518f31fa95f0d15917d6eb40b8e376d1a214e` | `/toxiproxy` has the sha256 `deploy/tools.lock` pins, on x86_64 and aarch64 |
| `node:22.23.3-bookworm-slim` (console build stage) | `sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c` | The Node major matches CI's web job |
| `cgr.dev/chainguard/python` (build and runtime) | the release Dockerfile's two digests | Identical to `deploy/containers/Dockerfile` (a test) |

The digests were resolved with the crane pinned in `deploy/tools.lock`, and the binaries were compared like this:

```bash
uv run python scripts/fetch_tools.py --arch x86_64 crane nats-server toxiproxy
.tools/x86_64/crane digest docker.io/library/nats:2.15.0-scratch
.tools/x86_64/crane digest ghcr.io/shopify/toxiproxy:2.12.0
.tools/x86_64/crane export --platform linux/amd64 docker.io/library/nats:2.15.0-scratch - | tar -xO nats-server | sha256sum
sha256sum .tools/x86_64/nats-server
```

When `deploy/tools.lock` moves to a new nats-server or Toxiproxy version, `tests/test_compose_stack.py` fails until the image tags follow. Resolve the new digests the same way and repeat the comparison.

**Why a second Dockerfile.** The release image (`deploy/containers/Dockerfile`) is built from an unpacked, signature-verified air-gap bundle. Making a bundle needs Node, uv and a download of every wheel on the host (`make bundle`), so it cannot be the one command a reviewer runs. `deploy/compose/Dockerfile` builds the same image from source with only Docker. `tests/test_compose_image.py` keeps the two aligned:

- the same Chainguard bases at the same digests;
- the dependency set exported from `uv.lock` exactly as the bundle exports it, and installed exactly as the release installs it (`--require-hashes`, binary wheels only);
- a runtime stage identical line for line.

The wheel is built against the setuptools that the pinned build image ships, so nothing unpinned is fetched to build it. The build context is an allowlist (`deploy/compose/Dockerfile.dockerignore`).

The compose image adds one thing to the release image: an empty `/var/lib/sentinel/trust`. A new named volume mounted over that directory takes its owner (65532), which lets the enrolment containers write the trust file. Both images carry the same reference data, the NASA CARA set and the OMM element-set snapshot a hub serves (`fixtures/omm`): the release image from the bundle's `fixtures/`, the compose image copied from the checkout.

## What the smoke test proves

`make compose-smoke` runs `harness/compose_smoke.py` against the consoles published on `127.0.0.1`. It records eight checks, and each one is shown to fail on its fault in `tests/test_compose_smoke.py`:

1. **Both nodes are healthy.** Each answers `/api/health`.
2. **The roles and markings are right.** The hub runs as a hub, the edge as an edge of it, and both are marked EXERCISE.
3. **Sync delivers and the edge verifies.** The hub's events reach the edge through sync, the two agree, and every edge event is VERIFIED: re-assessed at the edge and matched against what the hub asserted.
4. **DENIED is measured, not configured.** After `DENIED` is applied through the edge's own `/api/demo/link`, the edge's link monitor reports DENIED.
5. **The edge console keeps answering while DENIED.** Forty console requests return with a p95 under 200 ms, the DENIED scenario's bound. Meanwhile an operator annotates an event.
6. **Restoring the link converges.** Hub and edge again hold the same events, all VERIFIED, with equal operator-data digests.
7. **Operator data made while denied reaches the hub.** The annotation made at the edge during DENIED is at the hub. It is signed by the edge and merged by the hub, which proves the enrolment and trust file work.
8. **OPSEC: the unit stays on the edge.** A unit PUT on the edge returns 200 and reads back there, and the hub still answers 404 for it.

"Converged", the measured link state and the OPSEC unit use the DDIL harness's own definitions (`harness/scenarios.py`), so they mean what they mean in `docs/ddil-results.md`.

The smoke test writes to the stack: one triage annotation, and an exercise unit that it sets and then removes. Run it on a fresh stack. It always leaves the link CONNECTED.

The smoke test is not a DDIL measurement. It does not exercise LIMITED, DEGRADED or intermittent links, the earliest-deadline-first ordering, or the full OPSEC wire capture. Those come from `make ddil`, whose results are in `docs/ddil-results.md`.

## What was verified, and where

The development machine for this change had Docker Desktop without WSL integration, so **no container was built or run there**. Everything else was checked as follows.

| What | How | Where |
|---|---|---|
| Compose file is valid Compose | Validated against the compose-spec JSON schema, vendored with its commit and sha256 (`deploy/compose/schema/PROVENANCE.md`); `docker compose config --quiet` in CI | Static; CI |
| Pins, ports, the single link path, volumes, OPSEC mounts, hardening, start order | `tests/test_compose_stack.py` | Static |
| NATS configs identical to the harness's except addresses | `tests/test_compose_config.py` | Static |
| Release and compose images aligned | `tests/test_compose_image.py`, `hadolint` on both Dockerfiles | Static |
| CI job wiring, pinned actions | `tests/test_compose_wiring.py`, `tests/test_workflows_pinned.py`, `actionlint` | Static |
| Image binaries equal the tools.lock pins | `crane export`, then sha256, on x86_64 and aarch64 | Live, once, when pinning |
| The smoke test's eight checks | `compose_smoke.run()` against the process harness's real nats-server, Toxiproxy and sentinel processes, on Python 3.12 and on 3.14 (the image's Python) with the hash-locked runtime set | Live, without containers |
| The image's Python build steps | `uv export`, then the wheel built against setuptools 84 with no build isolation from an allowlist-only copy of the context, then a hash-locked binary-only install on Python 3.14 | Live, without containers |
| Enrolment as the containers run it | `harness/identity.py` run as a lone script against the installed wheel | Live, without containers |
| Harness refactor | The DENIED and OPSEC scenarios on real processes | Live |
| Image build, `up --wait` with the one-shot enrolments, volume ownership, the smoke test on containers | CI job `compose-smoke` | **CI only**, unproven until its first green run |
