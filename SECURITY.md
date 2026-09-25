# Security policy

Sentinel is a decision aid that demonstrates an architecture. It is not an
operational flight-safety system, and it has no authority to operate. This
page says how to report a vulnerability and what is known to be missing.

## Reporting a vulnerability

Report privately. Do not open a public issue for a vulnerability.

- **How:** use GitHub's private vulnerability reporting. On the repository's
  **Security** tab, choose **Report a vulnerability**. The report stays private
  between you and the maintainer until a fix is published.
- Include the commit or release version, what you did, what happened, and
  what an attacker gains.
- No response time is promised. Fixes land on `main`.

## Supported branch

Only `main` is supported. Releases are built from `vX.Y.Z` tags
(`.github/workflows/release.yml`), and older releases are not patched.

## In scope

- The node: everything under `sentinel/`, and the console it serves (`web/`).
- The install path: the signature gate and offline installer in
  `deploy/bundle/`, the NATS templates in `deploy/nats/`, the systemd unit,
  the container, the Ansible roles and the AWS Terraform under `deploy/`.
- The supply chain: `supplychain/`, the release and CI workflows under
  `.github/workflows/`, the pins in `deploy/tools.lock`, and the VEX
  statements in `deploy/vex/`.
- The compliance generator in `compliance/`. A control reported as
  implemented when it is not is a security bug.
- Answers that are wrong rather than refused. A Pc returned where the
  applicability gate should refuse, a number in an AI-written answer that
  the tools did not produce, or an unsigned bundle that installs are all in
  scope.

## Out of scope

- Vulnerabilities in third-party components themselves (`nats-server`,
  cosign, CesiumJS, Python and npm packages). Report those upstream. Do tell
  us if the way Sentinel pins or uses one makes it exploitable.
- The DDIL test harness in `harness/`, and the link-emulation controls a node
  exposes to localhost only when `SENTINEL_DEMO_CONTROLS` is set.
- The hosted AI services themselves.
- The four open gaps below, which are already tracked.

## Security posture

What is in place, and its limits, is written down rather than implied:

- **Supply chain.** Releases are signed keyless and verified offline before
  anything is unpacked. They ship SBOMs and SLSA Build L2 provenance, and a
  vulnerability gate fails on any finding without a reviewed VEX statement.
  `docs/supply-chain.md` lists what is claimed, the commands that prove it,
  and what is not claimed.
- **Controls.** `docs/compliance.md` explains the OSCAL package: a draft SSP,
  and assessment results and a POA&M generated from the test suite's
  evidence. Every control that is not fully implemented is a POA&M item in
  `compliance/oscal/plan-of-action-and-milestones/sentinel/`.
- **Secrets.** CI scans the whole git history for committed secrets on every
  push to `main` and every pull request.

## Known open gaps

These come from the POA&M. Each is a real weakness in the current code.

1. **Operator identity comes from a proxy header (IA-2).** The node records
   whoever the `X-Sentinel-Operator` header names (`sentinel/api/identity.py`).
   The shipped Caddy configuration neither sets that header from an
   authenticated identity nor strips a client-supplied one, so on a writable
   node any client can act under any operator name. Decision-log signatures
   bind an entry to a node, not to a person. Until an authenticating proxy is
   in place, keep writable nodes off untrusted networks. The AWS deployment
   in `docs/deploy-aws.md` runs read-only.
2. **No TLS on the leaf link (SC-8).** The hub-to-edge leafnode link carries
   CDMs, summaries and operator data in the clear. The templates in
   `deploy/nats/` leave a place for TLS, but none is configured, and the AWS
   security group keeps port 7422 closed unless edge networks are
   allow-listed. Decision-log entries are signed, so an altered entry is
   rejected, but nothing on the link is confidential.
3. **Truncating the newest AI-audit lines while the node is down is
   undetectable (AU-9).** The AI audit log is hash-chained
   (`sentinel/audit/chain.py`): an edited or deleted line is found at that
   line, and so is a truncation made while the node runs, because
   verification holds the file against the hashes the process has seen.
   Removing lines from the end while the node is stopped leaves a shorter
   chain that still verifies after a restart. The plan is to anchor the
   chain's head outside the file.

4. **Annotations are not signed (SC-8).** ADR-005 signs the decision log
   (decisions, notes and RESOLUTION entries), not the annotation registers
   (triage status, assignee, note). A register carries its causal context
   and no signature, so anyone who can reach `ops.<hub_id>.exchange` can
   erase or overwrite an annotation at the hub by sending a register that
   claims to have seen the write
   (`tests/test_ops_hostile_peer.py::test_an_untrusted_peer_cannot_erase_an_annotation`,
   a strict xfail). The hub then passes the change to every edge as an
   ordinary overwrite. Decision-log entries are not affected. Until
   registers are signed or the leaf link authenticates its peers (gap 2),
   treat annotations as advisory and read the decision log for what was
   decided.

`docs/compliance.md` ("The largest gaps") and the POA&M list the rest.
