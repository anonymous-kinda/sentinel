# Compliance package (OSCAL)

Sentinel keeps its security documentation as code, next to the evidence it
cites. A tailored NIST SP 800-53 Rev 5 profile, a component definition, a
draft system security plan and an assessment plan are generated from three
authored files. Every CI run then turns its own test evidence into OSCAL
assessment results and a plan of action and milestones (POA&M). Nothing
under `compliance/oscal/` is edited by hand, and `trestle validate -a`
checks every document on every run.

**No authorization to operate is claimed.** No authorizing official has
reviewed this system. The SSP is a draft, its security categorization is the
maintainer's provisional one, and every STIG deviation is recorded as
*requested*, never approved. What the package offers is ATO-ready evidence:
statements that say exactly what is and is not done, and point at the checks
that prove the part that is.

This is the pattern the maintainer runs in production: scanner and test
findings go in, governed artifacts come out, and a claim that the evidence
does not support is refused rather than printed.

## Status at a glance

Tailored baseline: **37** controls.

- By overall status: **8** implemented controls; **29** partial controls; **0** planned controls.
- A control is usually met by more than one component (the node software, its
  message bus, the host, the AWS hub, the pipeline, the owning organization).
  There are **65** contributions: **16** implemented contributions;
  **38** partial contributions; **11** planned contributions.
- DISA Canonical Ubuntu 24.04 LTS STIG V1R6 (194 rules): **55** applied rules;
  **25** deviating rules, grouped into **10** deviations; **8** not applicable rules;
  **106** unassessed rules.

These numbers are checked against the sources by
`tests/compliance/test_package_integrity.py`, so this page cannot drift from
the SSP.

What the statuses mean:

| Status | Rule |
|---|---|
| implemented | Everything the statement claims is backed by automated evidence: a pytest node id, a DDIL harness scenario, or a CI job. A file alone shows intent, not that it holds. |
| partial | Some of it is evidenced; the rest has a written plan. |
| planned | Only the plan exists. |

Every contribution that is not implemented becomes a POA&M item.

## What is in the package

| Path | What | How it is made |
|---|---|---|
| `compliance/sources/controls.toml` | Why each control was selected, and each component's statement, status, evidence and plan | Authored |
| `compliance/sources/system.toml` | System description, boundary, categorization, components, users, assessment methods | Authored |
| `compliance/sources/stig.toml` | Every STIG rule decision: applied, deviation (with justification, mitigation, plan) or not applicable | Authored |
| `compliance/vendor/nist/` | NIST SP 800-53 Rev 5.2.0 catalog from usnistgov/oscal-content v1.5.0, unmodified | Vendored, sha256 |
| `compliance/vendor/disa/` | DISA Ubuntu 24.04 STIG V1R6 (XCCDF) and the CCI list | Vendored, sha256 |
| `compliance/oscal/profiles/sentinel/` | Tailored profile: control selection, parameters, tailoring rationale per control | Generated |
| `compliance/oscal/component-definitions/sentinel/` | What each component contributes to each control | Generated |
| `compliance/oscal/system-security-plans/sentinel/` | Draft SSP | Generated |
| `compliance/oscal/assessment-plans/sentinel/` | Assessment plan: the controls reviewed, the three automated methods and their CI jobs | Generated |
| `compliance/oscal/assessment-results/sentinel/` | Assessment results from the last `make compliance` run | Generated from evidence |
| `compliance/oscal/plan-of-action-and-milestones/sentinel/` | POA&M from the same run | Generated from evidence |
| `compliance/*.py` | The generator (readers, source model, evidence matching, OSCAL builders) | Code, tested in `tests/compliance/` |
| `deploy/ansible/roles/stig/` | The STIG role: a documented V1R6 subset, OpenSCAP scan, checklist conversion | Code |

The workspace is a [compliance-trestle](https://github.com/oscal-compass/compliance-trestle)
workspace (trestle 5.1.0, OSCAL 1.2.1). The NIST catalog is imported into it
by `make compliance` after its checksum is verified; that imported copy is
build output and is not committed. Documents reference each other with
`trestle://` hrefs, because trestle resolves imports against the workspace
root.

## How it is generated

```
compliance/sources/*.toml  ─┐
compliance/vendor/ (sha256) ─┼─ scripts/oscal_evidence.py ─┬─ profile, component definition, SSP, assessment plan
pytest --junitxml           ─┤                             └─ assessment results, POA&M
harness/results/*.json      ─┤                                         │
OpenSCAP XCCDF results      ─┘                          trestle validate -a (every document)
```

```bash
make compliance                          # tests -> evidence -> all six documents -> trestle validate -a
make compliance XCCDF=build/stig/<host>/results.xml   # also triage a STIG scan into the POA&M
uv run python scripts/oscal_evidence.py  # authored documents only (profile, component definition, SSP, AP)
```

`make compliance` verifies the vendored catalog's checksum and imports it,
runs the whole pytest suite with `--junitxml`, runs the generator (adding
`harness/results/` if a DDIL run left results there), and validates the
workspace. If a test failed, the generator still runs, so the failure is in
the POA&M, and the target fails afterwards.

In CI the `compliance` job in `.github/workflows/ci.yml` runs the same target
on every push and pull request and uploads the six documents and the JUnit
XML as an artifact. The assessment results and POA&M committed here are the
snapshot from the last local run; CI's copies describe each commit.

The generator reads three kinds of evidence, one per assessment method in the
assessment plan:

| Method | Evidence | Reader |
|---|---|---|
| Test ladder | pytest JUnit XML | `compliance/inputs.py:read_junit` |
| DDIL harness | `harness/results/<scenario>.json` | `compliance/inputs.py:read_harness` |
| STIG scan | OpenSCAP XCCDF results | `compliance/inputs.py:read_xccdf` |

The same rule as Sentinel's CDM ingest applies to evidence. Input that would
make the assessment wrong raises and nothing is written: unparseable XML, a
run with no timestamp or no UTC offset, a result value the code does not
understand, a source that cites something that does not exist. Input that
makes it incomplete degrades and says so: harness results not supplied, a
scan rule the benchmark does not describe.

## The rules that keep it honest

Each rule is enforced in code and tested:

- **Implemented needs automated evidence.** The source loader refuses an
  `implemented` contribution without tests, harness scenarios or CI jobs, and
  anything less without a plan (`tests/compliance/test_sources.py`).
- **Every citation exists.** Every cited file, pytest node id (resolved from
  the source, not by running it), CI job and harness scenario is checked on
  every run; the generator refuses to write anything if one dangles
  (`tests/compliance/test_citations.py`, `test_package_integrity.py::test_every_citation_resolves`).
- **A citation that matched nothing is not a pass.** A cited test that was
  renamed, deleted, skipped or not run makes the control *not satisfied* in the
  assessment results and opens a POA&M item (`test_evidence.py`,
  `test_assessment.py`).
- **The committed documents are the generated ones.** A hand edit, or a source
  change without regeneration, fails `test_committed_documents_are_what_the_sources_generate`.
- **The catalog is the ground truth.** Every selected control, its assessment
  objective and every parameter the profile sets exist in the vendored NIST
  catalog, and none is withdrawn.
- **STIG facts come from DISA's files.** Rule titles, severities and CCIs are
  read from the vendored XCCDF; the link from a rule to 800-53 comes from
  DISA's CCI list. Every rule id in `stig.toml` and in the role must exist in
  V1R6; every applied rule must be implemented by the role; the SSH algorithms,
  audit rules, banner and acknowledgement script the role installs are
  compared with DISA's text (`test_stig_role.py`, `test_stig.py`).
- **Nothing is approved that nobody approved.** Deviations are
  `deviation-requested`; the SSP carries no authorization date and says none
  was sought (`test_no_authorization_is_claimed`).

## How to read it

| Question | Where |
|---|---|
| Which controls, and why? | The profile's `tailoring-rationale` props; the SSP's `remarks` per control |
| Who does what for a control? | The SSP's `by-components` (or the component definition) |
| What proves it? | `evidence-test`, `evidence-harness`, `evidence-ci`, `evidence-file` props on each statement; the assessment results' observations, one per control with automated evidence |
| What is not done yet? | The POA&M: failing tests, missing evidence, STIG scan results, every partial or planned contribution with its plan, every STIG deviation |

Sentinel's props use the namespace `urn:sentinel:oscal`:

| Prop | Meaning |
|---|---|
| `implementation-status` | implemented, partial or planned |
| `evidence-test` / `evidence-harness` / `evidence-ci` / `evidence-file` | Evidence that exists and is checked |
| `planned-evidence` | Evidence that will exist when the plan is done (for example `docs/supply-chain.md`) |
| `milestone` | The milestone a plan is scheduled in, where one is set |
| `tailoring-rationale` | Why the control is in the profile |
| `result` | An observation's per-citation outcome: passed, failed, missing, not-supplied |
| `related-control`, `component`, `stig-id`, `stig-severity` | POA&M item links |

For example:

```bash
jq -r '.["plan-of-action-and-milestones"]["poam-items"][].title' \
  compliance/oscal/plan-of-action-and-milestones/sentinel/plan-of-action-and-milestones.json
jq -r '.["system-security-plan"]["control-implementation"]["implemented-requirements"][]
       | [.["control-id"], (.props[] | select(.name=="implementation-status") | .value)] | @tsv' \
  compliance/oscal/system-security-plans/sentinel/system-security-plan.json
```

## Tailoring

The profile selects the controls Sentinel's design exercises and that its
evidence can speak to:

- **AC**: AC-2, AC-3, AC-4, AC-6, AC-17
- **AU**: AU-2, AU-3, AU-6, AU-9, AU-10
- **CA**: CA-7
- **CM**: CM-2, CM-3, CM-6, CM-7, CM-8, CM-14
- **IA**: IA-2, IA-5
- **RA**: RA-5
- **SA**: SA-10, SA-11, SA-15
- **SC**: SC-7, SC-8, SC-12, SC-13, SC-28
- **SI**: SI-2, SI-4, SI-7, SI-10, SI-15, SI-17
- **SR**: SR-3, SR-4, SR-11

Three were added to the starting list, each because Sentinel has something
specific to say about it. AC-17: administrators reach nodes remotely, and
DISA's CCI list maps the STIG's SSH rules there. SI-15: the AI number-grounding
guard is output filtering in exactly the control's sense. SI-17: losing the
link and receiving input the 2D method cannot handle are the two failures
Sentinel is designed around, and in both it fails to a known, stated state.

The profile also sets the organization-defined parameters where Sentinel has
a precise answer: AC-4 (the flow policies), SI-10 (which inputs are
validated), SI-15 (which outputs are filtered), SI-17 (the failure conditions
and the fail-safe procedures) and SC-13 (the cryptographic uses and
algorithms).

## The STIG role

`deploy/ansible/roles/stig/` applies a documented subset of the DISA Canonical
Ubuntu 24.04 LTS STIG, Version 1 Release 6 (Benchmark Date 01 Jul 2026), to a
single-purpose node. It is wired into `deploy/ansible/site.yml` behind
`stig_enabled` (off by default) and runs last, so the AIDE baseline it records
includes the installed node.

What it applies (55 rules): removal of telnetd, rsh-server, NFS and ntp;
chrony, auditd, AppArmor, ufw, AIDE and rsyslog installed and running; SSH
restricted to DISA's FIPS 140-3 approved ciphers, MACs and key exchange;
audit rules for account files, su, sudo, sudoers and kernel modules, immutable
once loaded and enabled from boot; root locked, inactive accounts disabled,
UMASK 077, a session limit, no `nullok`; kernel settings (dmesg restricted,
TCP syncookies, Ctrl-Alt-Delete masked, kdump off, USB storage off); APT
refusing unauthenticated packages; clock stepping and UTC. After a flush of
its handlers it checks what is in effect, not what it wrote: `sshd -T` for
every SSH setting, the running ASLR value, and that no account has an empty
password.

With `stig_scan: true` and `stig_scap_content` pointing at the DISA SCAP
benchmark on the controller, it runs `oscap xccdf eval` (default profile
`xccdf_mil.disa.stig_profile_MAC-2_Sensitive`), fetches the XCCDF results and
report to `build/stig/<host>/`, and converts them to a DISA checklist with the
MITRE SAF CLI (`npx @mitre/saf@1.7.0 convert xccdf_results2hdf`, then
`convert hdf2ckl`). Pass the results to `make compliance XCCDF=...` and the
POA&M sorts every rule: an applied rule that fails is a regression, a failure
the decisions do not cover is a new item, a documented deviation is confirmed
in its item's remarks, and a rule the scanner could not evaluate is an item of
its own.

The deviations, each a POA&M item with its justification, mitigation and plan
(`compliance/sources/stig.toml`):

| Deviation | Rules |
|---|---|
| SSH shows the exercise notice, not the DoD banner (the demonstration node is not a USG system; the DoD text is in the role behind `stig_dod_banner`) | UBTU-24-200640, UBTU-24-200680 |
| Only SSH is rate-limited (ufw LIMIT would block operators behind one NAT address and a leafnode reconnecting after a DDIL outage) | UBTU-24-600200 |
| No FIPS mode | UBTU-24-600030 |
| No CAC/PIV logon, no DoD PKI | 13 rules (UBTU-24-100650 and others) |
| The automation account's NOPASSWD sudo | UBTU-24-300020 |
| Data at rest encrypted by EBS, not the OS | UBTU-24-600090 |
| No boot-loader password | UBTU-24-102000 |
| Audit records stay on the node | UBTU-24-100450, UBTU-24-900950 |
| Default time source not a DoD source | UBTU-24-600160 |
| Audit alerts not mailed | UBTU-24-900960, UBTU-24-900980 |

The 8 rules for a graphical session are not applicable: the node is headless.
The remaining rules are not yet assessed; until a scan runs, the POA&M says so
in one item.

**What has not happened:** the role has not been run against a host. CI
checks the playbook's syntax (which also resolves every module), and the tests
check the role against DISA's text, but no scan results exist yet. That is
the first POA&M item.

## The largest gaps

The POA&M lists everything; these matter most:

1. **Operators are not authenticated** (IA-2, AC-2, AU-10). The node records the
   identity the front proxy asserts, and the current proxy neither sets nor
   strips it. Signatures bind decisions to nodes, not yet to people.
2. **The leaf link is not encrypted** (SC-8). The templates leave a place for
   mTLS; none is configured.
3. **AC-4 is proven in configuration, not on the wire.** A harness scenario that
   publishes on `unit.>` and `passes.>` at the edge and asserts nothing arrives
   at the hub would close it.
4. **The host baseline is unverified** until the STIG role and its scan run.
5. **Supply chain** controls (CM-8, CM-14, SI-7, SR-3, SR-4, SR-11, RA-5) are
   planned in the M4 release pipeline, documented in `docs/supply-chain.md`.
6. **Organizational responsibilities** (review cadences, approval authority,
   remediation timelines) are listed against a `program` component as planned,
   so the SSP says where they are missing.

## Versions

| Item | Version |
|---|---|
| compliance-trestle | 5.1.0 (validates OSCAL 1.2.1), run with `uvx`, not a project dependency |
| NIST SP 800-53 catalog | Rev 5.2.0, usnistgov/oscal-content v1.5.0, commit `78650f02` (OSCAL 1.2.2) |
| DISA STIG | Canonical Ubuntu 24.04 LTS V1R6, Benchmark Date 01 Jul 2026 |
| DISA CCI list | 2025-01-23 |
| MITRE SAF CLI | 1.7.0 |
| OpenSCAP | `openscap-scanner` from Ubuntu 24.04 (universe) |
