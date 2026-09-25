# Install guide: disconnected or classified site

One page for the person installing a Sentinel node where there is no internet. Every command below matches the scripts in `deploy/bundle/`. The full verification procedure, and the reasons behind it, are in [supply-chain.md](supply-chain.md).

Sentinel is a demonstration, not an accredited system. Installing it on a real network needs your site's approval process, and nothing here replaces it.

**The host.** Linux (glibc) on x86_64 or aarch64, with `python3.12` and systemd. The node needs no internet.

## 1. Receive the bundle

These files cross the gap together, through your site's software approval process:

| File | What it is |
|---|---|
| `sentinel-<ver>-<arch>.tar.gz` | The bundle: wheels, hash-locked requirements, console, NASA reference data, `install.sh` |
| `sentinel-<ver>-<arch>.tar.gz.sigstore.json` | Its signature |
| `sentinel-<ver>-<arch>.tar.gz.sha256` | Its digest |
| `trusted_root.json` | The Sigstore trust root, for keyless releases |
| `verify_signature.sh` | The verifier, from `deploy/bundle/verify_signature.sh` |
| `cosign` | The cosign binary for the host's architecture, pinned in `deploy/tools.lock` |
| `site.pub` | Only if your site countersigns software with its own key |
| `elements.json` | Optional: newer public element sets (CelesTrak OMM JSON). The bundle carries the snapshot it was built with, which goes stale three days after its epoch. |

## 2. Verify offline, before unpacking anything

Check the verifier first. These digests are the pins in `deploy/tools.lock` (cosign 3.1.3 for x86_64; use the aarch64 row on an aarch64 host).

```bash
VER=0.3.0; ARCH=x86_64
ID="https://github.com/OWNER/sentinel/.github/workflows/release.yml@refs/tags/v$VER"
echo "4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71  cosign" | sha256sum --strict -c -
echo "6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66  trusted_root.json" | sha256sum --strict -c -
```

Then verify the bundle's signature. For a release signed in CI (keyless), the signer must be exactly `$ID`:

```bash
COSIGN=./cosign SENTINEL_TRUSTED_ROOT=trusted_root.json \
SENTINEL_TRUSTED_ROOT_SHA256=6494e21ea73fa7ee769f85f57d5a3e6a08725eae1e38c755fc3517c9e6bc0b66 \
SENTINEL_CERT_IDENTITY="$ID" \
  unshare -rn ./verify_signature.sh sentinel-$VER-$ARCH.tar.gz
sha256sum --strict -c sentinel-$VER-$ARCH.tar.gz.sha256
```

For a bundle your site countersigned with its own key, use the key instead. Set one policy, never both:

```bash
COSIGN=./cosign SENTINEL_VERIFY_KEY=site.pub unshare -rn ./verify_signature.sh sentinel-$VER-$ARCH.tar.gz
```

Success ends with `verify_signature: OK sentinel-<ver>-<arch>.tar.gz (<sha256>)`. `unshare -rn` runs the check with no network at all, to prove it needs none. If the host forbids user namespaces, run the same command without `unshare -rn`.

## 3. Install

```bash
tar -xzf sentinel-$VER-$ARCH.tar.gz
cd sentinel-$VER-$ARCH
sudo ./install.sh
```

`install.sh` checks every file against the bundle's `SHA256SUMS` and refuses any file the list does not name. It installs dependencies from the bundle only (`--no-index --require-hashes`) and installs to `/opt/sentinel`. It then creates a `sentinel` system user and starts `sentinel.service`. On first install it writes `/opt/sentinel/sentinel.env` with exercise defaults. It never overwrites that file, so you can write it before installing.

Without root: `PREFIX=$HOME/sentinel SYSTEMD=0 ./install.sh`, then start the node by hand (step 5).

## 4. Configure

Edit `/opt/sentinel/sentinel.env`:

| Setting | Set it to |
|---|---|
| `SENTINEL_ROLE` | `standalone` for a single node. `hub` or `edge` for nodes that sync (see below). |
| `SENTINEL_NODE_ID` | This node's name. The default is the host name. |
| `SENTINEL_HUB_ID` | On an edge: the hub's node id. |
| `SENTINEL_MARKING` | Your site's classification marking, exactly as the banner must show it. Only `UNCLASSIFIED` or `UNCLASSIFIED // EXERCISE` allows hosted AI; any other marking, a caveated one such as `UNCLASSIFIED//CUI` included, keeps the assistant on the node. |
| `SENTINEL_READ_ONLY` | `1` for a display-only node: no CDM uploads, no screening, no operator writes. |
| `SENTINEL_AI` | `0` turns the assistant off. Left on, it runs local rules and templates only. The bundle carries no hosted AI libraries, and `SENTINEL_AI_CLOUD` stays `0`. |
| `SENTINEL_EXERCISE` | `0` stops the scripted exercise scenario. |
| `SENTINEL_LIBRARY` | Leave at `1`: it loads NASA's reference events, which the Validation tab and the smoke test use. |
| `SENTINEL_ELEMENTS` | Optional: the path of a newer element-set file you brought across. A hub or standalone node loads the bundled snapshot by default. An edge normally gets its element sets from its hub; an edge with no hub link can be given a file the same way. |
| `SENTINEL_SYNC_ELEMENTS` | On a hub: `catalog` (the default) offers edges only the imaging catalog's element sets that the pass module uses. `all` offers every set it holds and costs link time. |

**Where data comes from.**

- *CDMs:* upload each CCSDS CDM file with `curl -s --data-binary @FILE.cdm http://127.0.0.1:8000/api/ingest/cdm`. The reply is `201` when accepted, `200` for a CDM the node already holds, and `422` when rejected with a named reason. An edge also receives CDMs from its hub.
- *Element sets:* from `SENTINEL_ELEMENTS`, or from the hub. Screening gives geometry only and never a Pc: use the console's API (`POST /api/screening`, see [the screening ICD](icd/screening-api.md)) or `/opt/sentinel/venv/bin/sentinel screen --primary 41599 --elements /opt/sentinel/elements.json`.
- *A ground unit's position:* set it on the edge that serves the unit, in the Passes tab. It stays on that node, in one file readable only by the service, and is never sent to the hub ([the passes ICD](icd/passes-api.md)).

**Hub and edge.** Each node runs its own `nats-server`. The bundle ships the binary (`/opt/sentinel/bin/nats-server`), but not its configuration or a service unit. Render `deploy/nats/hub.conf.tmpl` or `deploy/nats/edge.conf.tmpl` from the source tree, run it as its own service, and set `SENTINEL_NATS_URL=nats://127.0.0.1:<client port>`. This step is not scripted yet; only the test harness (`harness/cluster.py`) has exercised it. The leaf link is not encrypted: configure TLS in the template before connecting a real link. Each node writes its public key to `/opt/sentinel/var/keys/<node-id>.pub` on first start. Merge every node's key into one JSON file and point `SENTINEL_TRUST_FILE` at it on each node. Without it, a node will not accept another node's decisions.

## 5. Start

```bash
sudo systemctl restart sentinel
```

Without systemd, from the install directory:

```bash
set -a; . ./sentinel.env; set +a
./venv/bin/sentinel serve --port 8000
```

The service listens on 127.0.0.1:8000 only. Put the site's TLS proxy in front of it; the proxy is also where operator identity belongs.

## 6. Smoke test

```bash
curl -sf http://127.0.0.1:8000/api/health
curl -sf http://127.0.0.1:8000/api/validation | /opt/sentinel/venv/bin/python -c 'import json,sys; d=json.load(sys.stdin); print(d["operational_count"], "events, worst rel error", d["worst_rel_error"], ", false negatives", d["confusion"]["fn"])'
curl -sf -o /dev/null http://127.0.0.1:8000/ && echo "console served"
```

Expect `"status":"ok"` with your node id; `53 events`, a worst relative error near 1.5e-08 and `false negatives 0`; then `console served`. The node has re-run the NASA comparison with the code it is actually running. Open the console through the proxy and check the banner shows your marking.

## 7. When verification fails

Stop. Do not unpack, install, or try another policy until you know why. Keep the files, note which one failed and its `sha256sum`, and report it to your ISSM.

| Message | Meaning |
|---|---|
| `sha256sum: WARNING: 1 computed checksum did NOT match` (cosign or trust root) | The verifier or the trust anchor is not the pinned one. Do not use it. |
| `no signature bundle: ... (an unsigned artifact is never installed)` | The `.sigstore.json` did not cross. Get it from the same release. |
| `no verification policy` or `ambiguous policy` | Set exactly one: the trust root and signer identity, or `SENTINEL_VERIFY_KEY`. |
| `trusted root digest ... does not match the pinned ...` | The trust root is not the pinned one. Do not substitute another; see "Trust root" in [supply-chain.md](supply-chain.md). |
| `verify_signature: FAIL: signature does not verify for ...` | The bundle was altered, or it was signed by a different identity or key than the one you trust. Treat it as tampered. |
| `sha256sum: WARNING` from `install.sh` | A file inside the bundle does not match its signed manifest. The installer stops before installing anything. |
| `verify_contents: refusing files that SHA256SUMS does not list:` | A file was added to the unpacked bundle after signing; the lines after it name each one. The installer stops before installing anything. Unpack the verified tarball again into an empty directory. |

The same refusals are exercised on every change: `make airgap-selftest` shows tampered, unsigned, wrong-key and wrong-identity bundles being refused, all with no network.
