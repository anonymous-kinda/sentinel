# DISA STIG and CCI list: provenance

Both files are published by DISA on the public STIG library
(https://public.cyber.mil/stigs/) and are byte-for-byte unmodified.
`SHA256SUMS` is verified by `tests/compliance/test_package_integrity.py`.

## Canonical Ubuntu 24.04 LTS STIG, Version 1 Release 6

| | |
|---|---|
| File | `U_CAN_Ubuntu_24-04_LTS_STIG_V1R6_Manual-xccdf.xml` (XCCDF 1.1) |
| Downloaded as | `https://dl.dod.cyber.mil/wp-content/uploads/stigs/zip/U_CAN_Ubuntu_24-04_LTS_V1R6_STIG.zip` (zip sha256 `2468e7fc35dc9e70ed6d1b7c87f5354b0cc9632882afafed6bad43cf49f2b837`), member `U_CAN_Ubuntu_24-04_LTS_V1R6_Manual_STIG/U_CAN_Ubuntu_24-04_LTS_STIG_V1R6_Manual-xccdf.xml` |
| Retrieved | 2026-09-23 |
| Release | `Release: 6 Benchmark Date: 01 Jul 2026`, status `accepted` (2026-05-14), 194 rules |

This is the newest release published at retrieval (V1R7 and V2R1 returned 404).
The DISA SCAP 1.3 benchmark for automated scanning lags one release
(`U_CAN_Ubuntu_24-04_LTS_V1R5_STIG_SCAP_1-3_Benchmark.zip`, 165 automated
rules, profiles `xccdf_mil.disa.stig_profile_MAC-{1,2,3}_{Classified,Sensitive,Public}`);
it is not vendored, because the STIG role's scan task takes the SCAP content
as an input on the host.

Used for: every STIG rule id in `compliance/sources/stig.toml` and in
`deploy/ansible/roles/stig/` is checked against this file, and the POA&M
generator reads rule titles, severities and CCIs from it rather than from
anything transcribed by hand.

## Control Correlation Identifier (CCI) list

| | |
|---|---|
| File | `U_CCI_List.zip` (contains `U_CCI_List.xml`, version and publish date 2025-01-23) |
| Downloaded as | `https://dl.dod.cyber.mil/wp-content/uploads/stigs/zip/U_CCI_List.zip` |
| Retrieved | 2026-09-23 |

Used for: the mapping from each STIG rule's CCIs to NIST SP 800-53 Rev 5
controls (`reference title="NIST SP 800-53 Revision 5"`). Sentinel does not
map STIG rules to controls itself; every rule-to-control link in the POA&M
comes from this file.
